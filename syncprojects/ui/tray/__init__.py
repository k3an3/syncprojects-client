import logging
from multiprocessing import Queue, Process
from os.path import isfile
from typing import Dict

import pystray
from PIL import Image
from pystray import MenuItem, Menu

from syncprojects.system import open_app_in_browser
from syncprojects.ui.settings_menu import SettingsUI
from syncprojects.utils import find_data_file, commit_settings, add_to_command_queue, request_local_api

ICON_FILE = "benny.ico"
logger = logging.getLogger('syncprojects.ui.tray')


def open_app_action():
    logger.debug("Requested to open app in browser")
    open_app_in_browser()


def settings_action():
    settings = SettingsUI()
    logger.info("Running settings UI")
    settings.run()
    commit_settings(settings)
    logger.info("Done")


class TrayIcon(Process):
    def __init__(self):
        super().__init__(daemon=True)
        self.logger = logging.getLogger('syncprojects.ui.tray.TrayIcon')

    # noinspection PyUnusedLocal
    @staticmethod
    def send_command(command: str, data: Dict = None) -> str:
        return request_local_api(command)

    def logs_action(self):
        self.logger.debug("Requested logs")
        self.send_command('logs')

    def update_action(self):
        self.logger.debug("Requested to update")
        self.send_command('update')

    def exit_action(self):
        logger.debug("Requested to exit")
        self.send_command('shutdown')

    def run(self):
        self.logger.debug("Starting icon thread...")
        icon_file = find_data_file(ICON_FILE)
        if not isfile(icon_file):
            self.logger.critical("Icon file not found!")
        image = Image.open(icon_file)
        menu = Menu(
            MenuItem('Open Syncprojects', open_app_action, default=True),
            MenuItem('Check for updates', self.update_action),
            MenuItem('Settings', settings_action),
            MenuItem('Send Logs', self.logs_action),
            MenuItem('Exit', self.exit_action),
        )
        icon = pystray.Icon("syncprojects", image, "syncprojects", menu)
        self.logger.debug("Starting icon loop...")
        icon.run()


if __name__ == "__main__":
    # For standalone mode
    t = TrayIcon()
    t.run()
