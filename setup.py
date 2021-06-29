import platform

from setuptools import find_packages

from syncprojects.syncprojects_app import __version__ as version

try:
    from cx_Freeze import setup, Executable

    print("Using cx_Freeze")
except ImportError:
    print("Not using cx_Freeze.")
    from setuptools import setup

packages = {'jinja2', 'sentry_sdk', 'html', 'boto3', 'pystray'}
base = None

APP = ['syncprojects/syncprojects_app.py']
DATA_FILES = []
ICON = 'res/benny.ico'

requirements = [
    'boto3==1.17.44',
    'requests==2.24.0',
    'psutil==5.7.2',
    'packaging==20.9',
    'progress==1.5',
    'flask==1.1.2',
    'Pillow==8.2.0',
    'pyjwt[crypto]==2.0.1',
    'pylint',
    'pyshortcuts==1.8.0',
    'pystray==0.17.3',
    'sqlitedict==1.7.0',
    'timeago==1.0.15',
    'watchdog==2.1.2',
]

SETUP_REQ = []
system = platform.system()

if system == "Windows":
    requirements.extend(('pywin32==228', 'cx_Freeze==6.5.3'))
    base = "Win32GUI"  # Tells the build script to hide the console.
    packages.add('win32file')


def gen_executables():
    try:
        return [Executable("syncprojects/syncprojects_app.py", icon=ICON, base=base)]
    except NameError:
        return []


setup(
    name='syncprojects',
    version=version,
    packages=find_packages(),
    url='https://syncprojects.example.com',
    license='',
    author="Keane O'Kelley",
    author_email='dev@keane.space',
    description='',
    entry_points={
        'console_scripts': [
            'syncprojects=syncprojects.syncprojects_app:main'
        ]
    },
    options={
        'build_exe': {
            # Slim down build
            'excludes': ['unittest', 'test', 'curses', 'asyncio', 'colorama', 'setuptools'],
            # Won't run correctly without
            'packages': packages,
            'include_files': [ICON],
        },
    },
    install_requires=requirements,
    executables=gen_executables(),
    app=APP,
    data_files=DATA_FILES,
    setup_requires=SETUP_REQ,
)
