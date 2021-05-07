import subprocess
import os
import sys

os.environ['PYTHONPATH'] = '.'
subprocess.run(['python', 'syncprojects/syncprojects_app.py', *sys.argv[1:]])