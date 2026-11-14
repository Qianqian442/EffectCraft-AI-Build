#!/usr/bin/env python3
"""Fetch a small build-time snapshot of public proxy candidates for first boot.

The APK revalidates every candidate against the exact Cloudflare Worker /health
endpoint before using it. This file is only a bootstrap list, never a trust list.
"""
from __future__ import annotations

import argparse
import ipaddress
import urllib.request
from pathlib import Path

FEEDS = [
    # Maintained feed with typed entries (http:// / socks5:// prefixes).
    ("https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/cn.txt", "http"),
    ("https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/hk.txt", "http"),
    ("https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/jp.txt", "http"),
    ("https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/sg.txt", "http"),
    ("https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/https.txt", "http"),
    ("https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/socks5.txt", "socks5"),
    # Second independent maintained source: unprefixed endpoints, typed by file.
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/http.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/https.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/hk/http.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/hk/https.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/hk/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/jp/http.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/jp/https.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/jp/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/sg/http.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/sg/https.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/sg/socks5.txt", "socks5"),
    # Additional general pools as fallback.
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/https.txt", "http"),
    ("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks5.txt", "socks5"),
]
MAX_BODY = 1_000_000
MAX_ENTRIES = 600


def valid_endpoint(line: str, default_protocol: str) -> str | None:
    value = line.strip()
    if not value or value.startswith("#") or len(value) > 160:
        return None
    if "://" not in value:
        value = default_protocol + "://" + value
    scheme, endpoint = value.split("://", 1)
    scheme = scheme.lower()
    if scheme not in {"http", "socks5", "socks5h"}:
        return None
    if any(ch in endpoint for ch in "@/?# "):
        return None
    host, sep, port_text = endpoint.rpartition(":")
    if not sep or not host or not port_text.isdigit():
        return None
    try:
        ip = ipaddress.ip_address(host)
        port = int(port_text)
    except ValueError:
        return None
    if ip.version != 4 or not ip.is_global or not (1 <= port <= 65535):
        return None
    return f"{'socks5' if scheme == 'socks5h' else scheme}://{ip}:{port}"


def download(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EffectCraft-ProxyBootstrap/1.0"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            return ""
        data = response.read(MAX_BODY + 1)
    if len(data) > MAX_BODY:
        return ""
    return data.decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result: list[str] = []
    seen: set[str] = set()
    for url, default_protocol in FEEDS:
        try:
            content = download(url)
        except Exception as error:
            print(f"Feed unavailable: {url} ({type(error).__name__})")
            continue
        for line in content.splitlines():
            candidate = valid_endpoint(line, default_protocol)
            if candidate and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
            if len(result) >= MAX_ENTRIES:
                break
        if len(result) >= MAX_ENTRIES:
            break

    if not result:
        raise SystemExit("No valid public proxy candidates could be downloaded; refusing to build a proxy-enabled APK with an empty bootstrap pool.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(result) + "\n", encoding="utf-8")
    print(f"Saved {len(result)} public proxy bootstrap candidates to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
