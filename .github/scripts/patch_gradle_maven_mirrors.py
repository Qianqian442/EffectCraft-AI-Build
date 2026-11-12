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
    if "maven.aliyun.com/repository/public" in source and "mirrors.cloud.tencent.com" in source:
        print(f"Maven fallback mirrors already configured in {path}")
        return

    # The generator embeds these blocks in a Python f-string; doubled braces
    # are intentional and become normal Gradle braces in settings.gradle.
    if source.count(PLUGIN_OLD) != 1:
        raise SystemExit("Expected exactly one pluginManagement repository block in android_project.py")
    if source.count(DEPENDENCY_OLD) != 1:
        raise SystemExit("Expected exactly one dependencyResolutionManagement repository block in android_project.py")

    source = source.replace(PLUGIN_OLD, PLUGIN_NEW, 1)
    source = source.replace(DEPENDENCY_OLD, DEPENDENCY_NEW, 1)
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
