import sys

try:
    from cx_Freeze import setup, Executable
except ImportError:
    print("Not using cx_Freeze.")
    from setuptools import setup

base = None
if sys.platform == "win32":
    base = "Win32GUI"  # Tells the build script to hide the console.


def gen_executables():
    try:
        return [Executable("syncprojects/main.py", icon="benny.ico", base=base)]
    except NameError:
        return []


setup(
    name='syncprojects',
    version='2.0',
    packages=['syncprojects'],
    url='https://syncprojects.example.com',
    license='',
    author="Keane O'Kelley",
    author_email='dev@keane.space',
    description='',
    entry_points={
        'console_scripts': [
            'syncprojects=syncprojects.main:main'
        ]
    },
    options={
        'build_exe': {
            # Slim down build
            'excludes': ['tkinter', 'unittest', 'test', 'curses', 'asyncio', 'colorama', 'setuptools'],
            # Won't run correctly without
            'packages': ['jinja2'],
        }
    },
    install_requires=[
        'requests==2.24.0',
        'psutil==5.7.2',
        'pywin32==228',
        'progress==1.5',
        'flask==1.1.2',
        'pyjwt[crypto]==2.0.1',
        'cx_Freeze==6.5.3',
        'sqlitedict==1.7.0',
        'timeago==1.0.15',
    ],
    executables=gen_executables()
)
