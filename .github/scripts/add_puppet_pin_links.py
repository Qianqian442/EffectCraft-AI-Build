#!/usr/bin/env python3
"""Draw an independent connected control-point rig for each Puppet mesh."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_PUPPET_CONNECTED_PINS_V1"


def patch(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/puppet_tool.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    anchor = "    for (_, mesh, def, pins) in ov.iter() {\n        if show_mesh {\n"
    replacement = r'''    for (_, mesh, def, pins) in ov.iter() {
        // EFFECTCRAFT_ANDROID_PUPPET_CONNECTED_PINS_V1
        // Build a small nearest-neighbour spanning rig from this mesh's own pins.
        // The scope is deliberately per mesh (and draw() is per layer), so lines
        // never connect control points belonging to different layers.
        let rig_nodes: Vec<Pos2> = pins.iter().map(|pin| scr(pin_position(mesh, def, pin))).collect();
        if rig_nodes.len() > 1 {
            let mut linked = vec![false; rig_nodes.len()];
            linked[0] = true;
            for _ in 1..rig_nodes.len() {
                let mut best_distance = f32::INFINITY;
                let mut best_edge: Option<(usize, usize)> = None;
                for from in 0..rig_nodes.len() {
                    if !linked[from] {
                        continue;
                    }
                    for to in 0..rig_nodes.len() {
                        if linked[to] {
                            continue;
                        }
                        let distance = rig_nodes[from].distance(rig_nodes[to]);
                        if distance < best_distance {
                            best_distance = distance;
                            best_edge = Some((from, to));
                        }
                    }
                }
                if let Some((from, to)) = best_edge {
                    painter.line_segment(
                        [rig_nodes[from], rig_nodes[to]],
                        Stroke::new(1.35, Color32::from_rgba_unmultiplied(0x55, 0xc6, 0xe8, 190)),
                    );
                    linked[to] = true;
                } else {
                    break;
                }
            }
        }
        if show_mesh {
'''
    count = source.count(anchor)
    if count != 1:
        raise SystemExit(f"Puppet connected rig: expected one draw-loop anchor, found {count}")
    source = source.replace(anchor, replacement, 1)
    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    patch(Path(os.environ.get("EFFECTCRAFT_DIR", "vendor/effectcraft")))
