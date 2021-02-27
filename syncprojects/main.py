import concurrent.futures
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import traceback
from argparse import ArgumentParser
from concurrent.futures.thread import ThreadPoolExecutor
from os import scandir
from os.path import join, isdir, isfile
from pathlib import Path
from queue import Queue
from threading import Thread

import requests
import timeago

import syncprojects.config as config
from syncprojects.server import app
from syncprojects.storage import appdata, HashStore

if os.name == 'nt':
    pass
from time import sleep

__version__ = '1.6'

from syncprojects.api import SyncAPI, login_prompt
from syncprojects.utils import format_time, current_user, prompt_to_exit, fmt_error, copy_tree, \
    process_running, get_input_choice, print_hr, print_latest_change, clean_up, update, hash_directory

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
        logger.debug(traceback.format_exc())
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
    # TODO: a mess
    from progress import spinner
    spinner = spinner.Spinner("Syncing Neural DSP presets ")
    for amp in get_local_neural_dsp_amps():
        push_amp_settings(amp)
        spinner.next()
        pull_amp_settings(amp)
        spinner.next()
    print()


local_hs = HashStore(config.LOCAL_HASH_STORE)
remote_hash_cache = {}
local_hash_cache = {}


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


def copy(dir_name, src, dst, update=True):
    copy_tree(join(src, dir_name), join(dst, dir_name), update=update)


def is_updated(dir_name, group, remote_hs):
    dest = config.DEST_MAPPING.get(group, config.DEFAULT_DEST)
    src_hash = local_hash_cache[dir_name]
    logger.debug(f"local_hash is {src_hash}")
    dst_hash = remote_hs.get(dir_name)
    remote_hash_cache[join(dest, dir_name)] = dst_hash
    if config.LEGACY_MODE or not dst_hash:
        logger.info("Checking with the slow/old method just in case we missed it...")
        try:
            dst_hash = hash_directory(join(dest, dir_name))
        except FileNotFoundError:
            dst_hash = ""
    logger.debug(f"remote_hash is {dst_hash}")
    known_hash = local_hs.get(dir_name)
    if not known_hash:
        logger.debug(f"didn't exist in database: {dir_name=}")
        logger.info("Not in database; adding...")
        new_hash = src_hash or dst_hash
        local_hs.update(dir_name, new_hash)
        known_hash = new_hash
    else:
        logger.debug(f"known_hash is {known_hash}")
    if not src_hash == known_hash and not dst_hash == known_hash:
        return "mismatch"
    elif src_hash and (not dst_hash or not src_hash == known_hash):
        return "local"
    elif dst_hash and (not src_hash or not dst_hash == known_hash):
        return "remote"


def check_out(project, api_client, hours=8):
    until = (datetime.datetime.now() + datetime.timedelta(hours=hours)).timestamp()
    lock(project, api_client, "checkout", until)


def lock(project, api_client, reason: str = "sync", duration: datetime.datetime = None):
    locked = api_client.lock(project, reason=reason, until=duration)
    logger.debug(f"Got lock response {locked}")
    if 'id' in locked:
        return locked['id']
    if locked['status'] == 'locked':
        if not locked.get('until'):
            logger.warning(f"{project['name']}: A sync is still running or did not complete successfully.")
            if not locked['locked_by'] == "self":
                logger.warning(
                    f"WARNING: It looks like {locked['locked_by']} is/was trying to sync (since {datetime.datetime.fromtimestamp(float(locked['since'])).isoformat()})... maybe talk to them before overriding?")
            choices = ("Try again", "override", "exit")
            choice = None
            while choice not in choices:
                choice = get_input_choice(choices)
            if choice == "exit":
                logger.info("Bailing!")
                raise SystemExit
            elif choice == "override":
                api_client.lock(project, force=True)
            elif choice == "Try Again":
                lock(project, api_client, reason, duration)
        elif not locked['locked_by'] == "self":
            checked_out_until = datetime.datetime.fromtimestamp(float(locked['until']))
            if ((checked_out_until - datetime.datetime.now()).total_seconds() / 3600) > 0:
                logger.info(
                    f"The project is currently checked out by {locked['locked_by']} for "
                    f"{timeago.format(checked_out_until, datetime.datetime.now())} hours "
                    f"or until it's checked in.")
                logger.info("Bailing!")
                raise SystemExit
            else:
                logger.debug("Expiring lock as time has passed. Server should have cleaned this up.")
        else:
            logger.debug("Hit lock() fallthrough case!")


