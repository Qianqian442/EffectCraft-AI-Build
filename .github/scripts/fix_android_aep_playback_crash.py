#!/usr/bin/env python3
"""Bound Android preview frame bursts that can OOM-kill playback of imported AEP projects.

Desktop preview scheduling is unchanged. This is a per-frame-worker/GPU-preview-cache
scheduling guard, not an application-wide memory limit and not an export quality cap.
"""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact anchor, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    frames_path = root / "crates/ui-egui/src/frames.rs"
    tests_path = root / "crates/ui-egui/src/frames/tests.rs"
    prefetch_path = root / "crates/ui-egui/src/app/prefetch.rs"
    cache_prefs_path = root / "crates/engine/src/settings/prefs/queries.rs"
    for path in (frames_path, tests_path, prefetch_path, cache_prefs_path):
        if not path.is_file():
            raise SystemExit(f"Required Android preview source is missing: {path}")

    frames = frames_path.read_text(encoding="utf-8")
    tests = tests_path.read_text(encoding="utf-8")
    prefetch = prefetch_path.read_text(encoding="utf-8")
    cache_prefs = cache_prefs_path.read_text(encoding="utf-8")

    marker = "EFFECTCRAFT_ANDROID_AEP_PLAYBACK_RESOURCE_GUARD_V1"
    if marker not in frames:
        budget_old = "const GPU_BUDGET: usize = 1 << 30;"
        budget_new = """// EFFECTCRAFT_ANDROID_AEP_PLAYBACK_RESOURCE_GUARD_V1
// Android GPUs share system RAM with the app. Keep a larger normal preview allowance,
// but lower it automatically after allocation pressure.
const DESKTOP_GPU_BUDGET: usize = 1 << 30;
const ANDROID_GPU_BUDGET: usize = 512 << 20;
const ANDROID_PREVIEW_CACHE_BUDGET: usize = 768 << 20;
const MIN_GPU_BUDGET: usize = 64 << 20;
const GPU_PRESSURE_COOLDOWN: std::time::Duration = std::time::Duration::from_secs(5);
const GPU_RECOVERY_INTERVAL: std::time::Duration = std::time::Duration::from_secs(30);

fn effectcraft_preview_gpu_budget(android: bool) -> usize {
    if android { ANDROID_GPU_BUDGET } else { DESKTOP_GPU_BUDGET }
}

fn effectcraft_preview_frame_cache_budget(requested: usize, android: bool) -> usize {
    if android { requested.min(ANDROID_PREVIEW_CACHE_BUDGET) } else { requested }
}

// Imported AEP timelines can trigger many expensive frame decodes/composites at once.
// Keep desktop's existing 2..16 pool unchanged; Android uses one frame worker.
fn effectcraft_preview_worker_threads(reported: Option<usize>, android: bool) -> usize {
    if android {
        // Prefer one decode/composite worker over smoothness: this device profile
        // explicitly prioritizes preventing playback OOM over frame throughput.
        let _ = reported;
        1
    } else {
        reported.unwrap_or(4).clamp(2, 16)
    }
}"""
        frames = replace_once(frames, budget_old, budget_new, "Android GPU preview budget")

        threads_old = "let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).clamp(2, 16);"
        threads_new = """let reported_threads = std::thread::available_parallelism().map(|n| n.get()).ok();
        let threads = effectcraft_preview_worker_threads(reported_threads, cfg!(target_os = "android"));"""
        frames = replace_once(frames, threads_old, threads_new, "Android preview worker count")

        # Keep the RAM preview cache and GPU-texture cache independently bounded on Android.
        frames = frames.replace(
            "budget: 3 << 30, gpu_budget: GPU_BUDGET,",
            "budget: effectcraft_preview_frame_cache_budget(3 << 30, cfg!(target_os = \"android\")), gpu_budget: effectcraft_preview_gpu_budget(cfg!(target_os = \"android\")),",
        )
        frames = frames.replace("c.budget = bytes;", "c.budget = effectcraft_preview_frame_cache_budget(bytes, cfg!(target_os = \"android\"));")
        frames = frames.replace("c.gpu_budget = GPU_BUDGET;", "c.gpu_budget = effectcraft_preview_gpu_budget(cfg!(target_os = \"android\"));")
        frames = frames.replace(".min(GPU_BUDGET);", ".min(effectcraft_preview_gpu_budget(cfg!(target_os = \"android\")));")
        frames = frames.replace('/// Bytes of GPU frames to keep at most ([`GPU_BUDGET`]).', '/// Bytes of GPU frames to keep at most (platform-specific preview budget).')
        if any(token in frames for token in ('budget: 3 << 30, gpu_budget: GPU_BUDGET,', 'c.budget = bytes;', 'c.gpu_budget = GPU_BUDGET;', '.min(GPU_BUDGET)')):
            raise SystemExit("A stale preview-cache budget reference remains after Android budget conversion.")
        if "effectcraft_preview_frame_cache_budget(3 << 30, cfg!(target_os = \"android\"))" not in frames:
            raise SystemExit("Android RAM preview cache budget was not applied at cache initialization.")
        if "effectcraft_preview_frame_cache_budget(bytes, cfg!(target_os = \"android\"))" not in frames:
            raise SystemExit("Android RAM preview cache cap is not applied when Settings changes the budget.")
        if "effectcraft_preview_gpu_budget(cfg!(target_os = \"android\"))" not in frames:
            raise SystemExit("Android GPU preview budget was not applied at cache initialization.")
        frames_path.write_text(frames, encoding="utf-8")

    cache_prefs_marker = "EFFECTCRAFT_ANDROID_RAM_RESERVATION_CAP_V1"
    if cache_prefs_marker not in cache_prefs:
        old_reserved = "            let reserved = (self.memory.ram_reserved_gb as u64) << 30;"
        new_reserved = """            // EFFECTCRAFT_ANDROID_RAM_RESERVATION_CAP_V1
            // A desktop-style 6 GiB reserve can consume the whole reported RAM on a phone,
            // collapsing every cache to its 64 MiB floor. On Android keep at least 25% of
            // physical RAM reserved for the OS and other apps, while respecting lower user values.
            let configured_reserved = (self.memory.ram_reserved_gb as u64) << 30;
            let reserved = if cfg!(target_os = "android") {
                configured_reserved.min(mem.total.saturating_mul(3) / 4)
            } else {
                configured_reserved
            };"""
        cache_prefs = replace_once(cache_prefs, old_reserved, new_reserved, "Android RAM reservation cap")
        cache_prefs_path.write_text(cache_prefs, encoding="utf-8")

    prefetch_marker = "EFFECTCRAFT_ANDROID_AEP_PLAYBACK_PREFETCH_GUARD_V1"
    if prefetch_marker not in prefetch:
        old = """        self.frames.parallelism()
    }
}"""
        new = """        // EFFECTCRAFT_ANDROID_AEP_PLAYBACK_PREFETCH_GUARD_V1
        // Limit Android future-frame prefetch to one worker to reduce peak memory.
        let workers = self.frames.parallelism();
        if cfg!(target_os = "android") { workers.min(1).max(1) } else { workers }
    }
}"""
        prefetch = replace_once(prefetch, old, new, "Android playback prefetch concurrency")
        prefetch_path.write_text(prefetch, encoding="utf-8")

    tests_marker = "fn android_aep_playback_resource_guard_is_tested()"
    if tests_marker not in tests:
        tests = tests.rstrip() + """

/// The Android preview limits protect playback only; desktop pool sizing is unchanged.
#[test]
fn android_aep_playback_resource_guard_is_tested() {
    assert_eq!(super::effectcraft_preview_worker_threads(Some(16), true), 1);
    assert_eq!(super::effectcraft_preview_worker_threads(Some(8), true), 1);
    assert_eq!(super::effectcraft_preview_worker_threads(None, true), 1);
    assert_eq!(super::effectcraft_preview_worker_threads(Some(1), false), 2);
    assert_eq!(super::effectcraft_preview_worker_threads(Some(8), false), 8);
    assert_eq!(super::effectcraft_preview_worker_threads(Some(32), false), 16);

    assert_eq!(super::effectcraft_preview_gpu_budget(true), 512 << 20);
    assert_eq!(super::effectcraft_preview_gpu_budget(false), 1 << 30);
    assert_eq!(super::effectcraft_preview_frame_cache_budget(3 << 30, true), 768 << 20);
    assert_eq!(super::effectcraft_preview_frame_cache_budget(256 << 20, true), 256 << 20);
    assert_eq!(super::effectcraft_preview_frame_cache_budget(3 << 30, false), 3 << 30);
}
"""
        tests_path.write_text(tests, encoding="utf-8")

    final_frames = frames_path.read_text(encoding="utf-8")
    final_tests = tests_path.read_text(encoding="utf-8")
    final_prefetch = prefetch_path.read_text(encoding="utf-8")
    final_cache_prefs = cache_prefs_path.read_text(encoding="utf-8")
    required = (
        "effectcraft_preview_worker_threads(reported_threads, cfg!(target_os = \"android\"))",
        "const ANDROID_GPU_BUDGET: usize = 512 << 20;",
        "effectcraft_preview_gpu_budget(cfg!(target_os = \"android\"))",
        "const ANDROID_GPU_BUDGET: usize = 512 << 20;",
        "const ANDROID_PREVIEW_CACHE_BUDGET: usize = 768 << 20;",
        "effectcraft_preview_frame_cache_budget(bytes, cfg!(target_os = \"android\"))",
    )
    for token in required:
        if token not in final_frames:
            raise SystemExit(f"Android preview guard is incomplete: {token}")
    if "workers.min(1).max(1)" not in final_prefetch or prefetch_marker not in final_prefetch:
        raise SystemExit("Android preview prefetch is not constrained to one worker.")
    if tests_marker not in final_tests:
        raise SystemExit("Android preview scheduling regression test is missing.")
    if "EFFECTCRAFT_ANDROID_RAM_RESERVATION_CAP_V1" not in final_cache_prefs:
        raise SystemExit("Android RAM reservation cap is missing from Prefs::cache_budgets_in.")

    print("Android RAM preview cache: capped at 768 MiB; desktop retains its configured 3 GiB default.")
    print("Android GPU preview cache: 512 MiB normally, halved on allocation pressure; desktop remains 1 GiB.")
    print("Android worker pool and playback prefetch: one frame worker each; desktop scheduling is unchanged.")
    print("Added regression tests; export resolution/quality and application-wide memory settings are unchanged.")


if __name__ == "__main__":
    main()
