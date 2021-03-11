import os
import sys
import traceback
from subprocess import check_output

from syncprojects.main import __version__ as version

try:
    print("Building version", version)
    os.makedirs('release', exist_ok=True)
    check_output(['python', 'setup.py', 'build_exe'])
    check_output(['7z', 'a', f'../../release/syncprojects-v{version}-release.zip', '*'], cwd=f'build/exe.win-amd64-{sys.version_info.major}.{sys.version_info.minor}')
except Exception:
    traceback.print_exc()
    input()