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

PACKAGE = None
LOGPATH = None
try:
    from local_update import PACKAGE, LOGPATH
except ImportError:
    pass

APP_NAME = "syncprojects"
EXE_NAME = "main"
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
    cmd = f"{get_install_location() / EXE_NAME}.exe"
    logger.debug(f"Run command: `{cmd}`")
    execl(cmd, cmd)


def create_shortcut():
    make_shortcut(str(get_install_location() / f"{EXE_NAME}.exe"),
                  name=APP_NAME.title(),
                  description=f"{APP_NAME} desktop client",
                  icon=str(get_install_location() / ICON_FILE),
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
    parser.add_argument('update_archive', nargs='?', default=PACKAGE)
    parser.add_argument('logpath', nargs='?', default=LOGPATH)
    parser.add_argument('-d', '--delete-archive', action='store_true')
    parser.add_argument('-k', '--kill-parent', action='store_true')
    # parser.add_argument('old_pid', type=int)
    args = parser.parse_args()
    if not args.update_archive:
        parser.print_usage()
        sys.exit(0)

    logger = logging.getLogger('syncprojects-update')
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)
    if args.logpath:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(join(args.logpath, f"{APP_NAME}-update.log"))
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.info(f"Logging debug output to {args.logpath}-update.log")
    if args.kill_parent:
        if not kill_old_process():
            logger.critical("Couldn't kill old process. Update failed!")
            sys.exit(-1)

    if args.update_archive.startswith('http'):
        logger.info("Fetching update from URL...")
        archive_path = fetch_update(args.update_archive)
    else:
        logger.info("Update is local archive")
        archive_path = args.update_archive

    try:
        install_program(archive_path)
    except Exception as e:
        logger.critical(f"Failed to install update! {e}\n{traceback.print_exc()}")
        sys.exit(-1)
    if sys.platform == "win32":
        logger.info("Installing to start menu and desktop...")
        create_shortcut()

    if args.delete_archive:
        logger.debug("Unlinking archive file...")
        unlink(archive_path)

    logger.info("Starting new program...")
    start_program()