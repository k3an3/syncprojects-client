import logging
import pathlib
import traceback
from argparse import ArgumentParser
from os import makedirs, getppid, execl, unlink
from os.path import isfile, join
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

import psutil
import requests
import sys
from pyshortcuts import make_shortcut

try:
    from local_update import PACKAGE, LOGPATH
except ImportError:
    PACKAGE = None
    LOGPATH = None

APP_NAME = "syncprojects"
ICON_FILE = "benny.ico"
WINDOWS_STARTUP = """@echo off
start cmd /c \"{path} && exit 0\"
"""


def get_install_location():
    home = pathlib.Path.home()

    if sys.platform == "win32":
        return home / "AppData/Local" / APP_NAME
    elif sys.platform == "linux":
        return home / ".local/share" / APP_NAME
    elif sys.platform == "darwin":
        return home / "Library/Application Support" / APP_NAME


def get_start_menu_path():
    home = pathlib.Path.home()

    if sys.platform == "win32":
        return home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs" / f"{APP_NAME}.bat"
    elif sys.platform == "linux":
        raise NotImplementedError()
    elif sys.platform == "darwin":
        raise NotImplementedError()


def get_startup_file():
    home = pathlib.Path.home()

    if sys.platform == "win32":
        return home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup" / f"{APP_NAME}.bat"
    elif sys.platform == "linux":
        raise NotImplementedError()
    elif sys.platform == "darwin":
        raise NotImplementedError()


def install_startup(force: bool = False):
    path = get_startup_file()
    if force or not isfile(path):
        with open(path, "w") as f:
            f.write(WINDOWS_STARTUP)


def kill_old_process():
    p = psutil.Process(getppid())
    logger.debug(f"Killing PID {p.pid} ({p.name})")
    p.terminate()
    return_code = p.wait()
    logger.debug(f"Kill return code was {return_code}")
    return return_code


def install_program(archive):
    path = get_install_location()
    logger.debug(f"Using install path {path}, creating dir if not exists")
    makedirs(path, exist_ok=True)
    with ZipFile(archive) as zf:
        logger.debug(f"Extracting {archive}")
        zf.extractall(path=path)


def start_program():
    execl(get_install_location() / f"{APP_NAME}.exe")


def create_shortcut():
    make_shortcut(get_install_location() / f"{APP_NAME}.exe",
                  name=APP_NAME.title(),
                  description=f"{APP_NAME} desktop client",
                  icon=get_install_location() / ICON_FILE,
                  terminal=True,
                  executable=None)


def fetch_update(url: str) -> str:
    ntf = NamedTemporaryFile(delete=False)
    resp = requests.get(url)
    resp.raise_for_status()
    ntf.write(resp.content)
    ntf.close()
    return ntf.name


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('update_archive')
    parser.add_argument('logpath', required=False)
    parser.add_argument('-d', '--delete-archive', action='store_true')
    # parser.add_argument('old_pid', type=int)
    args = parser.parse_args()

    logger = logging.getLogger('syncprojects-update')
    logger.setLevel(logging.DEBUG)
    if args.logfile() or LOGPATH:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(join(args.logpath or LOGPATH, f"{APP_NAME}-update.log"))
        fh.setLevel(logging.DEBUGargs.update_archive.startswith("http"))
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.info(f"Logging debug output to {args.logpath or LOGPATH}-update.log")
    if not kill_old_process():
        logger.critical("Couldn't kill old process. Update failed!")
        sys.exit(-1)

    update = args.update_archive or PACKAGE
    if update.startswith('http'):
        logger.info("Fetching update from URL...")
        archive_path = fetch_update(update)
    else:
        logger.info("Update is local archive")
        archive_path = update

    try:
        install_program(archive_path)
    except Exception as e:
        logger.critical(f"Failed to install update! {e}\n{traceback.print_exc()}")
        sys.exit(-1)
    if sys.platform == "win32":
        logger.debug("Installing to start menu...")

    if args.delete_archive:
        logger.debug("Unlinking archive file...")
        unlink(archive_path)
