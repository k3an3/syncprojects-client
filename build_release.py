#!/usr/bin/env python3
import glob
import traceback
from os.path import join

import os
import platform
import requests
import shutil
import sys
from argparse import ArgumentParser
from subprocess import check_output, CalledProcessError, run

from syncprojects.syncprojects_app import __version__ as version

URL = 'https://syncprojects.example.com/api/v1/updates/'
SUPPORTED_OS = {
    'Windows': 'build_exe',
    'Linux': 'build',
    'Darwin': 'py2app',
}

system = platform.system()
ICON = 'res/benny.ico'

BUILD_DIR = {
    'Windows': join('build', f'exe.win-amd64-{sys.version_info.major}.{sys.version_info.minor}'),
    'Darwin': 'dist',
    'Linux': join('build', 'lib'),
}[system]

PROD_CONFIG_DIR = {
    'Windows': BUILD_DIR,
    'Darwin': join(BUILD_DIR, 'syncprojects.app', 'Contents', 'Resources'),
    'Linux': BUILD_DIR,
}[system]

if system not in SUPPORTED_OS:
    print("Platform not supported!")

user, passwd = None, None
try:
    user, passwd = open(".updater-creds").read().split('\n')[:2]
    print("Will upload to API")
except FileNotFoundError:
    print("Creds not found")

parser = ArgumentParser()
parser.add_argument('-u', '--upload-only', action='store_true')
parser.add_argument('-n', '--no-upload', action='store_true')
parser.add_argument('-g', '--no-tag', action='store_true')
parser.add_argument('-b', '--no-build', action='store_true')
parser.add_argument('--url', default=URL)
args = parser.parse_args()

try:
    if not args.no_tag:
        print("Tagging release")
        run(['git', 'tag', '-f', version])
    target = '-'.join((platform.machine(), system)).lower()
    formatted_version = '-'.join((version, target))
    release = f'release/syncprojects-v{formatted_version}-release.zip'
    if not args.upload_only:
        if not args.no_build:
            print("Building version", formatted_version)
            os.makedirs('release', exist_ok=True)
            build_cmd = {}
            # Do application build
            check_output(['python', 'setup.py', SUPPORTED_OS[system]])
        try:
            shutil.copy("local_config_prod.py", join(PROD_CONFIG_DIR, 'local_config.py'))
            print("Copied production settings.")
        except FileNotFoundError as e:
            print("WARNING: No production settings found, or error copying.", e)
        print("Compressing into archive...")
        try:
            os.unlink(release)
        except FileNotFoundError:
            pass
        if system in ("Windows", "Linux"):
            target = '*'
            dir = '../../'
        elif system == 'Darwin':
            target = 'syncprojects.app'
            dir = '../'
        try:
            check_output(['7z', 'a', f'{dir}{release}', target],
                         cwd=BUILD_DIR)
        except (CalledProcessError, FileNotFoundError):
            check_output(['zip', '-r', f'{dir}{release}', target],
                         cwd=BUILD_DIR)
        shutil.copy(release, join('build', 'release.zip'))
        if system in ("Windows", "Linux"):
            check_output(['pyinstaller', '-F', '--specpath', 'update', '--add-data',
                          os.pathsep.join((f'../build/release.zip', '.')), '--icon', join('..', ICON),
                          join('update/update.py'), '--name', f'syncprojects-{formatted_version}-installer',
                          '--noconsole'])
            os.unlink(join('build', 'release.zip'))
            for f in glob.glob('dist/syncprojects-*-installer*'):
                try:
                    shutil.move(f, 'release')
                except shutil.Error:
                    pass
            shutil.rmtree('dist')
    if not args.no_upload and user and passwd:
        print("Uploading package...")
        try:
            files = {
                'package': open(release, 'rb'),
            }
            data = {
                'target': target,
                'version': version,
            }
            print(files, data)
            r = requests.post(args.url, files=files, data=data,
                              auth=(user, passwd))
            print(r.text)
            r.raise_for_status()
        except (requests.ConnectionError, requests.exceptions.HTTPError) as e:
            print(e)
            input("[enter]")
        else:
            print("Success.")

except Exception:
    traceback.print_exc()
    input()
