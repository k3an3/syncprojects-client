import datetime
import functools
import getpass
import logging
import pathlib
import sys
import traceback

import jwt
from flask import request, abort
from jwt import DecodeError, ExpiredSignatureError
from sqlitedict import SqliteDict

from syncprojects.config import DEV_PUBLIC_KEY, PROD_PUBLIC_KEY, DEBUG

logger = logging.getLogger('syncprojects.utils')


def fmt_error(func, e):
    return "Error during {}:\n{} {}".format(func, e, traceback.format_exc())


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
                data = request.args['data']
            return f(jwt.decode(data, get_public_key(), algorithms=["RS256"]), *args, **kwargs)
        except (ExpiredSignatureError, KeyError, ValueError, DecodeError) as e:
            if DEBUG:
                raise e
            abort(403)
        except TypeError as e:
            if DEBUG:
                raise e
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
        'amp_preset_sync_dir': config.AMP_PRESET_DIR,
        'neural_dsp_path': config.NEURAL_DSP_PATH,
        'legacy_mode': config.LEGACY_MODE,
    })
    new_config.commit()
    logger.info("Finished migration.")


def get_or_create_config():
    config_dir = get_datadir("syncprojects")
    config_created = False
    try:
        logger.debug(f"Creating new datadir in {config_dir}")
        config_dir.mkdir(parents=True)
        config_created = True
    except FileExistsError:
        logger.debug(f"Datadir already exists at {config_dir}")
    loaded_config = SqliteDict(str(config_dir / "config.sqlite"))
    if config_created:
        logger.info("Performing migration to new config storage...")
        migrate_old_settings(loaded_config)
    loaded_config.autocommit = True
    return loaded_config, config_created


appdata, created = get_or_create_config()
