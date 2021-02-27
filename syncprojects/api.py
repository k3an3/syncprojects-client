import datetime
import getpass
import logging
import sys
import webbrowser
from time import sleep

import requests
from requests import HTTPError

from syncprojects.config import LOGIN_MODE, SYNCPROJECTS_URL
from syncprojects.storage import appdata

API_BASE_URL = SYNCPROJECTS_URL + "api/v1/"
logger = logging.getLogger('syncprojects.api')


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
    def __init__(self, refresh_token: str, access_token: str = "", username: str = ""):
        self.refresh_token = refresh_token
        self.access_token = access_token
        self._username = username
        self.logger = logging.getLogger('syncprojects.api.SyncAPI')

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

    def _request(self, url: str, method: str = 'GET', params: dict = {}, json: dict = {}, headers: dict = {},
                 auth: bool = True, refresh: bool = True):
        attempts = 0
        while attempts < 2:
            if auth and self.access_token:
                headers['Authorization'] = f"Bearer {self.access_token}"
            # Try using access token, fall back to refreshing, then re-login
            r = requests.request(method=method, url=API_BASE_URL + url, params=params, json=json, headers=headers)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 401:
                self.logger.debug("Got 401 response, requesting credential re-entry...")
                login_prompt(self)
            elif refresh and r.status_code == 403:
                self.logger.debug("Got 403 response, attempting credential refresh...")
                self.refresh()
            attempts += 1
        self.logger.error(
            f"Multiple requests failed, most recent response code {r.status_code} and msg {r.text}. Exiting...")
        sys.exit(1)

    def get_projects(self):
        return self._request("projects/")["results"]

    def _lock_request(self, project: dict, lock: bool = False, force: bool = True, reason: str = "",
                      until: datetime.datetime = None):
        json = {}
        if force:
            json['force'] = force
        if reason:
            json['reason'] = reason
        if until:
            json['until'] = until.timestamp()
        self.logger.debug(f"Submitting {'' if lock else 'UN'}LOCK request for {project['name']} with config {json}")
        return self._request(f"projects/{project['id']}/lock/", method='PUT' if lock else 'DELETE', json=json)

    def lock(self, project: dict, force: bool = False, reason: str = "Sync", until: float = None):
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

    def refresh(self):
        resp = self._request('token/refresh/', 'POST', json={"refresh": self.refresh_token}, auth=False, refresh=False)
        self.access_token = resp["access"]
        appdata["access"] = resp["access"]
        self.logger.debug("Saved credentials updated after refresh.")

    def web_login(self):
        webbrowser.open(SYNCPROJECTS_URL + "sync/client_login/")
        self.logger.info("Waiting for successful login...")
        while True:
            if 'refresh_token' in appdata:
                self.refresh_token = appdata['refresh_token']
                self.access_token = appdata['access_token']
                self.logger.debug("Saved credentials updated from Flask server")
                return True
            sleep(1)
