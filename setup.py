try:
    from cx_Freeze import setup, Executable
except ImportError:
    print("Not using cx_Freeze.")
    from setuptools import setup


def gen_executables():
    try:
        return [Executable("syncprojects/main.py", icon="benny.ico")]
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
            'packages': ['jinja2', 'win32file'],
            'include_files': ['benny.ico'],
        }
    },
    install_requires=[
        'requests==2.24.0',
        'psutil==5.7.2',
        'pywin32==228',
        'packaging==20.9',
        'progress==1.5',
        'flask==1.1.2',
        'pyjwt[crypto]==2.0.1',
        'pyshortcuts==1.8.0',
        'cx_Freeze==6.5.3',
        'sqlitedict==1.7.0',
        'timeago==1.0.15',
    ],
    executables=gen_executables()
)
