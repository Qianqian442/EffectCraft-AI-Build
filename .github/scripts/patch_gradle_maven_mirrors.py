#!/usr/bin/env python3
"""Add resilient fallback Maven mirrors to the Android builder's generated settings."""
from __future__ import annotations

import argparse
from pathlib import Path

PLUGIN_OLD = """pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}"""
PLUGIN_NEW = """pluginManagement {{
    repositories {{
        // Fallback mirrors for transient upstream repository routing failures.
        maven {{ url = uri("https://maven.aliyun.com/repository/google") }}
        maven {{ url = uri("https://maven.aliyun.com/repository/public") }}
        maven {{ url = uri("https://maven.aliyun.com/repository/gradle-plugin") }}
        maven {{ url = uri("https://mirrors.cloud.tencent.com/nexus/repository/maven-public/") }}
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}"""

DEPENDENCY_OLD = """dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        google()
        mavenCentral()
    }}
}}"""
DEPENDENCY_NEW = """dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        maven {{ url = uri("https://maven.aliyun.com/repository/google") }}
        maven {{ url = uri("https://maven.aliyun.com/repository/public") }}
        maven {{ url = uri("https://mirrors.cloud.tencent.com/nexus/repository/maven-public/") }}
        google()
        mavenCentral()
    }}
}}"""


def patch(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"Android builder settings generator not found: {path}")
    source = path.read_text(encoding="utf-8")
    if "maven.aliyun.com/repository/public" not in source or "mirrors.cloud.tencent.com" not in source:
        # The generator embeds these blocks in a Python f-string; doubled braces
        # are intentional and become normal Gradle braces in settings.gradle.
        if source.count(PLUGIN_OLD) != 1:
            raise SystemExit("Expected exactly one pluginManagement repository block in android_project.py")
        if source.count(DEPENDENCY_OLD) != 1:
            raise SystemExit("Expected exactly one dependencyResolutionManagement repository block in android_project.py")
        source = source.replace(PLUGIN_OLD, PLUGIN_NEW, 1)
        source = source.replace(DEPENDENCY_OLD, DEPENDENCY_NEW, 1)

    # The upstream builder derives the same versionCode for every rebuild of
    # v0.21.1. Add one so Android accepts this APK as an in-place update over
    # the already-installed v0.21.1 app, without changing the package ID.
    version_old = "return (1 << 24) | (major << 16) | (minor << 8) | patch"
    version_new = "return ((1 << 24) | (major << 16) | (minor << 8) | patch) + 1"
    if version_old in source:
        source = source.replace(version_old, version_new, 1)
    elif version_new not in source:
        raise SystemExit("Could not safely bump the Android versionCode for an in-place update.")
    compile(source, str(path), "exec")
    if "maven.aliyun.com/repository/google" not in source:
        raise SystemExit("Plugin repository fallback verification failed")
    if "maven.aliyun.com/repository/public" not in source:
        raise SystemExit("Dependency repository fallback verification failed")
    path.write_text(source, encoding="utf-8")
    print(f"Added Aliyun and Tencent Maven fallback repositories to {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generator", required=True, type=Path)
    args = parser.parse_args()
    patch(args.generator)


if __name__ == "__main__":
    main()
