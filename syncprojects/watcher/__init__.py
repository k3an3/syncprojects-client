import logging
from abc import abstractmethod
from datetime import datetime
from os.path import join, dirname, basename, getsize
from threading import Thread

from time import sleep
from watchdog.events import FileSystemEventHandler, FileSystemEvent, FileSystemMovedEvent
from watchdog.observers import Observer

from syncprojects.api import SyncAPI
from syncprojects.storage import get_audiodata
from syncprojects.sync.backends.aws.auth import AWSAuth
from syncprojects.ui.tray import tray_icon
from syncprojects.utils import create_project_dirs, hash_file, report_error

logger = logging.getLogger('syncprojects.watcher')
WAIT_SECONDS = 10


def wait_for_write(path: str) -> None:
    logger.debug("Waiting for file size for %s to remain constant", path)
    size = -1
    try:
        while size != (new_size := getsize(path)):
            size = new_size
            sleep(1)
    except OSError:
        logger.error("Couldn't stat file %s", path)
    else:
        logger.debug("File stopped growing at %d bytes", new_size)


class AudioSyncHandler(FileSystemEventHandler):
    def __init__(self):
        self.sync_dir = None
        self.last_upload = {}
        self.store = get_audiodata()
        self.api_client = None

    def get_known_hash(self, path: str) -> str:
        return self.store.get(path)

    def file_changed(self, path: str) -> bool:
        return hash_file(path) != self.get_known_hash(path)

    def update_known_hash(self, path: str):
        self.store[path] = hash_file(path)

    def should_push(self, path: str) -> bool:
        result = False
        try:
            if getsize(path) > 0:
                if (datetime.now() - self.last_upload.get(path, datetime.min)).total_seconds() > WAIT_SECONDS:
                    if self.file_changed(path):
                        result = True
                    else:
                        logger.debug("File hasn't changed since last upload")
                else:
                    logger.debug("File %s last uploaded too recently", path)
            else:
                logger.debug("File size of %s is 0", path)
        except FileNotFoundError:
            logger.debug(f"{path=} doesn't exist")
        logger.debug(f"should_push {path=} {result=}")
        return result

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
            self.update_known_hash(event.dest_path)
            self.notify(event.dest_path)

    def on_deleted(self, event: FileSystemEvent):
        pass

    def _handle_push(self, event: FileSystemEvent):
        wait_for_write(event.src_path)
        self.push_file(event.src_path)
        self.last_upload[event.src_path] = datetime.now()
        self.update_known_hash(event.src_path)
        self.notify(event.src_path)

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and self.should_push(event.src_path):
            self._handle_push(event)

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and self.should_push(event.src_path):
            self._handle_push(event)

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

    def notify(self, path: str):
        if self.api_client:
            logger.debug("Notifying API of %s audio sync", path)
            project = basename(dirname(path))
            song = basename(path).split(".")[0]
            self.api_client.audio_sync(project, song)
        else:
            logger.debug("No API available, not notifying.")


def get_remote_path(path: str):
    return "/".join((basename(dirname(path)), basename(path)))


class S3AudioSyncHandler(AudioSyncHandler):
    def __init__(self, auth: AWSAuth, bucket: str):
        self.auth = auth
        self.bucket = bucket
        self.client = self.auth.authenticate()
        super().__init__()

    def push_file(self, path: str):
        tray_icon.notify(f"Uploading {basename(path)}")
        target = get_remote_path(path)
        logger.debug("Uploading %s to %s", path, target)
        attempts = 0
        try:
            while attempts < 6:
                try:
                    self.client.upload_file(path,
                                            self.bucket,
                                            target)
                    break
                except PermissionError:
                    # Linear backoff
                    sleep(attempts)
                    attempts += 1
            else:
                logger.error("Failed to read file!!!")
        except Exception as e:
            logger.error("Error! %s", e)
            report_error(e)

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
        src = get_remote_path(src)
        dest = get_remote_path(dest)
        tray_icon.notify(f"Moving {basename(src)} to {basename(dest)}")
        logger.debug("Moving %s to %s", src, dest)
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
        self.handler = handler
        # TODO: makes more sense somewhere else?
        self.handler.api_client = api_client
        self.start_watch()

    def start_watch(self):
        self.handler.sync_dir = self.sync_dir
        self.observer.schedule(self.handler, self.sync_dir, recursive=True)

    def stop_watch(self):
        self.observer.unschedule_all()

    def change_watch(self, new_watch_dir: str):
        logger.debug("Restarting watcher with new path %s...", new_watch_dir)
        self.stop_watch()
        self.sync_dir = new_watch_dir
        self.start_watch()

    def run(self):
        logger.info("Starting watcher in %s", self.sync_dir)
        create_project_dirs(self.api_client, self.sync_dir)
        self.observer.start()
        try:
            while self.observer.is_alive():
                self.observer.join(1)
        except FileNotFoundError as e:
            logger.debug("File not found: %s", e)
        except Exception as e:
            logger.error("Observer died with error: %s", e)
            report_error(e)
        finally:
            self.observer.stop()
            self.observer.join()
            logger.warning("Observer shut down")
