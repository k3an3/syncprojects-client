import json
import logging

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
    loaded_config = SqliteDict(str(config_dir / "config.sqlite"))
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
    def __init__(self, project):
        self.project = project
        self.content = {}

    def get(self, key):
        return self.content.get(key)

    def open(self):
        try:
            with open(self.store) as f:
                self.content = json.load(f)
                return self.content
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            return {}

    def update(self, key, value):
        self.content[key] = value
        with open(self.store, "w") as f:
            json.dump(self.content, f)
