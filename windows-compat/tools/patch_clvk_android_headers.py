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

    # Android NDK r26b headers predate VK_KHR_shader_fma. Provide the
    # extension's official ABI declaration when the SDK header has no definition.
    header = root / "src/device.hpp"
    source = header.read_text(encoding="utf-8")
    vulkan_include = "#include <vulkan/vulkan.h>"
    fallback = """#ifndef VK_KHR_SHADER_FMA_EXTENSION_NAME
#define VK_KHR_SHADER_FMA_EXTENSION_NAME "VK_KHR_shader_fma"
#define VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_FMA_FEATURES_KHR ((VkStructureType)1000579000)
typedef struct VkPhysicalDeviceShaderFmaFeaturesKHR {
    VkStructureType sType;
    void *pNext;
    VkBool32 shaderFmaFloat16;
    VkBool32 shaderFmaFloat32;
    VkBool32 shaderFmaFloat64;
} VkPhysicalDeviceShaderFmaFeaturesKHR;
#endif
"""
    if fallback not in source:
        if source.count(vulkan_include) != 1:
            raise SystemExit("device.hpp: expected one Vulkan header include")
        source = source.replace(vulkan_include, vulkan_include + "\n\n" + fallback, 1)
        header.write_text(source, encoding="utf-8")

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
