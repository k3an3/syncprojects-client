import os
import platform
import traceback
from os.path import join
from shutil import copy
from subprocess import check_output, CalledProcessError

import sys

from syncprojects.syncprojects_app import __version__ as version

BUILD_DIR = join('build', f'exe.win-amd64-{sys.version_info.major}.{sys.version_info.minor}')
SUPPORTED_OS = {
    'Windows': 'build_exe',
    'Linux': 'build',
    'Darwin': 'bulid_mac',
}

if not platform.system() in SUPPORTED_OS:
    print("Platform not supported!")

try:
    formatted_version = '-'.join((version, platform.machine(), platform.system())).lower()
    print("Building version", version)
    os.makedirs('release', exist_ok=True)
    build_cmd = {}
    check_output(['python', 'setup.py', SUPPORTED_OS[platform.system()]])
    print("Copying production settings...")
    copy("local_config_prod.py", join(BUILD_DIR, 'local_config.py'))
    print("Compressing into archive...")
    try:
        check_output(['7z', 'a', f'../../release/syncprojects-v{formatted_version}-release.zip', '*'], cwd=BUILD_DIR)
    except CalledProcessError:
        check_output(['zip', '-r', f'../../release/syncprojects-v{formatted_version}-release.zip', '*'], cwd=BUILD_DIR)
except Exception:
    traceback.print_exc()
    input()
