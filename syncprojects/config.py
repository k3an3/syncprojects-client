import re
from hashlib import md5
from os.path import expanduser
from shutil import which

# WARNING: hardcoded configuration is deprecated and will be removed soon!
######################
# User Configuration #
######################
# The directory where you store your Cubase project files.
SOURCE = ""
# The path to the network drive containing shared projects.
# Where the config file will be stored. On each line of this file
# should be a directory name that you wish to sync from the "source" directory.
# Where the hashes should be stored. Do not modify this file!
LOCAL_HASH_STORE = expanduser("~/Documents/studio_hashes.txt")
REMOTE_HASH_STORE = "hashes"
SMB_DRIVE = "X:"
SMB_SERVER = "mydomain.example.com"
SMB_SHARE = "studio_all"

FIREWALL_API_URL = 'https://mydomain.example.com/api/'
FIREWALL_API_KEY = ''
FIREWALL_NAME = "My Firewall"

##########################
# Advanced Configuration #
##########################
TELEMETRY = ""
# Number of threads
DEFAULT_HASH_ALGO = md5
# Use hashing over SMB instead of quicker, manifest hashfile
LEGACY_MODE = False
NEURAL_DSP_PATH = "C:\\ProgramData\\Neural DSP"
AMP_PRESET_DIR = "X:\\SomeDir\\Amp Settings"

# These will stay, though
#############
# CONSTANTS #
#############
CHANGELOG_HEADER_WIDTH = 50
MAX_WORKERS = 25
TEXT_EDITOR = which("notepad") or which("gedit")
PROJECT_GLOB = "*.cpr"
BINARY_CLEAN_GLOB = "syncprojects*.exe"
DAW_PROCESS_REGEX = re.compile(r'cubase', re.IGNORECASE)
DAW_EXE_SEARCH_PATH = "C:\\Program Files\\Steinberg"
UPDATE_INTERVAL = 3600 * 12

# Development key
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsgFcJbSX6zfOhx/MImB2
RY3vN1bXKN2dqz15B8os4yO9AdQIKPcNagWXeA/gbY+3YXuS6bexBcZe+B4jltoS
GHHyfRdmyAR3fDRvyBiehYkHK5u/NEw6OWflE70LCfT6UJodmiPbFHG9zhgOkb7U
bUzQg4Zoqg1tKD4ZkHzQCTMcJt1Ca4ai1LwajS0hUljr68GO7W3c51ADC0CD/K4p
itIt0NfNqf7bwU439aaXh36Mv076ydrnb46SH+0Wg/FrnlxpXVtUgPB0B7CGYrIH
O14n0DFluLdcCjIvpgDZMYu4ZIofiSx7FvPwB61KaQMZKgzeD/mPC1AaX7oQfiYj
YQIDAQAB
-----END PUBLIC KEY-----
"""

SIGNING_PUBLIC_KEY = ""

DEBUG = False
ENV = "DEV"
LOGIN_MODE = "web"  # prompt, web
SYNCPROJECTS_URL = "https://syncprojects.example.com/"

# Temporary
ACCESS_ID = ""
SECRET_KEY = ""

BUCKET_NAME = 'some-bucket'
AUDIO_BUCKET_NAME = 'some-bucket-audio'

SENTRY_URL = ''

try:
    from local_config import *
except ImportError:
    pass