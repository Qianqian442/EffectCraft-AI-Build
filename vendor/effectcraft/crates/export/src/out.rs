//! Output files: the file system, or an in-memory [`Sink`] chosen per job (the web app, which
//! offers every written file as a download; tests).

use std::io::{BufWriter, Cursor, Seek, SeekFrom, Write};

use crate::{ExportError, Result, io};

/// Receives each finished output file (path as resolved, complete contents) instead of the file
/// system. Called once per file; image sequences call it from the render threads.
pub type Sink = dyn Fn(&str, Vec<u8>) + Send + Sync;

/// One output file being written.
struct AtomicOutput {
    writer: BufWriter<std::fs::File>,
    temporary: std::path::PathBuf,
    destination: std::path::PathBuf,
}

impl Drop for AtomicOutput {
    fn drop(&mut self) {
        // A failed/cancelled export must not leave a truncated MP4/MOV at the final path.
        let _ = std::fs::remove_file(&self.temporary);
    }
}

pub(crate) enum Out<'a> {
    File(AtomicOutput),
    Mem { path: String, cur: Cursor<Vec<u8>>, sink: &'a Sink },
}

/// Create `path` (parent directories included) or an in-memory file for `sink`.
pub(crate) fn create<'a>(sink: Option<&'a Sink>, path: &str) -> Result<Out<'a>> {
    match sink {
        Some(sink) => Ok(Out::Mem { path: path.to_string(), cur: Cursor::new(Vec::new()), sink }),
        None => {
            if let Some(dir) = std::path::Path::new(path).parent().filter(|d| !d.as_os_str().is_empty()) {
                std::fs::create_dir_all(dir).map_err(io)?;
            }
            // Write beside the destination, then atomically publish only after the muxer
            // has finished and the file has been flushed. This prevents a crash or failed
            // encoder from leaving a half-written movie that looks like a completed export.
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
            let (temporary, file) = created.ok_or_else(|| ExportError::Io("无法创建视频临时文件，请检查存储空间和目录权限。".into()))?;
            Ok(Out::File(AtomicOutput { writer: BufWriter::new(file), temporary, destination }))
        }
    }
}

/// Whether `path` already exists (never for a sink: it has no memory of earlier jobs).
pub(crate) fn exists(sink: Option<&Sink>, path: &str) -> bool {
    sink.is_none() && std::path::Path::new(path).exists()
}

impl Out<'_> {
    /// Flush and close; a sink receives the contents now. Returns the file size.
    pub(crate) fn finish(self) -> Result<u64> {
        match self {
            Out::File(mut output) => {
                output.writer.flush().map_err(io)?;
                let file = output.writer.into_inner().map_err(|e| ExportError::Io(e.to_string()))?;
                file.sync_all().map_err(io)?;
                let bytes = file.metadata().map(|m| m.len()).unwrap_or(0);
                drop(file);
                std::fs::rename(&output.temporary, &output.destination).map_err(io)?;
                // The rename succeeded; prevent Drop from trying to remove the now-published file.
                output.temporary = output.destination.clone().with_extension("effectcraft-published");
                Ok(bytes)
            }
            Out::Mem { path, cur, sink } => {
                let data = cur.into_inner();
                let n = data.len() as u64;
                sink(&path, data);
                Ok(n)
            }
        }
    }
}

impl Write for Out<'_> {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        match self {
            Out::File(w) => w.writer.write(buf),
            Out::Mem { cur, .. } => cur.write(buf),
        }
    }
    fn flush(&mut self) -> std::io::Result<()> {
        match self {
            Out::File(w) => w.writer.flush(),
            Out::Mem { .. } => Ok(()),
        }
    }
}

impl Seek for Out<'_> {
    fn seek(&mut self, pos: SeekFrom) -> std::io::Result<u64> {
        match self {
            Out::File(w) => w.writer.seek(pos),
            Out::Mem { cur, .. } => cur.seek(pos),
        }
    }
}
