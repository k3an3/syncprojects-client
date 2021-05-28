import logging
from abc import abstractmethod
from datetime import datetime
from os import makedirs
from os.path import join, dirname, basename, getsize
from threading import Thread

from time import sleep
from watchdog.events import FileSystemEventHandler, FileSystemEvent, FileSystemMovedEvent
from watchdog.observers import Observer

from syncprojects.api import SyncAPI
from syncprojects.sync.backends.aws.auth import AWSAuth

logger = logging.getLogger('syncprojects.watcher')
WAIT_SECONDS = 10


def wait_for_write(path: str) -> None:
    size = -1
    try:
        while size != (new_size := getsize(path)):
            size = new_size
            sleep(1)
    except OSError:
        logger.error("Couldn't stat file %s", path)


class AudioSyncHandler(FileSystemEventHandler):
    def __init__(self):
        self.sync_dir = None
        self.last_upload = {}

    def should_push(self, path: str) -> bool:
        return (datetime.now() - self.last_upload.get(path, datetime.min)).total_seconds() > WAIT_SECONDS

    def on_any_event(self, event: FileSystemEvent):
        if not self.sync_dir:
            raise Exception("sync_dir not set")
        if not event.is_directory:
            logger.debug("File %s %s.", event.src_path, event.event_type)

    def on_moved(self, event: FileSystemMovedEvent):
        if not event.is_directory and self.should_push(event.dest_path):
            wait_for_write(event.dest_path)
            self.move_file(event.src_path, event.dest_path)
            self.last_upload[event.dest_path] = datetime.now()
            self.last_upload.pop(event.src_path, None)

    def on_deleted(self, event: FileSystemEvent):
        pass

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and self.should_push(event.src_path):
            wait_for_write(event.src_path)
            self.push_file(event.src_path)
            self.last_upload[event.src_path] = datetime.now()

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and self.should_push(event.src_path):
            wait_for_write(event.src_path)
            self.push_file(event.src_path)
            self.last_upload[event.src_path] = datetime.now()

    def on_closed(self, event):
        pass

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
    def move_file(self, src: str, dest: str):
        pass


class S3AudioSyncHandler(AudioSyncHandler):
    def __init__(self, auth: AWSAuth, bucket: str):
        self.auth = auth
        self.bucket = bucket
        self.client = self.auth.authenticate()
        super().__init__()

    def push_file(self, path: str):
        target = "{}/{}".format(basename(dirname(path)), basename(path))
        logger.debug("Uploading %s to %s", path, target)
        attempts = 0
        while attempts < 6:
            try:
                self.client.upload_file(path,
                                        self.bucket,
                                        target)
                break
            except PermissionError:
                sleep(1)
                attempts += 1
        else:
            logger.error("Failed to read file!!!")

        logger.debug("Done.")

    def pull_file(self, path: str):
        # Not sure if this will get used initially
        self.client.download_file(Bucket=self.bucket,
                                  Path=path,
                                  Filename=join(self.sync_dir, path))

    def delete_file(self, path: str):
        self.client.delete_object(Bucket=self.bucket,
                                  Key=path)

    def move_file(self, src: str, dest: str):
        copy_source = {
            'Bucket': self.bucket,
            'Key': src
        }
        self.client.copy(Bucket=self.bucket,
                         CopySource=copy_source,
                         Key=dest)
        self.delete_file(src)


class Watcher(Thread):
    def __init__(self, sync_dir: str, api_client: SyncAPI, handler: AudioSyncHandler):
        super().__init__(daemon=True)
        self.api_client = api_client
        self.observer = Observer()
        self.sync_dir = sync_dir
        handler.sync_dir = sync_dir
        self.observer.schedule(handler, self.sync_dir, recursive=True)

    def create_sync_dirs(self):
        logger.debug("Creating sync dirs")
        projects = self.api_client.get_all_projects()
        for project in projects:
            try:
                makedirs(join(self.sync_dir, project['name']), exist_ok=True)
            except OSError as e:
                logger.error("Cannot create directory: %s", e)

    def run(self):
        logger.info("Starting watcher in %s", self.sync_dir)
        self.create_sync_dirs()
        self.observer.start()
        try:
            while self.observer.is_alive():
                self.observer.join(1)
        except Exception as e:
            logger.error("Observer died with error: %s", e)
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(e)
            except ImportError:
                pass
        finally:
            self.observer.stop()
            self.observer.join()
            logger.warning("Observer shut down")
