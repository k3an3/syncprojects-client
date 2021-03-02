import getpass
import traceback
from glob import glob
from os import readlink, symlink
from os.path import join, isfile, abspath, dirname, basename

import datetime
import functools
import jwt
import logging
import pathlib
import psutil
import re
import requests
import subprocess
import sys
from argparse import ArgumentParser
from flask import request, abort
from jwt import DecodeError, ExpiredSignatureError
from pathlib import Path
from shutil import copyfile

import syncprojects.config as config

logger = logging.getLogger('syncprojects.utils')


def get_config_path():
    return str(get_datadir('syncprojects') / "config.sqlite")


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


def verify_data(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        try:
            if request.method == "POST":
                data = request.get_json()['data']
            else:
                data = request.args['data']
            return f(jwt.decode(data, config.PUBLIC_KEY, algorithms=["RS256"]), *args, **kwargs)
        except (ExpiredSignatureError, KeyError, ValueError, DecodeError) as e:
            if config.DEBUG:
                raise e
            abort(403)
        except TypeError as e:
            if config.DEBUG:
                raise e
            abort(400)

        return f(*args, **kwargs)

    return wrapped


def migrate_old_settings(new_config):
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


def get_patched_progress():
    # Import a clean version of the entire package.
    import progress

    # Import the wraps decorator for copying over the name, docstring, and other metadata.
    from functools import wraps

    # Get the current platform.
    from sys import platform

    # Check if we're on Windows.
    if platform.startswith("win"):
        # Disable HIDE_CURSOR and SHOW_CURSOR characters.
        progress.HIDE_CURSOR = ''
        progress.SHOW_CURSOR = ''

    # Create a patched clearln function that wraps the original function.
    @wraps(progress.Infinite.clearln)
    def patchedclearln(self):
        # Get the current platform.
        from sys import platform
        # Some sort of check copied from the source.
        if self.file and self.is_tty():
            # Check if we're on Windows.
            if platform.startswith("win"):
                # Don't use the character.
                print('\r', end='', file=self.file)
            else:
                # Use the character.
                print('\r\x1b[K', end='', file=self.file)

    # Copy over the patched clearln function into the imported clearln function.
    progress.Infinite.clearln = patchedclearln

    # Return the modified version of the entire package.
    return progress


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


# noinspection PyUnresolvedReferences
def move_file_on_reboot(src, dst):
    try:
        # pylint: disable=undefined-variable
        win32file.MoveFileEx(src, dst, win32file.MOVEFILE_DELAY_UNTIL_REBOOT)
    except Exception as e:
        logger.error(fmt_error("pending file move", e))


# TODO: prompt server instead
def get_input_choice(options):
    formatted_options = '[{}]: '.format('/'.join(["[{}]{}".format(o[0], o[1:]) for o in options]))
    while True:
        logger.info(formatted_options)
        s = input()
        # match partial option
        for sel in options:
            if len(s) > 1:
                logger.info("Did you know? You don't need to type the entire word. Save some time and just type the "
                            "first character, indicated by \"[{}].\"".format(s[0]))
            if s and sel.lower().startswith(s.lower()):
                logger.debug(f"User selected '{sel}' by typing '{s}':")
                return sel.lower()
            elif not s and sel[0].isupper():
                # Default
                return sel


def print_hr(char="-", chars=79):
    return char * chars


def print_latest_change(directory_path):
    changelog_file = join(directory_path, "changelog.txt")
    if not isfile(changelog_file):
        return
    with open(changelog_file) as f:
        lines = f.readlines()
    start = None
    end = None
    for n, line in enumerate(lines):
        if not start and line.startswith('--') and line.rstrip().endswith('--'):
            start = n
        elif start and not line.strip():
            end = n
            break
    if start:
        print("Latest changes:\n~~~")
        print(''.join(lines[start:end]))
        print("~~~")


def clean_up():
    try:
        current_file = abspath(sys.argv[0])
        for file in glob(join(dirname(current_file), config.BINARY_CLEAN_GLOB)):
            try:
                logger.debug(f"Unlinking {file}.")
                Path(file).unlink()
            except:
                logger.debug(f"Couldn't unlink {file}.")
    except Exception as e:
        logger.error(fmt_error("cleanup", e))


def update():
    local_file = abspath(sys.argv[0])
    logger.info("Checking for updates...")
    if not isfile(local_file):
        logger.info("Failed to resolve local file for update. Skipping...")
        return
    try:
        remote_file = glob(config.UPDATE_PATH_GLOB)[::-1][0]
    except IndexError:
        logger.info("Update file not found. Skipping...")
        return

    remote_hash = hash_file(remote_file)
    local_hash = hash_file(local_file)
    logger.debug(f"{local_file=} {local_hash=} {remote_file=} {remote_hash=}")
    if not local_hash == remote_hash:
        logger.info(f"Updating to {basename(remote_file)} from {local_file}")
        new_path = join(dirname(local_file), "syncprojects-{}.exe".format(int(datetime.datetime.now().timestamp())))
        copyfile(remote_file, new_path)
        move_file_on_reboot(new_path, join(dirname(local_file), 'syncprojects-latest.exe'))
        return subprocess.run([join(dirname(local_file), new_path)])


def hash_file(file_path, hash_algo=None, block_size=4096):
    if not hash_algo:
        hash_algo = config.DEFAULT_HASH_ALGO()
    with open(file_path, 'rb') as fp:
        while True:
            data = fp.read(block_size)
            if data:
                hash_algo.update(fp.read())
            else:
                break
    return hash_algo.hexdigest()


def mount_persistent_drive():
    try:
        subprocess.run(
            ["net", "use", config.SMB_DRIVE, f"\\\\{config.SMB_SERVER}\\{config.SMB_SHARE}", "/persistent:Yes"],
            check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Drive mount failed! {e.output.decode()}")


def api_unblock():
    logger.info("Requesting firewall exception... ")
    try:
        r = requests.post(config.FIREWALL_API_URL + "firewall/unblock",
                          headers={'X-Auth-Token': config.FIREWALL_API_KEY},
                          data={'device': config.FIREWALL_NAME})
    except Exception as e:
        logger.error(fmt_error("api_unblock", e))
        logger.warning("failed! Hopefully the sync still works...")
    if r.status_code == 204:
        logger.info("success!")
    else:
        logger.error(f"error code {r.status_code}")


def validate_changelog(changelog_file):
    r = re.compile(r'^-- [a-zA-Z0-9_-]+: ([0-9]{2}:){2}[0-9]{2} ([0-9]{2}-){2}[0-9]{4} --$')
    with open(changelog_file) as f:
        header = None
        inside_entry = False
        bullets = 0
        complete = False
        for line in f.readlines()[3:]:
            line = line.rstrip()
            # Seen nothing yet; look for header with username/date
            if not header and not inside_entry and r.match(line):
                header = line
            # Seen the header already, look for the opening divider
            elif not inside_entry and header and line.startswith('============'):
                inside_entry = True
            # Seen the header and opening divider
            elif header and inside_entry:
                # Line is a valid bullet, count these
                if line.startswith('* '):
                    bullets += 1
                # Seen at least one bullet, but current line is blank. Good to go.
                elif bullets > 0 and not line:
                    header = None
                    inside_entry = False
                    bullets = 0
                    complete = True
                else:
                    return f"Unexpected entry within block {header}:\n~~~\n{line}\n~~~\nA valid block looks like:\n-- User: HH:MM:SS MM-DD-YYYY --\n===============================\n* A bullet point\n* Another bullet point"
            # Outside block, line is empty
            elif not line.rstrip():
                continue
            # A complete block was parsed, and we reached the next header. Return successful validation.
            elif complete and r.match(line):
                return False
            else:
                return f"Unexpected text in body:\n~~~\n{line}\n~~~"
        return False


def check_daw_running():
    if p := process_running(config.DAW_PROCESS_REGEX):
        logger.warning(
            f"\nWARNING: It appears that your DAW is running ({p.name()}).\nThat's fine, but please close any open "
            f"synced projects before proceeding, else corruption may occur.")
        if get_input_choice(("Proceed", "cancel")) == "cancel":
            raise SystemExit


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--service', action='store_true')
    parser.add_argument('--tui', action='store_true')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--sync', action='store_true')
    return parser.parse_args()
