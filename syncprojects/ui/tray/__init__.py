import logging
from multiprocessing import Queue
from os.path import isfile
from threading import Thread
from typing import Dict

import pystray
from PIL import Image
from pystray import MenuItem, Menu

from syncprojects.system import open_app_in_browser
from syncprojects.ui.settings_menu import SettingsUI
from syncprojects.utils import find_data_file, commit_settings, add_to_command_queue

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


class TrayIcon(Thread):
    def __init__(self, queue: Queue):
        super().__init__(daemon=True)
        self.logger = logging.getLogger('syncprojects.ui.tray.TrayIcon')
        self.queue = queue

    def queue_put(self, command: str, data: Dict = None) -> str:
        return add_to_command_queue(self.queue, command, data)

    def logs_action(self):
        self.logger.debug("Requested logs")
        self.queue_put('logs')

    def update_action(self):
        self.logger.debug("Requested to update")
        self.queue_put('update')

    def exit_action(self):
        logger.debug("Requested to exit")
        self.queue_put('shutdown')

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
    # For testing
    t = TrayIcon()
    t.run()