def unlock(project, api_client):
    unlocked = api_client.unlock(project)
    if unlocked.get("result") == "success":
        logger.debug("Successful unlock")
    elif unlocked['status'] == 'locked':
        logger.warning(f"WARNING: The studio could not be unlocked: {unlocked}")
    elif unlocked['status'] == 'unlocked':
        logger.warning(f"WARNING: The studio was already unlocked: {unlocked}")


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
        logger.info("Creating changelog...")
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
        logger.warning("Error! Improper formatting in changelog. Please correct it:\n")
        logger.warning(err)
        subprocess.run([config.NOTEPAD, changelog_file])


def check_wants():
    wants_file = join(config.DEFAULT_DEST, 'remote.wants')
    if isfile(wants_file):
        try:
            logger.debug("Loading wants file...")
            with open(wants_file) as f:
                wants = json.load(f)
                logger.debug(f"Wants file contains: {wants}")
                if wants.get('user') != current_user():
                    logger.debug("Wants are not from current user, fetching")
                    Path(wants_file).unlink()
                    return wants['projects']
                else:
                    logger.debug("Wants are from current user, not fetching...")
        except Exception as e:
            logger.debug("Exception in wants:" + str(e))
    else:
        logger.debug("Didn't find wants file. Skipping...")
    return []


def handle_new_song(song_name, remote_hs):
    if song_name not in remote_hs.content:
        for song in remote_hs.content.keys():
            if song_name.lower() == song.lower():
                logger.error(
                    f"\nERROR: Your song is named \"{song_name}\", but a similarly named song \"{song}\" "
                    f"already exists remotely. Please check your spelling/capitalization and try again.")
                # TODO
                # unlock(project, api_client)
                prompt_to_exit()


def check_daw_running():
    if p := process_running(config.DAW_PROCESS_REGEX):
        logger.warning(
            f"\nWARNING: It appears that your DAW is running ({p.name()}).\nThat's fine, but please close any open "
            f"synced projects before proceeding, else corruption may occur.")
        if get_input_choice(("Proceed", "cancel")) == "cancel":
            raise SystemExit


def sync(project):
    logger.info(f"Syncing project {project['name']}...")
    logger.debug(f"{local_hs.open()=}")
    wants = check_wants()
    remote_stores = {}
    songs = [song.get('directory_name') or song['name'] for song in project['songs']]
    if not songs:
        logger.info("No songs, skipping")
        return
    logger.debug(f"Got songs list {songs}")
    project = project['name']

    logger.info("Checking local files for changes...")
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = {executor.submit(hash_directory, join(config.SOURCE, s)): s for s in songs}
        for result in concurrent.futures.as_completed(futures):
            song = futures[result]
            try:
                src_hash = result.result()
            except FileNotFoundError:
                logger.debug(f"Didn't get hash for {song}")
                src_hash = ""
            local_hash_cache[song] = src_hash
    project_dest = config.DEST_MAPPING.get(project, config.DEFAULT_DEST)
    remote_store_name = join(project_dest, config.REMOTE_HASH_STORE)
    logger.debug(f"Directory config: {project_dest=}, {remote_store_name=}")
    logger.debug(f"{local_hash_cache=}")
    try:
        # Database already opened, contents cached
        remote_hs = remote_stores[remote_store_name]
        logger.debug("Cache hit; remote database already opened.")
    except KeyError:
        remote_hs = HashStore(remote_store_name)
        # Database not opened yet, need to read from disk
        logger.debug(f"{remote_hs.open()=}")
        remote_stores[remote_store_name] = remote_hs

    for song in songs:
        print(print_hr())
        logger.info("Syncing {}...".format(song))
        not_local = False
        if not isdir(join(config.SOURCE, song)):
            logger.info("{} does not exist locally.".format(song))
            not_local = True
        up = is_updated(song, project, remote_hs)
        if not_local:
            up == "remote"
            handle_new_song(song, remote_hs)
        if song in wants:
            logger.warning(f"Overriding because {wants['user']} requested this song!!!!")
            sleep(0.9)
            up = "local"
        if up == "mismatch":
            print_latest_change(join(project_dest, song))
            logger.warning("WARNING: Both local and remote have changed!!!! Which to keep?")
            up = get_input_choice(("local", "remote", "skip"))
        if up == "remote":
            src = project_dest
            dst = config.SOURCE
            print_latest_change(join(project_dest, song))
        elif up == "local":
            src = config.SOURCE
            dst = project_dest
            changelog(song)
        else:
            logger.info(f"No change for {song}")
            continue
        local_hs.update(song, remote_hash_cache[join(src, song)])
        try:
            logger.info("Now copying {} from {} ({}) to {} ({})".format(song, up, src,
                                                                        "remote" if up == "local" else "local",
                                                                        dst))
            if up == "remote":
                if not get_input_choice(("Confirm", "skip")) == "confirm":
                    continue
            else:
                try:
                    remote_hs.update(song, remote_hash_cache[join(src, song)])
                except Exception as e:
                    logger.error(fmt_error("sync:update_remote_hashes", e))
                    if not config.LEGACY_MODE:
                        logger.critical("Failed to update remote hashes!")
                        raise e
            copy(song, src, dst)
        except Exception as e:
            logger.error(f"Error syncing {song}: {e}. If the remote directory does not exist, please remove it "
                         f"from the database.")
            sleep(2)
        else:
            logger.info(f"Successfully synced {song}")
    print(print_hr())
    print(print_hr('='))


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--service', action='store_true')
    parser.add_argument('--tui', action='store_true')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--sync', action='store_true')
    return parser.parse_args()


