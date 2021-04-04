import traceback

import datetime
import logging
import os
import uuid
from abc import ABC, abstractmethod
from typing import Dict

from syncprojects import config
from syncprojects.api import SyncAPI
from syncprojects.commands import AuthHandler, SyncMultipleHandler, WorkOnHandler, WorkDoneHandler, GetTasksHandler, \
    ShutdownHandler
from syncprojects.storage import appdata
from syncprojects.sync.operations import check_out
from syncprojects.utils import check_daw_running, api_unblock, print_hr, get_input_choice


class SyncManager(ABC):
    def __init__(self, api_client: SyncAPI, headless: bool = False):
        self.logger = logging.getLogger(f'syncprojects.sync.{self.__class__.__name__}')
        self.api_client = api_client
        self.headless = headless
        self.tasks = set()

    @abstractmethod
    def sync(self, project: Dict) -> Dict:
        pass

    def run_service(self):
        self.logger.debug("Starting syncprojects-client service")
        self.headless = True
        try:
            while msg := self.api_client.recv_queue.get():
                self.logger.debug(f"Received {msg['task_id']=} {msg['msg_type']=} {msg['data']=}")
                try:
                    {
                        'auth': AuthHandler,
                        'sync': SyncMultipleHandler,
                        'workon': WorkOnHandler,
                        'workdone': WorkDoneHandler,
                        'tasks': GetTasksHandler,
                        'shutdown': ShutdownHandler,
                    }[msg['msg_type']](msg['task_id'], self.api_client, self).exec(msg['data'])
                except Exception as e:
                    self.logger.error(f"Caught exception: {e}\n\n{traceback.print_exc()}")
                    # TODO: a little out of style
                    # How do we clean up locks and stuff?
                    self.api_client.send_queue.put({'task_id': msg['task_id'], 'status': 'error'})
                    self.tasks.remove(msg['task_id'])
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
        if appdata['firewall_api_url'] and appdata['firewall_api_key']:
            api_unblock()

        projects = self.api_client.get_all_projects()
        start = datetime.datetime.now()
        print(print_hr('='))
        SyncMultipleHandler(str(uuid.uuid4()), self.api_client, self).handle({'projects': projects})
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
            SyncMultipleHandler(str(uuid.uuid4()), self.api_client, self).handle({'projects': projects})

    def sync_amps(self, project: str):
        for amp in self.get_local_neural_dsp_amps():
            self.push_amp_settings(amp, project)
            self.pull_amp_settings(amp, project)

    @abstractmethod
    def push_amp_settings(self, amp: str, project: str):
        pass

    @abstractmethod
    def pull_amp_settings(self, amp: str, project: str):
        pass

    @staticmethod
    def get_local_neural_dsp_amps():
        with os.scandir(appdata['neural_dsp_path']) as entries:
            for entry in entries:
                if entry.is_dir() and entry.name != "Impulse Responses":
                    yield entry.name
