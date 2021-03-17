from queue import Empty
from typing import Dict
from uuid import uuid4


def queue_put(name, data: Dict = {}, dry_run: bool = False) -> str:
    from syncprojects.server.server import app
    task_id = gen_task_id()
    if not dry_run:
        app.config['main_queue'].put({'msg_type': name, 'task_id': task_id, 'data': data})
    return task_id


def queue_get() -> Dict:
    from syncprojects.server.server import app
    queue_results = []
    while True:
        try:
            queue_results.append(app.config['server_queue'].get_nowait())
        except Empty:
            break
    return queue_results


def gen_task_id() -> str:
    return str(uuid4())


def response_started(task_id: str) -> Dict:
    return {'result': 'started', 'task_id': task_id}
