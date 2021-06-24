#!/usr/bin/env python3
import glob
import os
import platform
import shutil
import traceback
from os.path import join
from subprocess import check_output, CalledProcessError

import requests
import sys

from syncprojects.syncprojects_app import __version__ as version

URL = 'https://syncprojects.example.com/api/v1/updates/'
SUPPORTED_OS = {
    'Windows': 'build_exe',
    'Linux': 'build',
    'Darwin': 'bdist_mac',
}

BUILD_DIR = join('build', {
    'Windows': f'exe.win-amd64-{sys.version_info.major}.{sys.version_info.minor}',
    'Darwin': join(f'syncprojects-{version}.app', 'Contents', 'MacOS'),
    'Linux': 'lib'
}[platform.system()])

if not platform.system() in SUPPORTED_OS:
    print("Platform not supported!")

user, passwd = None, None
try:
    user, passwd = open(".updater-creds").read().split('\n')
    print("Will upload to API")
except FileNotFoundError:
    print("Creds not found")

try:
    formatted_version = '-'.join((version, platform.machine(), platform.system())).lower()
    print("Building version", formatted_version)
    os.makedirs('release', exist_ok=True)
    build_cmd = {}
    check_output(['python', 'setup.py', SUPPORTED_OS[platform.system()]])
    try:
        shutil.copy("local_config_prod.py", join(BUILD_DIR, 'local_config.py'))
        print("Copied production settings.")
    except FileNotFoundError:
        pass
    if platform.system() in ("Windows", "Linux"):
        print("Compressing into archive...")
        release = f'release/syncprojects-v{formatted_version}-release.zip'
        try:
            os.unlink(release)
        except FileNotFoundError:
            pass
        try:
            check_output(['7z', 'a', f'../../{release}', '*'],
                         cwd=BUILD_DIR)
        except CalledProcessError:
            check_output(['zip', '-r', f'../../{release}', '*'],
                         cwd=BUILD_DIR)
        shutil.copy(release, 'release.zip')
        check_output(['pyinstaller', '-F', '--specpath', 'update', '--add-data',
                      os.pathsep.join((f'../release.zip', '.')), '--icon', '../benny.ico',
                      join('update/update.py'), '--name', f'syncprojects-{formatted_version}-installer',
                      '--noconsole'])
        os.unlink('release.zip')
        for f in glob.glob('dist/syncprojects-*-installer*'):
            try:
                shutil.move(f, 'release')
            except shutil.Error:
                pass
        shutil.rmtree('dist')
        if user and passwd:
            try:
                requests.post(URL, files=(
                    ('package', open(release, 'rb')),
                    ('target', formatted_version),
                    ('version', version),
                ), auth=(user, passwd))
            except (requests.ConnectionError, requests.exceptions.HTTPError) as e:
                print(e)
                input("[enter]")
    else:
        print("Copying...")
        shutil.copytree(join('build', f'syncprojects-{version}.app'), 'release')

except Exception:
    traceback.print_exc()
    input()
