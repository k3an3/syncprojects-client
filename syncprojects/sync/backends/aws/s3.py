from concurrent.futures import ThreadPoolExecutor, as_completed
from os.path import join, isdir

import logging
import os
import time
from typing import Dict, List, Callable

from syncprojects import config
from syncprojects.api import SyncAPI
from syncprojects.config import DEBUG
from syncprojects.storage import appdata, get_songdata, get_song, SongData
from syncprojects.sync import SyncBackend
from syncprojects.sync.backends import Verdict
from syncprojects.sync.backends.aws.auth import AWSAuth
from syncprojects.ui.message import MessageBoxUI
from syncprojects.ui.tray import notify
from syncprojects.utils import get_song_dir, report_error, hash_file, request_local_api

AWS_REGION = 'us-east-1'

logger = logging.getLogger('syncprojects.sync.backends.aws.s3')

try:
    from syncprojects_fast import walk_dir as fast_walk_dir
    logger.info("Using Rust modules")
    fast_get_difference = None
except ImportError:
    logger.info("Using native modules.")
    fast_walk_dir = None
    fast_get_difference = None
else:
    logger.info("Using Rust extensions.")


def handle_conflict(song_name: str) -> Verdict:
    logger.debug("Prompting user for conflict resolution")
    notify("Sync conflict! See the pop-up to resolve.")
    result = MessageBoxUI.yesnocancel(
        f"{song_name} has changed both locally and remotely! Which one do you "
        f"want to " f"keep? Note that proceeding may cause loss of "
        f"data.\n\nChoose \"yes\" to " f"confirm overwrite of local files, "
        f"\"no\" to confirm overwrite of server " f"files. Or, \"cancel\" "
        f"to skip.", "Sync Conflict")
    logger.debug(f"User pressed {result}")
    if result:
        return Verdict.REMOTE
    elif result is None:
        return None
    else:
        return Verdict.LOCAL


def handle_archive(song_name: str) -> Verdict:
    logger.debug("Trying to update archived song %s, prompting user", song_name)
    result = MessageBoxUI.yesnocancel(
        f"\"{song_name}\" is marked as archived, which means changes cannot be sent to the server. Would you like to "
        f"overwrite your local files with the server's files? All changes you have made may be irreversibly lost!",
        "Sync Conflict")
    logger.debug(f"User pressed {result}")
    if result:
        return Verdict.REMOTE
    else:
        return None


def diff_paths(src: Dict, dst: Dict) -> List:
    return src.keys() - dst.keys()


