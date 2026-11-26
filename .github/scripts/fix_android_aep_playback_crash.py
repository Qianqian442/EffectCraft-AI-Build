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
    for path in (frames_path, tests_path, prefetch_path):
        if not path.is_file():
            raise SystemExit(f"Required Android preview source is missing: {path}")

    frames = frames_path.read_text(encoding="utf-8")
    tests = tests_path.read_text(encoding="utf-8")
    prefetch = prefetch_path.read_text(encoding="utf-8")

    marker = "EFFECTCRAFT_ANDROID_AEP_PLAYBACK_RESOURCE_GUARD_V1"
    if marker not in frames:
        budget_old = "const GPU_BUDGET: usize = 1 << 30;"
        budget_new = """// EFFECTCRAFT_ANDROID_AEP_PLAYBACK_RESOURCE_GUARD_V1
// Mobile GPUs share system RAM with the app; keep preview textures bounded on Android.
const DESKTOP_GPU_BUDGET: usize = 1 << 30;
const ANDROID_GPU_BUDGET: usize = 256 << 20;

fn effectcraft_preview_gpu_budget(android: bool) -> usize {
    if android { ANDROID_GPU_BUDGET } else { DESKTOP_GPU_BUDGET }
}

// Imported AEP timelines can trigger many expensive frame decodes/composites at once.
// Keep desktop's existing 2..16 pool unchanged; Android gets at most two frame workers.
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

        # Set the mobile budget at construction, on recovery, and after clearing the cache.
        frames = frames.replace("gpu_budget: GPU_BUDGET,", "gpu_budget: effectcraft_preview_gpu_budget(cfg!(target_os = \"android\")),")
        frames = frames.replace(".min(GPU_BUDGET);", ".min(effectcraft_preview_gpu_budget(cfg!(target_os = \"android\")));")
        frames = frames.replace("c.gpu_budget = GPU_BUDGET;", "c.gpu_budget = effectcraft_preview_gpu_budget(cfg!(target_os = \"android\"));")
        frames = frames.replace('/// Bytes of GPU frames to keep at most ([`GPU_BUDGET`]).', '/// Bytes of GPU frames to keep at most (platform-specific preview budget).')
        if any(token in frames for token in ('gpu_budget: GPU_BUDGET,', '.min(GPU_BUDGET)', 'c.gpu_budget = GPU_BUDGET;')):
            raise SystemExit("A stale GPU_BUDGET code reference remains after Android budget conversion.")
        if "effectcraft_preview_gpu_budget(cfg!(target_os = \"android\"))" not in frames:
            raise SystemExit("Android GPU preview budget was not applied at cache initialization.")
        frames_path.write_text(frames, encoding="utf-8")

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

    assert_eq!(super::effectcraft_preview_gpu_budget(true), 256 << 20);
    assert_eq!(super::effectcraft_preview_gpu_budget(false), 1 << 30);
}
"""
        tests_path.write_text(tests, encoding="utf-8")

    final_frames = frames_path.read_text(encoding="utf-8")
    final_tests = tests_path.read_text(encoding="utf-8")
    final_prefetch = prefetch_path.read_text(encoding="utf-8")
    required = (
        "effectcraft_preview_worker_threads(reported_threads, cfg!(target_os = \"android\"))",
        "const ANDROID_GPU_BUDGET: usize = 256 << 20;",
        "effectcraft_preview_gpu_budget(cfg!(target_os = \"android\"))",
    )
    for token in required:
        if token not in final_frames:
            raise SystemExit(f"Android preview guard is incomplete: {token}")
    if "workers.min(1).max(1)" not in final_prefetch or prefetch_marker not in final_prefetch:
        raise SystemExit("Android preview prefetch is not constrained to one worker.")
    if tests_marker not in final_tests:
        raise SystemExit("Android preview scheduling regression test is missing.")

    print("Android preview worker pool: maximum 1 frame worker; desktop remains 2..16.")
    print("Android GPU preview frame cache: 256 MiB; desktop remains 1 GiB.")
    print("Android playback prefetch: maximum 1 worker (at most one requested future frame).")
    print("Added regression tests; no application-wide RAM cap, export FPS cap, or desktop scheduling change.")


if __name__ == "__main__":
    main()
