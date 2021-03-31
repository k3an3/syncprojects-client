import functools
from queue import Empty
from typing import Dict
from uuid import uuid4

import jwt
from flask import request, abort
from jwt import InvalidSignatureError, ExpiredSignatureError, DecodeError

from syncprojects import config as config
from syncprojects.storage import appdata


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


def verify_data(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        try:
            if request.referrer != config.SYNCPROJECTS_URL:
                abort(403)
            if request.method == "POST":
                data = request.get_json()['data']
            else:
                data = request.args['data']
            decoded = jwt.decode(data, config.PUBLIC_KEY, algorithms=["RS256"])
            decoded.pop('exp', None)
            # if 'user' in decoded and decoded['user'] != appdata['username']:
            #    abort(403)
            decoded.pop('user', None)
            return f(decoded, *args, **kwargs)
        except (InvalidSignatureError, ExpiredSignatureError, KeyError, ValueError, DecodeError) as e:
            if config.DEBUG:
                raise e
            abort(403)
        except TypeError as e:
            if config.DEBUG:
                raise e
            abort(400)

        return f(*args, **kwargs)

    return wrapped
