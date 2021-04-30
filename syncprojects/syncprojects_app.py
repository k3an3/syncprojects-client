import logging
import traceback
from multiprocessing import Queue, freeze_support
from multiprocessing.context import Process
from os.path import isdir

import sys

from syncprojects import config as config
from syncprojects.api import SyncAPI, login_prompt
from syncprojects.config import ACCESS_ID, SECRET_KEY
from syncprojects.server import start_server
from syncprojects.storage import appdata
from syncprojects.sync import SyncManager
from syncprojects.sync.backends.aws.auth import StaticAuth
from syncprojects.sync.backends.aws.s3 import S3SyncBackend
from syncprojects.sync.backends.copyfile import ShareDriveSyncBackend
from syncprojects.sync.backends.noop import RandomNoOpSyncBackend
from syncprojects.ui.first_start import SetupUI
from syncprojects.ui.message import MessageBoxUI
from syncprojects.utils import fmt_error, print_hr, get_latest_change, \
    hash_file, current_user, \
    get_datadir
from syncprojects.utils import prompt_to_exit, parse_args, logger, check_update, UpdateThread, api_unblock, \
    check_already_running, open_app_in_browser, test_mode

__version__ = '2.2'

CODENAME = "IT'S EVEN MORE IN THE CLOUD"
BANNER = """
███████╗██╗   ██╗███╗   ██╗ ██████╗██████╗ ██████╗  ██████╗      ██╗███████╗ ██████╗████████╗███████╗
██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔══██╗██╔══██╗██╔═══██╗     ██║██╔════╝██╔════╝╚══██╔══╝██╔════╝
███████╗ ╚████╔╝ ██╔██╗ ██║██║     ██████╔╝██████╔╝██║   ██║     ██║█████╗  ██║        ██║   ███████╗
╚════██║  ╚██╔╝  ██║╚██╗██║██║     ██╔═══╝ ██╔══██╗██║   ██║██   ██║██╔══╝  ██║        ██║   ╚════██║
███████║   ██║   ██║ ╚████║╚██████╗██║     ██║  ██║╚██████╔╝╚█████╔╝███████╗╚██████╗   ██║   ███████║
╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝╚═╝     ╚═╝  ╚═╝ ╚═════╝  ╚════╝ ╚══════╝ ╚═════╝   ╚═╝   ╚══════╝
\"{}\"""".format(CODENAME)


