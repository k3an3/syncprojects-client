import datetime
import getpass
import pathlib
import sys
import traceback
from os.path import join


class Logger:
    def __init__(self, telemetry_file: str, log_level: int = 0, default_dest: str = ""):
        self.log_level = log_level
        self.telemetry_file = telemetry_file
        self.default_dest = default_dest

    def log(self, *args, **kwargs):
        level = kwargs.pop('level', 0)
        if not kwargs.pop('quiet', None):
            print(*args, **kwargs)
        if self.telemetry_file and level <= self.log_level:
            try:
                with open(self.telemetry_file, "a") as f:
                    f.write("[{}]({}) {}{}".format(format_time(), level, kwargs.get('sep', ' ').join(args),
                                                   kwargs.get('endl', '\n')))
            except Exception:
                with open(join(self.default_dest, f"{current_user()}_syncprojects_debug.txt"), "a") as f:
                    f.write("[{}] ERROR IN LOGGING:\n{}".format(format_time(), traceback.format_exc()))

    def error_log(self, func, e):
        self.log("Error during {}:\n".format(func), str(e),
                 str(traceback.format_exc()), quiet=True)


def prompt_to_exit():
    input("[enter] to exit")
    sys.exit(0)


def format_time():
    return datetime.datetime.now().strftime("%H:%M:%S %m-%d-%Y")


def current_user():
    return resolve_username(getpass.getuser())


def resolve_username(user):
    if user == "Admin":
        return "Keane"
    return user


def get_datadir(app: str) -> pathlib.Path:
    """
    Returns a parent directory path
    where persistent application data can be stored.

    # linux: ~/.local/share
    # macOS: ~/Library/Application Support
    # windows: C:/Users/<USER>/AppData/Roaming
    """

    home = pathlib.Path.home()

    if sys.platform == "win32":
        return home / "AppData/Roaming" / app
    elif sys.platform == "linux":
        return home / ".local/share" / app
    elif sys.platform == "darwin":
        return home / "Library/Application Support" / app
