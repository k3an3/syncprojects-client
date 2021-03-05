import logging
from abc import ABC, abstractmethod
from typing import Dict

from syncprojects.api import SyncAPI
from syncprojects.operations import get_lock_status

logger = logging.getLogger('syncprojects.commands')


class CommandHandler(ABC):
    from syncprojects.main import SyncManager

    def __init__(self, api_client: SyncAPI, sync_manager: SyncManager):
        self.api_client = api_client
        self.sync_manager = sync_manager
        self.logger = logging.getLogger(f'syncprojects.commands.{self.__class__.__name__}')

    @abstractmethod
    def handle(self, task_id: str, data: Dict) -> Dict:
        pass

    def send_queue(self, task_id: str, response_data: Dict) -> None:
        self.api_client.send_queue.put({'task_id': task_id, **response_data})


class AuthHandler(CommandHandler):
    def handle(self, task_id: str, data: Dict) -> Dict:
        self.api_client.handle_auth_msg(data)
        self.send_queue(task_id, {'result': 'success'})


class SyncMultipleHandler(CommandHandler):
    def handle(self, task_id: str, data: Dict) -> Dict:
        """
        Handles syncing from the API
        :param task_id:
        :param data: Expects either a list of project or song IDs. Will automatically fetch the corresponding data for
        the IDs passed.
        :return:
        If progress is made, returns {'status': 'progress'} and the dict of the project that was completed.
        If a project is locked, status will instead be 'error', and 'locked' will contain information about the lock.
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
                    self.send_queue(task_id, {'status': 'progress', 'completed': sync})
                else:
                    self.logger.debug("Project is locked; returning error.")
                    # TODO: does this contain enough info about project?
                    self.send_queue(task_id, {'status': 'error', 'locked': lock})
        elif 'songs' in data:
            self.logger.debug("Got request to sync songs")
            # Thoughts on this: to avoid conflicts, we first lock the entire project, which will also ensure nobody
            # else is syncing. Then, while project is still locked, set the individual song to locked and unlock the
            # rest of the project. This way, if someone else wants to sync, they will see that the song is locked.
            for song in data['songs']:
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
                        sync = self.sync_manager.sync([project])
                        self.send_queue(task_id, {'status': 'progress', 'completed': sync})
                    else:
                        # TODO: does this contain enough info about song?
                        self.send_queue(task_id, {'status': 'error', 'locked': song_lock, 'component': 'song'})
                else:
                    # TODO: does this contain enough info about project?
                    self.send_queue(task_id, {'status': 'error', 'locked': project_lock, 'component': 'project'})


class StartProjectHandler(CommandHandler):
    def handle(self, task_id: str, data: Dict) -> Dict:
        pass
