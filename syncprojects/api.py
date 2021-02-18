import getpass
import sys
import webbrowser
from time import sleep

import requests
from requests import HTTPError

from syncprojects.config import LOGIN_MODE, DEBUG, SYNCPROJECTS_URL
from syncprojects.utils import Logger, appdata

if DEBUG:
    SYNCPROJECTS_URL = "http://localhost:8000/"
API_BASE_URL = SYNCPROJECTS_URL + "api/v1/"


def login_prompt(sync_api) -> bool:
    for key in ('refresh_token', 'access_token'):
        try:
            del appdata[key]
        except KeyError:
            pass
    attempts = 0
    if LOGIN_MODE == "web":
        return sync_api.web_login()
    else:
        # default: prompt
        while attempts < 3:
            try:
                sync_api.login(input(f"username for {SYNCPROJECTS_URL}: "), getpass.getpass())
                return True
            except HTTPError:
                attempts += 1
    return False


class Project:
    def __init__(self, name: str, p_id: int):
        self.name = name
        self.p_id = p_id


class SyncAPI:
    def __init__(self, logger: Logger, refresh_token: str, access_token: str = ""):
        self.refresh_token = refresh_token
        self.access_token = access_token
        self.logger = logger

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
                login_prompt(self)
                self.logger.log("Requesting credential re-entry...", level=1)
            elif refresh and r.status_code == 403:
                self.logger.log("Attempting credential refresh...", level=1)
                self.refresh()
            attempts += 1
        self.logger.log(
            f"Multiple requests failed, most recent response code {r.status_code} and msg {r.text}. Exiting...")
        sys.exit(1)

    def get_projects(self):
        return [Project(p["name"], p["id"]) for p in self._request("projects/")["results"]]

    def _lock_request(self, project: int, lock: bool = False, force: bool = True):
        json = {}
        if force:
            json = {'force': True}
        return self._request(f"projects/{project}/lock/", method='PUT' if lock else 'DELETE', json=json)

    def lock(self, project: Project, force: bool = False):
        return self._lock_request(project.p_id, True, force)

    def unlock(self, project: Project, force: bool = False):
        return self._lock_request(project.p_id, False, force)

    def login(self, username: str, password: str):
        resp = self._request('token/', 'POST', json={'username': username, 'password': password}, auth=False)
        self.access_token = resp['access']
        self.refresh_token = resp['refresh']
        appdata['access'] = resp['access']
        appdata['refresh'] = resp['refresh']

    def refresh(self):
        resp = self._request('token/refresh/', 'POST', json={"refresh": self.refresh_token}, auth=False, refresh=False)
        self.access_token = resp["access"]
        appdata["access"] = resp["access"]

    def web_login(self):
        webbrowser.open(SYNCPROJECTS_URL + "sync/client_login/")
        self.logger.log("Waiting for successful login...")
        while True:
            if 'refresh_token' in appdata:
                self.refresh_token = appdata['refresh_token']
                self.access_token = appdata['access_token']
                return True
            sleep(1)
