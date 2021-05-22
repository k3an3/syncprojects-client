import logging
from abc import abstractmethod
from os.path import join
from threading import Thread

from watchdog.events import FileSystemEventHandler, FileSystemEvent, FileSystemMovedEvent
from watchdog.observers import Observer

from syncprojects.storage import appdata
from syncprojects.sync.backends.aws.auth import AWSAuth

logger = logging.getLogger('syncprojects.watcher')


class Handler(FileSystemEventHandler):
    def on_any_event(self, event: FileSystemEvent):
        if not event.is_directory:
            logger.debug("File %s %s.", event.src_path, event.event_type)

    def on_moved(self, event: FileSystemMovedEvent):
        if not event.is_directory:
            self.copy_file(event.src_path, event.dest_path)
            self.delete_file(event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            self.delete_file(event.src_path)

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            self.push_file(event.src_path)

    def on_closed(self, event: FileSystemEvent):
        if not event.is_directory:
            self.push_file(event.src_path)

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            self.push_file(event.src_path)

    @abstractmethod
    def push_file(self, path: str):
        pass

    @abstractmethod
    def pull_file(self, path: str):
        pass

    @abstractmethod
    def delete_file(self, path: str):
        pass

    @abstractmethod
    def copy_file(self, src: str, dest: str):
        pass


class S3SyncHandler(Handler):
    def __init__(self, auth: AWSAuth, bucket: str):
        self.auth = auth
        self.bucket = bucket
        self.client = self.auth.authenticate()

    def push_file(self, path: str):
        self.client.upload_file(join(appdata['audio_sync_dir'], path),
                                self.bucket,
                                path)

    def pull_file(self, path: str):
        self.client.download_file(self.bucket,
                                  path,
                                  join(appdata['audio_sync_dir'], path))

    def delete_file(self, path: str):
        self.client.delete_object(self.bucket,
                                  path)

    def copy_file(self, src: str, dest: str):
        self.client.copy_object(Bucket=self.bucket,
                                CopySource=src,
                                Key=dest)


class Watcher(Thread):
    def __init__(self, *args, **kwargs):
        super().__init__(daemon=True)
        self.observer = Observer()
        self.observer.schedule(S3SyncHandler(*args, **kwargs), appdata['audio_sync_dir'])

    def run(self):
        self.observer.start()
