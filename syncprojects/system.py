import logging
import os
import pathlib
import platform
import subprocess
import webbrowser
from os import readlink, symlink

import psutil

from syncprojects import config

logger = logging.getLogger('syncprojects.system')


def get_host_platform() -> str:
    return platform.system()


def get_host_arch() -> str:
    return platform.machine()


def get_host_string() -> str:
    return "-".join((get_host_arch(), get_host_platform())).lower()


def open_app_in_browser():
    webbrowser.open(config.SYNCPROJECTS_URL)


def test_mode() -> bool:
    return os.getenv('TEST', '0') == '1'


# noinspection PyUnresolvedReferences
def move_file_on_reboot(src, dst):
    try:
        # pylint: disable=undefined-variable
        win32file.MoveFileEx(src, dst, win32file.MOVEFILE_DELAY_UNTIL_REBOOT)
    except Exception as e:
        from syncprojects.utils import fmt_error
        logger.error(fmt_error("pending file move", e))


def process_running(regex):
    for process in psutil.process_iter():
        if regex.search(process.name()):
            return process


def handle_link(src_name, dst_name, verbose, dry_run):
    link_dest = readlink(src_name)
    if verbose >= 1:
        logger.debug(f"linking {dst_name} -> {link_dest}")
    if not dry_run:
        symlink(link_dest, dst_name)
    return dst_name


def mount_persistent_drive():
    from syncprojects.storage import appdata
    try:
        subprocess.run(
            ["net", "use", appdata['smb_drive'],
             f"\\\\{appdata['smb_server']}\\{appdata['smb_share']}",
             "/persistent:Yes"],
            check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Drive mount failed! {e}")


def open_default_app(path: str):
    if get_host_platform() == "Windows":
        # os.startfile only exists on Windows
        # pylint: disable=no-name-in-module
        from os import startfile  # type: ignore
        return startfile(path)
    try:
        return subprocess.Popen(['open', path])
    except FileNotFoundError:
        return subprocess.Popen(['xdg-open', path])


def get_datadir(app: str) -> pathlib.Path:
    """
    Returns a parent directory path
    where persistent application data can be stored.

    # linux: ~/.local/share
    # macOS: ~/Library/Application Support
    # windows: C:/Users/<USER>/AppData/Roaming
    """

    home = pathlib.Path.home()

    plat = get_host_platform()

    if plat == "Windows":
        return home / "AppData/Roaming" / app
    elif plat == "Linux":
        return home / ".local/share" / app
    elif plat == "Darwin":
        return home / "Library/Application Support" / app
    else:
        raise NotImplementedError
