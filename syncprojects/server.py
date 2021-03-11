import logging

from flask import Flask, request, cli

from syncprojects.config import DEBUG, SYNCPROJECTS_URL
from syncprojects.utils import get_verified_data

app = Flask(__name__)
logger = logging.getLogger('syncprojects.server')
wz_logger = logging.getLogger('werkzeug')
if not DEBUG:
    wz_logger.disabled = True
    app.logger.disabled = True
    cli.show_server_banner = lambda *_: None


@app.route('/api/auth', methods=['GET', 'POST'])
@get_verified_data
def auth(data):
    app.config['queue'].put(data)
    if request.method == "POST":
        return '', 204
    else:
        return 'Login success. You may now close this tab.'


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
