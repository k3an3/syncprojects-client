try:
    from cx_Freeze import setup, Executable
except ImportError:
    print("Not using cx_Freeze.")
    from setuptools import setup


def gen_executables():
    try:
        return [Executable("main.py")]
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
    install_requires=[
        'requests',
        'psutil',
        'pywin32',
        'progress',
        'flask',
        'pyjwt[crypto]',
        'cx_Freeze',
        'sqlitedict',
        'timeago',
    ],
    executables=gen_executables()
)
