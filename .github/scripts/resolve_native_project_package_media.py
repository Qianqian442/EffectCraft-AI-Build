#!/usr/bin/env python3
"""Resolve project footage against the complete extracted package root before reporting missing media."""
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

NEW = """// EFFECTCRAFT_ANDROID_NATIVE_PROJECT_PACKAGE_MEDIA_V2
fn package_media_root(path: &str, requested: Option<&str>) -> String {
    requested.filter(|value| !value.trim().is_empty()).map(str::to_string)
        .unwrap_or_else(|| std::path::Path::new(path).parent()
            .map(|parent| parent.to_string_lossy().to_string()).unwrap_or_default())
}

fn resolve_footage(s: &Session, project: &mut Project, path: &str, requested_root: Option<&str>) -> Vec<String> {
    let stored: std::collections::HashMap<ItemId, String> =
        project.items.values().filter_map(|i| if let ItemKind::Footage(f) = &i.kind { Some((i.id, f.path.clone())) } else { None }).collect();
    let _refused = crate::doc_path::resolve_footage(project, Some(path));
    let services = s.services.clone();
    let exists = |p: &String| p.is_empty() || services.exists(p);
    // A project file can be nested under /project or /draft while its media lives
    // in /Media at the archive root. Never assume these two directories are identical.
    let package_root = package_media_root(path, requested_root);
    let mut missing = Vec::new();

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
    if "EFFECTCRAFT_ANDROID_NATIVE_PROJECT_PACKAGE_MEDIA_V2" not in source:
        if source.count(OLD) != 1:
            raise SystemExit("Could not locate the exact native project footage resolver.")
        source = source.replace(OLD, NEW, 1)

    call_old = "    let missing = resolve_footage(s, &mut sub, &path);"
    call_new = """    let package_root = str_p(p, "packageRoot");
    let missing = resolve_footage(s, &mut sub, &path, package_root);"""
    if call_new not in source:
        if source.count(call_old) != 1:
            raise SystemExit("Could not locate the unified native-project media resolver call.")
        source = source.replace(call_old, call_new, 1)

    tests = """
#[cfg(test)]
mod package_media_root_tests {
    use super::package_media_root;

    #[test]
    fn nested_project_uses_the_archive_root_for_media_recovery() {
        let root = package_media_root(
            "/app/Imported-Projects/demo/project/Main.ecproj",
            Some("/app/Imported-Projects/demo"),
        );
        assert_eq!(root, "/app/Imported-Projects/demo");
    }

    #[test]
    fn standalone_project_defaults_to_its_parent_folder() {
        let root = package_media_root("/storage/ae/Main.ecproj", None);
        assert_eq!(root, "/storage/ae");
    }
}
"""
    if "mod package_media_root_tests" not in source:
        source = source.rstrip() + "\n\n" + tests
    target.write_text(source, encoding="utf-8")
    print("Native project imports now search the explicit archive root, including assets outside nested project folders.")

if __name__ == "__main__":
    main()
