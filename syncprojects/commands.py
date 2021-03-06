from os.path import join

import logging
from abc import ABC, abstractmethod
from typing import Dict

from syncprojects.api import SyncAPI
from syncprojects.operations import get_lock_status
from syncprojects.storage import appdata
from syncprojects.utils import open_default_app

logger = logging.getLogger('syncprojects.commands')


class CommandHandler(ABC):
    from syncprojects.main import SyncManager

    def __init__(self, task_id: str, api_client: SyncAPI, sync_manager: SyncManager):
        self.task_id = task_id
        self.api_client = api_client
        self.sync_manager = sync_manager
        self.logger = logging.getLogger(f'syncprojects.commands.{self.__class__.__name__}')

    @abstractmethod
    def handle(self, data: Dict):
        pass

    def send_queue(self, response_data: Dict) -> None:
        self.api_client.send_queue.put({'task_id': self.task_id, **response_data})

    # TODO: does this really belong here?
    def lock_and_sync_song(self, song: Dict, unlock: bool = True) -> None:
        # Thoughts on this: to avoid conflicts, we first lock the entire project, which will also ensure nobody
        # else is syncing. Then, while project is still locked, set the individual song to locked and unlock the
        # rest of the project. This way, if someone else wants to sync, they will see that the song is locked.
        project = self.api_client.get_project(song['project'])
        self.logger.debug(f"Requesting lock of project {project['name']}")
        if get_lock_status(project_lock := self.api_client.lock(project)):
            self.logger.debug("Got exclusive lock of project")
            # Not efficient... if there are multiple songs under the same project for some reason,
            # really shouldn't check out the same project multiple times... use case TBD
            self.logger.debug(f"Requesting lock of project {project['name']} song {song['name']}")
            if get_lock_status(song_lock := self.api_client.lock(song)):
                self.logger.debug("Got exclusive lock of song, unlocking project")
                self.api_client.unlock(project)
                project['songs'] = song
                sync = self.sync_manager.sync(project)
                if unlock:
                    self.logger.debug("Unlocking song")
                    self.api_client.unlock(song)
                else:
                    self.logger.debug("Not unlocking song")
                self.send_queue({'status': 'progress', 'completed': sync})
            else:
                # TODO: does this contain enough info about song?
                self.send_queue({'status': 'error', 'lock': song_lock, 'component': 'song'})
        else:
            # TODO: does this contain enough info about project?
            self.send_queue({'status': 'error', 'lock': project_lock, 'component': 'project'})


class AuthHandler(CommandHandler):
    def handle(self, data: Dict):
        self.api_client.handle_auth_msg(data)
        self.send_queue({'result': 'success'})


class SyncMultipleHandler(CommandHandler):
    def handle(self, data: Dict):
        """
        Handles syncing from the API
        :param data: Expects either a list of project or song IDs. Will automatically fetch the corresponding data for
        the IDs passed.
        :return:
        If progress is made, returns {'status': 'progress'} and the dict of the project that was completed.
        If a project is locked, status will instead be 'lock', and 'lock' will contain information about the lock.
        If the current task is finished, it returns status 'complete'.
        If an error happens, I imagine we will return status 'error'.
        """
        if 'projects' in data:
            self.logger.debug("Got request to sync projects")
            for project in data['projects']:
                if 'songs' not in project:
                    # This request came from the API, we don't have the project data yet
                    project = self.api_client.get_project(project)
                try:
                    if not project['sync_enabled']:
                        self.logger.debug(f"Project {project['name']} sync disabled, skipping...")
                        continue
                except KeyError:
                    pass
                if get_lock_status(lock := self.api_client.lock(project)):
                    self.logger.debug("Project is unlocked; starting sync.")
                    sync = self.sync_manager.sync(project)
                    self.api_client.unlock(project)
                    # TODO: should these be the entire project dict or just id?
                    self.send_queue({'status': 'progress', 'completed': sync})
                else:
                    self.logger.debug("Project is locked; returning error.")
                    # TODO: does this contain enough info about project?
                    self.send_queue({'status': 'lock', 'lock': lock})
            self.send_queue({'status': 'complete'})
        elif 'songs' in data:
            self.logger.debug("Got request to sync songs")
            for song in data['songs']:
                self.lock_and_sync_song(song)
            self.send_queue({'status': 'complete'})


class WorkOnHandler(CommandHandler):
    def handle(self, data: Dict):
        song = data['song']
        """
        if not (exe := find_daw_exe()):
            # If we don't get the path to the DAW executable right away, we'll prompt the user to open their DAW just
            # this one time so we can learn the path to it.
            self.send_queue({'status': 'error', 'reason': 'daw_path'})
            return
        """
        # Keep song checked out afterwards
        self.lock_and_sync_song(song, unlock=False)
        open_default_app(join(appdata['source'], song.get('directory_name') or song['name']))


class WorkDoneHandler(CommandHandler):
    def handle(self, data: Dict):
        song = data['song']
        project = self.api_client.get_project(song['project'])
        project['songs'] = song
        sync = self.sync_manager.sync(project)
        self.send_queue({'status': 'complete', 'sync': sync})
