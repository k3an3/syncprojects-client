use std::{fs, io, thread};
use std::cmp::max;
use std::collections::HashMap;
use std::io::Read;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::sync::mpsc::channel;
use std::time;

use md5::{Digest, Md5};
use md5::digest::Output;
use pyo3::prelude::*;

const BUFFER_SIZE: usize = 1024;
const NUM_THREADS: usize = 32;

pub type FileMap = HashMap<String, String>;


/// Compute digest value for given `Reader` and print it
/// On any error simply return without doing anything
fn hash_file<D: Digest + Default, R: Read>(reader: &mut R) -> Output<D> {
    let mut sh = D::default();
    let mut buffer = [0u8; BUFFER_SIZE];
    loop {
        let n = match reader.read(&mut buffer) {
            Ok(n) => n,
            Err(_) => 0,
        };
        sh.update(&buffer[..n]);
        if n == 0 || n < BUFFER_SIZE {
            break;
        }
    }
    sh.finalize()
}

fn _walk_dir(dir: &Path, mut files: &mut Vec<String>) -> io::Result<()> {
    if dir.is_dir() {
        for entry in fs::read_dir(dir)? {
            let path = entry.unwrap().path();
            if path.is_dir() {
                if _walk_dir(&path, &mut files).is_err() {
                    println!("Error walking directory {}", dir.to_string_lossy());
                }
            } else {
                files.push(path.to_string_lossy().to_string());
            }
        }
    }
    Ok(())
}

#[pyfunction]
pub fn get_difference(src: FileMap, dst: FileMap) -> Vec<String> {
    let mut results = Vec::with_capacity(max(src.len(), dst.len()));
    for (name, hash) in src.iter() {
        let remote_hash = dst.get(name);
        if (remote_hash.is_some() && remote_hash.unwrap() != hash) || remote_hash.is_none() {
            results.push(name.to_owned());
        }
    }
    results
}

#[pyfunction]
pub fn walk_dir(base_path: String) -> FileMap {
    let dir = Path::new(&base_path);
    let mut files = Vec::new();
    let files_len = files.len();
    _walk_dir(&dir, &mut files).unwrap();
    let data = Arc::new(Mutex::new(files));
    let (tx, rx) = channel();
    for _ in 0..NUM_THREADS {
        let (data, tx, base_path) = (data.clone(), tx.clone(), base_path.clone());
        thread::spawn(move || {
            loop {
                let path = {
                    let mut data = data.lock().unwrap();
                    data.pop()
                };
                match path {
                    Some(path) => {
                        if path.ends_with(".peak") {
                            continue;
                        }
                        if let Ok(mut file) = fs::File::open(&path) {
                            let hash = hash_file::<Md5, _>(&mut file);
                            let mut hash_str = String::with_capacity(32);
                            for b in hash {
                                hash_str.push_str(&format!("{:02x}", b));
                            }
                            let path_dst = path.strip_prefix(&base_path).unwrap();
                            let path_dst = path_dst.strip_prefix("/").unwrap_or_else(|| {
                                // Windows compat
                                path_dst.strip_prefix("\\").unwrap()
                            });
                            tx.send(Some((path_dst.to_string().replace("\\", "/"), hash_str))).unwrap();
                        }
                    },
                    None => {
                        tx.send(None).unwrap();
                        break;
                    }
                }
            }
        });
        let ten_millis = time::Duration::from_millis(10);
        thread::sleep(ten_millis); // hack to let stack populate
    }
    let mut map = FileMap::with_capacity(files_len);
    let mut done = 0;
    while done < NUM_THREADS {
        match rx.recv() {
            Ok(Some((k, v))) => {
                map.insert(k, v);
                ()
            },
            _ => done += 1
        }
    }
    map
}

#[pymodule]
fn syncprojects_fast(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk_dir, m)?)?;
    m.add_function(wrap_pyfunction!(get_difference, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use crate::{get_difference, walk_dir};

    #[test]
    fn test_diff() {
        let old = [("test1".to_string(), "asdf".to_string()), ("test2".to_string(), "asdfyz".to_string()), ("test3".to_string(), "alkwjelj".to_string())].iter().cloned().collect();
        let new = [("test1".to_string(), "asdf".to_string()), ("test2".to_string(), "faslkjlk4".to_string()), ("test3".to_string(), "alkwjelj".to_string()), ("test4".to_string(), "asldfasdf".to_string())].iter().cloned().collect();
        let res = get_difference(new, old);
        assert_eq!(2, res.len());
    }

    #[test]
    fn test_walk() {
        let map = walk_dir("/home/keane/Documents/Divided".to_string());
        for (k, v) in &map {
            println!("{}: {}", k, v);
        }
        assert_eq!(1368, map.len());
    }
}