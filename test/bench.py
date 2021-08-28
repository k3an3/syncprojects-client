import time

# noinspection PyUnresolvedReferences
from syncprojects.system import is_windows, is_linux
from syncprojects_fast import walk_dir as fast_walk_dir
from syncprojects.sync.backends.aws.s3 import walk_dir

COUNT = 10

if is_windows():
    TARGET_DIR = "C:\\Users\\Admin\\Documents\\studio-dev\\S3 Test\\Debug"
elif is_linux():
    TARGET_DIR = "/etc"


def do_bench(func, *args, **kwargs):
    start = time.perf_counter()
    for _ in range(COUNT):
        func(*args, **kwargs)
    return (time.perf_counter() - start) / COUNT


print("Doing Python")
t = do_bench(walk_dir, TARGET_DIR)
print("Did Python in", t)

print("Doing Rust")
t = do_bench(fast_walk_dir, TARGET_DIR)
print("Did Rust in", t)
