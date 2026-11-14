# EffectCraft task-scoped Cloudflare MASQUE engine (prototype)

This is a Go Mobile bridge around the MIT-licensed
[Diniboy1123/usque](https://github.com/Diniboy1123/usque) MASQUE / Connect-IP
engine. It fetches upstream source at pinned commit
`6aa03fc97d12848dce34eedbd187fb1077b5d1ea`; it does not copy the Android
wrapper project or use its unlicensed binary AAR.

## Intended Android flow

1. Android obtains user consent for its own `VpnService` and calls
   `Builder.establish()`.
2. The VPN builder adds only the Cloudflare Worker account API IPv4 destinations
   as /32 routes; it does not install a default route.
3. The detached TUN descriptor is passed to `warpandroid.StartTunnel`.
4. The Go engine establishes MASQUE / Connect-IP using the device private key
   and Cloudflare endpoint public-key pin.
5. Only routed Worker HTTPS and WebSocket requests enter this tunnel. The
   MASQUE endpoint is deliberately outside the /32 routes, avoiding recursion.
6. After the account task, call `warpandroid.StopTunnel` to cancel the tunnel
   and close the detached TUN descriptor.

The Android VPN must route only the two EffectCraft packages. A Worker HTTPS
200 response alone is not proof of WARP: check that MASQUE status reached
`connected` before sending the account request.

## Required Cloudflare configuration

The engine needs a valid MASQUE device config with client private key, assigned
tunnel IP and pinned endpoint public key, plus the actual MASQUE endpoint
IP:UDP-port list and correct SNI. For Mainland China Global Acceleration, the
endpoints must be issued by a Cloudflare One account/partner with Global
Acceleration enabled. Do not guess endpoints or replace them with public WARP
addresses.

The upstream project can register a personal WARP device or use a Zero Trust
team JWT. That JWT is an enrollment credential and must never be embedded as
an APK constant. A production enrolment flow must provision per-device
credentials through an authenticated backend and protect private keys with
Android Keystore. No Cloudflare token or private key is committed here.

## Status

The Android bridge now exposes a device enrollment method that registers a
WARP device, enrolls a MASQUE key, and returns the device-specific tunnel
configuration. The Android services call the bridge with the matching method
signatures. Both APK workflows build the AAR before packaging it.

A successful APK build verifies compilation, native library inclusion,
package integrity, and signing; it does **not** prove that the tunnel connects
on a particular carrier or in Mainland China. The enrollment endpoint and
MASQUE endpoint still require live network validation on the target network.
For Mainland China Global Acceleration, use only endpoint details issued by
the relevant Cloudflare One account/partner; do not guess endpoints or replace
them with arbitrary public WARP addresses.

This is an unofficial third-party WARP/MASQUE implementation; it is not the
official Cloudflare One Agent and is not endorsed by Cloudflare.
