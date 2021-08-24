use md5::{Digest, Md5};
use md5::digest::Output;
use pyo3::prelude::*;
use std::{fs, io};
use std::cmp::max;
use std::collections::HashMap;
use std::io::Read;
use std::path::Path;

const BUFFER_SIZE: usize = 1024;

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

fn _walk_dir(dir: &Path, mut map: &mut FileMap) -> io::Result<()> {
    if dir.is_dir() {
        for entry in fs::read_dir(dir)? {
            let path = entry.unwrap().path();
            if path.is_dir() {
                if _walk_dir(&path, &mut map).is_err() {
                    println!("Error walking directory {}", dir.to_string_lossy());
                }
            } else {
                if let Ok(mut file) = fs::File::open(&path) {
                    let hash = hash_file::<Md5, _>(&mut file);
                    let mut hash_str = String::with_capacity(32);
                    for b in hash {
                        hash_str.push_str(&format!("{:02x}", b));
                    }
                    map.insert(path.to_string_lossy().to_string(), hash_str);
                }
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
        if remote_hash.is_some() && remote_hash.unwrap() != hash {
            results.push(name.to_owned());
        }
    }
    results
}

#[pyfunction]
pub fn walk_dir(path: String) -> FileMap {
    let dir = Path::new(&path);
    let mut map = HashMap::new();
    _walk_dir(&dir, &mut map).unwrap();
    map
}

#[pymodule]
fn syncprojects_fast(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk_dir, m)?)?;
    m.add_function(wrap_pyfunction!(get_difference, m)?)?;
    Ok(())
}