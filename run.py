#!/usr/bin/env python3
import os
import subprocess
import sys

os.environ['PYTHONPATH'] = '.'
subprocess.run(['python', 'syncprojects/syncprojects_app.py', *sys.argv[1:]])
