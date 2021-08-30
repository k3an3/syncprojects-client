import time

from syncprojects.sync.backends.aws.s3 import walk_dir
from syncprojects.system import is_windows, is_linux
# noinspection PyUnresolvedReferences
from syncprojects_fast import walk_dir as fast_walk_dir

COUNT = 10

if is_windows():
    TARGET_DIR = "C:\\Users\\Admin\\Documents\\studio-dev\\S3 Test\\Debug"
elif is_linux():
    TARGET_DIR = "/home/keane/Documents/Divided"


def do_bench(func, *args, **kwargs):
    start = time.perf_counter()
    for _ in range(COUNT):
        func(*args, **kwargs)
    return (time.perf_counter() - start) / COUNT


print("Doing Python")
t = do_bench(walk_dir, TARGET_DIR)
print("Did Python in", t)
py_result = walk_dir(TARGET_DIR)

print("Doing Rust")
t = do_bench(fast_walk_dir, TARGET_DIR)
print("Did Rust in", t)
rust_result = fast_walk_dir(TARGET_DIR)

assert (py_result == rust_result)
