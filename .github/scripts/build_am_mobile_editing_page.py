#!/usr/bin/env python3
"""Retired: AM mode now uses the original Ae editor panels and timeline.

The former generated am_editor page replaced the native timeline and dropped
keyframe, graph, puppet, vector and touch-trim interactions. Keep this script as
a harmless compatibility entry for older workflows; it intentionally creates
no editor surface and changes no EffectCraft source files.
"""
def main() -> None:
    print("Retired AM clip-editor page; native Ae panels, timeline and tools remain active.")

if __name__ == "__main__":
    main()
