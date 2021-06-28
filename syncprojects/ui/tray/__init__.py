import logging
from multiprocessing import Process
from os.path import isfile
from typing import Dict

import pystray
from PIL import Image
from pystray import MenuItem, Menu

from syncprojects.system import open_app_in_browser, is_mac
from syncprojects.utils import find_data_file, request_local_api

if is_mac():
    ICON_FILE = "res/benny.icns"
    # noinspection PyUnresolvedReferences
    from pystray import _darwin
else:
    ICON_FILE = "res/benny.ico"
logger = logging.getLogger('syncprojects.ui.tray')


def open_app_action():
    logger.debug("Requested to open app in browser")
    open_app_in_browser()


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

    def settings_action(self):
        logger.debug("Requested settings")
        self.send_command('settings')

    def run(self):
        self.logger.debug("Starting icon thread...")
        icon_file = find_data_file(ICON_FILE)
        if not isfile(icon_file):
            self.logger.critical("Icon file not resolved! Falling back.")
            icon_file = ICON_FILE
        image = Image.open(icon_file)
        menu = Menu(
            MenuItem('Open Syncprojects', open_app_action, default=True),
            MenuItem('Check for updates', self.update_action),
            MenuItem('Settings', self.settings_action),
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
