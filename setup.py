import sys

try:
    from cx_Freeze import setup, Executable
except ImportError:
    print("Not using cx_Freeze.")
    from setuptools import setup

base = None
if sys.platform == "win32":
    base = "Win32GUI"  # Tells the build script to hide the console.

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
    'cx_Freeze==6.5.3',
    'sqlitedict==1.7.0',
    'timeago==1.0.15',
]

if sys.platform == "win32":
    requirements.append('pywin32==228')


def gen_executables():
    try:
        return [Executable("syncprojects/syncprojects_app.py", icon="benny.ico", base=base)]
    except NameError:
        return []


setup(
    name='syncprojects',
    version='2.1',
    packages=['syncprojects'],
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
            'packages': ['jinja2', 'win32file', 'sentry_sdk', 'html', 'boto3', 'pystray'],
            'include_files': ['benny.ico'],
        }
    },
    install_requires=requirements,
    executables=gen_executables(),
)
