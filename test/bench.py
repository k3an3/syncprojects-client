from typing import Dict, List

import time

from syncprojects.sync.backends.aws.s3 import walk_dir
from syncprojects.system import is_windows, is_linux
# noinspection PyUnresolvedReferences
from syncprojects_fast import get_difference as fast_get_difference
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


def get_difference(src: Dict, dst: Dict) -> List:
    results = []
    for key, val in src.items():
        if key not in dst or val != dst[key]:
            if not key.endswith('.peak'):
                results.append(key.replace('\\', '/'))
    return results


print("Python bench of walk_dir")
py_time = do_bench(walk_dir, TARGET_DIR)
print("Did Python in", py_time)
py_result = walk_dir(TARGET_DIR)

print("Rust bench of walk_dir")
rust_time = do_bench(fast_walk_dir, TARGET_DIR)
print("Did Rust in", rust_time)
rust_result = fast_walk_dir(TARGET_DIR)
print("{:.2f}% improvement".format(100 - 100 * rust_time / py_time))

assert (py_result == rust_result)

print("Python bench of get_difference")
py_time = do_bench(get_difference, py_result, rust_result)
print("Python diff in", py_time)

print("Rust bench of get_difference")
rust_time = do_bench(fast_get_difference, py_result, rust_result)
print("Rust diff in", rust_time)
print("{:.2f}% improvement".format(100 - 100 * rust_time / py_time))

print("Diffing results with Rust")
r = fast_get_difference(py_result, rust_result)

assert (not r)
