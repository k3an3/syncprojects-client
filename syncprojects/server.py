import logging
from queue import Empty
from typing import Dict
from uuid import uuid4

from flask import Flask, request, cli

from syncprojects.config import DEBUG, SYNCPROJECTS_URL
from syncprojects.utils import verify_data

app = Flask(__name__)
logger = logging.getLogger('syncprojects.server')
wz_logger = logging.getLogger('werkzeug')
if not DEBUG:
    wz_logger.disabled = True
    app.logger.disabled = True
    cli.show_server_banner = lambda *_: None

RESP_BAD_DATA = {'result': 'error'}, 400


def queue_put(name, data: Dict = {}) -> str:
    task_id = gen_task_id()
    app.config['main_queue'].put({'msg_type': name, 'task_id': task_id, 'data': data})
    return task_id


def queue_get() -> Dict:
    try:
        return app.config['server_queue'].get_nowait()
    except Empty:
        return {}


def gen_task_id() -> str:
    return str(uuid4())


def response_started(task_id: str) -> Dict:
    return {'result': 'started', 'task_id': task_id}


@app.route('/api/auth', methods=['GET', 'POST'])
@verify_data
def auth(data):
    task = queue_put('auth', data)
    if request.method == "POST":
        return response_started(task)
    else:
        return 'Login success. You may now close this tab.'


@app.route('/api/sync', methods=['POST'])
@verify_data
def sync(data):
    if 'projects' in data:
        task = queue_put('sync', {'projects': data['projects']})
    elif 'songs' in data:
        task = queue_put('sync', {'songs': data['songs']})
    else:
        return RESP_BAD_DATA
    return response_started(task)


@app.route('/api/ping', methods=['GET'])
@verify_data
def ping(_):
    return {'result': 'pong', 'task_id': queue_put('ping')}


@app.route('/api/project_start', methods=['POST'])
@verify_data
def start_project(data):
    if 'project' in data:
        return response_started(queue_put('start_project', data))
    return RESP_BAD_DATA


@app.after_request
def add_cors_header(response):
    response.headers['Access-Control-Allow-Origin'] = SYNCPROJECTS_URL
    return response


if __name__ == "__main__":
    # Testing only
    app.run(debug=DEBUG)
