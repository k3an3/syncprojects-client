import os
import shutil

import sys

shutil.move(sys.argv[1], sys.argv[1] + ".exe")
os.execl(sys.argv[1], sys.argv[1])
