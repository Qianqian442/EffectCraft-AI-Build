#!/usr/bin/env python3
"""Guard CLVK's optional VK_KHR_shader_fma integration for older Android NDK headers."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("clvk_source", type=Path)
    root = parser.parse_args().clvk_source

    replace_once(
        root / "src/device.hpp",
        "    VkPhysicalDeviceShaderFmaFeaturesKHR m_features_shader_fma{};",
        """#ifdef VK_KHR_SHADER_FMA_EXTENSION_NAME
        VkPhysicalDeviceShaderFmaFeaturesKHR m_features_shader_fma{};
#endif""",
        "device.hpp shader-FMA feature field",
    )
    replace_once(
        root / "src/device.cpp",
        """    m_features_shader_fma.sType =
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_FMA_FEATURES_KHR;""",
        """#ifdef VK_KHR_SHADER_FMA_EXTENSION_NAME
    m_features_shader_fma.sType =
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_FMA_FEATURES_KHR;
#endif""",
        "device.cpp shader-FMA sType",
    )
    replace_once(
        root / "src/device.cpp",
        """            VER_EXT_FEAT(0, VK_KHR_SHADER_FMA_EXTENSION_NAME,
                         m_features_shader_fma),""",
        """#ifdef VK_KHR_SHADER_FMA_EXTENSION_NAME
            VER_EXT_FEAT(0, VK_KHR_SHADER_FMA_EXTENSION_NAME,
                         m_features_shader_fma),
#endif""",
        "device.cpp shader-FMA feature chain",
    )
    print("Patched CLVK: VK_KHR_shader_fma is enabled when the Vulkan headers expose it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
