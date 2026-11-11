#!/usr/bin/env python3
"""Expose selected Puppet pin Position properties as native Timeline keyframe rows.

Puppet pins are PropGroups whose animated Position is a normal nested Property.
The engine's generic keyframe commands already resolve nested property UIDs recursively,
so this patch makes selected pin Position tracks visible alongside ordinary tracks.
"""
from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    if not path.is_file():
        raise SystemExit(f"EffectCraft timeline source not found: {path}")
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_UNIFIED_PUPPET_POSITION_TRACKS_V1"
    if marker in source:
        print("Unified Puppet Position timeline rows already applied.")
        return

    anchor = """    rows
}

/// Rows of a twirled-open layer under the reveal shortcuts"""
    replacement = """    // EFFECTCRAFT_UNIFIED_PUPPET_POSITION_TRACKS_V1
    // Puppet selection stores the pin-group UID in selected_props. Resolve its animated
    // Position child and expose it as an ordinary property row, using the same RowKind::Prop,
    // KeyRef and generic timeline editing commands as Transform/Opacity/etc.
    for (layer_id, selected_uid) in &app.session.state.selected_props {
        let Some(layer) = comp.layer(*layer_id) else { continue };
        let Some(pin_group) = layer.props.find_group(*selected_uid) else { continue };
        let Some(position) = pin_group.get("position").filter(|prop| prop.is_animated()) else { continue };
        if !rows.iter().any(|row| row.layer == *layer_id && matches!(&row.kind, RowKind::Prop { uid } if *uid == position.uid)) {
            rows.push(Row {
                layer: *layer_id,
                depth: 2,
                kind: RowKind::Prop { uid: position.uid },
            });
        }
    }
    rows
}

/// Rows of a twirled-open layer under the reveal shortcuts"""
    if source.count(anchor) != 1:
        raise SystemExit(f"Expected one Timeline build_rows insertion point, found {source.count(anchor)}")
    source = source.replace(anchor, replacement, 1)
    path.write_text(source, encoding="utf-8")
    print("Selected Puppet pin Position properties now appear as native Timeline keyframe rows.")


if __name__ == "__main__":
    main()
