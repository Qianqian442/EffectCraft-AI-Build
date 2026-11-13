#!/usr/bin/env python3
"""Use a phone-first expanded composition workspace on first launch."""
from __future__ import annotations

from pathlib import Path
import os


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")

    state_path = root / "crates/ui-egui/src/state.rs"
    state = state_path.read_text(encoding="utf-8")
    state = replace_once(
        state,
        '            workspace: "Default".into(),\n            dock: crate::dock::Workspace::new(crate::dock::workspace("Default")),',
        '            // EFFECTCRAFT_ANDROID_DEFAULT_PHONE_WORKSPACE_V1\n'
        '            // Put Composition first and keep secondary panels as tabs on phone screens.\n'
        '            workspace: "Small Screen".into(),\n'
        '            dock: crate::dock::Workspace::new(crate::dock::workspace("Small Screen")),',
        "Phone-first default workspace",
    )
    state_path.write_text(state, encoding="utf-8")

    dock_path = root / "crates/ui-egui/src/dock.rs"
    dock = dock_path.read_text(encoding="utf-8")
    dock = replace_once(
        dock,
        '        "Small Screen" => vsplit(\n            Ratio(0.55),',
        '        "Small Screen" => vsplit(\n            // Reserve more height for the composition preview by default.\n'
        '            Ratio(0.62),',
        "Expanded phone composition area",
    )
    dock_path.write_text(dock, encoding="utf-8")

    if 'workspace: "Small Screen".into()' not in state:
        raise SystemExit("Phone-first default workspace verification failed")
    if '"Small Screen" => vsplit(\n            // Reserve more height for the composition preview by default.\n            Ratio(0.62),' not in dock:
        raise SystemExit("Expanded phone composition area verification failed")

    print("Applied EFFECTCRAFT_ANDROID_DEFAULT_PHONE_WORKSPACE_V1: full-width Composition tabs and a 62% upper preview area.")


if __name__ == "__main__":
    main()
