#!/usr/bin/env python3
import glob
import os
import platform
import shlex
import shutil
import traceback
from argparse import ArgumentParser
from os.path import join
from subprocess import check_output, CalledProcessError, run

import requests
import sys

from syncprojects.syncprojects_app import __version__ as version

URL = 'https://syncprojects.example.com/api/v1/updates/'
PLATFORM_BUILD_COMMAND = {
    'Windows': 'python setup.py build_exe',
    'Linux': 'python setup.py build',
    'Darwin': 'pyinstaller -y --osx-bundle-identifier com.syncprojects.app syncprojects.spec',
}

RUST_PLATFORMS = {"Windows"}

system = platform.system()
ICON = 'res/benny.ico'

BUILD_DIR = {
    'Windows': join('build', f'exe.win-amd64-{sys.version_info.major}.{sys.version_info.minor}'),
    'Darwin': 'dist',
    'Linux': join('build', 'lib'),
}[system]

PROD_CONFIG_DIR = {
    'Windows': BUILD_DIR,
    'Darwin': join(BUILD_DIR, 'syncprojects.app', 'Contents', 'MacOS'),
    'Linux': BUILD_DIR,
}[system]

if system not in PLATFORM_BUILD_COMMAND:
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
parser.add_argument('-t', '--tag', action='store_true')
parser.add_argument('-o', '--no-notarize', action='store_true')
parser.add_argument('-b', '--no-build', action='store_true')
parser.add_argument('--url', default=URL)
args = parser.parse_args()

try:
    if args.tag:
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
            # Do rust extension build, if applicable
            if system in RUST_PLATFORMS:
                # TODO: is windows only
                check_output('cargo build --release')
                try:
                    os.unlink('syncprojects_fast/syncprojects_fast.pyd')
                except FileNotFoundError:
                    pass
                shutil.copy('target/release/syncprojects_fast.dll', join('syncprojects_fast', 'syncprojects_fast.pyd'))
            # Do application build
            check_output(shlex.split(PLATFORM_BUILD_COMMAND[system]))
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
            zip_source = '*'
            dir_offset = '../../'
            try:
                check_output(['7z', 'a', f'{dir_offset}{release}', zip_source],
                             cwd=BUILD_DIR)
            except (CalledProcessError, FileNotFoundError):
                check_output(['zip', '-r', f'{dir_offset}{release}', zip_source],
                             cwd=BUILD_DIR)
        elif system == 'Darwin':
            zip_source = 'syncprojects.app'
            dir_offset = '../'
            print("Codesign")
            run(shlex.split('codesign --remove-signature dist/syncprojects.app/Contents/MacOS/Python3'))
            run(shlex.split(
                "codesign -s \"Developer ID Application: Keane O'Kelley\" -v --deep --timestamp --entitlements entitlements.plist -o runtime dist/syncprojects.app"))
            # run(['codesign', '--deep', '-s', "test@example.com", 'dist/syncprojects.app'])
            if not args.no_notarize:
                check_output(['./package.sh'])
        if system in ("Windows", "Linux"):
            shutil.copy(release, join('build', 'release.zip'))
            print("Running packager")
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
    if system in "Windows":
        release = f'release/syncprojects-{formatted_version}-installer.exe'
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
