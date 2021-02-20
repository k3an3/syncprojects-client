import concurrent.futures
import datetime
import json
import os
import re
import subprocess
import sys
import traceback
from concurrent.futures.thread import ThreadPoolExecutor
from glob import glob
from os import listdir, readlink, symlink, scandir
from os.path import basename, dirname, expanduser, join, isdir, isfile, abspath, islink
from pathlib import Path
from shutil import copyfile
from threading import Thread

import psutil
import requests
import timeago

import config
from syncprojects.server import app

if os.name == 'nt':
    import win32file
from time import sleep

__version__ = '1.6'

from syncprojects.api import SyncAPI, login_prompt
from syncprojects.utils import format_time, current_user, Logger, prompt_to_exit, appdata

CODENAME = "IT'S IN THE CLOUD"
BANNER = """
███████╗██╗   ██╗███╗   ██╗ ██████╗██████╗ ██████╗  ██████╗      ██╗███████╗ ██████╗████████╗███████╗
██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔══██╗██╔══██╗██╔═══██╗     ██║██╔════╝██╔════╝╚══██╔══╝██╔════╝
███████╗ ╚████╔╝ ██╔██╗ ██║██║     ██████╔╝██████╔╝██║   ██║     ██║█████╗  ██║        ██║   ███████╗
╚════██║  ╚██╔╝  ██║╚██╗██║██║     ██╔═══╝ ██╔══██╗██║   ██║██   ██║██╔══╝  ██║        ██║   ╚════██║
███████║   ██║   ██║ ╚████║╚██████╗██║     ██║  ██║╚██████╔╝╚█████╔╝███████╗╚██████╗   ██║   ███████║
╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝╚═╝     ╚═╝  ╚═╝ ╚═════╝  ╚════╝ ╚══════╝ ╚═════╝   ╚═╝   ╚══════╝
\"{}\"""".format(CODENAME)


def get_local_neural_dsp_amps():
    with scandir(config.NEURAL_DSP_PATH) as entries:
        for entry in entries:
            if entry.is_dir() and entry.name != "Impulse Responses":
                yield entry.name


def push_amp_settings(amp):
    try:
        copy_tree(join(config.NEURAL_DSP_PATH, amp, "User"),
                  join(config.AMP_PRESET_DIR, amp, current_user()),
                  single_depth=True,
                  update=True,
                  progress=False)
    except FileNotFoundError:
        log(traceback.format_exc(), level=2)
        pass


def pull_amp_settings(amp):
    with scandir(join(config.AMP_PRESET_DIR, amp)) as entries:
        for entry in entries:
            if entry.name != current_user():
                copy_tree(entry.path,
                          join(config.NEURAL_DSP_PATH, amp, "User", entry.name),
                          update=True,
                          progress=False)


def sync_amps():
    spinner = Spinner("Syncing Neural DSP presets ")
    for amp in get_local_neural_dsp_amps():
        push_amp_settings(amp)
        spinner.next()
        pull_amp_settings(amp)
        spinner.next()
    print()


class HashStore:
    def __init__(self, hash_store_path):
        self.store = hash_store_path
        self.content = {}

    def get(self, key):
        return self.content.get(key)

    def open(self):
        try:
            with open(self.store) as f:
                self.content = json.load(f)
                return self.content
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            return {}

    def update(self, key, value):
        self.content[key] = value
        with open(self.store, "w") as f:
            json.dump(self.content, f)


local_hs = HashStore(config.LOCAL_HASH_STORE)
remote_hash_cache = {}
local_hash_cache = {}


def mount_persistent_drive():
    try:
        subprocess.run(
            ["net", "use", config.SMB_DRIVE, f"\\\\{config.SMB_SERVER}\\{config.SMB_SHARE}", "/persistent:Yes"],
            check=True)
    except subprocess.CalledProcessError as e:
        log("Drive mount failed!", e.output.decode())


def api_unblock():
    log("Requesting firewall exception... ", end="")
    try:
        r = requests.post(config.FIREWALL_API_URL + "firewall/unblock",
                          headers={'X-Auth-Token': config.FIREWALL_API_KEY},
                          data={'device': config.FIREWALL_NAME})
    except Exception as e:
        error_log("api_unblock", e)
        log("failed! Hopefully the sync still works...")
    if r.status_code == 204:
        log("success!")
    else:
        log("error code", r.status_code)


def copy(dir_name, src, dst, update=True):
    copy_tree(join(src, dir_name), join(dst, dir_name), update=update)


def print_hr(char="-", chars=79):
    return char * chars


def hash_file(file_path, hash=None, block_size=4096):
    if not hash:
        hash = config.DEFAULT_HASH_ALGO()
    with open(file_path, 'rb') as fp:
        while True:
            data = fp.read(block_size)
            if data:
                hash.update(fp.read())
            else:
                break
    return hash.hexdigest()


