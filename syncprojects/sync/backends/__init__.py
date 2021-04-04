import concurrent
import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from glob import glob
from os.path import join, isdir, isfile
from typing import Dict, List

from syncprojects import config
from syncprojects.api import SyncAPI
from syncprojects.storage import appdata
from syncprojects.utils import hash_file


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

    def hash_directory(self, dir_name):
        hash_algo = config.DEFAULT_HASH_ALGO()
        if isdir(dir_name):
            for file_name in glob(join(dir_name, config.PROJECT_GLOB)):
                if isfile(file_name):
                    self.logger.debug(f"Hashing {file_name}")
                    hash_file(file_name, hash_algo)
            hash_digest = hash_algo.hexdigest()
            self.remote_hash_cache[dir_name] = hash_digest
            return hash_digest

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
