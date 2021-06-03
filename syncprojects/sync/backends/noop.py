import os
import random
from typing import Dict, List

from syncprojects.sync import SyncBackend, Verdict


class RandomNoOpSyncBackend(SyncBackend):
    """
    A SyncManager that doesn't actually do anything, but produces random output.
    """

    def sync(self, project: Dict, songs: List[Dict], verdict: Verdict = None):
        result = {'status': 'done', 'songs': []}
        for song in songs:
            song_name = song['name']
            if verdict:
                changed = verdict
            elif os.getenv('CHANGED'):
                changed = os.environ['CHANGED']
            else:
                changed = random.choice((*list(Verdict), 'error', None, 'locked', 'disabled'))
            if isinstance(changed, Verdict):
                changed = changed.value
            self.logger.info(f"{project=} {song_name=} {changed=}")
            result['songs'].append(
                {'id': song['id'], 'song': song_name, 'result': 'error' if changed == 'error' else 'success',
                 'action': changed})
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