def hash_directory(dir_name):
    hash = config.DEFAULT_HASH_ALGO()
    if isdir(dir_name):
        for file_name in glob(join(dir_name, config.PROJECT_GLOB)):
            if isfile(file_name):
                log("Hashing", file_name, quiet=True, level=3)
                hash_file(file_name, hash)
        hash_digest = hash.hexdigest()
        remote_hash_cache[dir_name] = hash_digest
        return hash_digest


def is_updated(dir_name, group, remote_hs):
    dest = config.DEST_MAPPING.get(group, config.DEFAULT_DEST)
    src_hash = local_hash_cache[dir_name]
    log("local_hash is", src_hash, quiet=True, level=2)
    dst_hash = remote_hs.get(dir_name)
    remote_hash_cache[join(dest, dir_name)] = dst_hash
    if config.LEGACY_MODE or not dst_hash:
        log("Checking with the slow/old method just in case we missed it...")
        try:
            dst_hash = hash_directory(join(dest, dir_name))
        except FileNotFoundError:
            dst_hash = ""
    log("remote_hash is", dst_hash, quiet=True, level=2)
    known_hash = local_hs.get(dir_name)
    if not known_hash:
        log("Not in database; adding...")
        new_hash = src_hash or dst_hash
        local_hs.update(dir_name, new_hash)
        known_hash = new_hash
    else:
        log("known_hash is", known_hash, quiet=True, level=2)
    if not src_hash == known_hash and not dst_hash == known_hash:
        return "mismatch"
    elif src_hash and (not dst_hash or not src_hash == known_hash):
        return "local"
    elif dst_hash and (not src_hash or not dst_hash == known_hash):
        return "remote"


def get_input_choice(options):
    # TODO: default option
    formatted_options = '[{}]: '.format('/'.join(["[{}]{}".format(o[0], o[1:]) for o in options]))
    while True:
        log(formatted_options, end='', level=1)
        s = input()
        # match partial option
        for sel in options:
            if len(s) > 1:
                log("Did you know? You don't need to type the entire word. Save some time and just type the "
                    "first character, indicated by \"[{}].\"".format(s[0]))
            if s and sel.lower().startswith(s.lower()):
                log(f"User selected '{sel}' by typing '{s}':", quiet=True, level=1)
                return sel.lower()
            elif not s and sel[0].isupper():
                return sel.lower()


def check_out(user, hours=8):
    until = (datetime.datetime.now() + datetime.timedelta(hours=hours)).timestamp()
    lock(project, api_client)
    with open(expanduser(config.MUTEX_PATH), "w") as f:
        f.write("{},{},{}".format(user, until, datetime.datetime.now().timestamp()))


def lock(project, api_client, reason, duration):
    locked = api_client.lock(project, reason, duration)
    if locked['status'] == 'locked':
        if locked['locked_by'] == api_client.username or not locked['until']:
            log("A sync is still running or did not complete successfully.")
            if not locked['locked_by'] == api_client.username:
                log(
                    f"WARNING: It looks like {locked['locked_by']} is/was trying to sync (since {datetime.datetime.fromtimestamp(float(locked['locked_by'])).isoformat()})... maybe talk to them before overriding?")
            choices = ("Try again", "override", "exit")
            choice = None
            while choice not in choices:
                choice = get_input_choice(choices)
            if choice == "exit":
                log("Bailing!")
                raise SystemExit
            elif choice == "override":
                api_client.lock(project, force=True)
        else:
            checked_out_until = datetime.datetime.fromtimestamp(float(locked['until']))
            if ((checked_out_until - datetime.datetime.now()).total_seconds() / 3600) > 0:
                log(
                    f"The studio is currently checked out by {locked['locked_by']} for "
                    f"{timeago.format(checked_out_until, datetime.datetime.now())} hours "
                    f"or until it's checked in.")
                log("Bailing!")
                raise SystemExit


def unlock(project, api_client):
    unlocked = api_client.unlock(project)
    if unlocked['status'] == 'locked':
        log(f"WARNING: The studio could not be unlocked: {unlocked}")
    elif unlocked['status'] == 'unlocked':
        log(f"WARNING: The studio was already unlocked: {unlocked}")


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


