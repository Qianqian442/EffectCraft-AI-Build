#!/usr/bin/env python3
"""Keep account security data locally while suppressing ban/whitelist/server details in the Ae client UI."""
from __future__ import annotations

import os
import re
from pathlib import Path


MARKER = "EFFECTCRAFT_ACCOUNT_SECURITY_DETAIL_DISPLAY_SUPPRESSED_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source and old not in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/account.rs"
    if not path.is_file():
        raise SystemExit(f"Missing generated account UI: {path}")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Account ban/whitelist details are already hidden from the Ae client UI.")
        return

    # Keep the downloaded, hashed whitelist and persisted ban details intact, but
    # never expose their values, counts, dates, reasons, or whitelist membership.
    source = replace_once(
        source,
        '''            if app.account.whitelist_ready {
                ui.label(format!(
                    "本机白名单已下载：QQ {} 条，微信 {} 条",
                    app.account.whitelist.qq_hashes.len(),
                    app.account.whitelist.wechat_hashes.len()
                ));
            } else {
                ui.label("正在下载白名单；下载完成前不能注册或登录。");
            }
''',
        "",
        "remove visible local-whitelist summary",
    )

    source = replace_once(
        source,
        '''                ui.label(&app.account.ban_reason);
                ui.add_space(8.0);
                ui.label(app.account.ban_countdown_label());
                ui.add_space(12.0);
                if ui.button("联网核验是否已解封").clicked() {
                    app.account.retry(config);
                }
''',
        '''                ui.label("账号当前无法通过验证，请稍后重试。");
                ui.add_space(18.0);
''',
        "replace visible ban reason and expiry with generic status",
    )
    source = replace_once(
        source,
        'Mode::Banned => centered_window(ctx, "账号已被封禁"',
        'Mode::Banned => centered_window(ctx, "暂不可用"',
        "hide ban-specific window title",
    )
    source = replace_once(
        source,
        'ui.heading("账号已被封禁");',
        'ui.heading("暂时无法进入");',
        "hide ban-specific heading",
    )

    replacements = {
        "本机白名单尚未下载，请连接网络后重试。": "账号验证暂不可用，请稍后重试。",
        "该 QQ号不在本机白名单中，不能登录。": "账号验证未通过，请检查账号信息后重试。",
        "该微信号不在本机白名单中，不能登录。": "账号验证未通过，请检查账号信息后重试。",
        "填写的 QQ号或微信号不在本机白名单中，不能注册。": "账号验证未通过，请检查账号信息后重试。",
        "白名单更新失败，当前使用上次下载的本地白名单。": "账号验证暂不可用，请稍后重试。",
        "服务器返回的白名单版本信息不完整。": "账号验证数据暂不可用，请稍后重试。",
        "服务器连接地址已隐藏，系统会自动选择连接线路": "正在安全验证账号，请稍后重试。",
        "服务器地址已隐藏": "网络连接失败，请稍后重试。",
    }
    for old, new in replacements.items():
        if old in source:
            source = source.replace(old, new)

    # API-side ban and whitelist denials are deliberately indistinguishable in
    # the ordinary client. The server remains authoritative and still rejects them.
    source = replace_once(
        source,
        'self.status = format!("{detail}（HTTP {}）", response.status);',
        '''self.status = if response.status == 403 || response.status == 423 {
                    "账号验证未通过，请稍后重试。".to_string()
                } else {
                    format!("{detail}（HTTP {}）", response.status)
                };''',
        "mask server ban/whitelist denial details",
    )

    # The detailed countdown is no longer rendered; remove its helper and import
    # so the Rust module stays warning-clean. The actual ban fields remain persisted.
    source = source.replace("use chrono::DateTime;\n", "")
    source, removed = re.subn(
        r"\n    fn ban_countdown_label\(&self\) -> String \{.*?\n    \}\n",
        "\n",
        source,
        count=1,
        flags=re.S,
    )
    if removed not in (0, 1):
        raise SystemExit("Unexpected number of ban countdown helpers.")

    source = source.replace('ui.label("云端账号服务地址");', 'ui.label("账号服务已自动配置");')
    source = source.replace(
        'ui.small("此地址由构建配置自动设置，主 APK 直接通过 HTTPS 连接 Cloudflare 账号服务器。");',
        'ui.small("正在安全连接账号服务。");',
    )

    # Never render the configured server endpoint or an endpoint-derived error.
    # The address remains private configuration used by the transport layer.
    if "fn safe_account_status(" in source:
        source = source.replace("服务器地址已隐藏", "网络连接失败，请稍后重试。")
    source = "// " + MARKER + "\n" + source

    show_at = source.find("pub(crate) fn show(")
    if show_at < 0:
        raise SystemExit("Account UI entry point was not found.")
    ui_source = source[show_at:]
    forbidden = (
        "app.account.server_url",
        "app.account.banned_until",
        "app.account.ban_reason",
        "app.account.whitelist.qq_hashes",
        "app.account.whitelist.wechat_hashes",
        "账号已被封禁",
        "封禁截止时间",
        "封禁原因",
        "白名单已下载",
        "服务器地址",
        "云端账号服务地址",
        "此地址由构建配置自动设置",
    )
    found = [item for item in forbidden if item in ui_source]
    if found:
        raise SystemExit("Sensitive account/server details still appear in the client UI: " + ", ".join(found))

    path.write_text(source, encoding="utf-8")
    print("Downloaded whitelist hashes and ban state remain in app-private local storage.")
    print("Ordinary Ae UI no longer displays ban dates/reasons, whitelist status/counts, or server addresses.")
    print("Server-side ban and whitelist enforcement is unchanged.")


if __name__ == "__main__":
    main()
