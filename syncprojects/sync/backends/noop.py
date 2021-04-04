import random
from typing import Dict

from syncprojects.sync import SyncBackend


class RandomNoOpSyncBackend(SyncBackend):
    """
    A SyncManager that doesn't actually do anything, but produces random output.
    """

    def sync(self, project: Dict):
        songs = [song['name'] for song in project['songs'] if
                 song['sync_enabled'] and not song['is_locked']]
        result = {'status': 'done', 'songs': []}
        for song in songs:
            changed = random.choice(('local', 'remote', 'error', None, 'locked', 'disabled'))
            self.logger.info(f"{project=} {song=} {changed=}")
            result['songs'].append(
                {'song': song, 'result': 'error' if changed == 'error' else 'success', 'action': changed})
        return result

    def push_amp_settings(self, project: str):
        pass

    def pull_amp_settings(self, project: str):
        pass

    @staticmethod
    def get_local_neural_dsp_amps():
        return []
