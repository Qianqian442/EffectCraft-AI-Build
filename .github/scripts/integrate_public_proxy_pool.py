#!/usr/bin/env python3
"""Install the dynamic public HTTPS CONNECT/SOCKS5 pool in the Cloudflare account client."""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit


MARKER = "EFFECTCRAFT_PUBLIC_PROXY_POOL_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    assets = Path(os.environ.get("BUILD_ASSETS_DIR", Path(__file__).resolve().parents[2])).resolve()
    api_url = os.environ.get("AE_ACCOUNT_API_URL", "").strip().rstrip("/")
    if not api_url.startswith("https://") or not (api_url.endswith(".workers.dev") or api_url.endswith(".pages.dev")):
        raise SystemExit("AE_ACCOUNT_API_URL must be a verified HTTPS Cloudflare workers.dev or pages.dev URL")

    # Optional additional Cloudflare account hosts: newline/comma/semicolon separated.
    # Runtime health/TLS checks still decide whether each endpoint is actually usable.
    extra_fallbacks: list[str] = []
    for raw in re.split(r"[\r\n,;]+", os.environ.get("AE_ACCOUNT_API_FALLBACK_URLS", "")):
        candidate = raw.strip().rstrip("/")
        if not candidate:
            continue
        parts = urlsplit(candidate)
        host = (parts.hostname or "").lower()
        if (
            parts.scheme != "https"
            or not host.endswith((".workers.dev", ".pages.dev"))
            or parts.netloc.lower() != host
            or parts.username is not None
            or parts.password is not None
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise SystemExit("Each AE_ACCOUNT_API_FALLBACK_URLS entry must be an HTTPS Cloudflare workers.dev/pages.dev host with no path, port or credentials.")
        if candidate != api_url and candidate != "https://ae-account-api-gateway-alt.pages.dev" and candidate not in extra_fallbacks:
            extra_fallbacks.append(candidate)
        if len(extra_fallbacks) > 5:
            raise SystemExit("A maximum of five additional Cloudflare HTTPS fallback hosts is supported.")

    account_path = root / "crates/ui-egui/src/account.rs"
    lib_path = root / "crates/ui-egui/src/lib.rs"
    module_source = assets / ".github/native/public_proxy_pool.rs"
    bootstrap_source = Path(os.environ.get("PUBLIC_PROXY_BOOTSTRAP_FILE", "")).resolve()
    if not account_path.is_file() or not lib_path.is_file() or not module_source.is_file():
        raise SystemExit("Missing generated account.rs, ui-egui/lib.rs, or public_proxy_pool.rs")
    if not bootstrap_source.is_file() or bootstrap_source.stat().st_size == 0:
        raise SystemExit("Missing non-empty build-time public proxy bootstrap snapshot")

    account = account_path.read_text(encoding="utf-8")
    lib = lib_path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_CLOUDFLARE_ACCOUNT_GATE_V1" not in account:
        raise SystemExit("Cloudflare account conversion must run before public proxy integration")
    if MARKER in account and "mod public_proxy_pool;" in lib:
        print("Public proxy pool is already integrated.")
        return

    http_pattern = re.compile(
        r"fn http_request\(url: &str, method: &str, path: &str, body: Value, token: Option<&str>\) -> Result<HttpResult, String> \{.*?\n\}\n\n(?=fn blocking_overlay)",
        re.S,
    )
    wrapper = """fn http_request(url: &str, method: &str, path: &str, body: Value, token: Option<&str>) -> Result<HttpResult, String> {
    let (status, body) = crate::public_proxy_pool::account_http_request(
        url, method, path, body, token
    )?;
    Ok(HttpResult { status, body })
}

"""
    account, replaced = http_pattern.subn(wrapper, account, count=1)
    if replaced != 1:
        raise SystemExit(f"Cloudflare account HTTP request replacement expected once, found {replaced}")

    websocket_calls = account.count("tungstenite::connect(request)")
    if websocket_calls != 2:
        raise SystemExit(f"Expected two authenticated WSS connections, found {websocket_calls}")
    account = account.replace(
        "tungstenite::connect(request)",
        "crate::public_proxy_pool::connect_websocket(request)",
    )
    account = account.replace(
        "//! EFFECTCRAFT_CLOUDFLARE_ACCOUNT_GATE_V1",
        f"//! EFFECTCRAFT_CLOUDFLARE_ACCOUNT_GATE_V1\n//! {MARKER}",
        1,
    )

    module_declaration = "mod account;\n"
    module_new = "mod account;\nmod public_proxy_pool;\n"
    lib = replace_once(lib, module_declaration, module_new, "public proxy module declaration")

    destination = root / "crates/ui-egui/src/public_proxy_pool.rs"
    bootstrap_destination = root / "crates/ui-egui/src/public_proxy_bootstrap.txt"
    module_text = module_source.read_text(encoding="utf-8")
    begin = "    // AE_EXTRA_FALLBACK_BASE_URLS_BEGIN\n"
    end = "    // AE_EXTRA_FALLBACK_BASE_URLS_END"
    if module_text.count(begin) != 1 or module_text.count(end) != 1:
        raise SystemExit("Public proxy module is missing the configured HTTPS fallback insertion markers.")
    insertion = "".join(f'    "{url}",\n' for url in extra_fallbacks)
    module_text = module_text.replace(begin, begin + insertion, 1)
    if any(f'    "{url}",' not in module_text for url in extra_fallbacks):
        raise SystemExit("One or more configured HTTPS fallbacks were not embedded.")
    destination.write_text(module_text, encoding="utf-8")
    bootstrap_destination.write_text(bootstrap_source.read_text(encoding="utf-8"), encoding="utf-8")
    account_path.write_text(account, encoding="utf-8")
    lib_path.write_text(lib, encoding="utf-8")

    workspace = (root / "Cargo.toml").read_text(encoding="utf-8")
    ui = (root / "crates/ui-egui/Cargo.toml").read_text(encoding="utf-8")
    if 'ureq = { version = "3.5", features = ["socks-proxy"] }' not in workspace:
        raise SystemExit("Workspace ureq dependency must enable the socks-proxy feature")
    if 'ureq = { workspace = true }' not in ui:
        raise SystemExit("UI crate must depend on workspace ureq")
    if 'tungstenite = { workspace = true }' not in ui:
        raise SystemExit("UI crate must depend on workspace tungstenite")
    if "rustls-tls-webpki-roots" not in workspace:
        raise SystemExit("WSS TLS validation must use the WebPKI root certificates")
    if bootstrap_destination.stat().st_size == 0:
        raise SystemExit("Public proxy bootstrap snapshot is empty")
    print(f"Integrated the primary HTTPS endpoint, one built-in alternate, and {len(extra_fallbacks)} configured Cloudflare HTTPS fallbacks.")
    print("Each account endpoint must pass runtime HTTPS/TLS and /health database checks before use.")
    print("Direct HTTPS remains preferred; TLS verification stays enabled and account POST requests are never blindly replayed.")


if __name__ == "__main__":
    main()
