import concurrent.futures
import datetime
import logging
import traceback

import sys
from concurrent.futures.thread import ThreadPoolExecutor
from glob import glob
from os import scandir
from os.path import join, isdir, isfile
from queue import Queue
from threading import Thread
from typing import Dict

import sys
import timeago
from packaging.version import parse
from time import sleep
from typing import Dict

from syncprojects import config as config
from syncprojects.commands import AuthHandler, SyncMultipleHandler, WorkOnHandler, WorkDoneHandler
from syncprojects.operations import copy, changelog, handle_new_song, copy_tree, check_out
from syncprojects.server import app
from syncprojects.storage import appdata, HashStore

__version__ = '2.0'

from syncprojects.api import SyncAPI, login_prompt
from syncprojects.utils import current_user, prompt_to_exit, fmt_error, get_input_choice, print_hr, print_latest_change, \
    update, api_unblock, \
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


class SyncManager:
    def __init__(self, api_client: SyncAPI, headless: bool = False):
        self.api_client = api_client
        self.headless = headless
        self.logger = logging.getLogger('syncprojects.main.SyncManager')

    def print(self, *args, **kwargs):
        if not self.headless:
            print(*args, **kwargs)

    # TODO: return something relevant
    def sync(self, project: Dict) -> Dict:
        self.logger.info(f"Syncing project {project['name']}...")
        self.logger.debug(f"{local_hs.open()=}")
        remote_stores = {}
        songs = [song.get('directory_name') or song['name'] for song in project['songs'] if
                 song['sync_enabled'] and not song['is_locked']]
        if not songs:
            self.logger.warning("No songs, skipping")
            return
        self.logger.debug(f"Got songs list {songs}")
        project = project['name']

        self.logger.info("Checking local files for changes...")
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            futures = {executor.submit(hash_directory, join(config.SOURCE, s)): s for s in songs}
            # concurrency bug with cx_freeze here
            for result in concurrent.futures.as_completed(futures):
                song = futures[result]
                try:
                    src_hash = result.result()
                except FileNotFoundError:
                    self.logger.debug(f"Didn't get hash for {song}")
                    src_hash = ""
                local_hash_cache[join(config.SOURCE, song)] = src_hash
        project_dest = config.DEST_MAPPING.get(project, config.DEFAULT_DEST)
        remote_store_name = join(project_dest, config.REMOTE_HASH_STORE)
        self.logger.debug(f"Directory config: {project_dest=}, {remote_store_name=}")
        self.logger.debug(f"{local_hash_cache=}")
        self.logger.debug(f"{remote_hash_cache=}")
        try:
            # Database already opened, contents cached
            remote_hs = remote_stores[remote_store_name]
            self.logger.debug("Cache hit; remote database already opened.")
        except KeyError:
            remote_hs = HashStore(remote_store_name)
            # Database not opened yet, need to read from disk
            self.logger.debug(f"{remote_hs.open()=}")
            remote_stores[remote_store_name] = remote_hs

        for song in songs:
            self.print(print_hr())
            self.logger.info("Syncing {}...".format(song))
            not_local = False
            if not isdir(join(config.SOURCE, song)):
                self.logger.info("{} does not exist locally.".format(song))
                not_local = True
            up = is_updated(song, project, remote_hs)
            if not_local:
                up == "remote"
                handle_new_song(song, remote_hs)
            if up == "mismatch":
                print_latest_change(join(project_dest, song))
                self.logger.warning("WARNING: Both local and remote have changed!!!! Which to keep?")
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
                self.logger.info(f"No change for {song}")
                continue
            local_hs.update(song, remote_hash_cache[join(src, song)])
            try:
                self.logger.info("Now copying {} from {} ({}) to {} ({})".format(song, up, src,
                                                                                 "remote" if up == "local" else "local",
                                                                                 dst))
                if up == "remote":
                    if not get_input_choice(("Confirm", "skip")) == "confirm":
                        continue
                else:
                    try:
                        remote_hs.update(song, remote_hash_cache[join(src, song)])
                    except Exception as e:
                        self.logger.error(fmt_error("sync:update_remote_hashes", e))
                        if not config.LEGACY_MODE:
                            self.logger.critical("Failed to update remote hashes!")
                            raise e
                copy(song, src, dst)
            except Exception as e:
                self.logger.error(
                    f"Error syncing {song}: {e}. If the remote directory does not exist, please remove it "
                    f"from the database.")
                sleep(2)
            else:
                self.logger.info(f"Successfully synced {song}")
        self.print(print_hr())
        self.print(print_hr('='))

    def run_service(self):
        self.logger.debug("Starting syncprojects-client service")
        self.headless = True
        while msg := self.api_client.recv_queue.get():
            {
                'auth': AuthHandler,
                'sync': SyncMultipleHandler,
                'workon': WorkOnHandler,
                'workdone': WorkDoneHandler,
            }[msg['msg_type']](msg['task_id'], self.api_client, self).handle(msg['data'])

    def run_tui(self):
        self.logger.debug("Starting sync TUI")
        check_daw_running()
        if config.FIREWALL_API_URL and config.FIREWALL_API_KEY:
            api_unblock()

        projects = self.api_client.get_all_projects()
        start = datetime.datetime.now()
        print(print_hr('='))
        self.sync_multiple(projects)
        print(print_hr('='))
        sync_amps()
        print(print_hr('='))
        self.logger.info("All projects up-to-date. Took {} seconds.".format((datetime.datetime.now() - start).seconds))

        self.logger.info(
            "Would you like to check out the studio for up to 8 hours? This will prevent other users from making "
            "edits, as to avoid conflicts.")
        if get_input_choice(("yes", "No")) == "yes":
            # TODO: don't check out all projects
            for project in projects:
                check_out(project, self.api_client)
            self.logger.info(
                "Alright, it's all yours. This window will stay open. Please remember to check in when you "
                "are done.")
            input("[enter] to check in")
            self.sync_multiple(projects)
        if not len(sys.argv) > 1:
            prompt_to_exit()


def check_update(api_client: SyncAPI) -> Dict:
    try:
        latest_version = api_client.get_updates()[-1]
    except IndexError:
        return None
    if parse(__version__) < parse(latest_version['version']):
        return latest_version


def main():
    error = []
    main_queue = Queue()
    server_queue = Queue()

    # init API client
    api_client = SyncAPI(appdata.get('refresh'), appdata.get('access'), appdata.get('username'), main_queue,
                         server_queue)

    # Start local Flask server
    app.config['main_queue'] = main_queue
    app.config['server_queue'] = server_queue
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

        sync = SyncManager(api_client)
        if parsed_args.service:
            sync.run_service()
        else:
            sync.run_tui()
    except Exception as e:
        logger.critical(f"Fatal error! Provide the help desk (support@syncprojects.app) with the following "
                        f"information:\n{str(e)} {str(traceback.format_exc())}")
        prompt_to_exit()


if __name__ == '__main__':
    parsed_args = parse_args()
    if parsed_args.debug:
        config.DEBUG = True
    # Set up logging
    logger = logging.getLogger('syncprojects.main')
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
