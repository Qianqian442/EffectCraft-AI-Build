# Account service and distributed phone-compute scope

Status: implementation scope clarification. This document does not claim that distributed phone rendering is already implemented.

## Account and administrator functions

Keep the existing HTTPS Cloudflare Worker account service for functions that need shared state and administrator authority:
1. Registration, login, and account verification.
2. Account profile lookup and shared account state.
3. Administrator ban/unban, mandatory ban reason, and expiry.
4. Live ban/unban notifications and re-verification before enabling the editor.
5. Administrator-controlled global node-network enable/disable and node presence.

The main APK must not display the global network switch. The separate admin APK owns that control and must not act as a worker node.

The Worker URL is supplied through the GitHub repository variable `AE_ACCOUNT_API_URL`. It must be an HTTPS `.workers.dev` URL. Both APK workflows must use the same configured endpoint. Builds must fail clearly if the variable is missing; no fake URL, home-Wi-Fi fallback, or UI-only account stub is acceptable.

## Local EffectCraft functions

These functions remain in the main APK and must not depend on the account server for their actual processing:
- Existing editor and timeline functions.
- AI frame interpolation (RIFE).
- AI quality enhancement (Real-ESRGAN).
- Project import/export and supported preset ZIP import.
- WASM plug-ins and supported desktop-AE plug-in inspection/migration.
- Export to the phone gallery.

The optional DeepSeek model/plugin remains separate and is not bundled into the main APK. Do not remove existing functions to force a build.

## Distributed phone compute (separate from account server)

The long-term goal is to let consenting main-APK devices contribute spare compute to independent EffectCraft tasks. The account Worker is not a video-rendering server and must not receive users' video frames or model weights as a substitute for local processing.

Before enabling distributed work, implement and test:
1. Explicit opt-in worker participation, visible status, and user pause/stop controls.
2. Capability negotiation (CPU/GPU, memory, codec support, thermal state, battery, and network).
3. Task scheduler, bounded work leases, chunking, and retries.
4. Correct frame overlap/context for temporal algorithms such as RIFE.
5. Result integrity checks and deterministic merge on the initiating device.
6. Privacy-preserving transport and authenticated peer sessions.
7. Resource limits, charging/Wi-Fi preferences, and pause-on-overheat/low-battery behavior.
8. Cross-network transport tests. Direct P2P is not guaranteed on every carrier NAT; any relay/bootstrap dependency must be disclosed.

Do not silently consume another user's phone resources. A device is a worker only after its owner has opted in. A few hundred phones also cannot be joined as a full mesh; use a bounded overlay/task topology.

## Acceptance gates

- Both APKs use the same configured HTTPS account endpoint.
- Registration/login and editor access checks work against the deployed Worker.
- Admin ban/unban and reason/expiry persist and notify online clients; offline clients re-check on next connection.
- Global node switch is visible only in the admin APK.
- Admin APK does not advertise itself as a worker node.
- Main APK retains RIFE, Real-ESRGAN, editor, project import/export, plug-ins, and export.
- APK signature, manifest, ABI, alignment, and package-integrity checks pass.
- Distributed compute is not marked complete until multi-device task execution, result verification, failure recovery, and network tests pass.
