import datetime
import getpass
import logging
import os
import re
import subprocess
import traceback
from argparse import ArgumentParser
from json import JSONDecodeError
from multiprocessing import Queue
from os.path import join, isfile
from tempfile import NamedTemporaryFile
from threading import Thread
from typing import Dict, Union
from uuid import uuid4

import requests
import sys
from packaging.version import parse
from time import sleep

import syncprojects.config as config
from syncprojects.system import open_app_in_browser, process_running, get_datadir, is_mac
from syncprojects.ui.message import MessageBoxUI

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
    return getpass.getuser()


def migrate_old_settings(new_config):
    new_config.update({
        'remote_hash_store': config.REMOTE_HASH_STORE,
        'smb_drive': config.SMB_DRIVE,
        'smb_server': config.SMB_SERVER,
        'smb_share': config.SMB_SHARE,
        'firewall_api_url': config.FIREWALL_API_URL,
        'firewall_api_key': config.FIREWALL_API_KEY,
        'firewall_name': config.FIREWALL_NAME,
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


def get_input_choice(options):
    formatted_options = '[{}]: '.format('/'.join(["[{}]{}".format(o[0], o[1:]) for o in options]))
    while True:
        logger.warning(formatted_options)
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


def get_latest_change(directory_path):
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
        return "Latest changes:\n~~~\n" + ''.join(lines[start:end]) + "\n~~~"


def fetch_update(url: str) -> str:
    ntf = NamedTemporaryFile(delete=False)
    resp = requests.get(url)
    resp.raise_for_status()
    ntf.write(resp.content)
    ntf.close()
    return ntf.name


def update(new_version: Dict):
    logger.debug(f"Fetching package from {new_version['package']}")
    package = fetch_update(new_version['package'])
    if not verify_signature(package, ''):
        logger.error("Package failed signature check! Aborting.")
        # TODO: Alert user
        return
    args = (package, "-d")
    if is_mac():
        logger.debug(f"Starting updater: `open {package}`")
        subprocess.Popen(['open', package])
    else:
        logger.debug(f"Starting updater: `{' '.join(args)}`")
        subprocess.Popen(args)


def hash_file(file_path, hash_inst=None, block_size=4096) -> str:
    if not hash_inst:
        hash_inst = config.DEFAULT_HASH_ALGO()
    with open(file_path, 'rb') as fp:
        while True:
            data = fp.read(block_size)
            if data:
                hash_inst.update(data)
            else:
                break
    return hash_inst.hexdigest()


def api_unblock():
    logger.info("Requesting firewall exception... ")
    try:
        from syncprojects.storage import appdata
        r = requests.post(appdata['firewall_api_url'] + "firewall/unblock",
                          headers={'X-Auth-Token': appdata['firewall_api_key']},
                          data={'device': appdata['firewall_name']})
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
    from syncprojects.syncprojects_app import __version__
    parser = ArgumentParser(description=f"Syncprojects-client v{__version__}\nBy default, a background service "
                                        "is started.")
    parser.add_argument('--tui', action='store_true')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--sync', action='store_true')
    return parser.parse_args()


def find_daw_exe(search: bool = False) -> Union[str, None]:
    from syncprojects.storage import appdata
    try:
        return appdata['daw_exe_path']
    except KeyError:
        pass
    if search:
        try:
            return process_running(config.DAW_PROCESS_REGEX).exe()
        except AttributeError:
            pass
    return None


def verify_signature(path: str, given_hash: str) -> bool:
    # TODO: Implement
    return True


def check_update(api_client) -> Union[Dict, None]:
    try:
        latest_version = api_client.get_client_updates()[-1]
    except IndexError:
        return None
    from syncprojects.syncprojects_app import __version__
    if parse(__version__) < parse(latest_version['version']):
        logger.info(f"New update found! {latest_version['version']}")
        update(latest_version)
        sys.exit(0)
    else:
        logger.info("No new updates.")
    return None


class UpdateThread(Thread):
    def __init__(self, api_client):
        super().__init__(daemon=True)
        self.logger = logging.getLogger('syncprojects.utils.UpdateThread')
        self.api_client = api_client
        self.next_check = None
        self.update_next_check()

    def update_next_check(self):
        self.next_check = datetime.datetime.now() + datetime.timedelta(seconds=config.UPDATE_INTERVAL)
        self.logger.debug(f"Next update check at {self.next_check.isoformat()}")

    def run(self):
        self.logger.debug("Starting updater thread...")
        while True:
            if datetime.datetime.now() >= self.next_check:
                self.logger.info("Checking for update...")
                check_update(self.api_client)
                self.update_next_check()
            sleep(3600)

    def remote_trigger(self):
        self.logger.info("Got remote call request, checking for update...")
        check_update(self.api_client)


def request_local_api(route: str):
    try:
        requests.post(f"http://localhost:5000/api/{route}", json={}, headers={"Accept": "application/json"})
    except requests.exceptions.ConnectionError:
        pass


def check_already_running():
    try:
        r = requests.get("http://localhost:5000/api/ping", headers={"Accept": "application/json"})
    except requests.exceptions.ConnectionError:
        return False
    try:
        if r.json()['result'] == 'pong':
            logger.info("syncprojects-client already running; opening browser")
            open_app_in_browser()
            return True
    except JSONDecodeError:
        pass
    logger.critical("Something else is already using port 5000! Exiting...")
    MessageBoxUI.error("Syncprojects cannot start; something is already using TCP port 5000. Please disable any "
                       "conflicting programs or contact support.")
    sys.exit(-1)


def get_song_dir(song: Dict) -> str:
    """
    resolve song directory
    :param song:
    :return:
    """
    path = song.get('directory_name') or song['name']
    from syncprojects.storage import appdata
    if appdata.get('nested_folders'):
        path = join(song['project_name'], path)
    return path


# https://cx-freeze.readthedocs.io/en/latest/faq.html#using-data-files
def find_data_file(filename: str) -> str:
    if getattr(sys, "frozen", False):
        # The application is frozen
        datadir = os.path.dirname(sys.executable)
        path = os.path.join(datadir, filename)
        if not isfile(path):
            # handle pyinstaller case
            bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
            path = os.path.abspath(os.path.join(bundle_dir, filename))
        return path
    else:
        # The application is not frozen
        return join('res', filename)


def commit_settings(settings):
    from syncprojects.storage import appdata
    if settings.sync_source_dir:
        appdata['source'] = settings.sync_source_dir
    if settings.audio_sync_source_dir:
        appdata['audio_sync_dir'] = settings.audio_sync_source_dir
    appdata['nested_folders'] = settings.nested


def create_project_dirs(api_client, base_dir):
    logger.debug("Creating dirs in %s", base_dir)
    projects = api_client.get_all_projects()
    for project in projects:
        try:
            os.makedirs(join(base_dir, project['name']), exist_ok=True)
        except OSError as e:
            logger.error("Cannot create directory: %s", e)


def report_error(e):
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(e)
    except ImportError:
        pass


def gen_task_id() -> str:
    return str(uuid4())


def add_to_command_queue(q: Queue, command: str, data: Dict = None) -> str:
    task_id = gen_task_id()
    q.put({'msg_type': command, 'task_id': task_id, 'data': data})
    return task_id


def init_sentry(url: str, release: str) -> None:
    try:
        import sentry_sdk
        sentry_sdk.init(url, traces_sample_rate=1.0, release='@'.join(('syncprojects', release)))
    except ImportError:
        logger.warning("Sentry package not available.")