def sync_all_projects(projects, api_client):
    start = datetime.datetime.now()
    print(print_hr('='))
    for project in projects:
        try:
            if not project['sync_enabled']:
                logger.debug(f"Project {project['name']} sync disabled, skipping...")
                continue
        except KeyError:
            pass
        lock(project, api_client)
        sync(project)
        unlock(project, api_client)
    print(print_hr('='))
    sync_amps()
    print(print_hr('='))
    logger.info("All projects up-to-date. Took {} seconds.".format((datetime.datetime.now() - start).seconds))


def main(args):
    error = []
    queue = Queue()

    # init API client
    api_client = SyncAPI(appdata.get('refresh'), appdata.get('access'), appdata.get('username'), queue)

    # Start local Flask server
    app.config['queue'] = queue
    web_thread = Thread(target=app.run, kwargs=dict(debug=config.DEBUG, use_reloader=False), daemon=True)
    web_thread.start()

    if not api_client.has_tokens():
        if not login_prompt(api_client):
            logger.error("Couldn't log in with provided credentials.")
            prompt_to_exit()

    try:
        clean_up()
        if config.UPDATE_PATH_GLOB and update():
            raise SystemExit
        if not isdir(config.SOURCE):
            error.append(f"Error! Source path \"{config.SOURCE}\" not found.")
        for directory in (config.DEFAULT_DEST, *config.DEST_MAPPING.values()):
            if not (config.DEBUG or isdir(directory)):
                error.append(f"Error! Destination path {directory} not found.")
        if error:
            logger.error(','.join(error))
            prompt_to_exit()

        check_daw_running()
        if config.FIREWALL_API_URL and config.FIREWALL_API_KEY:
            api_unblock()

        projects = api_client.get_projects()
        sync_all_projects(projects, api_client)

        logger.info(
            "Would you like to check out the studio for up to 8 hours? This will prevent other users from making "
            "edits, as to avoid conflicts.")
        if get_input_choice(("yes", "No")) == "yes":
            # TODO: don't check out all projects
            for project in projects:
                check_out(project, api_client)
            logger.info("Alright, it's all yours. This window will stay open. Please remember to check in when you "
                        "are done.")
            input("[enter] to check in")
            sync_all_projects(projects, api_client)
        if not len(sys.argv) > 1:
            prompt_to_exit()
    except Exception as e:
        logger.critical(f"Fatal error! Provide the developer (syncprojects-dev@keane.space) with the following "
                        f"information:\n{str(e)} {str(traceback.format_exc())}")
        prompt_to_exit()


if __name__ == '__main__':
    args = parse_args()
    if args.debug:
        config.DEBUG = True
    # Set up logging
    logger = logging.getLogger('syncprojects')
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    if config.DEBUG:
        ch.setLevel(logging.DEBUG)
    else:
        ch.setLevel(logging.INFO)
    logger.addHandler(ch)
    if appdata.get('telemetry_file'):
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(appdata['telemetry_file'])
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.info(f"Logging debug output to {appdata['telemetry_file']}")

    print(BANNER)
    logger.info("[v{}]".format(__version__))
    main(args)
