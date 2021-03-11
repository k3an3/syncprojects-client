import concurrent.futures
import datetime
import logging
import traceback
from concurrent.futures.thread import ThreadPoolExecutor
from glob import glob
from os import scandir
from os.path import join, isdir, isfile
from queue import Queue
from threading import Thread

import sys
import timeago
from packaging.version import parse
from time import sleep

from syncprojects import config as config
from syncprojects.operations import copy, changelog, handle_new_song, copy_tree
from syncprojects.server import app
from syncprojects.storage import appdata, HashStore

__version__ = '1.6'

from syncprojects.api import SyncAPI, login_prompt
from syncprojects.utils import current_user, prompt_to_exit, fmt_error, get_input_choice, print_hr, print_latest_change, \
    update, api_unblock, \
    check_daw_running, parse_args, logger, hash_file

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
    with scandir(appdata['neural_dsp_path']) as entries:
        for entry in entries:
            if entry.is_dir() and entry.name != "Impulse Responses":
                yield entry.name


def push_amp_settings(amp):
    try:
        copy_tree(join(appdata['neural_dsp_path'], amp, "User"),
                  join(appdata['amp_preset_sync_dir'], amp, current_user()),
                  single_depth=True,
                  update=True,
                  progress=False)
    except FileNotFoundError:
        logger.debug(traceback.format_exc())
        pass


def pull_amp_settings(amp):
    with scandir(join(appdata['amp_preset_sync_dir'], amp)) as entries:
        for entry in entries:
            if entry.name != current_user():
                copy_tree(entry.path,
                          join(appdata['neural_dsp_path'], amp, "User", entry.name),
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


local_hs = HashStore(appdata['local_hash_store'])
remote_hash_cache = {}
local_hash_cache = {}


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


def is_updated(dir_name, group, remote_hs):
    # Can't refactor move with the hash caches here
    dest = appdata['dest_mapping'].get(group, appdata['default_dest'])
    src_hash = local_hash_cache[join(appdata['source'], dir_name)]
    logger.debug(f"local_hash is {src_hash}")
    dst_hash = remote_hs.get(dir_name)
    remote_hash_cache[join(dest, dir_name)] = dst_hash
    if appdata['legacy_mode'] or not dst_hash:
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


def sync(project):
    logger.info(f"Syncing project {project['name']}...")
    logger.debug(f"{local_hs.open()=}")
    remote_stores = {}
    songs = [song.get('directory_name') or song['name'] for song in project['songs']]
    if not songs:
        logger.info("No songs, skipping")
        return
    logger.debug(f"Got songs list {songs}")
    project = project['name']

    logger.info("Checking local files for changes...")
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = {executor.submit(hash_directory, join(appdata['source'], s)): s for s in songs}
        # concurrency bug with cx_freeze here
        for result in concurrent.futures.as_completed(futures):
            song = futures[result]
            try:
                src_hash = result.result()
            except FileNotFoundError:
                logger.debug(f"Didn't get hash for {song}")
                src_hash = ""
            local_hash_cache[join(appdata['source'], song)] = src_hash
    project_dest = appdata['dest_mapping'].get(project, appdata['default_dest'])
    remote_store_name = join(project_dest, appdata['remote_hash_store'])
    logger.debug(f"Directory config: {project_dest=}, {remote_store_name=}")
    logger.debug(f"{local_hash_cache=}")
    logger.debug(f"{remote_hash_cache=}")
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
        if not isdir(join(appdata['source'], song)):
            logger.info("{} does not exist locally.".format(song))
            not_local = True
        up = is_updated(song, project, remote_hs)
        if not_local:
            up == "remote"
            handle_new_song(song, remote_hs)
        if up == "mismatch":
            print_latest_change(join(project_dest, song))
            logger.warning("WARNING: Both local and remote have changed!!!! Which to keep?")
            up = get_input_choice(("local", "remote", "skip"))
        if up == "remote":
            src = project_dest
            dst = appdata['source']
            print_latest_change(join(project_dest, song))
        elif up == "local":
            src = appdata['source']
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
                    if not appdata['legacy_mode']:
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


def check_update(api_client: SyncAPI) -> str:
    latest_version = api_client.get_updates()[-1]
    if parse(__version__) < parse(latest_version['version']):
        return latest_version


def main():
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
        if new_version := check_update(api_client):
            logger.info(f"New update found! {new_version['version']}")
            update(new_version)
            raise SystemExit
        else:
            logger.info("No new updates.")

        if not isdir(appdata['source']):
            error.append(f"Error! Source path \"{appdata['source']}\" not found.")
        for directory in (appdata['default_dest'], *appdata['dest_mapping'].values()):
            if not (config.DEBUG or isdir(directory)):
                error.append(f"Error! Destination path {directory} not found.")
        if error:
            logger.error(','.join(error))
            prompt_to_exit()

        check_daw_running()
        if appdata['firewall_api_url'] and appdata['firewall_api_key']:
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
        logger.critical(f"Fatal error! Provide the help desk (support@syncprojects.app) with the following "
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
    main()

