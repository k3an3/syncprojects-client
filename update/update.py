import logging
import traceback
from argparse import ArgumentParser
from os import makedirs, getppid, execl, unlink
from tempfile import NamedTemporaryFile
from threading import Thread
from tkinter import Tk, ttk, BOTH, TOP, Label
from tkinter.messagebox import showerror
from tkinter.ttk import Frame
from zipfile import ZipFile

import psutil
import requests
import sys
from pyshortcuts import make_shortcut

PACKAGE = None
PRE_UPDATE = None
POST_UPDATE = None
try:
    from local_update import *
except ImportError:
    pass

APP_NAME = "syncprojects"
EXE_NAME = "syncprojects_app"
ICON_FILE = "benny.ico"
WINDOWS_STARTUP = """@echo off
start cmd /c \"{path} && exit 0\"
"""

update_success = False


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


def get_startup_path():
    home = pathlib.Path.home()

    if sys.platform == "win32":
        return home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
    elif sys.platform == "linux":
        raise NotImplementedError()
    elif sys.platform == "darwin":
        raise NotImplementedError()


def install_startup():
    create_shortcut(str(get_startup_path()))


def remove_old_install():
    rmtree(get_install_location())


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


def create_shortcut(folder: str = None):
    make_shortcut(str(get_install_location() / f"{EXE_NAME}.exe"),
                  name=APP_NAME.title(),
                  description=f"{APP_NAME} desktop client",
                  icon=str(get_install_location() / ICON_FILE),
                  terminal=True,
                  executable=None,
                  folder=folder)


def fetch_update(url: str) -> str:
    ntf = NamedTemporaryFile(delete=False)
    resp = requests.get(url)
    resp.raise_for_status()
    ntf.write(resp.content)
    ntf.close()
    return ntf.name


def run_ui(root):
    ft = Frame()
    label = Label(text=f"Updating {APP_NAME}...")
    label.pack()
    progress_bar = ttk.Progressbar(ft, orient='horizontal', mode='indeterminate')
    progress_bar.pack(expand=True, fill=BOTH, side=TOP)
    progress_bar.start(10)
    ft.pack(expand=True, fill=BOTH, side=TOP)
    root.mainloop()


def update(root):
    try:
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

        # TODO: Needs more testing. Old dir still in use
        # remove_old_install()

        try:
            install_program(archive_path)
        except Exception as e:
            logger.critical(f"Failed to install update! {e}\n{traceback.print_exc()}")
            sys.exit(-1)

        if args.delete_archive:
            logger.debug("Unlinking archive file...")
            unlink(archive_path)
        global update_success
        update_success = True
    except Exception as e:
        logger.critical(str(e))
        showerror(master=root, title="Syncprojects Install Error", message="Critical error during installation!"
                                                                           "\nContact support.")
        traceback.print_exc()
        sys.exit(-1)
    finally:
        root.destroy()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('update_archive', nargs='?', default=PACKAGE)
    parser.add_argument('logpath', nargs='?')
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
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ntf = NamedTemporaryFile(delete=False, prefix=f"{APP_NAME}-update-", suffix=".txt")
    fh = logging.FileHandler(ntf.name)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.info(f"Logging debug output to {ntf.name}")

    if PRE_UPDATE:
        logger.info("Running pre update script...")
        PRE_UPDATE()

    tk = Tk()
    tk.title(f"{APP_NAME.title()} updater")

    update_thread = Thread(target=update, args=(tk,), daemon=True)
    update_thread.start()
    run_ui(tk)
    if sys.platform == "win32":
        logger.info("Installing to start menu and desktop...")
        create_shortcut()
        logger.info("Installing startup...")
        install_startup()
    if POST_UPDATE:
        logger.info("Running post update script...")
        POST_UPDATE()
    if update_success:
        logger.info("Starting new program...")
        start_program()