class CopyFileSyncManager(SyncManager):
    def __init__(self, *args, **kwargs):
        self.local_hs = HashStore(str(get_datadir(APP_NAME) / "hashes"))
        self.remote_hash_cache = {}
        self.local_hash_cache = {}
        super().__init__(*args, **kwargs)

    def print(self, *args, **kwargs):
        if not self.headless:
            print(*args, **kwargs)

    def hash_directory(self, dir_name):
        hash_algo = config.DEFAULT_HASH_ALGO()
        if isdir(dir_name):
            for file_name in glob(join(dir_name, config.PROJECT_GLOB)):
                if isfile(file_name):
                    logger.debug(f"Hashing {file_name}")
                    hash_file(file_name, hash_algo)
            hash_digest = hash_algo.hexdigest()
            self.remote_hash_cache[dir_name] = hash_digest
            return hash_digest

    def is_updated(self, dir_name, group, remote_hs):
        dest = join(appdata['smb_drive'], group)
        src_hash = self.local_hash_cache[join(appdata['source'], dir_name)]
        logger.debug(f"local_hash is {src_hash}")
        dst_hash = remote_hs.get(dir_name)
        self.remote_hash_cache[join(dest, dir_name)] = dst_hash
        if appdata['legacy_mode'] or not dst_hash:
            logger.info("Checking with the slow/old method just in case we missed it...")
            try:
                dst_hash = self.hash_directory(join(dest, dir_name))
            except FileNotFoundError:
                dst_hash = ""
        logger.debug(f"remote_hash is {dst_hash}")
        known_hash = self.local_hs.get(dir_name)
        if not known_hash:
            logger.debug(f"didn't exist in database: {dir_name=}")
            logger.info("Not in database; adding...")
            new_hash = src_hash or dst_hash
            self.local_hs.update(dir_name, new_hash)
            known_hash = new_hash
        else:
            logger.debug(f"known_hash is {known_hash}")
        if src_hash != known_hash and dst_hash != known_hash:
            return "mismatch"
        elif src_hash and (not dst_hash or src_hash != known_hash):
            return "local"
        elif dst_hash and (not src_hash or dst_hash != known_hash):
            return "remote"

    def sync(self, project: Dict) -> Dict:
        self.logger.info(f"Syncing project {project['name']}...")
        self.logger.debug(f"{self.local_hs.open()=}")
        remote_stores = {}
        songs = project['songs']
        if not songs:
            self.logger.warning("No songs, skipping")
            return {'status': 'done', 'songs': None}
        self.logger.debug(f"Got songs list {songs}")
        project = project['name']

        self.logger.info("Checking local files for changes...")
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            futures = {
                executor.submit(self.hash_directory, join(appdata['source'], s.get('directory_name') or s['name'])): s
                for s in
                songs}
            for results in concurrent.futures.as_completed(futures):
                song = futures[results]
                try:
                    src_hash = results.result()
                except FileNotFoundError:
                    self.logger.debug(f"Didn't get hash for {song['name']}")
                    src_hash = ""
                self.local_hash_cache[join(appdata['source'], song.get('directory_name') or song['name'])] = src_hash
        project_dest = join(appdata['smb_drive'], project)
        remote_store_name = join(project_dest, appdata['remote_hash_store'])
        self.logger.debug(f"Directory config: {project_dest=}, {remote_store_name=}")
        self.logger.debug(f"{self.local_hash_cache=}")
        self.logger.debug(f"{self.remote_hash_cache=}")
        try:
            # Database already opened, contents cached
            remote_hs = remote_stores[remote_store_name]
            self.logger.debug("Cache hit; remote database already opened.")
        except KeyError:
            remote_hs = HashStore(remote_store_name)
            # Database not opened yet, need to read from disk
            self.logger.debug(f"{remote_hs.open()=}")
            remote_stores[remote_store_name] = remote_hs

        results = {'status': 'done', 'songs': []}
        for song in songs:
            song_name = song['name']
            if not song['sync_enabled']:
                self.logger.debug(f"{song_name} sync disabled, skipping...")
                results['songs'].append({'song': song_name, 'result': 'success', 'action': 'disabled'})
                continue
            elif song['is_locked']:
                self.logger.debug(f"{song_name} locked, skipping...")
                results['songs'].append({'song': song_name, 'result': 'error', 'action': 'locked'})
                continue
            song = song.get('directory_name') or song['name']
            self.print(print_hr())
            self.logger.info("Syncing {}...".format(song))
            not_local = False
            if not isdir(join(appdata['source'], song)):
                self.logger.info(f"{song_name} does not exist locally.")
                not_local = True
            up = self.is_updated(song, project, remote_hs)
            self.logger.debug(f"Got status: {up}")
            if not_local:
                up == "remote"
                handle_new_song(song, remote_hs)
            if up == "mismatch":
                self.logger.warning("Sync conflict: both local and remote have changed!")
                if changes := get_latest_change(join(project_dest, song)):
                    MessageBoxUI.info(changes, "Sync Conflict: changes")
                result = MessageBoxUI.yesnocancel(
                    f"{song_name} has changed both locally and remotely! Which one do you "
                    f"want to " f"keep? Note that proceeding may cause loss of "
                    f"data.\n\nChoose \"yes\" to " f"confirm overwrite of local files, "
                    f"\"no\" to confirm overwrite of server " f"files. Or, \"cancel\" "
                    f"to skip.", "Sync Conflict")
                if result:
                    up = "remote"
                elif result is None:
                    up = None
                else:
                    up = "local"
            if up == "remote":
                src = project_dest
                dst = appdata['source']
            elif up == "local":
                src = appdata['source']
                dst = project_dest
                self.logger.debug("Prompting for changelog")
                changelog(song)
            else:
                self.logger.info(f"No action for {song_name}")
                results['songs'].append({'song': song_name, 'result': 'success', 'action': up})
                continue
            self.local_hs.update(song, self.remote_hash_cache[join(src, song)])
            try:
                self.logger.info("Now copying {} from {} ({}) to {} ({})".format(song_name, up, src,
                                                                                 "remote" if up == "local" else "local",
                                                                                 dst))
                try:
                    remote_hs.update(song, self.remote_hash_cache[join(src, song)])
                except Exception as e:
                    self.logger.error(fmt_error("sync:update_remote_hashes", e))
                    if not appdata['legacy_mode']:
                        self.logger.critical("Failed to update remote hashes!")
                        raise e
                copy(song, src, dst)
            except Exception as e:
                results['songs'].append({'song': song_name, 'result': 'error', 'msg': str(e)})
                self.logger.error(
                    f"Error syncing {song_name}: {e}. If the remote directory does not exist, please remove it "
                    f"from the database.")
            else:
                results['songs'].append({'song': song_name, 'result': 'success', 'action': up})
                self.logger.info(f"Successfully synced {song_name}")
        self.print(print_hr())
        self.print(print_hr('='))
        return results

    def push_amp_settings(self, amp, project):
        try:
            copy_tree(join(appdata['neural_dsp_path'], amp, "User"),
                      join(appdata['smb_drive'], project, 'Amp Settings', amp, current_user()),
                      single_depth=True,
                      update=True,
                      progress=False)
        except FileNotFoundError:
            logger.debug(traceback.format_exc())
            pass

    def pull_amp_settings(self, amp, project):
        with os.scandir(join(appdata['smb_drive'], project, 'Amp Settings', amp)) as entries:
            for entry in entries:
                if entry.name != current_user():
                    copy_tree(entry.path,
                              join(appdata['neural_dsp_path'], amp, "User", entry.name),
                              update=True,
                              progress=False)

    @staticmethod
    def get_local_neural_dsp_amps():
        with os.scandir(appdata['neural_dsp_path']) as entries:
            for entry in entries:
                if entry.is_dir() and entry.name != "Impulse Responses":
                    yield entry.name


