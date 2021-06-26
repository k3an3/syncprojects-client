import logging
import traceback
from logging.handlers import RotatingFileHandler
from multiprocessing import Queue, freeze_support
from multiprocessing.context import Process
from os.path import isdir

import sys

from syncprojects import config as config
from syncprojects.api import SyncAPI, login_prompt
from syncprojects.config import ACCESS_ID, SECRET_KEY, DEBUG, BUCKET_NAME, AUDIO_BUCKET_NAME
from syncprojects.server import start_server
from syncprojects.storage import appdata
from syncprojects.sync import SyncManager
from syncprojects.sync.backends.aws import NoAuthenticationCredentialsError
from syncprojects.sync.backends.aws.auth import StaticAuth
from syncprojects.sync.backends.aws.s3 import S3SyncBackend
from syncprojects.sync.backends.noop import RandomNoOpSyncBackend
from syncprojects.system import open_app_in_browser, test_mode
from syncprojects.ui.message import MessageBoxUI
from syncprojects.ui.settings_menu import SettingsUI
from syncprojects.ui.tray import TrayIcon
from syncprojects.utils import prompt_to_exit, parse_args, logger, check_update, UpdateThread, api_unblock, \
    check_already_running, commit_settings
from syncprojects.watcher import S3AudioSyncHandler, Watcher

__version__ = '2.4.10'

CODENAME = "IT RUNS ON ALL THE THINGS"
BANNER = """
███████╗██╗   ██╗███╗   ██╗ ██████╗██████╗ ██████╗  ██████╗      ██╗███████╗ ██████╗████████╗███████╗
██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔══██╗██╔══██╗██╔═══██╗     ██║██╔════╝██╔════╝╚══██╔══╝██╔════╝
███████╗ ╚████╔╝ ██╔██╗ ██║██║     ██████╔╝██████╔╝██║   ██║     ██║█████╗  ██║        ██║   ███████╗
╚════██║  ╚██╔╝  ██║╚██╗██║██║     ██╔═══╝ ██╔══██╗██║   ██║██   ██║██╔══╝  ██║        ██║   ╚════██║
███████║   ██║   ██║ ╚████║╚██████╗██║     ██║  ██║╚██████╔╝╚█████╔╝███████╗╚██████╗   ██║   ███████║
╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝╚═╝     ╚═╝  ╚═╝ ╚═════╝  ╚════╝ ╚══════╝ ╚═════╝   ╚═╝   ╚══════╝
\"{}\"""".format(CODENAME)


def first_time_run():
    settings = SettingsUI()
    logger.info("Running first time setup")
    settings.run()
    logger.info("First time setup complete")
    logger.debug(f"{settings.sync_source_dir=} {settings.audio_sync_source_dir=}")
    if not settings.sync_source_dir and not settings.audio_sync_source_dir:
        logger.error("Required settings weren't provided; quitting.")
        MessageBoxUI.error("Syncprojects was improperly configured! Try again, or contact support if the issue "
                           "persists.")
        sys.exit(1)
    commit_settings(settings)
    appdata['first_time_setup_complete'] = True


def main():
    if check_already_running():
        sys.exit(0)

    main_queue = Queue()
    server_queue = Queue()

    was_first_start = False
    # Check for first time setup needed
    if not appdata.get('first_time_setup_complete'):
        first_time_run()
        was_first_start = True

    # Add icon to tray
    ti = TrayIcon()
    ti.start()

    # Start local Flask server
    logger.debug("Starting web API server process...")
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
    server_queue.put('authed')

    if was_first_start:
        open_app_in_browser()

    try:
        check_update(api_client)

        # Start update thread
        update_thread = UpdateThread(api_client)
        update_thread.start()

        context = {}

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
            if not ACCESS_ID or not SECRET_KEY:
                creds = api_client.get_backend_creds()
                if not creds:
                    raise NoAuthenticationCredentialsError
                access_id = creds['access_id']
                secret_key = creds['secret_key']
            else:
                access_id = ACCESS_ID
                secret_key = SECRET_KEY
            aws_auth = StaticAuth(access_id, secret_key)
            args = [aws_auth, BUCKET_NAME + ("-debug" if DEBUG else "")]

            audio_handler = S3AudioSyncHandler(aws_auth, AUDIO_BUCKET_NAME + ("-debug" if DEBUG else ""))
            watcher = Watcher(appdata['audio_sync_dir'], api_client, audio_handler)
            context['watcher'] = watcher
            watcher.start()

        sync = SyncManager(api_client, backend, context=context, args=args)

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
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s %(funcName)s - %(lineno)d - %(message)s')
        fh = RotatingFileHandler(appdata['telemetry_file'], maxBytes=1024 * 100, backupCount=3)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.info(f"Logging debug output to {appdata['telemetry_file']}")

    print(BANNER)
    logger.info("[v{}]".format(__version__))
    main()
