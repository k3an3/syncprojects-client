import os
import sys
import traceback
from os.path import join
from shutil import copy
from subprocess import check_output

from syncprojects.main import __version__ as version

BUILD_DIR = join('build', f'exe.win-amd64-{sys.version_info.major}.{sys.version_info.minor}')

try:
    print("Building version", version)
    os.makedirs('release', exist_ok=True)
    check_output(['python', 'setup.py', 'build_exe'])
    print("Copying production settings...")
    copy("local_config_prod.py", join(BUILD_DIR, 'local_config.py'))
    print("Compressing into archive...")
    check_output(['7z', 'a', f'../../release/syncprojects-v{version}-release.zip', '*'], cwd=BUILD_DIR)
except Exception:
    traceback.print_exc()
    input()