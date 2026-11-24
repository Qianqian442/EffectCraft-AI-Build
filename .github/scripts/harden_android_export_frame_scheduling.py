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
    required = (
        marker,
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
    )
    for token in required:
        if token not in source:
            raise SystemExit(f"Android export frame scheduling is incomplete: {token}")

    path.write_text(source, encoding="utf-8")
    print("Android export defaults to one output frame in flight; explicit valid CPU_INFLIGHT values remain effective.")
    print("Desktop export is unchanged. Output resolution, frame rate, codec and total app memory policy are unchanged.")


if __name__ == "__main__":
    main()
