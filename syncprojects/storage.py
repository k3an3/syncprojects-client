import json
import logging
from os.path import isfile

from sqlitedict import SqliteDict

from syncprojects.utils import get_datadir, migrate_old_settings, get_config_path

logger = logging.getLogger('syncprojects.storage')


def get_appdata():
    config_dir = get_datadir("syncprojects")
    config_created = False
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


appdata = get_appdata()


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
        try:
            with open(self.store) as f:
                self.content = json.load(f)
                return self.content
        except FileNotFoundError:
            logger.debug(f"Didn't find hash store at {self.store}, returning empty")
            return {}
        except json.decoder.JSONDecodeError:
            logger.debug(f"Error decoding JSON in hash store {self.store}, returning empty")
            return {}

    def update(self, key, value):
        self.content[key] = value
        with open(self.store, "w") as f:
            json.dump(self.content, f)
