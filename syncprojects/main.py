import traceback
from glob import glob
from os import scandir
from os.path import join, isdir, isfile

import concurrent.futures
import datetime
import logging
import sys
from concurrent.futures.thread import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from time import sleep

from syncprojects import config as config
from syncprojects.operations import copy, changelog, check_wants, handle_new_song, copy_tree, check_out, lock, unlock
from syncprojects.server import app
from syncprojects.storage import appdata, HashStore

__version__ = '1.7'

from syncprojects.api import SyncAPI, login_prompt
from syncprojects.utils import current_user, prompt_to_exit, fmt_error, get_input_choice, print_hr, print_latest_change, \
    clean_up, update, api_unblock, \
    check_daw_running, parse_args, logger, hash_file

CODENAME = "IT'S MORE IN THE CLOUD"
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
    dest = config.DEST_MAPPING.get(group, config.DEFAULT_DEST)
    src_hash = local_hash_cache[join(config.SOURCE, dir_name)]
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


class Sync:
    def __init__(self, api_client: SyncAPI, headless: bool = False):
        self.api_client = api_client
        self.headless = headless

    def print(self, *args, **kwargs):
        if not self.headless:
            print(*args, **kwargs)

    def sync(self, project):
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
            # concurrency bug with cx_freeze here
            for result in concurrent.futures.as_completed(futures):
                song = futures[result]
                try:
                    src_hash = result.result()
                except FileNotFoundError:
                    logger.debug(f"Didn't get hash for {song}")
                    src_hash = ""
                local_hash_cache[join(config.SOURCE, song)] = src_hash
        project_dest = config.DEST_MAPPING.get(project, config.DEFAULT_DEST)
        remote_store_name = join(project_dest, config.REMOTE_HASH_STORE)
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
            self.print(print_hr())
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
        self.print(print_hr())
        self.print(print_hr('='))

    def sync_multiple_projects(self, projects):
        for project in projects:
            if 'songs' not in project:
                # This request came from the API, we don't have the project data yet
                project = self.api_client.get_project(project)
            try:
                if not project['sync_enabled']:
                    logger.debug(f"Project {project['name']} sync disabled, skipping...")
                    continue
            except KeyError:
                pass
            lock(project, self.api_client)
            self.sync(project)
            unlock(project, self.api_client)

    def handle_service(self):
        logger.debug("Starting syncprojects-client service")
        self.headless = True
        while msg := self.api_cient.queue.get():
            {
                'auth': self.api_cient.handle_auth_msg,
                'sync': self.sync_multiple_projects,
            }[msg['msg_type']](msg['data'])

    def handle_tui(self):
        logger.debug("Starting sync TUI")
        check_daw_running()
        if config.FIREWALL_API_URL and config.FIREWALL_API_KEY:
            api_unblock()

        projects = self.api_client.get_all_projects()
        start = datetime.datetime.now()
        print(print_hr('='))
        self.sync_multiple_projects(projects)
        print(print_hr('='))
        sync_amps()
        print(print_hr('='))
        logger.info("All projects up-to-date. Took {} seconds.".format((datetime.datetime.now() - start).seconds))

        logger.info(
            "Would you like to check out the studio for up to 8 hours? This will prevent other users from making "
            "edits, as to avoid conflicts.")
        if get_input_choice(("yes", "No")) == "yes":
            # TODO: don't check out all projects
            for project in projects:
                check_out(project, self.api_client)
            logger.info("Alright, it's all yours. This window will stay open. Please remember to check in when you "
                        "are done.")
            input("[enter] to check in")
            self.sync_multiple_projects(projects)
        if not len(sys.argv) > 1:
            prompt_to_exit()


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

        sync = Sync(api_client)
        if args.service:
            sync.handle_service()
        else:
            sync.handle_tui()
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
    main(args)
