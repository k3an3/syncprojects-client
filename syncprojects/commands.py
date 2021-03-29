import glob
import logging
from abc import ABC, abstractmethod
from os.path import join, getctime
from typing import Dict

from requests import HTTPError

from syncprojects.api import SyncAPI
from syncprojects.operations import get_lock_status
from syncprojects.storage import appdata
from syncprojects.utils import open_default_app, check_update

logger = logging.getLogger('syncprojects.commands')


class TaskIDLogWrapper:
    def __init__(self, configured_logger, task_id: str):
        self.logger = configured_logger
        self.task_id = task_id

    def __getattr__(self, item):
        def function(msg, *args, **kwargs):
            return getattr(self.logger, item)(f"[{self.task_id}] {msg}", *args, **kwargs)

        return function


class CommandHandler(ABC):
    def __init__(self, task_id: str, api_client: SyncAPI, sync_manager):
        self.task_id = task_id
        self.api_client = api_client
        self.sync_manager = sync_manager
        self.logger = TaskIDLogWrapper(logging.getLogger(f'syncprojects.commands.{self.__class__.__name__}'),
                                       self.task_id)

    def __repr__(self):
        return self.task_id

    @abstractmethod
    def handle(self, data: Dict):
        """
        Method to actually handle processing of the data.
        This method should not usually be called directly;
        use exec() instead.
        :param data:
        :return:
        """
        pass

    def exec(self, data: Dict):
        """
        Public-facing method to handle adding the current task to the tracker,
        and removing it upon success. It is the caller's job to clean that up
        if there is an error during execution.
        :param data:
        :return:
        """
        self.sync_manager.tasks.add(self.task_id)
        self.handle(data)
        self.sync_manager.tasks.remove(self.task_id)

    def send_queue(self, response_data: Dict) -> None:
        self.api_client.send_queue.put({'task_id': self.task_id, **response_data})

    # TODO: does this really belong here?
    def lock_and_sync_song(self, song: Dict, unlock: bool = True) -> Dict:
        # Thoughts on this: to avoid conflicts, we first lock the entire project, which will also ensure nobody
        # else is syncing. Then, while project is still locked, set the individual song to locked and unlock the
        # rest of the project. This way, if someone else wants to sync, they will see that the song is locked.
        project = self.api_client.get_project(song['project'])
        song = next(s for s in project['songs'] if s['id'] == song['song'])
        self.logger.debug(f"Requesting lock of project {project['name']}")
        if get_lock_status(project_lock := self.api_client.lock(project)):
            self.logger.debug("Got exclusive lock of project")
            # Not efficient... if there are multiple songs under the same project for some reason,
            # really shouldn't check out the same project multiple times... use case TBD
            self.logger.debug(f"Requesting lock of project {project['name']} song {song['name']}")
            if get_lock_status(song_lock := self.api_client.lock(song, reason="Checked out")):
                self.logger.debug("Got exclusive lock of song, unlocking project")
                self.api_client.unlock(project)
                project['songs'] = [song]
                sync = self.sync_manager.sync(project)
                if unlock:
                    self.logger.debug("Unlocking song")
                    self.api_client.unlock(song)
                else:
                    self.logger.debug("Not unlocking song")
                self.send_queue({'status': 'progress', 'completed': {'project': project['name'], **sync}})
                return song
            else:
                # TODO: does this contain enough info about song?
                self.api_client.unlock(project)
                self.send_queue({'status': 'error', 'lock': song_lock, 'msg': f"Song \"{song['name']}\" is locked",
                                 'component': 'song'})
        else:
            # TODO: does this contain enough info about project?
            self.send_queue({'status': 'error', 'lock': project_lock, 'msg': f"Project \"{project['name']}\" is locked",
                             'component': 'project'})


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
                if not isinstance(project, dict):
                    # This request came from the API, we don't have the project data yet
                    project = self.api_client.get_project(project)
                try:
                    if not project['sync_enabled']:
                        self.logger.debug(f"Project {project['name']} sync disabled, skipping...")
                        continue
                except KeyError:
                    pass
                try:
                    lock = self.api_client.lock(project)
                except HTTPError:
                    self.send_queue({'status': 'error', 'msg': f'Error checking out {project["name"]}'})
                    continue
                if get_lock_status(lock):
                    self.logger.debug(f"Unlocked project {project['name']}; starting sync.")
                    sync = self.sync_manager.sync(project)
                    self.sync_manager.sync_amps(project["name"])
                    self.api_client.unlock(project)
                    self.send_queue({'status': 'progress', 'completed': {'project': project['name'], **sync}})
                else:
                    self.logger.debug("Project is locked; returning error.")
                    # Lock is only a warning here since other projects can still sync
                    self.send_queue({'status': 'warn', 'failed': {'project': project['name'], 'lock': lock},
                                     'msg': f"Project \"{project['name']}\" is locked"})
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
        if not (song := self.lock_and_sync_song(song, unlock=False)):
            self.send_queue({'status': 'complete'})
            return
        # TODO: DAW agnostic?
        # just guessing at which file to open
        project_files = glob.glob(join(appdata['source'], song.get('directory_name') or song['name'], "*.cpr"))
        try:
            latest_project_file = max(project_files, key=getctime)
        except ValueError:
            self.send_queue({'status': 'error', 'msg': 'no DAW project file'})
            return
        self.logger.debug(f"Resolved project file to {latest_project_file}")
        open_default_app(latest_project_file)
        self.send_queue({'status': 'complete'})


class WorkDoneHandler(CommandHandler):
    def handle(self, data: Dict):
        song = data['song']
        project = self.api_client.get_project(song['project'])
        # TODO: do we just want to call the sync method at the top of this file and add a way to not lock there?
        song = next(s for s in project['songs'] if s['id'] == song['song'])
        project['songs'] = [song]
        sync = self.sync_manager.sync(project)
        try:
            self.api_client.unlock(song)
        except HTTPError:
            self.send_queue({'status': 'error', 'msg': f'Error unlocking {song["name"]}'})
        self.send_queue({'status': 'complete', 'sync': sync})


class UpdateHandler(CommandHandler):
    def handle(self, data: Dict):
        check_update(self.api_client)


class GetTasksHandler(CommandHandler):
    def handle(self, data: Dict):
        tasks = self.sync_manager.tasks.copy()
        tasks.remove(self.task_id)
        self.send_queue({'status': 'tasks', 'tasks': list(tasks)})
