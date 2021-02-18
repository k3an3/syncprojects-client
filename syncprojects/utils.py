import datetime
import functools
import getpass
import pathlib
import sys
import traceback
from os.path import join

import jwt
from flask import request, abort
from jwt import DecodeError, ExpiredSignatureError
from sqlitedict import SqliteDict

from syncprojects.config import DEV_PUBLIC_KEY, PROD_PUBLIC_KEY


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


def get_public_key():
    return PROD_PUBLIC_KEY or DEV_PUBLIC_KEY


def get_verified_data(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        try:
            if request.method == "POST":
                data = request.get_json()['data']
            else:
                data = request.params['data']
            return f(jwt.decode(data, get_public_key(), algorithms=["RS256"]), *args, **kwargs)
        except (ExpiredSignatureError, KeyError, ValueError, DecodeError):
            abort(403)
        except TypeError:
            abort(400)

        return f(*args, **kwargs)

    return wrapped


def migrate_old_settings(new_config):
    import config
    new_config.update({
        'source': config.SOURCE,
        'default_dest': config.DEFAULT_DEST,
        'local_hash_store': config.LOCAL_HASH_STORE,
        'remote_hash_store': config.REMOTE_HASH_STORE,
        'smb_drive': config.SMB_DRIVE,
        'smb_server': config.SMB_SERVER,
        'smb_share': config.SMB_SHARE,
        'firewall_api_url': config.FIREWALL_API_URL,
        'firewall_api_key': config.FIREWALL_API_KEY,
        'firewall_name': config.FIREWALL_NAME,
        'dest_mapping': config.DEST_MAPPING,
        'mutex_path': config.MUTEX_PATH,
        'update_path_glob': config.UPDATE_PATH_GLOB,
        'telemetry_file': config.TELEMETRY,
        'log_level': config.LOG_LEVEL,
        'amp_preset_sync_dir': config.AMP_PRESET_DIR,
        'neural_dsp_path': config.NEURAL_DSP_PATH,
        'legacy_mode': config.LEGACY_MODE,
    })
    new_config.commit()


def get_or_create_config():
    config_dir = get_datadir("syncprojects")
    config_created = False
    try:
        config_dir.mkdir(parents=True)
    except FileExistsError:
        config_created = True
    loaded_config = SqliteDict(str(config_dir / "config.db"))
    if config_created:
        migrate_old_settings(loaded_config)
    loaded_config.autocommit = True
    return loaded_config, config_created


appdata, created = get_or_create_config()
