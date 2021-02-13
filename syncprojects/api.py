import requests

API_BASE_URL = "https://syncprojects.app/api/v1/"


class SyncAPI:
    def __init__(self, refresh_token: str, access_token: str = ""):
        self.refresh_token = refresh_token
        self.access_token = access_token

    @staticmethod
    def _request(url: str, method: str = 'GET', params: dict = {}, json: dict = {}):
        return requests.request(method=method, url=API_BASE_URL + url, params=params, json=json).json()

    def get_projects(self):
        self._request("projects")

    def lock(self, project: str, force: bool = False):
        json = {}
        if force:
            json = {'force': True}
        self._request(f"projects/{project}/lock/", method='PUT', json=json)

    def unlock(self, project, force: bool = False):
        json = {}
        if force:
            json = {'force': True}
        self._request(f"projects/{project}/lock/", method='DELETE', json=json)
