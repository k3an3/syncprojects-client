import logging

from flask import Flask, request

from syncprojects.config import DEBUG, SYNCPROJECTS_URL
from syncprojects.utils import get_verified_data, appdata

app = Flask(__name__)
logger = logging.getLogger('syncprojects.server')


@app.route('/api/auth', methods=['GET', 'POST'])
@get_verified_data
def auth(data):
    appdata.update(data)
    if request.method == "POST":
        return '', 204
    else:
        return 'Login success. You may now close this tab.'


@app.after_request
def add_cors_header(response):
    if not DEBUG:
        response.headers['Access-Control-Allow-Origin'] = SYNCPROJECTS_URL
    return response


if __name__ == "__main__":
    # Testing only
    app.run(debug=DEBUG)