class S3SyncBackend(SyncBackend):
    def __init__(self, api_client: SyncAPI, auth: AWSAuth, bucket: str):
        super().__init__(api_client)
        self.auth = auth
        self.client = self.auth.authenticate()
        self.bucket = bucket
        self.logger.debug(f"Using bucket {bucket}")

    # This seems pretty generic; maybe it could be promoted?
    def get_verdict(self, song_data: SongData, song: Dict) -> Verdict:
        """
        Determine whether sync should copy local to remote, remote to local, or no action.
        :param song_data: Locally-stored song information
        :param song: Song information from the API
        :return: A Verdict enum selection for what to do
        """
        self.logger.debug(
            f"Local revision {song_data.revision}, remote revision {song['revision']}")
        local_hash = self.local_hash_cache.get(f"{song['project']}:{song['id']}")
        local_changed = local_hash != song_data.known_hash
        if song['revision'] == song_data.revision:
            self.logger.debug("Local revision same as remote, further checks needed")
            if not local_hash:
                self.logger.debug("No local hash, song doesn't exist locally.")
                return Verdict.REMOTE
            elif local_changed:
                self.logger.debug("Local hash differs from known; local was changed.")
                return Verdict.LOCAL
            else:
                self.logger.debug("No changes detected.")
        elif song['revision'] > song_data.revision:
            self.logger.debug("Local revision out-of-date")
            if local_changed:
                self.logger.warn("Local AND remote changed")
                return Verdict.CONFLICT
            return Verdict.REMOTE
        else:
            self.logger.info("Local revision newer")
            return Verdict.LOCAL

    def get_remote_manifest(self, path: str) -> Dict:
        manifest = {}
        self.logger.debug(f"Generating remote manifest from bucket {self.bucket} {path=}")
        continuation_token = ""
        while True:
            if continuation_token:
                results = self.client.list_objects_v2(Bucket=self.bucket, Prefix=path,
                                                      ContinuationToken=continuation_token)
            else:
                results = self.client.list_objects_v2(Bucket=self.bucket, Prefix=path)
            if 'Contents' in results:
                logger.debug("Got %d results", len(results['Contents']))
                manifest.update({obj['Key'].split(path)[1]: obj['ETag'][1:-1] for obj in results['Contents']})
            else:
                logger.warning("No results retrieved")
                break
            if not results['IsTruncated']:
                break
            else:
                continuation_token = results['NextContinuationToken']
                logger.debug("Results truncated, fetching more")
        return manifest

    def get_local_manifest(self, path: str) -> Dict:
        path = join(appdata['source'], path)
        self.logger.debug(f"Generating local manifest from {path}")
        start = time.perf_counter()
        if fast_walk_dir:
            results = fast_walk_dir(path)
        else:
            results = walk_dir(path)
        duration = time.perf_counter() - start
        self.logger.debug(
            f"Got {len(results)} files from local manifest; {round(duration, 4)} seconds; {fast_walk_dir=}")

        return results

    def handle_upload(self, song: Dict, key: str, remote_path: str):
        self.client.upload_file(join(appdata['source'], get_song_dir(song), key),
                                self.bucket,
                                remote_path + key)

    def handle_download(self, song: Dict, key: str, remote_path: str):
        fail_count = 0
        while fail_count < 2:
            try:
                self.client.download_file(self.bucket,
                                          remote_path + key,
                                          join(appdata['source'], get_song_dir(song), *key.split('/'))
                                          )
                break
            except FileNotFoundError:
                os.makedirs(join(appdata['source'], get_song_dir(song), *key.split('/')[:-1]), exist_ok=True)
                fail_count += 1

    def sync(self, project: Dict, songs: List[Dict], force_verdict: Verdict = None) -> Dict:
        results = {'status': 'done', 'songs': []}
        with get_songdata(str(project['id'])) as project_song_data:
            for song in songs:
                try:
                    # Used to parse nested directories
                    song['project_name'] = project['name']
                    # Locally-cached song information for comparison
                    song_data = get_song(project_song_data, song['id'])
                    # Break out the song name since this is used a lot
                    song_name = song['name']

                    self.logger.debug(f"Working on {song_name}")
                    if force_verdict:
                        verdict = force_verdict
                        self.logger.debug(f"Using pre-specified {verdict=}")
                    else:
                        verdict = self.get_verdict(song_data, song)

                    self.logger.debug(f"Got initial {verdict=}")
                    if not verdict:
                        self.logger.info(f"No action for {song_name}")
                        results['songs'].append({'song': song_name, 'result': 'success', 'action': None})
                        continue
                    remote_path = f"{project['id']}/{song['id']}/"
                    remote_manifest = self.get_remote_manifest(remote_path)
                    local_manifest = self.get_local_manifest(get_song_dir(song))

                    if not local_manifest:
                        if not remote_manifest:
                            logger.info("Both manifests empty; doing nothing")
                            verdict = None
                        else:
                            logger.warning("Local manifest empty; assuming remote")
                            verdict = Verdict.REMOTE

                    if verdict == Verdict.LOCAL and song['archived']:
                        verdict = handle_archive(song_name)

                    if verdict == Verdict.CONFLICT:
                        verdict = handle_conflict(song_name)

                    if verdict == Verdict.LOCAL:
                        src = local_manifest
                        dst = remote_manifest
                        action = self.handle_upload
                        # This object will replace the local song data upon completion
                        new_song_data = SongData(song_id=song['id'],
                                                 known_hash=self.local_hash_cache.get(
                                                     f"{song['project']}:{song['id']}"),
                                                 revision=song['revision'] + 1)
                    elif verdict == Verdict.REMOTE:
                        src = remote_manifest
                        dst = local_manifest
                        action = self.handle_download
                        new_song_data = SongData(song_id=song['id'],
                                                 revision=song['revision'])
                    else:
                        self.logger.info(f"{song_name} skipped")
                        results['songs'].append({'song': song_name, 'result': 'success', 'action': None})
                        continue

                    self.logger.info("Starting parallel file transfer...")
                    start_time = time.perf_counter()
                    completed = do_action(action, song, src, dst, remote_path)
                    duration = time.perf_counter() - start_time
                    self.logger.info(f"Updated {completed} files in {round(duration, 4)} seconds.")
                except Exception as e:
                    results['songs'].append({'song': song_name, 'result': 'error', 'msg': str(e)})
                    self.logger.error("Error syncing %s: %s.", song_name, e)
                    MessageBoxUI.error(f'Error syncing {song_name}; please try again or contact support if the error '
                                       f'persists.')
                    if DEBUG:
                        raise e
                    report_error(e)
                else:
                    if new_song_data:
                        if not new_song_data.known_hash:
                            new_song_data.known_hash = SyncBackend.hash_project_root_directory(
                                join(appdata['source'], get_song_dir(song)))
                        project_song_data[song['id']] = new_song_data
                        project_song_data.commit()
                    results['songs'].append(
                        {'song': song_name, 'id': song['id'],
                         'result': 'success',
                         'revision': song_data.revision,
                         'action': verdict.value
                         })
                    self.logger.info(f"Successfully synced {song_name}")
        return results

    def push_amp_settings(self, amp: str, project: Dict):
        try:
            bases = [join(appdata['neural_dsp_path'], amp, "User")]
            remote_path = f"{project['id']}/Amp Settings/{amp}/"
            while bases:
                base = bases.pop()
                for root, dirs, files in os.walk(base):
                    for file in files:
                        self.client.upload_file(join(root, file),
                                                self.bucket,
                                                '/'.join(remote_path + file))
                    for d in dirs:
                        bases.extend(join(base, d))
        except Exception as e:
            report_error(e)

    def pull_amp_settings(self, amp: str, project: Dict):
        continuation_token = ""
        remote_path = f"{project['id']}/Amp Settings/{amp}/"
        try:
            while True:
                if continuation_token:
                    results = self.client.list_objects_v2(Bucket=self.bucket, Prefix=remote_path,
                                                          ContinuationToken=continuation_token)
                else:
                    results = self.client.list_objects_v2(Bucket=self.bucket, Prefix=remote_path)
                if 'Contents' in results:
                    logger.debug("Got %d results", len(results['Contents']))
                    results.extend([obj['Key'] for obj in results['Contents']])
                else:
                    logger.warning("No results retrieved")
                    break
                if not results['IsTruncated']:
                    break
                else:
                    continuation_token = results['NextContinuationToken']
                    logger.debug("Results truncated, fetching more")
            base = join(appdata['neural_dsp_path'], amp, "User")
            for result in results:
                self.client.download_file(self.bucket,
                                          remote_path + result,
                                          join(base, *result.split('/'))
                                          )
        except Exception as e:
            report_error(e)


