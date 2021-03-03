import logging
from flask import Flask, request, cli, abort

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


def queue_put(data):
    app.config['queue'].put(data)


@app.route('/api/auth', methods=['GET', 'POST'])
@verify_data
def auth(data):
    queue_put({'msg_type': 'auth', 'data': data})
    if request.method == "POST":
        return SUCCESS
    else:
        return 'Login success. You may now close this tab.'


@app.route('/api/sync', methods=['POST'])
@verify_data
def sync(data):
    if 'projects' in data:
        queue_put({'msg_type': 'sync', 'data': {'projects': data['projects']}})
    elif 'songs' in data:
        queue_put({'msg_type': 'sync', 'data': {'songs': data['songs']}})
    else:
        return BAD_DATA
    return SUCCESS


@app.route('/api/ping', methods=['GET'])
@verify_data
def ping(_):
    return {'result': 'pong'}


@app.after_request
def add_cors_header(response):
    if not DEBUG:
        response.headers['Access-Control-Allow-Origin'] = SYNCPROJECTS_URL
    return response


if __name__ == "__main__":
    # Testing only
    app.run(debug=DEBUG)
