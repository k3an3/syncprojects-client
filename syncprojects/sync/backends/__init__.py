from os.path import join, isdir, isfile

import concurrent
import logging
import os
import time
from abc import ABC, abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum
from glob import glob
from typing import Dict, List, Union

from syncprojects import config
from syncprojects.api import SyncAPI
from syncprojects.storage import appdata
from syncprojects.utils import hash_file, get_song_dir, report_error

logger = logging.getLogger('syncprojects.sync.backends')


class Verdict(Enum):
    LOCAL = "local"
    REMOTE = "remote"
    CONFLICT = "conflict"


ResultType = Dict[str, Union[str, List[Dict]]]


class SyncBackend(ABC):
    def __init__(self, api_client: SyncAPI, *args, **kwargs):
        self.api_client = api_client
        self.local_hash_cache = {}
        self.logger = logging.getLogger(f'syncprojects.sync.backends.{self.__class__.__name__}')

    @abstractmethod
    def sync(self, project: Dict, songs: List[Dict], force_verdict: Verdict = None):
        pass

    def sync_amps(self, project: Dict):
        try:
            for amp in self.get_local_neural_dsp_amps():
                self.push_amp_settings(amp, project)
                self.pull_amp_settings(amp, project)
        except FileNotFoundError as e:
            self.logger.error("Didn't find amp preset dir: %s", e)
        except Exception as e:
            self.logger.error("Error syncing amps: %s", e)
            report_error(e)

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

    @staticmethod
    def hash_project_root_directory(dir_name):
        hash_algo = config.DEFAULT_HASH_ALGO()
        if isdir(dir_name):
            for file_name in glob(join(dir_name, config.PROJECT_GLOB)):
                if isfile(file_name):
                    logger.debug(f"Hashing {file_name}")
                    hash_file(file_name, hash_algo)
            hash_digest = hash_algo.hexdigest()
            return hash_digest

    def get_local_changes(self, songs: List[Dict]):
        self.logger.info("Checking local files for changes...")
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            futures = {
                executor.submit(self.hash_project_root_directory,
                                join(appdata['source'], get_song_dir(s))): s
                for s in
                songs}
            for results in concurrent.futures.as_completed(futures):
                song = futures[results]
                try:
                    src_hash = results.result()
                except FileNotFoundError:
                    self.logger.debug(f"Didn't get hash for {song['name']}")
                    src_hash = ""
                self.local_hash_cache[f"{song['project']}:{song['id']}"] = src_hash
        self.logger.debug("Completed in %ds", round(time.perf_counter() - start, 2))