def changelog(directory):
    changelog_file = join(config.SOURCE, directory, "changelog.txt")
    if not isfile(changelog_file):
        log("Creating changelog...")
        divider = print_hr("*", config.CHANGELOG_HEADER_WIDTH)
        changelog_header = divider + "\n*{}*\n".format(
            ("CHANGELOG: " + directory).center(config.CHANGELOG_HEADER_WIDTH - 2)) + divider
        with open(changelog_file, "w") as f:
            f.write(changelog_header)
    print("Add a summary of the changes you made to {}, then save and close Notepad.".format(directory))
    user = current_user()
    header = "\n\n-- {}: {} --\n".format(user, format_time())
    header += "=" * (len(header) - 3) + "\n\n"
    with open(changelog_file, "r+") as f:
        lines = f.readlines()
        lines.insert(3, header)
        f.seek(0)
        f.writelines(lines)
    subprocess.run([config.NOTEPAD, changelog_file])
    while err := validate_changelog(changelog_file):
        log("Error! Improper formatting in changelog. Please correct it:\n")
        log(err)
        subprocess.run([config.NOTEPAD, changelog_file])


def clean_up():
    try:
        current_file = abspath(sys.argv[0])
        for file in glob(join(dirname(current_file), config.BINARY_CLEAN_GLOB)):
            try:
                log(f"Unlinking {file}.", quiet=True, level=3)
                Path(file).unlink()
            except:
                log(f"Couldn't unlink {file}.", quiet=True, level=3)
    except Exception as e:
        error_log("cleanup", e)


def move_file_on_reboot(src, dst):
    try:
        win32file.MoveFileEx(src, dst, win32file.MOVEFILE_DELAY_UNTIL_REBOOT)
    except Exception as e:
        error_log("pending file move", e)


def update():
    local_file = abspath(sys.argv[0])
    log("Checking for updates...")
    if not isfile(local_file):
        log("Failed to resolve local file for update. Skipping...")
        return
    try:
        remote_file = glob(config.UPDATE_PATH_GLOB)[::-1][0]
    except IndexError:
        log("Update file not found. Skipping...")
        return

    remote_hash = hash_file(remote_file)
    local_hash = hash_file(local_file)
    log(f"{local_file=} {local_hash=} {remote_file=} {remote_hash=}", quiet=True, level=2)
    if not local_hash == remote_hash:
        log("Updating to", basename(remote_file), "from", local_file)
        new_path = join(dirname(local_file), "syncprojects-{}.exe".format(int(datetime.datetime.now().timestamp())))
        copyfile(remote_file, new_path)
        move_file_on_reboot(new_path, join(dirname(local_file), 'syncprojects-latest.exe'))
        return subprocess.run([join(dirname(local_file), new_path)])


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


def handle_link(src_name, dst_name, verbose, dry_run):
    link_dest = readlink(src_name)
    if verbose >= 1:
        log("linking %s -> %s", dst_name, link_dest, level=3)
    if not dry_run:
        symlink(link_dest, dst_name)
    return dst_name


progress = get_patched_progress()
from progress.bar import IncrementalBar
from progress.spinner import Spinner


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


def check_wants():
    wants_file = join(config.DEFAULT_DEST, 'remote.wants')
    if isfile(wants_file):
        try:
            log("Loading wants file...", quiet=True)
            with open(wants_file) as f:
                wants = json.load(f)
                log("Wants file contains:", wants, quiet=True)
                if wants.get('user') != current_user():
                    log("Wants are not from current user, fetching", level=1, quiet=True)
                    Path(wants_file).unlink()
                    return wants['projects']
                else:
                    log("Wants are from current user, not fetching...", level=1, quiet=True)
        except Exception as e:
            log("Exception in wants:", str(e), quiet=True)
    else:
        log("Didn't find wants file. Skipping...", quiet=True)
    return []


def read_paths():
    paths = set()
    with open(config.CONFIG_PATH) as f:
        for line in f:
            try:
                project, group = line.strip().split(":")
            except ValueError:
                project, group = line.strip(), ""
            paths.add((project, group))
    return paths


def handle_new_project(project_name, remote_hs):
    if project_name not in remote_hs.content:
        for proj in remote_hs.content.keys():
            if project_name.lower() == proj.lower():
                log(
                    f"\nERROR: Your project is named \"{project_name}\", but a similarly named project \"{proj}\" already exists remotely. Please check your spelling/capitalization and try again.")
                unlock()
                prompt_to_exit()


