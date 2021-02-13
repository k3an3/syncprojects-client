from cx_Freeze import setup, Executable

setup(
    name='syncprojects',
    version='2.0',
    packages=['syncprojects'],
    url='https://syncprojects.app',
    license='',
    author="Keane O'Kelley",
    author_email='dev@keane.space',
    description='',
    install_requires=[
        'requests',
        'psutil',
        'pywin32',
    ],
    executables=[Executable("main.py")]
)
