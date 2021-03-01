import subprocess
import os
import sys

os.environ['PYTHONPATH'] = '.'
subprocess.run(['python', 'syncprojects/main.py', *sys.argv[1:]])