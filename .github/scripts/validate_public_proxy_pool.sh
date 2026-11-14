#!/usr/bin/env bash
set -euo pipefail

BUILD_ASSETS_DIR="${BUILD_ASSETS_DIR:-$PWD}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/src"

cp "$BUILD_ASSETS_DIR/.github/native/public_proxy_pool.rs" "$TMP_DIR/src/lib.rs"
cat > "$TMP_DIR/src/public_proxy_bootstrap.txt" <<'EOF'
http://1.1.1.1:8080
socks5://8.8.8.8:1080
EOF

cat > "$TMP_DIR/Cargo.toml" <<'EOF'
[package]
name = "effectcraft-public-proxy-validation"
version = "0.1.0"
edition = "2021"

[dependencies]
serde_json = "1"
ureq = { version = "3.5", features = ["socks-proxy"] }
tungstenite = { version = "0.30", default-features = false, features = ["handshake", "rustls-tls-webpki-roots"] }
EOF

export CARGO_TARGET_DIR="${RUNNER_TEMP:-$TMP_DIR}/effectcraft-public-proxy-validation-target"
cargo test --manifest-path "$TMP_DIR/Cargo.toml"