def first_time_run():
    setup = SetupUI()
    logger.info("Running first time setup")
    setup.run()
    logger.info("First time setup complete")
    logger.debug(f"{setup.sync_source_dir=} {setup.audio_sync_source_dir=}")
    if not setup.sync_source_dir and not setup.audio_sync_source_dir:
        logger.error("Required settings weren't provided; quitting.")
        sys.exit(1)
    appdata['source'] = setup.sync_source_dir
    appdata['audio_sync_dir'] = setup.audio_sync_source_dir
    appdata['first_time_setup_complete'] = True


def main():
    if check_already_running():
        sys.exit(0)
    main_queue = Queue()
    server_queue = Queue()

    # Check for first time setup needed
    if not appdata.get('first_time_setup_complete'):
        first_time_run()
        open_app_in_browser()

    # Start local Flask server
    logger.debug("Starting web API server thread...")
    web_process = Process(target=start_server, args=(main_queue, server_queue),
                          kwargs=dict(debug=config.DEBUG, use_reloader=False), daemon=True)
    web_process.start()

    # init API client
    api_client = SyncAPI(appdata.get('refresh'), appdata.get('access'), appdata.get('username'), main_queue,
                         server_queue)

    if not api_client.has_tokens():
        if not login_prompt(api_client):
            logger.error("Couldn't log in with provided credentials.")
            prompt_to_exit()
    # Not only is this line useful for logging, but it populates appdata['username']
    logger.info(f"Logged in as {api_client.username}")

    try:
        check_update(api_client)

        # Start update thread
        update_thread = UpdateThread(api_client)
        update_thread.start()

        if not isdir(appdata['source']):
            logger.critical(f"Error! Source path \"{appdata['source']}\" not found.")
            prompt_to_exit()
        if appdata['firewall_api_url'] and appdata['firewall_api_key']:
            api_unblock()

        if test_mode():
            backend = RandomNoOpSyncBackend
            args = []
        else:
            backend = S3SyncBackend
            args = [StaticAuth(ACCESS_ID, SECRET_KEY), 'syncprojects']

        sync = SyncManager(api_client, backend, args=args)

        if parsed_args.tui:
            sync.run_tui()
        else:
            sync.run_service()
    except Exception as e:
        logger.critical(f"Fatal error!\n{str(e)} {str(traceback.format_exc())}")
        MessageBoxUI.error("Syncprojects encountered a fatal error and must exit. Please contact support.")
        sys.exit(-1)


if __name__ == '__main__':
    if sys.platform == "win32":
        freeze_support()
    parsed_args = parse_args()
    if parsed_args.debug:
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
