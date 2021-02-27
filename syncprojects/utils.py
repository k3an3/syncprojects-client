import datetime
import functools
import getpass
import logging
import pathlib
import subprocess
import sys
import traceback
from concurrent.futures.thread import ThreadPoolExecutor
from glob import glob
from os import listdir, readlink, symlink
from os.path import join, islink, isdir, isfile, abspath, dirname, basename
from pathlib import Path
from shutil import copyfile

import jwt
import psutil
from flask import request, abort
from jwt import DecodeError, ExpiredSignatureError
from progress.bar import IncrementalBar

import syncprojects.config as config
from syncprojects.main import logger, remote_hash_cache

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


def get_verified_data(f):
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


progress = get_patched_progress()


def copy_tree(src, dst, preserve_mode=1, preserve_times=1,
              preserve_symlinks=0, update=0, verbose=1, dry_run=0,
              progress=True, executor=None, single_depth=False):
    from distutils.file_util import copy_file
    from distutils.dir_util import mkpath

    if not executor:
        executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)

    names = listdir(src)

    if not dry_run:
        mkpath(dst, verbose=verbose)

    outputs = []
    if progress:
        bar = IncrementalBar("Copying", max=len(names))
    for n in names:
        src_name = join(src, n)
        dst_name = join(dst, n)

        if progress:
            bar.next()
        if n.startswith('.nfs'):
            # skip NFS rename files
            continue

        if preserve_symlinks and islink(src_name):
            outputs.append(executor.submit(handle_link, src_name, dst_name, verbose, dry_run))

        elif isdir(src_name) and not single_depth:
            outputs.append(
                executor.submit(
                    copy_tree, src_name, dst_name, preserve_mode,
                    preserve_times, preserve_symlinks, update,
                    verbose=verbose, dry_run=dry_run, progress=False, executor=executor))
        else:
            executor.submit(
                copy_file, src_name, dst_name, preserve_mode,
                preserve_times, update, verbose=verbose,
                dry_run=dry_run)
            outputs.append(dst_name)
    if progress:
        bar.finish()
    return outputs


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


def hash_directory(dir_name):
    hash_algo = config.DEFAULT_HASH_ALGO()
    if isdir(dir_name):
        for file_name in glob(join(dir_name, config.PROJECT_GLOB)):
            if isfile(file_name):
                logger.debug(f"Hashing {file_name}")
                hash_file(file_name, hash_algo)
        hash_digest = hash_algo.hexdigest()
        remote_hash_cache[dir_name] = hash_digest
        return hash_digest