def sync():
    if p := process_running(config.DAW_PROCESS_REGEX):
        log(
            f"\nWARNING: It appears that your DAW is running ({p.name()}).\nThat's fine, but please close any open synced projects before proceeding, else corruption may occur.")
        if get_input_choice(("Proceed", "cancel")) == "cancel":
            unlock()
            raise SystemExit
    if config.FIREWALL_API_URL and config.FIREWALL_API_KEY:
        api_unblock()
    log("Syncing projects...")
    start = datetime.datetime.now()
    log("Opening local database: " + str(local_hs.open()), quiet=True, level=1)
    wants = check_wants()
    remote_stores = {}
    paths = read_paths()

    log("Checking local projects for changes...")
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = {executor.submit(hash_directory, join(config.SOURCE, p[0])): p[0] for p in paths}
        for result in concurrent.futures.as_completed(futures):
            project = futures[result]
            try:
                src_hash = result.result()
            except FileNotFoundError:
                src_hash = ""
            local_hash_cache[project] = src_hash

    for project, group in paths:
        print(print_hr())
        log("Syncing {}...".format(project))
        not_local = False
        if not isdir(join(config.SOURCE, project)):
            log("{} does not exist locally.".format(project))
            not_local = True
        dest = config.DEST_MAPPING.get(group, config.DEFAULT_DEST)
        remote_store_name = join(dest, config.REMOTE_HASH_STORE)
        try:
            # Database already opened, contents cached
            remote_hs = remote_stores[remote_store_name]
        except KeyError:
            remote_hs = HashStore(remote_store_name)
            # Database not opened yet, need to read from disk
            log("Opening remote database: " + str(remote_hs.open()), quiet=True, level=1)
            remote_stores[remote_store_name] = remote_hs
        up = is_updated(project, group, remote_hs)
        if not_local:
            up == "remote"
            handle_new_project(project, remote_hs)
        if project in wants:
            log(f"Overriding because {wants['user']} requested this project!!!!")
            sleep(0.9)
            up = "local"
        if up == "mismatch":
            print_latest_change(join(dest, project))
            log("WARNING: Both local and remote have changed!!!! Which to keep?")
            up = get_input_choice(("local", "remote", "skip"))
        if up == "remote":
            src = dest
            dst = config.SOURCE
            print_latest_change(join(dest, project))
        elif up == "local":
            src = config.SOURCE
            dst = dest
            changelog(project)
        else:
            log("No change for", project)
            continue
        local_hs.update(project, remote_hash_cache[join(src, project)])
        try:
            log("Now copying {} from {} ({}) to {} ({})".format(project, up, src,
                                                                "remote" if up == "local" else "local",
                                                                dst))
            if up == "remote":
                if not get_input_choice(("Confirm", "skip")) == "confirm":
                    continue
            else:
                try:
                    remote_hs.update(project, remote_hash_cache[join(src, project)])
                except Exception as e:
                    error_log("sync:update_remote_hashes", e)
                    if not config.LEGACY_MODE:
                        log("Failed to update remote hashes!")
                        raise e
            copy(project, src, dst)
        except Exception as e:
            log("Error syncing", project, str(e))
            log("If the remote directory does not exist, please remove it from", config.CONFIG_PATH)
            sleep(2)
        else:
            log("Successfully synced", project)
    print(print_hr())
    sync_amps()
    print(print_hr('='))
    log("All projects up-to-date. Took {} seconds.".format((datetime.datetime.now() - start).seconds))


if __name__ == '__main__':
    logger = Logger(config.TELEMETRY, config.LOG_LEVEL, config.DEFAULT_DEST)
    # TODO: quick hack
    log = logger.log
    error_log = logger.error_log

    log(BANNER, level=99)
    log("[v{}]".format(__version__))
    error = []

    # init API client
    api_client = SyncAPI(logger, appdata.get('refresh'), appdata.get('access'), appdata.get('username'))

    # Start local Flask server
    web_thread = Thread(target=app.run, kwargs=dict(debug=config.DEBUG, use_reloader=False), daemon=True)
    web_thread.start()

    if not api_client.has_tokens():
        if not login_prompt(api_client):
            log("Couldn't log in with provided credentials.")
            prompt_to_exit()

    try:
        if config.TELEMETRY:
            print("Logging enabled with loglevel", config.LOG_LEVEL)
        clean_up()
        if config.UPDATE_PATH_GLOB and update():
            raise SystemExit
        if not (config.DEBUG or isdir(config.SOURCE)):
            error.append(f"Error! Source path \"{config.SOURCE}\" not found.")
        for directory in (config.DEFAULT_DEST, *config.DEST_MAPPING.values()):
            if not (config.DEBUG or isdir(directory)):
                error.append(f"Error! Destination path {directory} not found.")
        if error:
            log(*error)
            prompt_to_exit()
        projects = api_client.get_projects()
        for project in projects:
            # TODO: sync one at a time
            lock(project, api_client)
            sync(project)
            unlock(project, api_client)
            api_client.unlock(project)

        log(
            "Would you like to check out the studio for up to 8 hours? This will prevent other users from making "
            "edits, as to avoid conflicts.")
        if get_input_choice(("yes", "No")) == "yes":
            check_out(current_user())
            log("Alright, it's all yours. This window will stay open. Please remember to check in when you are done.")
            input("[enter] to check in")
            sync()
        if not len(sys.argv) > 1:
            prompt_to_exit()
    except Exception as e:
        log("Fatal error! Provide the developer (syncprojects-dev@keane.space) with the following information:\n",
            str(e),
            str(traceback.format_exc()))
        prompt_to_exit()
