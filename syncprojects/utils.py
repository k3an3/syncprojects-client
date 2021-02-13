import traceback
from os.path import join

from syncprojects.main import TELEMETRY, LOG_LEVEL, format_time, DEFAULT_DEST, current_user


def error_log(func, e):
    log("Error during {}:\n".format(func), str(e),
        str(traceback.format_exc()), quiet=True)


def log(*args, **kwargs):
    level = kwargs.pop('level', 0)
    if not kwargs.pop('quiet', None):
        print(*args, **kwargs)
    if TELEMETRY and level <= LOG_LEVEL:
        try:
            with open(TELEMETRY, "a") as f:
                f.write("[{}]({}) {}{}".format(format_time(), level, kwargs.get('sep', ' ').join(args),
                                               kwargs.get('endl', '\n')))
        except Exception:
            with open(join(DEFAULT_DEST, f"{current_user()}_syncprojects_debug.txt"), "a") as f:
                f.write("[{}] ERROR IN LOGGING:\n{}".format(format_time(), traceback.format_exc()))