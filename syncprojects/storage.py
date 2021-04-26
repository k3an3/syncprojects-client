import json
import logging
import os
import pathlib
from os.path import isfile, dirname

from sqlitedict import SqliteDict

from syncprojects import config
from syncprojects.utils import get_datadir, migrate_old_settings, get_config_path

logger = logging.getLogger('syncprojects.storage')


class SongData:
    def __init__(self, song_id: int, revision: int = 0, known_hash: str = ""):
        self.song_id = song_id
        self.revision = revision
        self.known_hash = known_hash


def get_song(data: SqliteDict, song: int):
    if song not in data:
        logger.info("Song doesn't exist in local db, adding...")
        data[song] = SongData(song)
    return data[song]


def get_appdata():
    config_created = False
    if config.DEBUG:
        config_dir = pathlib.Path("..")
    else:
        config_dir = get_datadir("syncprojects")
    try:
        logger.debug(f"Creating new datadir in {config_dir}")
        config_dir.mkdir(parents=True)
        config_created = True
    except FileExistsError:
        logger.debug(f"Datadir already exists at {config_dir}")
    config_file = str(config_dir / "config.sqlite")
    if not isfile(config_file):
        config_created = True
    loaded_config = SqliteDict(config_file)
    if config_created:
        logger.info("Performing migration to new config storage...")
        migrate_old_settings(loaded_config)
    loaded_config.autocommit = True
    return loaded_config


def get_songdata(project: str):
    if config.DEBUG:
        config_dir = pathlib.Path("..")
    else:
        config_dir = get_datadir("syncprojects")
    config_file = str(config_dir / "songdata.sqlite")
    if not isfile(config_file):
        config_created = True
    loaded_config = SqliteDict(config_file, tablename=project)
    if config_created:
        logger.info("Created songdata db.")
    loaded_config.autocommit = True
    return loaded_config


appdata = get_appdata()
songdata = get_songdata()


def get_hash_store(project):
    loaded_store = SqliteDict(get_config_path(), tablename=project, autocommit=True)
    return loaded_store


# legacy
class HashStore:
    def __init__(self, hash_store_path):
        self.store = hash_store_path
        self.content = {}

    def get(self, key):
        return self.content.get(key)

    def open(self):
        logger.debug(f"Opening hash store at {self.store}")
        try:
            with open(self.store) as f:
                self.content = json.load(f)
                logger.debug(f"Loaded hash store successfully")
                return self.content
        except FileNotFoundError as e:
            if not os.access(dirname(self.store), os.W_OK):
                logger.critical(f"Couldn't open hash store at {self.store} for writing!")
                raise e
            logger.debug(f"Didn't find hash store at {self.store}, returning empty")
            return {}
        except json.decoder.JSONDecodeError:
            logger.debug(f"Error decoding JSON in hash store {self.store}, returning empty")
            return {}

    def update(self, key, value):
        self.content[key] = value
        try:
            with open(self.store, "w") as f:
                json.dump(self.content, f)
        except FileNotFoundError as e:
            logger.critical(f"Couldn't open hash store at {self.store} for writing!")
            raise e