def do_action(action: Callable, song: Dict, src: Dict, dst: Dict, remote_path: str) -> int:
    if os.getenv('THREADS_OFF') == '1':
        logger.debug("Not using threading!")
        results = []
        if fast_get_difference:
            for key in fast_get_difference(src, dst):
                try:
                    results.append(action(song, key, remote_path))
                except Exception as e:
                    logger.error(f"{action=} failed with exception: {e}")
        else:
            for key, tag in src.items():
                if key not in dst or tag != dst[key]:
                    try:
                        results.append(action(song, key, remote_path))
                    except Exception as e:
                        logger.error(f"{action=} failed with exception: {e}")
        return len(results)
    else:
        workers = appdata.get('workers', config.MAX_WORKERS)
        logger.debug("Using %d threads", workers)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            if fast_get_difference:
                for key in fast_get_difference(src, dst):
                    futures.append(executor.submit(action, song, key, remote_path))
            else:
                for key, tag in src.items():
                    if key not in dst or tag != dst[key]:
                        futures.append(executor.submit(action, song, key, remote_path))
            done = 0
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"{action=} failed with exception: {e}")
                else:
                    done += 1
            if done != len(futures):
                # noinspection PyBroadException
                try:
                    request_local_api('logs')
                except Exception:
                    pass
            return done


def walk_dir(root: str, base: str = "", executor: ThreadPoolExecutor = None) -> Dict[str, str]:
    top = False
    if not executor:
        if not isdir(root):
            return {}
        executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)
        top = True
    futures = {}
    for entry in os.scandir(root):
        path = join(root, entry)
        if isdir(path):
            futures.update(walk_dir(path, join(base, entry.name), executor))
            continue
        if not entry.name.endswith('.peak') and '\\' not in entry.name:
            futures[executor.submit(hash_file, path)] = join(base, entry.name).replace("\\", "/")
    if top:
        manifest = {}
        for future in as_completed(futures):
            manifest[futures[future]] = future.result()
        return manifest
    return futures
