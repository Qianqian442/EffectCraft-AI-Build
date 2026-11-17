# AbsentMotion open-source AM integration

## Selected upstream source

- Project: [Comett1225/AbsentMotion](https://github.com/Comett1225/AbsentMotion)
- Release: `v5.1.1` (published 14 November 2026)
- Immutable source commit: `f350576485c42ff7aefa5c2f205b9f1b8ad873f7`
- License from 5.0 onward: GNU GPL-3.0; preserve the upstream `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, copyright attributions and corresponding source when redistributing modified binaries.
- This is an independent Android editor with its own Compose editing UI and C++/Skia rendering engine. It is not the proprietary Alight Motion application or its source code.

## Product naming rules

- Installed app / launcher / Android application label: **Ae**.
- The standard Ae editing layout continues to display **Ae**.
- Only while the user is inside the AM-derived editing layout, the in-app brand label is **Ae×am**.
- Returning to the standard Ae layout restores **Ae**. Do not globally rename upstream identifiers, package namespaces, file formats, copyright notices or license text.

## Account privacy and local data

- The main Ae client continues to download and store the hashed whitelist snapshot and the server-issued ban state in app-private local storage.
- The normal Ae/AM user interface must not show whitelist contents/counts, ban reasons/expiry details, or account-server host/IP/URL.
- Server-side ban and whitelist enforcement must remain active. Hiding the details is a presentation/privacy requirement, not a removal of account checks.
- The administrator-only app keeps the controls and data it needs to manage bans and whitelist membership; its server endpoint itself is not shown.

## Integration boundary

The AbsentMotion project is selected and source-audited, but it is **not yet integrated into the generated Ae APK**. The remaining engineering work is to:
1. bring the pinned source into the Android build as a separately namespaced library/activity, retaining its own Compose editor and native rendering engine;
2. launch that independent editor only when AM layout is selected, while keeping the launcher/app label as Ae;
3. carry the in-layout brand as Ae×am and return to Ae branding when switching back;
4. bridge the project/media data and save/export path between Ae and AM without silently flattening or dropping unsupported content;
5. build the Android 8–12 compatible native library and validate the combined single APK, including signing, native libraries, UI routing and project round trips.

No build or feature-parity claim is made until these steps and tests pass.
