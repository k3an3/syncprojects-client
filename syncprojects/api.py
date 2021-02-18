import getpass
import webbrowser
from time import sleep

import requests
from requests import HTTPError

from syncprojects.config import LOGIN_MODE, SYNCPROJECTS_URL
from syncprojects.utils import Logger, appdata

API_BASE_URL = SYNCPROJECTS_URL + "api/v1/"


def login_prompt(sync_api) -> bool:
    del appdata['refresh_token']
    del appdata['access_token']
    attempts = 0
    if LOGIN_MODE == "web":
        return sync_api.web_login()
    else:
        # default: prompt
        while attempts < 3:
            try:
                sync_api.login(input("syncprojects.app username: "), getpass.getpass())
                return True
            except HTTPError:
                attempts += 1
    return False


class Project:
    def __init__(self, name: str, p_id: int):
        self.name = name
        self.p_id = p_id


class SyncAPI:
    def __init__(self, refresh_token: str, access_token: str = ""):
        self.refresh_token = refresh_token
        self.access_token = access_token

    @staticmethod
    def _request(url: str, method: str = 'GET', params: dict = {}, json: dict = {}, headers: dict = {}):
        return requests.request(method=method, url=API_BASE_URL + url, params=params, json=json).json()

    def get_projects(self):
        return [Project(p["name"], p["id"]) for p in self._request("projects")["results"]]

    def _lock_request(self, project: int, lock: bool = False, force: bool = True):
        json = {}
        if force:
            json = {'force': True}
        attempts = 0
        while attempts < 2:
            # Try using access token, fall back to refreshing, then re-login
            r = self._request(f"projects/{project}/lock/", method='PUT' if lock else 'DELETE', json=json)
            if r.status_code == 200:
                return r.json()
            elif attempts > 0:
                login_prompt(self)
            elif r.status_code == 401:
                self.refresh()
            attempts += 1

    def lock(self, project: Project, force: bool = False):
        return self._lock_request(project.p_id, True, force)

    def unlock(self, project: Project, force: bool = False):
        return self._lock_request(project.p_id, False, force)

    def login(self, username: str, password: str):
        resp = self._request('token/', 'POST', json={'username': username, 'password': password})
        resp.raise_for_status()
        resp = resp.json()
        self.access_token = resp['access']
        self.refresh_token = resp['refresh']

    def refresh(self):
        resp = self._request('token/refresh/', 'POST', json={"refresh": self.refresh_token}).json()
        self.access_token = resp["access"]

    def web_login(self):
        webbrowser.open(API_BASE_URL + "token/fetch")
        Logger.log("Waiting for successful login...")
        while True:
            if 'refresh_token' in appdata:
                self.refresh_token = appdata['refresh_token']
                self.access_token = appdata['access_token']
                return True
            sleep(1)
