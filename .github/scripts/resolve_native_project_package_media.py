#!/usr/bin/env python3
"""Resolve packaged native-project footage recursively before reporting missing media."""
from __future__ import annotations

import os
from pathlib import Path

OLD = """fn resolve_footage(s: &Session, project: &mut Project, path: &str) -> Vec<String> {
    let stored: std::collections::HashMap<ItemId, String> =
        project.items.values().filter_map(|i| if let ItemKind::Footage(f) = &i.kind { Some((i.id, f.path.clone())) } else { None }).collect();
    let refused = crate::doc_path::resolve_footage(project, Some(path));
    let services = s.services.clone();
    let exists = |p: &String| p.is_empty() || services.exists(p);
    let mut missing: Vec<String> = refused.iter().map(|(_, p, _)| p.clone()).collect();
    for it in project.items.values() {
        if let ItemKind::Footage(f) = &it.kind {
            if refused.iter().any(|(id, _, _)| *id == it.id) {
                continue;
            }
            let present = if f.sequence.is_empty() { exists(&f.path) } else { f.sequence.iter().all(exists) };
            if !present {
                missing.push(stored.get(&it.id).cloned().unwrap_or_else(|| f.path.clone()));
            }
        }
    }
    missing
}"""

NEW = """// EFFECTCRAFT_ANDROID_NATIVE_PROJECT_PACKAGE_MEDIA_V1
fn resolve_footage(s: &Session, project: &mut Project, path: &str) -> Vec<String> {
    let stored: std::collections::HashMap<ItemId, String> =
        project.items.values().filter_map(|i| if let ItemKind::Footage(f) = &i.kind { Some((i.id, f.path.clone())) } else { None }).collect();
    let _refused = crate::doc_path::resolve_footage(project, Some(path));
    let services = s.services.clone();
    let exists = |p: &String| p.is_empty() || services.exists(p);
    let package_root = std::path::Path::new(path).parent()
        .map(|parent| parent.to_string_lossy().to_string()).unwrap_or_default();
    let mut missing = Vec::new();

    // Project ZIP extraction preserves the complete directory tree. Search that tree
    // recursively for missing media, including nested footage, audio and image-sequence
    // folders. The shared resolver accepts only unique case-insensitive filename matches.
    for (id, item) in project.items.iter_mut() {
        if let ItemKind::Footage(f) = &mut item.kind {
            if f.sequence.is_empty() {
                if !f.path.is_empty() && !exists(&f.path) {
                    if let Some(found) = super::am_nv::media_file(&package_root, &f.path) {
                        f.path = found;
                        f.missing = false;
                    } else {
                        f.missing = true;
                    }
                }
            } else {
                for frame in &mut f.sequence {
                    if !exists(frame) {
                        if let Some(found) = super::am_nv::media_file(&package_root, frame) {
                            *frame = found;
                        }
                    }
                }
                f.missing = !f.sequence.iter().all(exists);
            }
            let present = if f.sequence.is_empty() { exists(&f.path) } else { f.sequence.iter().all(exists) };
            if !present {
                missing.push(stored.get(id).cloned().unwrap_or_else(|| f.path.clone()));
            }
        }
    }
    missing
}"""

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    target = root / "crates/engine/src/cmd/import_project.rs"
    source = target.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_NATIVE_PROJECT_PACKAGE_MEDIA_V1" in source:
        print("Native project package media resolution already installed.")
        return
    if source.count(OLD) != 1:
        raise SystemExit("Could not locate the exact native project footage resolver.")
    source = source.replace(OLD, NEW, 1)
    target.write_text(source, encoding="utf-8")
    print("Native project import now searches extracted package folders for unique media matches.")

if __name__ == "__main__":
    main()
