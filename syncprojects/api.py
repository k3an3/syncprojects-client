import datetime
import getpass
import logging
import webbrowser
from json import JSONDecodeError
from queue import Queue
from typing import Dict
from typing import List

import requests
import sys
from requests import HTTPError

from syncprojects.config import LOGIN_MODE, SYNCPROJECTS_URL
from syncprojects.storage import appdata
from syncprojects.system import get_host_string
from syncprojects.ui.message import MessageBoxUI

API_BASE_URL = SYNCPROJECTS_URL + "api/v1/"
logger = logging.getLogger('syncprojects.api')


# TODO: this should go back under class
def login_prompt(sync_api) -> bool:
    for key in ('refresh_token', 'access_token'):
        try:
            del appdata[key]
            logger.debug(f"Existing {key} deleted from appdata.")
        except KeyError:
            pass
    attempts = 0
    if LOGIN_MODE == "web":
        logger.debug("Attempting web logon")
        return sync_api.web_login()
    else:
        # default: prompt
        logger.debug("Attempting prompt logon")
        while attempts < 3:
            try:
                sync_api.login(input(f"username for {SYNCPROJECTS_URL}: "), getpass.getpass())
                logger.debug(f"Login success.")
                return True
            except HTTPError as e:
                attempts += 1
                logger.debug(f"Got error: {e}")
    return False


class SyncAPI:
    def __init__(self, refresh_token: str, access_token: str = "", username: str = "", recv_queue: Queue = None,
                 send_queue: Queue = None):
        self.refresh_token = refresh_token
        self.access_token = access_token
        self._username = username
        self.logger = logging.getLogger('syncprojects.api.SyncAPI')
        self.recv_queue = recv_queue
        self.send_queue = send_queue

    @property
    def username(self) -> str:
        """
        Lazy evaluate; fetch the first time this is called.
        :return:
        """
        if not self._username:
            self.logger.debug("Fetching username from API")
            self._username = self._request('users/self/')['username']
            appdata['username'] = self._username
            self.logger.debug(f"Got result {self._username}")
        return self._username

    def has_tokens(self) -> bool:
        return self.refresh_token and self.access_token

    def _request(self, path: str, method: str = 'GET', params: dict = {}, json: dict = {}, headers: dict = {},
                 files: Dict = None, auth: bool = True, refresh: bool = True):
        attempts = 0
        headers['User-Agent'] = "syncprojects-client"
        while attempts < 2:
            if auth and self.access_token:
                headers['Authorization'] = f"Bearer {self.access_token}"
            # Try using access token, fall back to refreshing, then re-login
            try:
                r = requests.request(method=method, url=API_BASE_URL + path, params=params, json=json,
                                     headers=headers, files=files)
            except requests.exceptions.ConnectionError:
                MessageBoxUI.error("Failed to connect to the Syncprojects API! Check your internet connection and try "
                                   "again, or contact support if the error persists.\n\nExiting...")
                sys.exit(1)
            # 2xx status code
            if r.status_code // 100 == 2:
                try:
                    return r.json()
                except JSONDecodeError:
                    return r.text
            elif r.status_code == 401:
                self.logger.debug("Got 401 response, requesting credential re-entry...")
                login_prompt(self)
            elif refresh and r.status_code == 403:
                self.logger.debug("Got 403 response, attempting credential refresh...")
                self.refresh()
            attempts += 1
        self.logger.error(
            f"Multiple requests failed, most recent response code {r.status_code} and msg {r.text}.")
        MessageBoxUI.error("Error communicating with Syncprojects API! A server error occured, or you could not be "
                           "identified. Try again, or contact support if the error persists.\n\nExiting...")
        sys.exit(1)

    def get_all_projects(self):
        return self._request("projects/")["results"]

    def get_project(self, project_id: int):
        return self._request(f"projects/{project_id}/")

    def _lock_request(self, obj: dict, lock: bool = False, force: bool = True, reason: str = "",
                      until: datetime.datetime = None):
        json = {}
        if force:
            json['force'] = force
        if reason:
            json['reason'] = reason
        if until:
            json['until'] = until.timestamp()
        self.logger.debug(f"Submitting {'' if lock else 'UN'}LOCK request for {obj['name']} with config {json}")
        if 'project' in obj:
            # obj is song
            json['song'] = obj['id']
            return self._request(f"projects/{obj['project']}/lock/", method='PUT' if lock else 'DELETE', json=json)
        elif 'songs' in obj:
            # obj is project
            return self._request(f"projects/{obj['id']}/lock/", method='PUT' if lock else 'DELETE', json=json)
        else:
            raise NotImplementedError()

    def lock(self, project: dict, force: bool = False, reason: str = "sync", until: float = None):
        return self._lock_request(project, True, force, reason, until)

    def unlock(self, project: dict, force: bool = False):
        return self._lock_request(project, False, force)

    def login(self, username: str, password: str):
        self.logger.debug("Sending creds for login")
        resp = self._request('token/', 'POST', json={'username': username, 'password': password}, auth=False)
        self.access_token = resp['access']
        self.refresh_token = resp['refresh']
        appdata['access'] = resp['access']
        appdata['refresh'] = resp['refresh']
        self.logger.debug("Saved credentials updated after login.")
        self._username = None
        return self.username

    def refresh(self):
        resp = self._request('token/refresh/', 'POST', json={"refresh": self.refresh_token}, auth=False, refresh=False)
        self.access_token = resp["access"]
        appdata["access"] = resp["access"]
        self.logger.debug("Saved credentials updated after refresh.")

    def handle_auth_msg(self, config: Dict) -> str:
        self.refresh_token = config['refresh']
        self.access_token = config['access']
        appdata.update(config)
        self.logger.debug("Saved credentials updated from API")
        self._username = None
        return self.username

    def web_login(self):
        webbrowser.open(SYNCPROJECTS_URL + "sync/client_login/")
        self.logger.info("Waiting for successful login...")
        while config := self.recv_queue.get():
            if config['msg_type'] == 'auth':
                self.handle_auth_msg(config['data'])
                break
        return True

    def get_client_updates(self):
        return self._request("updates/", params={'target': get_host_string()})['results']

    def add_sync(self, project: Dict, songs: List[int]):
        return self._request("syncs/", "POST", json={
            'project': project['id'],
            'songs': songs,
        })

    def get_backend_creds(self):
        return self._request("backend_creds/", headers={"Content-Type": "application/json"}, params={'id': 1})

    def update_song_url(self, song: Dict):
        if not song['url']:
            return self._request(f"songs/{song['id']}/", "POST", json={
                'url': '#'
            })

    def report_logs(self, log_data: bytes):
        return self._request("logs/", "POST", files={'log_compressed': log_data})
