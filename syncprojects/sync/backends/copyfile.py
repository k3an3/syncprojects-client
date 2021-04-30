import os
import traceback
from os.path import isdir, join
from typing import Dict, List

import sys

from syncprojects.storage import HashStore, appdata
from syncprojects.sync import SyncBackend
from syncprojects.sync.operations import handle_new_song, changelog, copy, copy_tree
from syncprojects.ui.message import MessageBoxUI
from syncprojects.utils import get_datadir, print_hr, get_latest_change, fmt_error, current_user, \
    mount_persistent_drive, test_mode


class ShareDriveSyncBackend(SyncBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.local_hs = HashStore(str(get_datadir("syncprojects") / "hashes"))
        self.remote_hash_cache = {}
        if not isdir(appdata['smb_drive']):
            mount_persistent_drive()
        if not isdir(appdata['smb_drive']) and not test_mode():
            self.logger.critical(f"Error! Destination path {appdata['smb_drive']} not found.")
            MessageBoxUI.error(f"Syncprojects could not find your share drive f{appdata['smb_drive']}. Please ensure "
                               f"it is connected.")
            sys.exit(-1)

    def print(self, *args, **kwargs):
        if not self.headless:
            print(*args, **kwargs)

    def is_updated(self, song: Dict, dir_name: str, group: str, remote_hs: HashStore) -> str:
        dest = join(appdata['smb_drive'], group)
        src_hash = self.local_hash_cache[f"{song['project']}:{song['id']}"]
        self.logger.debug(f"local_hash is {src_hash}")
        dst_hash = remote_hs.get(dir_name)
        self.remote_hash_cache[join(dest, dir_name)] = dst_hash
        if appdata['legacy_mode'] or not dst_hash:
            self.logger.info("Checking with the slow/old method just in case we missed it...")
            try:
                dst_hash = self.hash_project_root_directory(join(dest, dir_name))
            except FileNotFoundError:
                dst_hash = ""
        self.logger.debug(f"remote_hash is {dst_hash}")
        known_hash = self.local_hs.get(dir_name)
        if not known_hash:
            self.logger.debug(f"didn't exist in database: {dir_name=}")
            self.logger.info("Not in database; adding...")
            new_hash = src_hash or dst_hash
            self.local_hs.update(dir_name, new_hash)
            known_hash = new_hash
        else:
            self.logger.debug(f"known_hash is {known_hash}")
        if src_hash != known_hash and dst_hash != known_hash:
            return "mismatch"
        elif src_hash and (not dst_hash or src_hash != known_hash):
            return "local"
        elif dst_hash and (not src_hash or dst_hash != known_hash):
            return "remote"

    def sync(self, project: Dict, songs: List[Dict]) -> Dict:
        project = project['name']
        remote_stores = {}

        project_dest = join(appdata['smb_drive'], project)
        remote_store_name = join(project_dest, appdata['remote_hash_store'])
        self.logger.debug(f"Directory config: {project_dest=}, {remote_store_name=}")
        self.logger.debug(f"{self.local_hash_cache=}")
        self.logger.debug(f"{self.remote_hash_cache=}")
        try:
            # Database already opened, contents cached
            remote_hs = remote_stores[remote_store_name]
            self.logger.debug("Cache hit; remote database already opened.")
        except KeyError:
            remote_hs = HashStore(remote_store_name)
            # Database not opened yet, need to read from disk
            self.logger.debug(f"{remote_hs.open()=}")
            remote_stores[remote_store_name] = remote_hs

        results = {'status': 'done', 'songs': []}
        for song in songs:
            song_name = song['name']
            og_song = song
            song = song.get('directory_name') or song['name']
            self.print(print_hr())
            self.logger.info(f"Syncing {song_name}")
            not_local = False
            if not isdir(join(appdata['source'], song)):
                self.logger.info(f"{song_name} does not exist locally.")
                not_local = True
            up = self.is_updated(og_song, song, project, remote_hs)
            self.logger.debug(f"Got status: {up}")
            if not_local:
                up == "remote"
                handle_new_song(song, remote_hs)
            if up == "mismatch":
                self.logger.warning("Sync conflict: both local and remote have changed!")
                if changes := get_latest_change(join(project_dest, song)):
                    MessageBoxUI.info(changes, "Sync Conflict: changes")
                result = MessageBoxUI.yesnocancel(
                    f"{song_name} has changed both locally and remotely! Which one do you "
                    f"want to " f"keep? Note that proceeding may cause loss of "
                    f"data.\n\nChoose \"yes\" to " f"confirm overwrite of local files, "
                    f"\"no\" to confirm overwrite of server " f"files. Or, \"cancel\" "
                    f"to skip.", "Sync Conflict")
                if result:
                    up = "remote"
                elif result is None:
                    up = None
                else:
                    up = "local"
            if up == "remote":
                src = project_dest
                dst = appdata['source']
            elif up == "local":
                src = appdata['source']
                dst = project_dest
                self.logger.debug("Prompting for changelog")
                changelog(song)
            else:
                self.logger.info(f"No action for {song_name}")
                results['songs'].append({'song': song_name, 'result': 'success', 'action': up})
                continue
            self.local_hs.update(song, self.remote_hash_cache[join(src, song)])
            try:
                self.logger.info("Now copying {} from {} ({}) to {} ({})".format(song, up, src,
                                                                                 "remote" if up == "local" else "local",
                                                                                 dst))
                try:
                    remote_hs.update(song, self.remote_hash_cache[join(src, song)])
                except Exception as e:
                    self.logger.error(fmt_error("sync:update_remote_hashes", e))
                    if not appdata['legacy_mode']:
                        self.logger.critical("Failed to update remote hashes!")
                        raise e
                copy(song, src, dst)
            except Exception as e:
                results['songs'].append({'song': song_name, 'result': 'error', 'msg': str(e)})
                self.logger.error(f"Error syncing {song}: {e}.")
            else:
                results['songs'].append({'song': song_name, 'result': 'success', 'action': up})
                self.logger.info(f"Successfully synced {song_name}")
        self.print(print_hr())
        self.print(print_hr('='))
        return results

    def push_amp_settings(self, amp, project):
        try:
            copy_tree(join(appdata['neural_dsp_path'], amp, "User"),
                      join(appdata['smb_drive'], project, 'Amp Settings', amp, current_user()),
                      single_depth=True,
                      update=True,
                      progress=False)
        except FileNotFoundError:
            self.logger.debug(traceback.format_exc())
            pass

    def pull_amp_settings(self, amp, project):
        with os.scandir(join(appdata['smb_drive'], project, 'Amp Settings', amp)) as entries:
            for entry in entries:
                if entry.name != current_user():
                    copy_tree(entry.path,
                              join(appdata['neural_dsp_path'], amp, "User", entry.name),
                              update=True,
                              progress=False)
