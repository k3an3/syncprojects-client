import concurrent
import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from os.path import join
from typing import Dict, List

from syncprojects import config
from syncprojects.api import SyncAPI
from syncprojects.storage import appdata


class SyncBackend(ABC):
    def __init__(self, api_client: SyncAPI):
        self.api_client = api_client
        self.local_hash_cache = {}
        self.logger = logging.getLogger(f'syncprojects.sync.backends.{self.__class__.__name__}')

    @abstractmethod
    def sync(self, project: Dict):
        pass

    def sync_amps(self, project: str):
        for amp in self.get_local_neural_dsp_amps():
            self.push_amp_settings(amp, project)
            self.pull_amp_settings(amp, project)

    @abstractmethod
    def push_amp_settings(self, amp: str, project: str):
        pass

    @abstractmethod
    def pull_amp_settings(self, amp: str, project: str):
        pass

    @staticmethod
    def get_local_neural_dsp_amps():
        with os.scandir(appdata['neural_dsp_path']) as entries:
            for entry in entries:
                if entry.is_dir() and entry.name != "Impulse Responses":
                    yield entry.name

    def get_local_changes(self, songs: List[Dict]):
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
