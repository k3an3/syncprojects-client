import logging
from typing import Dict

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

SUCCESS = {'result': 'success'}
BAD_DATA = {'result': 'error'}, 400


def queue_put(name, data: Dict = {}):
    app.config['queue'].put({'msg_type': name, 'data': data})


@app.route('/api/auth', methods=['GET', 'POST'])
@verify_data
def auth(data):
    queue_put('auth', data)
    if request.method == "POST":
        return SUCCESS
    else:
        return 'Login success. You may now close this tab.'


@app.route('/api/sync', methods=['POST'])
@verify_data
def sync(data):
    if 'projects' in data:
        queue_put('sync', {'projects': data['projects']})
    elif 'songs' in data:
        queue_put('sync', {'songs': data['songs']})
    else:
        return BAD_DATA
    return SUCCESS


@app.route('/api/ping', methods=['GET'])
@verify_data
def ping(_):
    queue_put('ping')
    return {'result': 'pong'}


@app.route('/api/project_start', methods=['POST'])
@verify_data
def start_project(data):
    if 'project' in data:
        queue_put('start_project', data)
        return SUCCESS
    return BAD_DATA


@app.after_request
def add_cors_header(response):
    response.headers['Access-Control-Allow-Origin'] = SYNCPROJECTS_URL
    return response


if __name__ == "__main__":
    # Testing only
    app.run(debug=DEBUG)
