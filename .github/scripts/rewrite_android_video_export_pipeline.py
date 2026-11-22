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
    writer: BufWriter<std::fs::File>,
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
            Ok(Out::File(AtomicOutput { writer: BufWriter::new(file), temporary: Some(temporary), destination }))""",
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
                output.writer.flush().map_err(io)?;
                let file = output.writer.into_inner().map_err(|e| ExportError::Io(e.to_string()))?;
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
        source = once(source, "            Out::File(w) => w.write(buf),", "            Out::File(w) => w.writer.write(buf),", "Atomic output write")
        source = once(source, "            Out::File(w) => w.flush(),", "            Out::File(w) => w.writer.flush(),", "Atomic output flush")
        source = once(source, "            Out::File(w) => w.seek(pos),", "            Out::File(w) => w.writer.seek(pos),", "Atomic output seek")
    out.write_text(source, encoding="utf-8")
    print("Android video export uses one-frame sequential render/encode and atomically publishes only complete output files.")
    print("Desktop parallel export, codec selection, resolution/FPS controls, audio and AI features are unchanged.")


if __name__ == "__main__":
    main()
