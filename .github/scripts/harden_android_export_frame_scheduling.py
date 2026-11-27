#!/usr/bin/env python3
"""Serialize Android export frame scheduling by default to avoid burst OOM crashes."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    n = source.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected one exact anchor, found {n}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/export/src/pipeline.rs"
    if not path.is_file():
        raise SystemExit(f"Export frame pipeline source is missing: {path}")
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_EXPORT_FRAME_SCHEDULING_V1"

    # Android's one-frame export must execute on the dedicated render-queue thread,
    # not bounce a full-resolution frame through the global Rayon worker pool.
    serial_marker = "EFFECTCRAFT_ANDROID_EXPORT_SERIAL_FRAME_LOOP_V1"
    if serial_marker not in source:
        serial_anchor = """    use rayon::prelude::*;
    if caps.renders(gpu_live()).is_none() {"""
        serial_patch = """    use rayon::prelude::*;
    // EFFECTCRAFT_ANDROID_EXPORT_SERIAL_FRAME_LOOP_V1
    if cfg!(target_os = "android") && caps.cpu == Some(1) {
        let mut output = Vec::with_capacity(ks.len());
        for k in ks {
            output.push(encode(k, render(k)));
        }
        return output;
    }
    if caps.renders(gpu_live()).is_none() {"""
        source = replace_once(source, serial_anchor, serial_patch, "Run Android single-frame export on the dedicated render thread")


    if marker not in source:
        helper_anchor = """pub(crate) fn cpu_inflight(var: Option<&str>) -> Option<usize> {
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
}"""
        helper = helper_anchor + """

/// EFFECTCRAFT_ANDROID_EXPORT_FRAME_SCHEDULING_V1
/// Keep only one CPU-rendered output frame in flight on Android by default.
/// An explicit valid EFFECTCRAFT_CPU_INFLIGHT setting remains the user's override.
/// This bounds concurrent frame buffers; it is not an application-wide RAM limit.
pub(crate) fn cpu_inflight_for_platform(var: Option<&str>, android: bool) -> Option<usize> {
    cpu_inflight(var).or_else(|| android.then_some(1))
}"""
        source = replace_once(source, helper_anchor, helper, "Android export CPU frame scheduling helper")

        old = "Inflight { gpu: self.gpu_cap(), cpu: cpu_inflight(std::env::var(CPU_INFLIGHT_ENV).ok().as_deref()) }"
        new = 'Inflight { gpu: self.gpu_cap(), cpu: cpu_inflight_for_platform(std::env::var(CPU_INFLIGHT_ENV).ok().as_deref(), cfg!(target_os = "android")) }'
        source = replace_once(source, old, new, "Android export frame cap integration")

        test_anchor = """    /// Dither may round a colour up while alpha rounds down; premultiplied colour stays at or
    /// below the written alpha at every pixel."""
        tests = """    #[test]
    fn android_export_defaults_to_one_in_flight_frame_without_overriding_explicit_settings() {
        assert_eq!(cpu_inflight_for_platform(None, true), Some(1));
        assert_eq!(cpu_inflight_for_platform(Some(""), true), Some(1));
        assert_eq!(cpu_inflight_for_platform(Some("2"), true), Some(2));
        assert_eq!(cpu_inflight_for_platform(Some("3"), true), Some(3));
        assert_eq!(cpu_inflight_for_platform(None, false), None);
        assert_eq!(cpu_inflight_for_platform(Some("2"), false), Some(2));
        // Invalid settings are warned about by cpu_inflight and fall back to the Android default.
        assert_eq!(cpu_inflight_for_platform(Some("0"), true), Some(1));
    }

"""
        source = replace_once(source, test_anchor, tests + test_anchor, "Android export scheduling regression tests")

    # Android software rendering can use deeper native/effect call stacks than the
    # platform's default pthread stack. Give the one render worker an explicit 8 MiB stack.
    queue_path = root / "crates/engine/src/render_queue.rs"
    if not queue_path.is_file():
        raise SystemExit(f"Render Queue runtime source is missing: {queue_path}")
    queue_source = queue_path.read_text(encoding="utf-8")
    queue_marker = "EFFECTCRAFT_ANDROID_RENDER_WORKER_STACK_V1"
    if queue_marker not in queue_source:
        queue_anchor = """            let thread = std::thread::Builder::new()
                .name("render-queue".into())
                .spawn(move || {"""
        queue_patch = """            // EFFECTCRAFT_ANDROID_RENDER_WORKER_STACK_V1
            // Keep deep software-renderer/effect call stacks off Android's small default thread stack.
            let thread_builder = std::thread::Builder::new()
                .name("render-queue".into());
            #[cfg(target_os = "android")]
            let thread_builder = thread_builder.stack_size(8 * 1024 * 1024);
            let thread = thread_builder.spawn(move || {"""
        queue_source = replace_once(queue_source, queue_anchor, queue_patch, "Set an explicit Android render-worker stack size")
        queue_path.write_text(queue_source, encoding="utf-8")
    if queue_marker not in queue_path.read_text(encoding="utf-8") or "stack_size(8 * 1024 * 1024)" not in queue_path.read_text(encoding="utf-8"):
        raise SystemExit("Android render-worker stack configuration is incomplete.")

    cpu_marker = "EFFECTCRAFT_ANDROID_EXPORT_CPU_RENDER_FALLBACK_V1"
    if cpu_marker not in source:
        source = replace_once(source,
            "let backend = if self.project.settings.gpu_acceleration { Backend::Gpu } else { Backend::Cpu };",
            'let backend = if cfg!(target_os = "android") { Backend::Cpu } else if self.project.settings.gpu_acceleration { Backend::Gpu } else { Backend::Cpu };',
            "Use software renderer for Android video export",
        )
        source = replace_once(source,
            "        r.accel = self.job.accel;",
            "        // EFFECTCRAFT_ANDROID_EXPORT_CPU_RENDER_FALLBACK_V1\n        // Keep preview GPU acceleration, but render exported frames through the stable software backend on Android.\n        r.accel = if cfg!(target_os = \"android\") { None } else { self.job.accel };",
            "Disable Android GPU accelerator in export renderer",
        )
        source = replace_once(source,
            "        effectcraft_render::passes::is_deferred(self.job.accel)",
            "        !cfg!(target_os = \"android\") && effectcraft_render::passes::is_deferred(self.job.accel)",
            "Disable deferred GPU export readbacks on Android",
        )
        gpu_live_old = "        let gpu_live = || self.job.accel.is_none_or(|a| a.available());"
        gpu_live_new = "        let gpu_live = || !cfg!(target_os = \"android\") && self.job.accel.is_none_or(|a| a.available());"
        if source.count(gpu_live_old) != 2:
            raise SystemExit("Expected both Android export frame loops to have a GPU-live guard.")
        source = source.replace(gpu_live_old, gpu_live_new)
        source = replace_once(source,
            "        cache.set_gate(job.accel.and_then(|a| a.miss_gate()));",
            "        cache.set_gate(if cfg!(target_os = \"android\") { None } else { job.accel.and_then(|a| a.miss_gate()) });",
            "Disable deferred cache gates for Android CPU export",
        )
        source = replace_once(source,
            "(self.job.accel.is_some() && self.project.settings.gpu_acceleration).then(|| gpu_inflight(std::env::var(GPU_INFLIGHT_ENV).ok().as_deref()))",
            "(!cfg!(target_os = \"android\") && self.job.accel.is_some() && self.project.settings.gpu_acceleration).then(|| gpu_inflight(std::env::var(GPU_INFLIGHT_ENV).ok().as_deref()))",
            "Disable Android GPU frame cap in export scheduler",
        )

    # On Android, do not encode one batch while rendering the next. The Render Queue
    # already caps CPU frames in flight at one; serializing the encoder avoids retaining
    # two full-resolution frame batches at once on memory-constrained phones.
    beside_helper = """/// Whether movie encoding may overlap the next render batch.
/// Android keeps this false so render and encode release their large frame buffers in turn.
pub(crate) fn encode_beside_for_platform(android: bool) -> bool {
    !android
}

"""
    if "pub(crate) fn encode_beside_for_platform(android: bool) -> bool" not in source:
        anchor = """impl Beside {
    fn new() -> Beside {
        Beside(rayon::ThreadPoolBuilder::new().thread_name(|i| format!("export-encode-{i}")).build().ok())
    }"""
        replacement = beside_helper + """impl Beside {
    fn new() -> Beside {
        if !encode_beside_for_platform(cfg!(target_os = "android")) {
            return Beside(None);
        }
        Beside(rayon::ThreadPoolBuilder::new().thread_name(|i| format!("export-encode-{i}")).build().ok())
    }"""
        source = replace_once(source, anchor, replacement, "Serialize Android movie encoding after rendering")
    test_anchor = """    /// Dither may round a colour up while alpha rounds down; premultiplied colour stays at or
    /// below the written alpha at every pixel."""
    if "android_export_does_not_overlap_encoding_with_next_render_batch" not in source:
        tests = """    #[test]
    fn android_export_does_not_overlap_encoding_with_next_render_batch() {
        assert!(!encode_beside_for_platform(true));
        assert!(encode_beside_for_platform(false));
    }

"""
        source = replace_once(source, test_anchor, tests + test_anchor, "Android export render/encode serialization regression test")

    required = (
        marker,
        serial_marker,
        "if cfg!(target_os = \"android\") && caps.cpu == Some(1)",
        cpu_marker,
        "pub(crate) fn cpu_inflight_for_platform(var: Option<&str>, android: bool) -> Option<usize>",
        'let backend = if cfg!(target_os = "android") { Backend::Cpu } else if self.project.settings.gpu_acceleration { Backend::Gpu } else { Backend::Cpu }',
        'r.accel = if cfg!(target_os = "android") { None } else { self.job.accel };',
        '!cfg!(target_os = "android") && effectcraft_render::passes::is_deferred(self.job.accel)',
        'cache.set_gate(if cfg!(target_os = "android") { None } else { job.accel.and_then(|a| a.miss_gate()) });',
        '(!cfg!(target_os = "android") && self.job.accel.is_some() && self.project.settings.gpu_acceleration).then(|| gpu_inflight(std::env::var(GPU_INFLIGHT_ENV).ok().as_deref()))',
        'let gpu_live = || !cfg!(target_os = "android") && self.job.accel.is_none_or(|a| a.available());',
        'cpu_inflight_for_platform(std::env::var(CPU_INFLIGHT_ENV).ok().as_deref(), cfg!(target_os = "android"))',
        "android_export_defaults_to_one_in_flight_frame_without_overriding_explicit_settings",
        "pub(crate) fn encode_beside_for_platform(android: bool) -> bool",
        "android_export_does_not_overlap_encoding_with_next_render_batch",
    )
    for token in required:
        if token not in source:
            raise SystemExit(f"Android export frame scheduling is incomplete: {token}")

    path.write_text(source, encoding="utf-8")

    # A failed encoder/render must not leave a truncated MP4 that looks like a successful export.
    # The export context tracks only files created by this job, so remove those on every error.
    export_lib_path = root / "crates/export/src/lib.rs"
    export_lib = export_lib_path.read_text(encoding="utf-8")
    old_failure_cleanup = """    if matches!(r, Err(ExportError::Cancelled)) {
        cx.remove_cancelled_outputs()?;
        return r;
    }"""
    new_failure_cleanup = """    if r.is_err() {
        // Cancellation and render/encode failures all remove only this job's partial outputs.
        cx.remove_cancelled_outputs()?;
        return r;
    }"""
    if new_failure_cleanup not in export_lib:
        export_lib = replace_once(export_lib, old_failure_cleanup, new_failure_cleanup,
                                  "Clean partial video files after any render/encoder failure")
        export_lib_path.write_text(export_lib, encoding="utf-8")
    if "if r.is_err() {" not in export_lib or "cx.remove_cancelled_outputs()?;" not in export_lib:
        raise SystemExit("Failed export output cleanup is incomplete.")
    print("Failed or cancelled exports remove their incomplete output files.");
    print("Android export defaults to one output frame in flight; explicit valid CPU_INFLIGHT values remain effective.")
    print("Android movie rendering and encoding run sequentially to reduce peak frame-buffer memory.")
    print("Desktop export is unchanged. Output resolution, frame rate, codec and total app memory policy are unchanged.")


if __name__ == "__main__":
    main()
