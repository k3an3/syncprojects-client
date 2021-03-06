import traceback

import datetime
import logging
import uuid
from threading import Lock
from typing import Dict, List, Type

from syncprojects import config, commands
from syncprojects.api import SyncAPI
from syncprojects.storage import appdata
from syncprojects.sync.backends import SyncBackend, Verdict
from syncprojects.sync.operations import check_out
from syncprojects.utils import check_daw_running, print_hr, get_input_choice, create_project_dirs


class SyncManager:
    def __init__(self, api_client: SyncAPI, backend: Type[SyncBackend], headless: bool = False, context: Dict = None,
                 args: List = None, **kwargs):
        self.logger = logging.getLogger(f'syncprojects.sync.{self.__class__.__name__}')
        self.api_client = api_client
        self.headless = headless
        self.tasks = set()
        if appdata.get('nested_folders'):
            create_project_dirs(self.api_client, appdata['source'])
        self._backend = backend(self.api_client, *args, **kwargs)
        self.context = context

    def sync(self, project: Dict, force_verdict: Verdict = None) -> Dict:
        self.logger.info(f"Syncing project {project['name']}...")
        pre_results = []
        songs = []
        for song in project['songs']:
            if not song['sync_enabled']:
                pre_results.append({'song': song['name'], 'result': 'success', 'action': 'disabled'})
                continue
            elif song['is_locked']:
                pre_results.append({'song': song['name'], 'result': 'error', 'action': 'locked'})
                continue
            else:
                song['project_name'] = project['name']
                songs.append(song)
        if not songs:
            self.logger.warning("No songs, skipping")
            return {'status': 'done', 'songs': None}
        self.logger.debug(f"Got songs list {songs}")
        self._backend.get_local_changes(songs)
        results = self._backend.sync(project, songs, force_verdict)
        results['songs'].extend(pre_results)
        api_results = [s['id'] for s in results['songs'] if 'id' in s and s['action'] == "local"]
        if api_results:
            self.api_client.add_sync(project, api_results)
        return results

    def sync_amps(self, project: Dict):
        return self._backend.sync_amps(project)

    def run_service(self):
        self.logger.debug("Starting syncprojects-client service")
        self.headless = True
        try:
            while msg := self.api_client.recv_queue.get():
                self.logger.debug(f"Received {msg['task_id']=} {msg['msg_type']=} {msg['data']=}")
                try:
                    {
                        'auth': commands.AuthHandler,
                        'sync': commands.SyncMultipleHandler,
                        'workon': commands.WorkOnHandler,
                        'workdone': commands.WorkDoneHandler,
                        'tasks': commands.GetTasksHandler,
                        'shutdown': commands.ShutdownHandler,
                        'update': commands.UpdateHandler,
                        'logs': commands.LogReportHandler,
                        'settings': commands.SettingsHandler,
                    }[msg['msg_type']](msg['task_id'], self.api_client, self).exec(msg['data'])
                except Exception as e:
                    # How do we clean up locks and stuff?
                    self.logger.error(f"Caught exception: {e}\n\n{traceback.print_exc()}")
                    # TODO: a little out of style
                    self.api_client.send_queue.put({'task_id': msg['task_id'], 'status': 'error'})
                    self.tasks.remove(msg['task_id'])
                    if sync_lock.locked():
                        self.logger.debug("Lock was locked, unlocking.")
                        sync_lock.release()
                    if config.DEBUG:
                        raise e
                    try:
                        import sentry_sdk
                        sentry_sdk.capture_exception(e)
                    except ImportError:
                        pass
        except KeyboardInterrupt:
            self.logger.warning("Received SIGINT, exiting...")

    def run_tui(self):
        self.logger.debug("Starting sync TUI")
        check_daw_running()

        projects = self.api_client.get_all_projects()
        start = datetime.datetime.now()
        print(print_hr('='))
        commands.SyncMultipleHandler(str(uuid.uuid4()), self.api_client, self).handle({'projects': projects})
        print(print_hr('='))
        print(print_hr('='))
        self.logger.info("All projects up-to-date. Took {} seconds.".format((datetime.datetime.now() - start).seconds))

        self.logger.info(
            "Would you like to check out the studio for up to 8 hours? This will prevent other users from making "
            "edits, as to avoid conflicts.")
        if get_input_choice(("yes", "No")) == "yes":
            # TODO: don't check out all projects
            for project in projects:
                check_out(project, self.api_client)
            self.logger.info(
                "Alright, it's all yours. This window will stay open. Please remember to check in when you "
                "are done.")
            input("[enter] to check in")
            projects = self.api_client.get_all_projects()
            commands.SyncMultipleHandler(str(uuid.uuid4()), self.api_client, self).handle({'projects': projects})


sync_lock = Lock()
