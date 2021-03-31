from syncprojects.server.app import app


def start_server(main_queue, server_queue, **kwargs):
    app.config['main_queue'] = main_queue
    app.config['server_queue'] = server_queue
    app.run(**kwargs)
