# EffectCraft public P2P transport

This native module is the shared peer transport for the Android account manager and, in a subsequent integration step, the main EffectCraft APK.

## Included in this transport milestone

- persistent per-install Ed25519 libp2p identity in app-private storage;
- distinct admin-authority and normal-client startup roles (only the manager advertises the admin-authority DHT provider key);
- identify-protocol filtering so only peers that explicitly announce Circuit Relay v2 `hop` are asked for relay reservations;
- listen-address push updates so peers learn fresh direct and reserved relay addresses;
- TCP and QUIC transports with authenticated Noise encryption and Yamux multiplexing;
- same-Wi-Fi peer discovery using mDNS;
- public Kademlia DHT bootstrap and repeated closest-peer sampling keyed to this node's own Peer ID (the standard AutoRelay discovery approach);
- Identify protocol filtering for `/libp2p/circuit/relay/0.2.0/hop` because public Relay v2 peers do not necessarily publish a dedicated relay-provider record;
- administrator discovery via a dedicated DHT provider key; ordinary client phones do not advertise themselves as account authorities;
- Circuit Relay v2 reservation probes and a rolling relay candidate pool;
- multiple accepted relay reservations; discovery/probing is batched, but accepted relays are not limited to two;
- periodic ping health signals, failed-node cooldown, and repeated DHT discovery;
- AutoNAT and DCUtR behaviours for NAT assessment and direct-upgrade attempts.

DHT bootstrap peers are discovery infrastructure, not automatically relays. A peer only counts as a relay after Circuit Relay v2 accepts a reservation. Nodes that reject reservations are cooled down and may be tested again after subsequent discovery.

## Not yet complete

This transport crate now separates admin-authority discovery from relay discovery, but it does not yet implement the authenticated EffectCraft account request/response protocol, administrator-signed account event replication, user-facing peer pairing, or main-APK registration/login routing over P2P. Those pieces must be connected before cross-network account registration and login can be called complete. Public relay availability is opportunistic and cannot be guaranteed.

## Android build

Compile this crate for arm64-v8a as a cdylib and copy libeffectcraft_p2p.so into the Android app's jniLibs/arm64-v8a directory. NativeP2P.start(filesDir) starts the node and keeps its Ed25519 identity stable across restarts and app updates.