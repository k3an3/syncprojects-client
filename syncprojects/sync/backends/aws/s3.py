from bisect import bisect_left
from os.path import join
from pathlib import Path
from typing import Dict

from syncprojects.storage import appdata
from syncprojects.sync import SyncBackend
from syncprojects.sync.backends.aws.auth import AWSAuth

AWS_REGION = 'us-east-1'


class S3SyncBackend(SyncBackend):
    def __init__(self, auth: AWSAuth):
        super().__init__()
        self.auth = auth
        self.client = self.auth.authenticate()

    def sync(self, project: Dict) -> Dict:
        self.logger.info(f"Syncing project {project['name']}...")
        songs = project['songs']
        if not songs:
            self.logger.warning("No songs, skipping")
            return {'status': 'done', 'songs': None}
        self.logger.debug(f"Got songs list {songs}")
        project = project['name']

        paths = self.list_source_objects(source_folder=join(appdata['source'], s.get('directory_name') or s['name']))
        objects = self.list_bucket_objects(self.bucket)

        # Getting the keys and ordering to perform binary search
        # each time we want to check if any paths is already there.
        object_keys = [obj['Key'] for obj in objects]
        object_keys.sort()
        object_keys_length = len(object_keys)

        for path in paths:
            # Binary search.
            index = bisect_left(object_keys, path)
            if index == object_keys_length:
                # If path not found in object_keys, it has to be sync-ed.
                self._s3.upload_file(str(Path(source).joinpath(path)), Bucket=dest, Key=path)

    def push_amp_settings(self, amp: str, project: str):
        pass

    def pull_amp_settings(self, amp: str, project: str):
        pass

    def list_bucket_objects(self, bucket: str) -> [dict]:
        """
        List all objects for the given bucket.

        :param bucket: Bucket name.
        :return: A [dict] containing the elements in the bucket.

        Example of a single object.

        {
            'Key': 'example/example.txt',
            'LastModified': datetime.datetime(2019, 7, 4, 13, 50, 34, 893000, tzinfo=tzutc()),
            'ETag': '"b11564415be7f58435013b414a59ae5c"',
            'Size': 115280,
            'StorageClass': 'STANDARD',
            'Owner': {
                'DisplayName': 'webfile',
                'ID': '75aa57f09aa0c8caeab4f8c24e99d10f8e7faeebf76c078efc7c6caea54ba06a'
            }
        }

        """
        try:
            contents = self._s3.list_objects(Bucket=bucket)['Contents']
        except KeyError:
            # No Contents Key, empty bucket.
            return []
        else:
            return contents

    @staticmethod
    def list_source_objects(source_folder: str) -> [str]:
        """
        :param source_folder:  Root folder for resources you want to list.
        :return: A [str] containing relative names of the files.

        Example:

            /tmp
                - example
                    - file_1.txt
                    - some_folder
                        - file_2.txt

            >>> sync.list_source_objects("/tmp/example")
            ['file_1.txt', 'some_folder/file_2.txt']

        """

        path = Path(source_folder)

        paths = []

        for file_path in path.rglob("*"):
            if file_path.is_dir():
                continue
            str_file_path = str(file_path)
            str_file_path = str_file_path.replace(f'{str(path)}/', "")
            paths.append(str_file_path)

        return paths
