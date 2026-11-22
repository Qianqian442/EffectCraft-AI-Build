#!/usr/bin/env python3
"""Rebuild the Android movie-export path as a sequential, transactional pipeline."""
from __future__ import annotations

import os
from pathlib import Path


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count == 0 and new in source:
        return source
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()

    # 1) Mobile export: one frame at a time, no encode/render overlap pool.
    pipeline = root / "crates/export/src/pipeline.rs"
    source = pipeline.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_SEQUENTIAL_VIDEO_PIPELINE_V1"
    if marker not in source:
        source = once(
            source,
            """pub(crate) fn cpu_inflight(var: Option<&str>) -> Option<usize> {
    let v = var?;
    if v.trim().is_empty() {
        return None;
    }
    match v.trim().parse::<usize>() {
        Ok(n) if n >= 1 => Some(n),
        _ => {
            log::warn!(target: "effectcraft_export", "{CPU_INFLIGHT_ENV}={v:?} is not a whole number of frames of at least 1: CPU frames are not capped");
            None
        }
    }
}""",
            """pub(crate) fn cpu_inflight(var: Option<&str>) -> Option<usize> {
    let v = var?;
    if v.trim().is_empty() {
        return None;
    }
    match v.trim().parse::<usize>() {
        Ok(n) if n >= 1 => Some(n),
        _ => {
            log::warn!(target: "effectcraft_export", "{CPU_INFLIGHT_ENV}={v:?} is not a whole number of frames of at least 1: CPU frames are not capped");
            None
        }
    }
}

/// EFFECTCRAFT_ANDROID_SEQUENTIAL_VIDEO_PIPELINE_V1
/// Android defaults to a single in-flight CPU frame; an explicit positive override is retained.
pub(crate) fn cpu_inflight_for_platform(var: Option<&str>, android: bool) -> Option<usize> {
    cpu_inflight(var).or_else(|| android.then_some(1))
}""",
            "Android CPU frame scheduler",
        )
        source = once(
            source,
            "Inflight { gpu: self.gpu_cap(), cpu: cpu_inflight(std::env::var(CPU_INFLIGHT_ENV).ok().as_deref()) }",
            'Inflight { gpu: self.gpu_cap(), cpu: cpu_inflight_for_platform(std::env::var(CPU_INFLIGHT_ENV).ok().as_deref(), cfg!(target_os = "android")) }',
            "Android CPU frame scheduler integration",
        )
        source = once(
            source,
            """impl Beside {
    fn new() -> Beside {
        Beside(rayon::ThreadPoolBuilder::new().thread_name(|i| format!("export-encode-{i}")).build().ok())
    }""",
            """impl Beside {
    fn new() -> Beside {
        // Mobile exports do not overlap encoding with the next render: this retains extra
        // full-resolution frame buffers and can cause Android's low-memory killer to stop us.
        #[cfg(target_os = "android")]
        { return Beside(None); }
        #[cfg(not(target_os = "android"))]
        { Beside(rayon::ThreadPoolBuilder::new().thread_name(|i| format!("export-encode-{i}")).build().ok()) }
    }""",
            "Android encode/render overlap pool",
        )
    pipeline.write_text(source, encoding="utf-8")

    # 2) Keep the existing codec implementations, but make Android movie batches single-frame.
    lib = root / "crates/export/src/lib.rs"
    source = lib.read_text(encoding="utf-8")
    source = once(
        source,
        """pub(crate) fn batch_size() -> u64 {
    rayon::current_num_threads().clamp(2, 16) as u64
}""",
        """pub(crate) fn batch_size() -> u64 {
    // EFFECTCRAFT_ANDROID_SEQUENTIAL_VIDEO_PIPELINE_V1
    // Desktop retains parallel batches; Android renders and encodes one frame before advancing.
    #[cfg(target_os = "android")]
    { return 1; }
    #[cfg(not(target_os = "android"))]
    { rayon::current_num_threads().clamp(2, 16) as u64 }
}""",
        "Android movie batch size",
    )
    lib.write_text(source, encoding="utf-8")

    # 3) Transactional output: write to a sibling .partial file, fsync, then atomically publish.
    # A failed encoder/cancelled export never leaves a truncated file at the final movie path.
    out = root / "crates/export/src/out.rs"
    source = out.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ATOMIC_EXPORT_OUTPUT_V1"
    if marker not in source:
        source = once(
            source,
            """pub(crate) enum Out<'a> {
    File(BufWriter<std::fs::File>),
    Mem { path: String, cur: Cursor<Vec<u8>>, sink: &'a Sink },
}""",
            """/// EFFECTCRAFT_ATOMIC_EXPORT_OUTPUT_V1
struct AtomicOutput {
    writer: Option<BufWriter<std::fs::File>>,
    temporary: Option<std::path::PathBuf>,
    destination: std::path::PathBuf,
}

impl Drop for AtomicOutput {
    fn drop(&mut self) {
        if let Some(path) = &self.temporary {
            let _ = std::fs::remove_file(path);
        }
    }
}

pub(crate) enum Out<'a> {
    File(AtomicOutput),
    Mem { path: String, cur: Cursor<Vec<u8>>, sink: &'a Sink },
}""",
            "Atomic output structure",
        )
        source = once(
            source,
            "            Ok(Out::File(BufWriter::new(std::fs::File::create(path).map_err(io)?)))",
            """            // Use a unique temporary file in the destination directory so rename is atomic.
            static NEXT_TEMP: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
            let destination = std::path::PathBuf::from(path);
            let parent = destination.parent().filter(|d| !d.as_os_str().is_empty()).unwrap_or_else(|| std::path::Path::new("."));
            let name = destination.file_name().and_then(|n| n.to_str()).unwrap_or("effectcraft-export");
            let mut created = None;
            for _ in 0..32 {
                let serial = NEXT_TEMP.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                let temporary = parent.join(format!(".{name}.{}.{}.partial", std::process::id(), serial));
                match std::fs::OpenOptions::new().write(true).read(true).create_new(true).open(&temporary) {
                    Ok(file) => { created = Some((temporary, file)); break; }
                    Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                    Err(error) => return Err(io(error)),
                }
            }
            let (temporary, file) = created.ok_or_else(|| ExportError::Io("无法创建导出临时文件，请检查存储空间和目录权限。".into()))?;
            Ok(Out::File(AtomicOutput { writer: Some(BufWriter::new(file)), temporary: Some(temporary), destination }))""",
            "Atomic output creation",
        )
        source = once(
            source,
            """            Out::File(mut w) => {
                w.flush().map_err(io)?;
                let f = w.into_inner().map_err(|e| ExportError::Io(e.to_string()))?;
                Ok(f.metadata().map(|m| m.len()).unwrap_or(0))
            }""",
            """            Out::File(mut output) => {
                let mut writer = output.writer.take().ok_or_else(|| ExportError::Io("导出文件写入器状态无效。".into()))?;
                writer.flush().map_err(io)?;
                let file = writer.into_inner().map_err(|e| ExportError::Io(e.to_string()))?;
                file.sync_all().map_err(io)?;
                let bytes = file.metadata().map(|m| m.len()).unwrap_or(0);
                drop(file);
                let temporary = output.temporary.as_ref().ok_or_else(|| ExportError::Io("导出临时文件状态无效。".into()))?;
                std::fs::rename(temporary, &output.destination).map_err(io)?;
                output.temporary = None;
                Ok(bytes)
            }""",
            "Atomic output commit",
        )
        source = once(source, "            Out::File(w) => w.write(buf),", """            Out::File(w) => match w.writer.as_mut() { Some(writer) => writer.write(buf), None => Err(std::io::Error::new(std::io::ErrorKind::BrokenPipe, "export output is already finalized")) },""", "Atomic output write")
        source = once(source, "            Out::File(w) => w.flush(),", """            Out::File(w) => match w.writer.as_mut() { Some(writer) => writer.flush(), None => Err(std::io::Error::new(std::io::ErrorKind::BrokenPipe, "export output is already finalized")) },""", "Atomic output flush")
        source = once(source, "            Out::File(w) => w.seek(pos),", """            Out::File(w) => match w.writer.as_mut() { Some(writer) => writer.seek(pos), None => Err(std::io::Error::new(std::io::ErrorKind::BrokenPipe, "export output is already finalized")) },""", "Atomic output seek")
    tests_marker = "EFFECTCRAFT_ATOMIC_EXPORT_OUTPUT_TESTS_V1"
    if tests_marker not in source:
        source += r"""
// EFFECTCRAFT_ATOMIC_EXPORT_OUTPUT_TESTS_V1
#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::panic)]
mod android_atomic_output_tests {
    use super::*;
    use std::io::Write;

    fn test_path(label: &str) -> std::path::PathBuf {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        std::env::temp_dir().join(format!(
            "effectcraft-{label}-{}-{}.mp4",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ))
    }

    #[test]
    fn final_movie_appears_only_after_atomic_finish() {
        let path = test_path("commit");
        let _ = std::fs::remove_file(&path);
        let mut output = match create(None, path.to_str().unwrap_or_default()) { Ok(value) => value, Err(error) => { assert!(false, "{error}"); return; } };
        output.write_all(b"complete-movie").unwrap();
        assert!(!path.exists(), "partial movie must not be visible at its final path");
        assert_eq!(output.finish().ok(), Some(14));
        assert_eq!(std::fs::read(&path).ok(), Some(b"complete-movie".to_vec()));
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn dropping_failed_movie_removes_partial_file_and_keeps_existing_output() {
        let path = test_path("rollback");
        std::fs::write(&path, b"previous-valid-movie").unwrap();
        {
            let mut output = match create(None, path.to_str().unwrap_or_default()) { Ok(value) => value, Err(error) => { assert!(false, "{error}"); return; } };
            output.write_all(b"incomplete").unwrap();
        }
        assert_eq!(std::fs::read(&path).ok(), Some(b"previous-valid-movie".to_vec()));
        let Some(parent) = path.parent() else { assert!(false, "test path has no parent"); return; };
        let partials = match std::fs::read_dir(parent) { Ok(entries) => entries, Err(error) => { assert!(false, "{error}"); return; } }
            .filter_map(|entry| entry.ok())
            .filter(|entry| entry.file_name().to_string_lossy().starts_with(
                &format!(".{}.{}.", path.file_name().unwrap().to_string_lossy(), std::process::id())
            ))
            .collect::<Vec<_>>();
        assert!(partials.is_empty(), "failed export must clean its partial file");
        std::fs::remove_file(path).unwrap();
    }
}
"""
    out.write_text(source, encoding="utf-8")
    print("Android video export uses one-frame sequential render/encode and atomically publishes only complete output files.")
    print("Desktop parallel export, codec selection, resolution/FPS controls, audio and AI features are unchanged.")


if __name__ == "__main__":
    main()
