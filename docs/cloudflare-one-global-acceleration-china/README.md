# EffectCraft: Cloudflare One Global Acceleration (Mainland China)

## Current decision

The mainland-China target is **Cloudflare One Client Global Acceleration**, not ordinary public WARP and not the existing EffectCraft SOCKS/tun2socks transport.

Cloudflare documents Global Acceleration as a partner-delivered connectivity offering for Cloudflare One Client use in Mainland China. Cloudflare lists China Mobile International (CMI), CBC Tech, and JD Cloud as partners. Deployment requires Cloudflare One Client entitlement, an account-team/partner contract, and partner deployment. This repository cannot enable the entitlement or provision the China-side access endpoints by itself.

Official reference:
- https://developers.cloudflare.com/china-network/concepts/global-acceleration/
- https://developers.cloudflare.com/cloudflare-one/team-and-resources/devices/cloudflare-one-client/deployment/mdm-deployment/
- https://developers.cloudflare.com/cloudflare-one/team-and-resources/devices/cloudflare-one-client/deployment/mdm-deployment/parameters/

## Android integration boundary

Cloudflare's supported Android delivery path is the separate **Cloudflare One Agent** app (package `com.cloudflare.cloudflareoneagent`) with Android Enterprise / MDM managed configuration. The MDM configuration can assign per-app VPN routing to EffectCraft's packages:

- Main app: `com.artcraft.effectcraft`
- Admin app: `com.qianqian.effectcraftadmin`

The `android-managed-configuration.template.json` file in this folder is a template only. Replace the organization/team name and configure it through an MDM tool that supports Android Enterprise managed configurations. It is not an importable profile for an unmanaged personal phone.

The public Cloudflare documentation does **not** provide a supported third-party Android API for EffectCraft to silently start and stop the separate Cloudflare One Agent's VPN service. Android also permits only one active VPN service at a time. Therefore, this repository must not claim that EffectCraft has embedded WARP or can task-start/task-stop the Agent automatically.

## Runtime behavior policy

1. Prefer Cloudflare One Client Global Acceleration when the organization has enabled it and the Android Agent is enrolled.
2. Route only the two EffectCraft packages through the Agent using the MDM per-app VPN list.
3. If the Agent is missing, unenrolled, or disconnected, show an explicit diagnostic instead of labeling the existing local SOCKS tunnel as WARP.
4. Keep the existing EffectCraft task-scoped VPN / P2P route as a clearly identified fallback only; it is a separate transport, not Cloudflare WARP.
5. Do not silently switch to an unverified public proxy when the user has requested the Cloudflare VPN path.

## Mainland-China validation checklist

Validate on mainland China networks before marking the feature available:
- China Mobile, China Unicom, and China Telecom.
- Domestic Wi-Fi and mobile data.
- OPPO Android 12 (the current target device); Huawei devices as a separate compatibility pass.
- Cloudflare One Agent enrollment, tunnel establishment, reconnect after network changes, DNS, HTTPS account calls, and task completion.
- Confirm the actual Cloudflare One Client endpoint/tunnel status; an HTTP 200 from the Worker alone is not proof that WARP was used.

## Android support caveat

Cloudflare's support lifecycle page says Android 9-12 are not officially supported, although the Agent is expected to generally work on Android 9 or later. OPPO Android 12 must therefore be tested as a compatibility target, not assumed to be officially supported.

## What is still required outside this repository

- A Cloudflare account with Cloudflare One Client entitlement.
- A Global Acceleration agreement arranged through Cloudflare or a listed local partner.
- The organization/team name and enrollment method.
- An Android Enterprise / MDM channel for deploying Cloudflare One Agent and its managed per-app VPN configuration.
- Real mainland-China network tests.

No credentials, registration tokens, organization identifiers, or private keys belong in this repository.
