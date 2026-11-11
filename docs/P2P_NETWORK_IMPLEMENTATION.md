# EffectCraft mobile P2P network implementation plan

## User-facing network requirement

Public Wi-Fi is a supported Internet access path, not a special same-LAN mode. Two phones may be connected to unrelated public Wi-Fi hotspots in different buildings, cities or regions and must still be able to discover and connect through the Internet. Do not require matching SSIDs, private IPv4 subnets, manual IP addresses, router port forwarding or the same hotspot.

A public hotspot may enable AP/client isolation, block multicast, restrict peer-to-peer traffic, require captive-portal sign-in, or filter UDP. Therefore:
- Use outbound TLS/WebSocket signaling over the currently usable Internet connection for rendezvous and authorization.
- Attempt authenticated direct peer transport/NAT traversal where the network permits it.
- Fall back to an available public relay over an allowed outbound path when direct connectivity is blocked.
- Treat local mDNS/UDP broadcast as an optional same-LAN fast path only; never make it the only discovery or connectivity mechanism.
- Detect captive portals/offline Wi-Fi and report that the hotspot has no usable Internet until the user completes its sign-in.
- Do not attempt to bypass hotspot isolation, captive portals, network policy, or security controls.

Public Wi-Fi does not imply a public IP address. Many hotspots use NAT/CGNAT, so reliable cross-network communication needs a reachable signaling/bootstrap service and a relay fallback. A pure phone-to-phone direct path cannot be guaranteed on every public hotspot.

## Selected engine

Use the official Rust implementation of libp2p (the libp2p crate, MIT license) as the peer transport and protocol engine. Pin an exact crate version in the implementation commit and update the Cargo lockfile in CI. Do not vendor an unpinned upstream branch.

Official project: https://github.com/libp2p/rust-libp2p

## Required protocol stack

- Noise/TLS authenticated encrypted peer sessions and stable Peer IDs.
- Identify for exchanging peer identity and observed addresses.
- AutoNAT for reachability classification.
- Circuit Relay v2 for connectivity when direct inbound access is impossible.
- DCUtR for upgrading a relayed session to a direct connection where NAT behavior permits it.
- QUIC first, with TCP/TLS fallback for restrictive public Wi-Fi networks.
- An authenticated application protocol for task offers, task acceptance, task data, results and signed control messages.
- Optional Kademlia/Gossipsub only after peer discovery and abuse controls are in place; account authorization must not be delegated to gossip.

## Authority and service boundaries

- Keep the administrator-phone account database private. Never expose its SQLite database or unauthenticated account HTTP listener to the public Internet.
- Keep account-server and node-network switches independent.
- The administrator APK remains the control plane for the global node-network switch. OFF must reject new node sessions and close/revoke existing sessions; ON permits eligible nodes to reconnect automatically.
- Node traffic must use authenticated, encrypted peer sessions or encrypted relay envelopes. The relay must not read or persist application payload plaintext.
- The administrator phone may participate as an ordinary node, but must not be assumed to be the only globally reachable relay or bootstrap endpoint.
- A public bootstrap/relay endpoint is required for peers behind restrictive NAT/CGNAT. If no such endpoint is configured and neither peer is directly reachable, cross-network communication cannot work. Do not claim otherwise.

## Android requirements

- Keep the main APK node participation behavior aligned with the user's selected automatic-join design and the administrator global switch. Explain battery, Wi-Fi/mobile-data use and resource use through Android-visible notices.
- Use an Android foreground service with a persistent notification while a user-enabled node is actively relaying or processing tasks. Respect Android background execution and battery restrictions.
- Persist the device private key in Android Keystore-backed storage; never put private keys, bearer tokens, passwords or signing secrets in source code, APK resources, logs or exported projects.
- On logout, ban, global OFF or explicit system/user stop, stop task acceptance and close peer sessions.
- Do not require the two phones to share an SSID or subnet. Do not require router port forwarding or manual peer IP entry.

## Existing implementation checkpoint

- The admin phone's account API currently listens on the local Wi-Fi network and explicitly restricts account requests to the same subnet. Keep that boundary until a secure, authenticated remote-account access design is implemented; do not simply remove the subnet check or expose port 8788.
- Current admin-side mDNS/UDP discovery and the peer health listener are LAN-only helpers. They are not cross-network transport and must remain optional accelerators, not the public-Wi-Fi networking solution.
- The current P2P plan and staged Worker/native work do not yet constitute a complete, tested public-Wi-Fi peer data path. Actual authenticated payload transfer, relay fallback and global OFF/ON behavior still require implementation and two-device testing on unrelated public Wi-Fi networks.

## Build and verification gates

1. Preserve both APKs' existing editor/account features and build pipelines.
2. Implement a public-Wi-Fi-compatible outbound signaling path that does not depend on multicast or LAN broadcast.
3. Implement end-to-end authenticated encryption, peer trust, replay protection and bounded payload delivery.
4. Integrate direct NAT traversal plus a reachable relay fallback over outbound-friendly transports.
5. Test two real Android devices on different public Wi-Fi hotspots (not just two emulators or the same router), including hotspots with client isolation; record direct-vs-relay outcome.
6. Verify the administrator global OFF stops new and existing node traffic, and ON permits automatic reconnect.
7. Verify account database remains private and account-server/node-network switches remain independent.
8. Do not mark the network operational until bidirectional test payloads pass on genuinely unrelated public Wi-Fi networks.

## Non-regression

Do not remove or weaken EffectCraft editor functionality, project import/export, WASM plugins, desktop AE plugin inspection/import, RIFE frame interpolation, Real-ESRGAN enhancement, or the separate optional DeepSeek plugin to make the network compile.
