import random
from typing import Dict, List

from syncprojects.sync import SyncBackend


class RandomNoOpSyncBackend(SyncBackend):
    """
    A SyncManager that doesn't actually do anything, but produces random output.
    """

    def sync(self, project: Dict, songs: List[Dict]):
        result = {'status': 'done', 'songs': []}
        for song in songs:
            song = song['name']
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

    def get_local_changes(self, songs: List[Dict]):
        pass
