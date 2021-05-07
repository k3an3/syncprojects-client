import logging
from os.path import isfile
from threading import Thread

import pystray
from PIL import Image
from pystray import MenuItem, Menu

from syncprojects.utils import open_app_in_browser, call_api, find_data_file

ICON_FILE = "benny.ico"
logger = logging.getLogger('syncprojects.ui.tray')


def open_app_action():
    logger.debug("Requested to open app in browser")
    open_app_in_browser()


def exit_action():
    logger.debug("Requested to exit")
    call_api('shutdown')


def update_action():
    logger.debug("Requested to update")
    call_api('update')


class TrayIcon(Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.logger = logging.getLogger('syncprojects.ui.tray.TrayIcon')

    def run(self):
        self.logger.debug("Starting icon thread...")
        icon_file = find_data_file(ICON_FILE)
        if not isfile(icon_file):
            self.logger.critical("Icon file not found!")
            # last ditch fallback to cwd
            icon_file = ICON_FILE
        image = Image.open(icon_file)
        menu = Menu(
            MenuItem('Open App', open_app_action, default=True),
            MenuItem('Check for updates', update_action),
            MenuItem('Exit', exit_action),
        )
        icon = pystray.Icon("syncprojects", image, "syncprojects", menu)
        self.logger.debug("Starting icon loop...")
        icon.run()


if __name__ == "__main__":
    # For testing
    t = TrayIcon()
    t.run()
