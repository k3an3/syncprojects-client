import logging

from flask import Flask, request, cli

from syncprojects.config import DEBUG, SYNCPROJECTS_URL
from syncprojects.server.utils import queue_put, queue_get, response_started, verify_data

app = Flask(__name__)
logger = logging.getLogger('syncprojects.server')
wz_logger = logging.getLogger('werkzeug')
if not DEBUG:
    wz_logger.disabled = True
    app.logger.disabled = True
    cli.show_server_banner = lambda *_: None

RESP_BAD_DATA = {'result': 'error'}, 400

authed = False


@app.route('/api/auth', methods=['GET', 'POST'])
@verify_data
def auth(data):
    task = queue_put('auth', data)
    global authed
    authed = True
    if request.method == "POST":
        return response_started(task)
    else:
        return 'Login success. You may now close this tab.'


@app.route('/api/results')
def results():
    return {'results': queue_get()}


@app.route('/api/update', methods=['POST'])
def update_client():
    # TODO: security
    return {'result': 'success', 'task_id': queue_put('update')}


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
def ping():
    global authed
    if not authed:
        for res in queue_get():
            if res == 'authed':
                authed = True
    return {'result': 'pong', 'task_id': queue_put('ping', dry_run=True), 'auth': authed}


@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    # TODO: security
    return {'result': 'started', 'task_id': queue_put('shutdown')}


@app.route('/api/settings', methods=['POST'])
def settings():
    # TODO: security
    return {'result': 'started', 'task_id': queue_put('settings')}


@app.route('/api/workon', methods=['POST'])
@verify_data
def work_on(data):
    if 'song' in data:
        return response_started(queue_put('workon', data))
    return RESP_BAD_DATA


@app.route('/api/workdone', methods=['POST'])
@verify_data
def work_done(data):
    if 'song' in data:
        return response_started(queue_put('workdone', data))
    return RESP_BAD_DATA


@app.route('/api/tasks', methods=['POST'])
@verify_data
def get_tasks(_):
    return response_started(queue_put('tasks'))


@app.after_request
def add_cors_header(response):
    response.headers['Access-Control-Allow-Origin'] = SYNCPROJECTS_URL.rstrip('/')
    response.headers['Access-Control-Allow-Headers'] = "Access-Control-Allow-Headers, Origin, Accept, " \
                                                       "X-Requested-With, Content-Type, " \
                                                       "Access-Control-Request-Method, Access-Control-Request-Headers "
    return response


if __name__ == "__main__":
    # Testing only
    app.run(debug=DEBUG)
