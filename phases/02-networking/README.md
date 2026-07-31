# Phase 02 — 🌐 Networking From First Principles

> The internet is held together with retries and optimism.

Nothing about the network is solid: packets vanish, arrive twice, or show up out of order, and every reliable-looking abstraction — TCP, HTTP, TLS — is an elaborate coping mechanism built on that chaos. This phase walks the stack from IP packets to HTTP/3, and twice makes you build the thing yourself with raw sockets, because nobody who has hand-parsed an HTTP request ever again believes the network is magic. By the end, "it's a network issue" stops being an incantation and becomes a checklist.

## 01. OSI vs TCP/IP: the maps of the internet

**MOTTO:** OSI is the map they teach; TCP/IP is the terrain you'll die on.

### The Problem

Networking involves a dozen concerns at once — voltages, frames, addresses, retransmissions, encryption, application semantics. Without layering, every program would reimplement all of it, and no two vendors' gear would interoperate. But two competing maps of the layers exist, and confusing the idealized one with the deployed one breeds real misunderstandings.

### The Concept

Layering is postal logistics: you write a letter (application), an envelope gets an address (transport/network), trucks move bags of envelopes (link/physical) — and no layer needs to understand the others, only the interfaces between them. Each layer *encapsulates* the one above: your bytes ride inside TCP segments inside IP packets inside Ethernet frames.

```
 OSI (theory)          TCP/IP (reality)         what actually runs there
 7 Application  \
 6 Presentation  |---- Application ........... HTTP, DNS, TLS, gRPC
 5 Session      /
 4 Transport    ------ Transport ............. TCP, UDP, QUIC
 3 Network      ------ Internet .............. IP, ICMP, BGP
 2 Data link    \_____ Link .................. Ethernet, Wi-Fi, ARP
 1 Physical     /                              fiber, radio, copper
```

OSI (1984, ISO committee) is a seven-layer reference model whose actual protocols lost; TCP/IP's four rough layers are what shipped. Use OSI as vocabulary ("layer 4 load balancer"), TCP/IP as reality.

### Build It

Decode encapsulation by hand:

1. Run a container from your Phase 0 lab and capture: `tcpdump -i any -X port 5432 -c 5`.
2. In each dump, identify the nesting: Ethernet header (14 B) → IP header (20 B, find the source/dest addresses) → TCP header (20 B+, find the ports) → payload (Postgres wire bytes).
3. Note the overhead: ~54+ bytes of headers to move even 1 byte of payload — one reason tiny chatty messages are expensive.
4. Vocabulary drill: an "L4 load balancer" routes on IP+port without reading HTTP; an "L7 load balancer" parses HTTP and can route on paths. Same box-and-arrow, different layer of visibility.

### Use It

| You say | You mean |
|---|---|
| L3 problem | routing/IP reachability (ping, traceroute) |
| L4 problem | TCP/UDP — ports, handshakes, resets |
| L7 problem | the application protocol — HTTP codes, headers |

Debugging is binary search over layers: `ping` (L3) → `nc -v host port` (L4) → `curl -v` (L7). Each success eliminates everything below it.

### War Story

The 1980s–90s "protocol wars" pitted the official, government-backed OSI protocol suite against scrappy TCP/IP — and TCP/IP won decisively, a victory the IETF culture summarizes in its famous credo: "We reject kings, presidents and voting. We believe in rough consensus and running code." The seven-layer model survived only as vocabulary — a map outliving its intended territory.

### Checkpoint

- What does a layer 4 load balancer see that a layer 3 router doesn't, and what does it *not* see that an L7 proxy does?
- Walk through the encapsulation of an HTTP request byte down to the wire.
- Why did the OSI *model* survive while the OSI *protocols* died?

## 02. IP addressing and routing

**MOTTO:** IP delivers packets the way you deliver gossip: best effort, no receipts.

### The Problem

Billions of devices need to find each other with no central directory and no machine knowing the whole map. And IP promises almost nothing: packets may be dropped, duplicated, or reordered. Everything above IP exists to launder that non-promise into something usable.

### The Concept

An IPv4 address is 32 bits (~4.3B total — see Lesson 12 for how that ran out); IPv6 is 128 bits (effectively infinite). CIDR notation writes a *prefix*: `10.1.2.0/24` means "first 24 bits fixed, 256 addresses." Routers don't know hosts; they know prefixes, and forward each packet to the **longest matching prefix** — like sorting mail by "US" then "ON" then "M5V", each hop knowing only the next hop.

```
 routing table (simplified):
   0.0.0.0/0        -> ISP uplink          (default: "everything else")
   10.0.0.0/8       -> internal backbone
   10.1.2.0/24      -> rack switch 7       <- most specific wins
 packet to 10.1.2.9 --> matches /24 --> rack switch 7
```

Within your network, routes are static or via IGPs (OSPF); *between* networks (ASes), BGP does it — held for Lesson 13.

### Build It

1. Your own view: `ip addr` / `ipconfig` — find your address and prefix length; `ip route` — find your default route.
2. Subnet math by hand: how many hosts in a `/26`? (2³² ⁻ ²⁶ = 64, minus network+broadcast = 62.) A VPC "carved into subnets" is exactly this arithmetic.
3. Trace a real path: `traceroute example.com` (or `tracert`) — each line is a router decrementing your packet's TTL; watch your bytes change carriers mid-ocean.
4. Know the reserved ranges cold: `10/8`, `172.16/12`, `192.168/16` (private — RFC 1918), `127/8` (loopback), `169.254/16` (link-local, a.k.a. "DHCP failed").

### Use It

Cloud networking is CIDR all the way down: a VPC is a prefix, subnets are sub-prefixes, security groups and route tables match on them. Longest-prefix-match is also a traffic tool — advertising a more-specific prefix pulls traffic toward you, which enables both clever failover and Lesson 13's hijacks.

### War Story

In February 2008, Pakistan Telecom — ordered to block YouTube domestically — announced a more-specific prefix for YouTube's address space, which leaked to the global routing system; longest-prefix-match then obediently steered much of the world's YouTube traffic into Pakistan's null route for about two hours. The internet's map is written by whoever announces most specifically, and in 2008 almost nobody checked signatures.

### Checkpoint

- How many usable host addresses in a `/20`?
- Explain longest-prefix matching and why a `/25` beats a `/8` for a covered address.
- What exactly does IP *not* guarantee, and name two protocols whose job is compensating.

## 03. TCP: handshakes, flow control, congestion

**MOTTO:** TCP builds a promise out of a network that makes none.

### The Problem

IP hands you a firehose of maybe-lost, maybe-duplicated, maybe-reordered packets. Applications want a clean fiction: a two-way stream of bytes that arrive exactly once, in order. Someone has to fake it — and also stop fast senders from drowning slow receivers, and stop *everyone* from drowning the network itself.

### The Concept

Three mechanisms, one protocol. **Reliability:** number every byte, ACK what's received, retransmit what isn't. **Connection setup:** the three-way handshake agrees on starting numbers. **Flow control:** the receiver advertises a window ("I have room for N more bytes"). **Congestion control:** the sender probes the *network's* capacity — start slow, accelerate until loss hints at a full queue somewhere, back off, repeat. Two thermostats on one pipe: one for the receiver, one for the internet.

```
 handshake:                      congestion (sawtooth):
 A --SYN(seq=x)-->      B        cwnd
 A <-SYN+ACK(y,x+1)--   B          ^      /|    /|    /|
 A --ACK(y+1)------->   B          |  ___/ |___/ |___/ |
   1 RTT before data flows         +------------------------> time
                                       loss^  loss^  loss^
```

Also budget for teardown (FIN/ACK×2) and the famous `TIME_WAIT` lingering state.

### Build It

Congestion control's skeleton (classic Reno flavor):

1. `cwnd = small` (a few segments). Effective send limit = min(cwnd, receiver window).
2. **Slow start:** each RTT, double cwnd (exponential!) until a threshold.
3. **Congestion avoidance:** grow linearly, +1 segment per RTT.
4. On packet loss: cut cwnd (halve, classically), remember threshold, resume.
5. Modern refinement: BBR estimates bandwidth×RTT directly instead of waiting for loss.

Consequences you'll design around: every new connection pays 1 RTT (plus TLS) before data — hence connection reuse; short transfers never leave slow start — hence "warm" connections outperform cold ones; loss on high-latency links craters throughput — hence CDNs.

### Use It

| Knob/behavior | Design consequence |
|---|---|
| Handshake RTT | connection pooling, keep-alive (Lesson 06) |
| Nagle vs delayed ACK | latency traps for small writes (Lesson 11) |
| TIME_WAIT | port exhaustion on churny clients |
| Head-of-line blocking | one lost packet stalls the whole stream (Lessons 07–08) |

### War Story

In October 1986, the early Internet suffered congestion collapse: the LBL-to-Berkeley link's effective throughput fell from 32 kbps to about 40 bps — a thousandfold — as naive senders retransmitted into a full network, making it fuller. Van Jacobson's response, slow start and congestion avoidance (1988), is arguably the patch that let the internet scale at all.

### Checkpoint

- Why does TCP need *both* flow control and congestion control? What does each protect?
- Draw the three-way handshake and explain what each message establishes.
- Why does a 50 KB transfer on a fresh connection behave worse than the same transfer on a warm one?

## 04. UDP: when losing packets is fine

**MOTTO:** UDP is a postcard: cheap, fast, and nobody promises delivery.

### The Problem

TCP's guarantees have prices: handshake RTT, ordering delays, retransmission stalls. For a video call, a retransmitted packet arrives *after* the moment it described — worse than useless. Some applications need the network raw: send now, no ceremony, and let *me* decide what loss means.

### The Concept

UDP adds almost nothing to IP: source port, destination port, length, checksum — 8 bytes of header, no connection, no ordering, no retransmission, no congestion control. That last absence is the sharp edge: a naive UDP sender is a firehose with no thermostat, and datagram boundaries are preserved (unlike TCP's byte stream) but each datagram sinks or swims alone.

```
 TCP: [handshake]->[ordered reliable byte stream]->[teardown]   dinner service
 UDP: [datagram] [datagram]    [datagram]                        food cannon
              (one never arrived; nobody was notified)
```

### Build It

A complete UDP exchange — note what's missing versus Lesson 11's TCP lab:

```python
# server.py
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", 9999))
while True:
    data, addr = s.recvfrom(2048)          # no accept(), no connection
    s.sendto(data.upper(), addr)

# client.py
import socket
c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
c.sendto(b"hello", ("127.0.0.1", 9999))    # fire and forget
print(c.recvfrom(2048))                    # would hang forever if the reply died
```

Design rules when you adopt UDP: add sequence numbers if you must detect loss; add your own pacing or you're a menace; timestamps beat retransmits for real-time data ("skip the stale frame, render the next").

### Use It

| Use case | Why UDP |
|---|---|
| DNS queries | one tiny request/reply; a retry is cheaper than a connection |
| Video calls, game state (WebRTC/custom) | freshness > completeness |
| QUIC / HTTP/3 | reliability rebuilt *in userspace* on UDP to escape TCP's rigidity |
| Metrics (statsd) | losing 0.1% of counters is fine; blocking the app is not |

### War Story

UDP's no-handshake nature enables *amplification* attacks: spoof the victim's address, send tiny queries to open servers, and the large replies converge on the target. In February 2018, GitHub absorbed a then-record ~1.35 Tbps attack built on exposed memcached UDP endpoints with an amplification factor in the tens of thousands; mitigation shed the load through a scrubbing service in minutes. Every open UDP service is a potential megaphone pointed wherever an attacker claims to be.

### Checkpoint

- Name four services TCP provides that UDP does not.
- Why is a retransmitted packet actively harmful in a live video call?
- What makes UDP uniquely suited to amplification DDoS attacks, and what two properties of a reply make it worse?

## 05. DNS from scratch

**MOTTO:** DNS is the phone book — distributed, cached, occasionally wrong, and holding up everything.

### The Problem

Humans use names; IP uses numbers; and mappings change constantly as services move and scale. A central lookup table for the whole internet would be a throughput bottleneck, a single point of failure, and a political warzone. The solution has to be delegated, cached, and eventually consistent — and you inherit all three properties whether you like it or not.

### The Concept

DNS is a hierarchy read right-to-left: `api.shop.example.com.` — root (`.`) delegates `com` to TLD servers, which delegate `example.com` to its authoritative servers, which answer for `api.shop`. Your **recursive resolver** (ISP's, or 8.8.8.8/1.1.1.1) walks this chain once, then **caches** each answer for its TTL. Nearly every lookup on Earth is a cache hit.

```
 stub (your OS) -> recursive resolver
    resolver -> root:            "ask com's servers"      (cached ~forever)
    resolver -> com TLD:         "ask ns1.example.com"    (cached ~1 day)
    resolver -> ns1.example.com: "api.shop = 93.184.216.34, TTL 300"
 record types: A/AAAA (name->IP)  CNAME (alias)  MX (mail)  NS (delegation)  TXT (misc/proofs)
```

### Build It

1. Replay the recursion yourself: `dig +trace api.github.com` — watch root → TLD → authoritative in real output.
2. Inspect caching: `dig github.com`, note the TTL, run it again and watch the TTL count down in your resolver's cache.
3. Follow a CNAME chain: `dig www.<some-cdn-customer>.com` often yields CNAME → CDN hostname → A records near you.
4. Design levers: **low TTL** (60 s) = fast failover, more query load and slower resolution on miss; **high TTL** (1 day) = cheap and fast, but changes propagate glacially. DNS is also a *load balancer* (multiple A records, GeoDNS answering by client location) — crude, cache-delayed, but globally free.

### Use It

Route 53, Cloudflare DNS, and friends offer health-checked failover and geo-routing on this substrate. Kubernetes runs its own DNS for service discovery. Cardinal caveat: DNS changes are not instantaneous and resolvers ignore your urgency — never design a failover plan whose first step is "quickly change DNS" with a 24-hour TTL already in the wild.

### War Story

On October 21, 2016, a Mirai botnet of hacked cameras and DVRs DDoSed Dyn, a major managed-DNS provider — and Twitter, Reddit, Spotify, GitHub, and much of the US East Coast internet "went down" while their servers hummed along perfectly healthy. Nobody could *look up their addresses*. The postmortem lesson standardized: use multiple DNS providers; the phone book is infrastructure.

### Checkpoint

- Walk the full resolution of a fresh name from root to A record — who answers what?
- You're planning a migration and want fast rollback via DNS. What must you do to TTLs, and *when*?
- In the Dyn attack, why did perfectly healthy services become unreachable?

## 06. HTTP/1.1: keep-alive and head-of-line blocking

**MOTTO:** HTTP/1.1 is a polite queue: one question, one answer, no cutting.

### The Problem

HTTP/1.0 opened a fresh TCP connection per request — handshake, slow start, teardown, repeat — brutal for a page with dozens of assets. HTTP/1.1 fixed that with reuse, but kept a deeper flaw: each connection is a strict one-at-a-time queue, and the modern web needs a hundred things at once.

### The Concept

HTTP/1.1 is human-readable request/response over TCP. **Keep-alive** (default) reuses the connection for the next request. But requests on one connection are serial: a slow response blocks everything queued behind it — **head-of-line (HOL) blocking** at the application layer. (Pipelining — send several requests ahead — was specified, but responses still had to return in order, and broken intermediaries got it disabled everywhere.) Browsers compensated with parallelism by brute force: ~6 TCP connections per host.

```
 GET /index.html HTTP/1.1          HTTP/1.1 200 OK
 Host: example.com                 Content-Type: text/html
 Connection: keep-alive            Content-Length: 1270
 <blank line>                      <blank line> <1270 bytes>

 one connection:  [req A |-- 3s slow response --][req B waits][req C waits]
```

### Build It

Speak it by hand — it's just text over a socket:

1. `nc example.com 80` (or `telnet`), type: `GET / HTTP/1.1`, `Host: example.com`, blank line. Read the raw response.
2. Framing rules you now care about: `Content-Length` tells the client where the body ends; `Transfer-Encoding: chunked` streams unknown-length bodies as `<hex size>\r\n<chunk>` pieces ending with a `0` chunk. Get these wrong in Lesson 14 and clients hang forever.
3. Observe reuse: `curl -v https://example.com/a https://example.com/b` — one connection, note "Re-using existing connection."
4. The workarounds era, so you recognize the fossils: domain sharding (`img1.`, `img2.` — more hosts ⇒ more connections), spriting, inlining, JS/CSS bundling. All were HOL-blocking dodges.

### Use It

HTTP/1.1 remains everywhere: origin hops behind CDNs, health checks, webhooks, countless internal services. Rules that still pay rent: always reuse connections (pools in your HTTP client), always set timeouts, and know your framing when debugging with `curl -v` — which will never stop being the tool you reach for first.

### War Story

The six-connections-per-host convention shaped a decade of web architecture: entire performance industries (sharded asset domains, sprite sheets, bundlers) existed purely to smuggle parallelism past HTTP/1.1's serial queue. When HTTP/2 landed, those same optimizations became *anti*-patterns overnight — sharding defeated its single-connection design — a tidy lesson in how workarounds calcify into "best practices."

### Checkpoint

- What problem does keep-alive solve, and what problem does it explicitly not solve?
- Why did HTTP/1.1 pipelining fail in practice?
- Explain how `Content-Length` and chunked encoding each solve message framing.

## 07. HTTP/2: multiplexing and server push

**MOTTO:** HTTP/2 turned the polite queue into a well-run switchboard — over one wire.

### The Problem

Lesson 06 left the web faking parallelism with six TCP connections and sharded domains — wasteful handshakes, redundant slow starts, and still-limited concurrency. The fix had to allow many simultaneous requests over *one* connection without any response blocking the others.

### The Concept

HTTP/2 (2015, from Google's SPDY) keeps HTTP's semantics but replaces the text protocol with **binary frames**. Each request/response is a **stream**; frames from many streams interleave freely over one TCP connection — a slow response no longer blocks others, because its frames simply yield the wire. Add **HPACK** header compression (headers are repetitive; index them) and stream prioritization.

```
 HTTP/1.1 (per connection):   [respA........][respB][respC]
 HTTP/2 (one connection):     [A1][B1][C1][A2][C2][B2][A3]...
                               \_ frames tagged with stream IDs,
                                  reassembled per stream at the far end
```

**Server push** let servers volunteer resources ("you'll want this CSS") before being asked — remember it mostly as a cautionary tale (see War Story). The asterisk: multiplexing happens *above* TCP, and TCP doesn't know about streams — one lost packet halts delivery of **all** streams until retransmission. HOL blocking wasn't killed; it moved down a layer.

### Build It

1. See it live: `curl -v --http2 https://www.google.com` — watch the `h2` negotiation (via TLS ALPN); browser DevTools shows Protocol `h2` and one connection carrying dozens of parallel requests.
2. Mechanics to internalize: frame types (HEADERS, DATA, SETTINGS, RST_STREAM, GOAWAY), stream IDs (client-initiated odd, server even), per-stream flow-control windows layered atop TCP's.
3. Unlearn the fossils: with h2, domain sharding actively hurts (splits one good connection into several cold ones) and bundling matters less.
4. Enable it: `listen 443 ssl http2;` in nginx (h2 is TLS-only in every browser).

### Use It

| Situation | Verdict |
|---|---|
| Browser ↔ edge | h2 default, big win |
| Many small parallel API calls | h2 shines (one warm connection) |
| Lossy/mobile networks | TCP-level HOL bites; HTTP/3 territory |
| gRPC | built directly on h2 streams (Phase 3) |

### War Story

Server push looked brilliant and measured badly: servers guessed wrong, pushed resources browsers already had cached, and wasted bandwidth. After years of near-zero effective adoption, Chrome removed HTTP/2 server push support in 2022 — a rare, clean example of the web platform admitting a shipped feature failed the experiment. (Its spiritual successor: `103 Early Hints`, which merely *suggests* instead of sending.)

### Checkpoint

- How does HTTP/2 fix application-layer HOL blocking, and why does TCP-layer HOL blocking remain?
- Why does domain sharding change from optimization to anti-pattern under h2?
- What killed server push in practice?

## 08. HTTP/3 and QUIC

**MOTTO:** To fix TCP, they gave up on fixing TCP.

### The Problem

HTTP/2's residual sin (Lesson 07): one lost TCP packet freezes every multiplexed stream, painful precisely where the modern web lives — lossy mobile and Wi-Fi. Worse, TCP itself is unfixable in practice: it lives in kernels and middleboxes that take a decade to upgrade and actively drop unfamiliar TCP options ("ossification").

### The Concept

QUIC's escape: rebuild transport **in userspace on UDP**, which middleboxes pass untouched, and encrypt almost everything so they can never grow opinions about it. QUIC provides independently-delivered streams (loss in one stream stalls only that stream), integrates TLS 1.3 into its handshake (1 RTT to encrypted data; 0-RTT on resumption), and identifies connections by ID rather than IP/port 4-tuple — so your download *survives switching from Wi-Fi to cellular*. HTTP/3 is HTTP mapped onto QUIC streams.

```
 h2 over TCP:  streams A,B,C -> one ordered byte stream -> [lost pkt] -> ALL wait
 h3 over QUIC: stream A [ok]  stream B [lost, retransmitting]  stream C [ok]
               A and C keep flowing; only B waits

 handshake RTTs to first encrypted byte:
   TCP+TLS1.2: 3   TCP+TLS1.3: 2   QUIC: 1   QUIC resumed: 0
```

### Build It

1. Discovery: servers advertise h3 via the `Alt-Svc` response header (`alt-svc: h3=":443"`); browsers try QUIC next time and race fallbacks.
2. Observe: DevTools Protocol column shows `h3` on Google/YouTube/Cloudflare properties; `curl --http3 -v` on a curl built with an h3 stack.
3. Design consequences: congestion control now iterates at software speed (QUIC stacks ship new algorithms without OS upgrades); CPU cost is higher than TCP (userspace crypto per packet, less NIC offload — improving); some enterprise networks still throttle/block UDP 443, so h2 fallback stays mandatory.
4. Mental model check: QUIC ≈ "TCP's reliability + TLS 1.3 + h2's streams, reimplemented above UDP with connection migration."

### Use It

| Property | Beneficiary |
|---|---|
| Per-stream loss recovery | video, mobile browsing, many-asset pages |
| 0/1-RTT setup | short connections, cold starts |
| Connection migration | phones changing networks mid-transfer |
| Userspace evolution | rapid congestion-control iteration (e.g., BBR variants) |

### War Story

Google began deploying QUIC in Chrome and its services around 2013 and by 2017 reported it carrying over a third of Google egress traffic, with measurable improvements to Search latency and YouTube rebuffering. The IETF standardized its evolution as RFC 9000 in May 2021 — one of the few times the internet successfully swapped out a transport protocol, achieved by tunneling through the one hole middleboxes leave open: UDP.

### Checkpoint

- Why was building on UDP the only realistic deployment path for a new transport?
- Explain how QUIC eliminates transport-layer HOL blocking where HTTP/2 could not.
- What is connection migration, and which everyday user scenario does it rescue?

## 09. TLS: the handshake that secures the web

**MOTTO:** TLS lets two strangers whisper in a room full of eavesdroppers — after one very careful introduction.

### The Problem

Every hop in Phase 2 so far — routers, proxies, coffee-shop Wi-Fi — can read and rewrite your bytes. Commerce, medicine, and login pages need three guarantees over that hostile path: nobody read it (confidentiality), nobody altered it (integrity), and you're talking to the real server (authenticity). Miss any one and the other two are decorative.

### The Concept

Two-phase trick. **Handshake** (expensive, asymmetric crypto): verify the server's identity and agree on a shared secret. **Record phase** (cheap, symmetric crypto): encrypt the actual traffic with that secret. Identity rides on **certificates**: the server presents a public key signed by a Certificate Authority your OS/browser already trusts — a passport, checkable against a known issuer, for `example.com`. Key exchange uses (elliptic-curve) Diffie–Hellman: both sides derive the same secret while an eavesdropper watching *every byte* cannot — and ephemeral keys mean recorded traffic stays safe even if the server's long-term key later leaks (forward secrecy).

```
 TLS 1.3 (1 RTT):
 Client -> ClientHello: my ciphers + my DH key share + SNI: example.com
 Server -> ServerHello: chosen cipher + DH share, then (encrypted:)
           Certificate + proof-of-private-key + Finished
 Client -> verifies cert chain to a trusted CA -> Finished
 [symmetric encryption on; HTTP flows]
```

### Build It

1. Read a real handshake: `openssl s_client -connect example.com:443` — the certificate chain (leaf → intermediate → root), protocol, cipher.
2. Verify the chain's logic: leaf signed by intermediate, intermediate by a root in your trust store; any break = the browser warning users click through at their peril.
3. Get certs the modern way: Let's Encrypt + ACME (`certbot`) — free, automated, 90-day rotations; hand-managed certs are how outages are scheduled.
4. Two names that unlock debugging: **SNI** (client names the host in ClientHello so shared IPs can pick a cert) and **ALPN** (negotiates h2/h3 inside the handshake). Ops note: at scale you usually *terminate* TLS at the edge/load balancer, then re-encrypt or trust the internal network — with mTLS (both sides present certs) as the zero-trust option service-to-service.

### Use It

| Choice | Tradeoff |
|---|---|
| TLS 1.3 only | fewer round trips, fewer footguns; drops ancient clients |
| Terminate at edge | cheap, centralizes certs; internal hops need their own story |
| mTLS everywhere | strong identity; certificate lifecycle ops for every service |
| 0-RTT resumption | latency win; replay-attack caveats for non-idempotent requests |

### War Story

Heartbleed (April 2014): a missing bounds check in OpenSSL's heartbeat extension let anyone ask a server to echo up to 64 KB of its own memory — which could contain session cookies, passwords, or the private key itself — leaving no trace in logs. An estimated hundreds of thousands of servers were exposed, mass certificate reissuance followed, and the industry finally funded core infrastructure (Core Infrastructure Initiative) it had been freeriding on.

### Checkpoint

- Why do we use asymmetric crypto only for the handshake and symmetric crypto for the data?
- What chain of signatures makes a certificate trustworthy, and what's the root of that chain?
- What is forward secrecy, and what attack scenario does it neutralize?

## 10. WebSockets, SSE, and long polling

**MOTTO:** HTTP only speaks when spoken to; real-time apps need the server to interrupt.

### The Problem

Chat, dashboards, multiplayer, notifications: the *server* learns something first and must tell the client now. HTTP's model is strictly client-asks/server-answers. Naive fix — poll every second — is a self-inflicted DDoS of mostly-empty responses with average latency of half the interval.

### The Concept

Three escalating escapes:

```
 short poll:  C: anything? S: no. C: anything? S: no. C: anything? S: yes!
              (waste + latency)
 long poll:   C: anything? S: ...holds request open... "yes!" -> C reconnects
              (near-realtime; one hop of headers per message)
 SSE:         C: GET /stream           S: sends events forever ->
              (one-way server->client, plain HTTP, auto-reconnect built in)
 WebSocket:   C: HTTP + "Upgrade: websocket" -> protocol switches ->
              <== full-duplex message frames both ways, one TCP connection ==>
```

WebSocket begins life as an HTTP request (`Upgrade: websocket`, status `101 Switching Protocols`) then sheds HTTP entirely: both sides send lightweight frames anytime. SSE (`Content-Type: text/event-stream`) stays plain HTTP — trivially proxy/CDN-friendly, auto-reconnecting via `Last-Event-ID`, but server→client only.

### Build It

SSE needs no library at all:

```python
# pip install flask
import time
from flask import Flask, Response
app = Flask(__name__)

@app.get("/stream")
def stream():
    def events():
        n = 0
        while True:
            yield f"id: {n}\ndata: tick {n}\n\n"   # SSE wire format
            n += 1; time.sleep(1)
    return Response(events(), mimetype="text/event-stream")
# browser: new EventSource("/stream").onmessage = e => console.log(e.data)
```

The hard part isn't the protocol — it's the *state*: a million WebSockets = a million open connections pinned to specific servers. Now you need connection-aware load balancing, heartbeats to detect silent death, reconnect-with-backoff clients, and a pub/sub backbone (e.g., Redis) so any server can reach any user's connection.

### Use It

| Need | Pick |
|---|---|
| Server→client only (feeds, tickers, LLM token streams) | SSE |
| Bidirectional, low-latency (chat, games, collab editing) | WebSocket |
| Hostile proxies / maximum compatibility | long polling fallback |
| Voice/video | none of these — WebRTC/UDP territory |

### War Story

Slack's real-time messaging rides persistent WebSocket connections to edge servers — millions of them held open concurrently — and its engineering writeups describe the true boss fight: not message delivery, but *reconnection storms*, when a network blip or deploy disconnects a huge population that then tries to come back, all at once, with full state resync. Persistent connections turn "restart the server" into a capacity event.

### Checkpoint

- Why does long polling approximate real-time while short polling structurally cannot?
- SSE vs WebSocket: name two operational advantages of each.
- Your WebSocket fleet restarts and 2M clients reconnect simultaneously. Name three mechanisms that keep this survivable.

## 11. Sockets lab: build a TCP server by hand

**MOTTO:** TCP hands you a stream of bytes — where the messages begin and end is entirely your problem.

### The Problem

Every abstraction in this phase sits on the socket API, and its number-one betrayal stays invisible until you build on it: `send()` boundaries are *not preserved*. Three sends may arrive as one `recv`; one send may arrive as five. Framing bugs from ignoring this haunt production systems everywhere.

### The Concept

The BSD socket lifecycle: server does `socket → bind → listen → accept` (accept blocks until a completed handshake pops off the queue, yielding a *new* socket per client); client does `socket → connect`. After that, both hold phone lines that carry undifferentiated bytes.

```
 server                          client
 socket() bind(:9000) listen()
 accept() ─ waits ─┐             socket() connect() ──┘ 3-way handshake
        conn ◄─────┘
 conn.recv(4096) ◄════ bytes ════ send(b"...")     # boundaries NOT preserved
```

### Build It

A newline-framed echo server — complete and runnable:

```python
# echo_server.py  — run, then: nc 127.0.0.1 9000
import socket, threading

def handle(conn, addr):
    buf = b""
    with conn:
        while True:
            data = conn.recv(4096)
            if not data:                      # b"" == peer closed
                break
            buf += data
            while b"\n" in buf:               # framing: OUR job, not TCP's
                line, buf = buf.split(b"\n", 1)
                conn.sendall(b"echo: " + line + b"\n")
    print("bye", addr)

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 9000)); srv.listen(64)
print("listening on :9000")
while True:
    conn, addr = srv.accept()
    threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
```

Details that are the actual lesson: the recv-loop accumulates a buffer because messages ≠ packets; `sendall` loops because `send` may write partially; `recv` returning `b""` is the only clean-close signal; `SO_REUSEADDR` sidesteps TIME_WAIT on restarts. Experiments: connect two `nc` clients at once; paste a huge line; kill the client mid-send and watch the server's error path.

### Use It

Every serious protocol picks a framing scheme: **delimiter** (newline — Redis' original protocol, SMTP), **length-prefix** (4-byte size then payload — gRPC, Kafka, most binary protocols), or **self-describing headers** (HTTP's `Content-Length`). Length-prefix is the default choice for binary work: no escaping, O(1) to know how much to read.

### War Story

John Nagle — who created Nagle's algorithm (batch tiny TCP writes) in 1984 — has spent years explaining on forums that its infamous interaction with *delayed ACKs* (two well-meaning optimizations deadlocking into ~200 ms stalls on request/response traffic) comes from the two features never being designed together. It's why latency-sensitive servers set `TCP_NODELAY`, and why Redis, nginx, and virtually every RPC stack ship with it on.

### Checkpoint

- Why must a TCP application maintain its own receive buffer and framing logic?
- What are the three common framing strategies, and which would you pick for a binary RPC protocol?
- What do `recv() == b""` and a `ConnectionResetError` each tell you about the peer?

## 12. NAT, firewalls, and proxies

**MOTTO:** Half the internet is machines pretending to be other machines — on purpose.

### The Problem

IPv4 has ~4.3 billion addresses; humanity has tens of billions of devices. Also: you don't actually *want* every laptop and lightbulb directly reachable from the whole internet. Both problems got the same answer — middleboxes that rewrite, filter, and impersonate — and that answer quietly broke the internet's original any-to-any symmetry.

### The Concept

**NAT** (network address translation): your router owns one public IP; as connections leave, it rewrites `private-IP:port → public-IP:new-port` and keeps a translation table to route replies back. Consequence: outbound works, *unsolicited inbound has no table entry and dies* — which is why two phones can't just call each other (hole-punching via STUN/TURN exists for that). **Firewalls** filter by rule (default: outbound yes, inbound no). **Proxies** terminate your connection and open their own: forward proxies impersonate the *client* (egress control), reverse proxies impersonate the *server* (nginx/Envoy/CDNs — load balancing, TLS termination, caching).

```
 laptop 192.168.1.7:52001 ──┐
 phone  192.168.1.9:44310 ──┤ NAT (203.0.113.5) ──> internet
   table: 52001→203.0.113.5:61001, 44310→203.0.113.5:61002
   inbound to :61001 → laptop ✓     inbound to :9999 → (no entry) ✗

 client ──> [reverse proxy] ──> app1 / app2 / app3
             TLS ends here; apps see proxy's IP (hence X-Forwarded-For)
```

### Build It

1. See your own double identity: `ip addr` (private, RFC 1918) vs `curl ifconfig.me` (public — the NAT's face).
2. Reverse-proxy your Phase 0 lab: nginx container with `proxy_pass http://app:8000;` in front of an app container; confirm the app logs show nginx's IP, then add `proxy_set_header X-Forwarded-For $remote_addr;` and re-check.
3. Internalize the traps: NAT/firewall state tables expire idle flows (~minutes) — long-lived quiet connections (DB pools, WebSockets) die silently, hence TCP keepalives and heartbeats; anything reading `X-Forwarded-For` for auth or rate limiting must remember *clients can forge it* unless the edge strips it.
4. Cloud mapping: security groups = stateful firewalls; NAT gateways = NAT-as-a-service (with per-GB pricing that surprises people); load balancers = managed reverse proxies.

### Use It

| Middlebox | Superpower | Tax |
|---|---|---|
| NAT | address scarcity survival, incidental shielding | breaks inbound & P2P; state timeouts |
| Firewall | attack-surface reduction | mystery "connection refused/timeout" debugging |
| Reverse proxy | TLS, LB, caching in one hop | extra hop; true-client-IP plumbing |
| Forward proxy | egress visibility/control | TLS interception ethics & breakage |

### War Story

IANA allocated its final IPv4 address blocks to the regional registries on February 3, 2011, and the registries subsequently exhausted their own pools — yet the internet kept growing for over a decade largely *because* NAT (including carrier-grade NAT stacking whole neighborhoods behind one IP) let billions of devices share the scraps. The workaround was so effective it removed much of the urgency that was supposed to drive IPv6 adoption.

### Checkpoint

- Trace the address translations for a request from `192.168.1.7` to a public website and its reply.
- Why can't an unsolicited internet packet reach a device behind NAT, and what techniques exist for P2P anyway?
- Why do idle database connections through cloud NATs/firewalls die, and what's the standard defense?

## 13. Anycast and BGP basics

**MOTTO:** BGP is the internet's word-of-mouth: routes spread by gossip, and everyone believes what they hear.

### The Problem

No one runs the internet. It's ~100,000 independent networks (autonomous systems — ISPs, clouds, universities) that must collectively figure out how to reach every prefix on Earth, with no central authority, while each pursues its own commercial interests. The protocol that makes this work is also the internet's most famous single point of systemic fragility.

### The Concept

**BGP**: each AS announces to its neighbors "I can reach prefix X" (with the AS-path so far); neighbors append themselves and re-announce; every AS picks its preferred path per prefix (shortest AS-path, tie-broken heavily by *business policy* — customer routes over peer routes over paid transit). Trust model: historically, none — you believed announcements (Lesson 02's hijack; RPKI now adds cryptographic origin checks, adoption growing). **Anycast** rides on this: announce the *same prefix from many locations*, and BGP naturally routes each user to the topologically nearest copy — global load balancing with zero code.

```
 AS64500 (you): "I own 198.51.100.0/24" ──> ISP A ──> their peers ──> ...
                                       └──> ISP B ──> ...
 each AS hears multiple paths, picks one, tells its neighbors

 anycast: announce 1.1.1.1 from 300 cities
   Tokyo user -> Tokyo POP     Berlin user -> Berlin POP   (same IP!)
```

### Build It

1. Look up real objects: `whois -h whois.radb.net 8.8.8.8` or bgp.tools — find the origin AS (AS15169, Google) and prefix.
2. Watch convergence thinking: a route withdrawal ripples AS-by-AS; global convergence takes seconds to minutes — during which traffic blackholes. That's the gap status pages live in.
3. Anycast mechanics worth knowing: brilliant for stateless/short exchanges (DNS — the root servers are anycast; CDN edges); trickier for long TCP flows since a route shift mid-connection changes which POP receives your packets (CDNs engineer around it).
4. Defensive vocabulary: route leak (oops), hijack (malice), RPKI (signed "AS X may originate prefix Y"), and "more-specific wins" as the eternal attack vector.

### Use It

Cloudflare's 1.1.1.1, Google's 8.8.8.8, every root DNS server, and every serious CDN edge are anycast. DDoS resilience is a headline benefit: attack traffic gets *diffused* to hundreds of sites instead of concentrating on one. Your likely touchpoint: cloud services ("Global Accelerator"-style products) sell managed anycast so you never speak BGP yourself.

### War Story

On October 4, 2021, a maintenance command at Facebook withdrew the BGP routes to its own DNS infrastructure; with DNS unreachable, facebook.com, Instagram, and WhatsApp vanished globally for ~6 hours. Legend-grade detail from the postmortems: internal tooling and badge systems depended on the same infrastructure, reportedly complicating engineers' physical access to fix the very routers that needed fixing. When you withdraw your routes, you cease to exist — even to yourself.

### Checkpoint

- How does a BGP announcement propagate, and what two factors dominate route selection?
- Why does announcing one prefix from 200 cities function as load balancing *and* DDoS armor?
- In the Facebook 2021 outage, why did a routing change make healthy servers unreachable worldwide?

## 14. Build a tiny HTTP server from scratch

**MOTTO:** HTTP stops being magic the moment you've parsed it with your own hands.

### The Problem

You've used HTTP all phase through curl and browsers. Final exam: there is no framework — just the Lesson 11 socket skills and the Lesson 06 wire format. If you can turn raw bytes into a request and craft bytes a real browser accepts, the entire stack beneath you is demystified.

### The Concept

An HTTP server is a loop with four duties: **accept** a connection, **parse** bytes into (method, path, headers, body), **dispatch** to a handler, **serialize** a correctly framed response. Every framework — Flask, Express, Spring — is these four verbs wearing increasingly nice clothes.

```
 bytes in:  "GET /hello HTTP/1.1\r\nHost: x\r\n\r\n"
              parse -> route -> handle -> serialize
 bytes out: "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"
```

### Build It

Complete, runnable, browser-compatible:

```python
# tinyhttp.py — python tinyhttp.py, then open http://127.0.0.1:8080/hello
import socket, threading

ROUTES = {
    "/hello": lambda: (200, "text/plain", b"hello"),
    "/":      lambda: (200, "text/html",  b"<h1>tiny server</h1>"),
}
REASONS = {200: "OK", 404: "Not Found", 400: "Bad Request"}

def respond(conn, status, ctype, body):
    head = (f"HTTP/1.1 {status} {REASONS[status]}\r\n"
            f"Content-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\n"      # framing! (Lesson 06)
            f"Connection: close\r\n\r\n")
    conn.sendall(head.encode() + body)

def handle(conn):
    with conn:
        buf = b""
        while b"\r\n\r\n" not in buf:               # read until end of headers
            data = conn.recv(4096)
            if not data: return
            buf += data
        try:
            request_line = buf.split(b"\r\n", 1)[0].decode()
            method, path, version = request_line.split(" ")
        except ValueError:
            return respond(conn, 400, "text/plain", b"bad request")
        handler = ROUTES.get(path)
        if handler is None:
            return respond(conn, 404, "text/plain", b"not found")
        respond(conn, *handler())

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 8080)); srv.listen(64)
print("http://127.0.0.1:8080")
while True:
    conn, _ = srv.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
```

Extension ladder (each rung teaches a real lesson): (1) keep-alive — stop closing, loop parsing multiple requests per connection, and now `Content-Length` framing is *load-bearing*; (2) parse headers into a dict, echo `User-Agent`; (3) serve files — and discover path traversal (`GET /../../etc/passwd`) needs defending; (4) load test with `hey -n 5000 -c 100` and compare against the asyncio version you can now write (Phase 1, Lesson 07).

### Use It

What production servers add to your 45 lines: robust parsing (header limits, timeouts, slow-client defense), chunked encoding, TLS, HTTP/2+, worker models, logging. That's nginx's and gunicorn's whole job description — and now you can read their configs as *decisions about this exact loop* rather than incantations.

### War Story

The web's first server was Tim Berners-Lee's CERN httpd (1990), hand-built much like today's exercise; the Apache HTTP Server that came to dominate the 90s web began in 1995 as shared patches to NCSA's httpd — the name widely told as a pun on "a patchy server." The web was bootstrapped by people doing precisely this lab, then refusing to stop.

### Checkpoint

- Why is `Content-Length` merely polite when `Connection: close`, but load-bearing under keep-alive?
- What are the four duties every HTTP server performs, framework or not?
- What vulnerability appears the moment your server maps URL paths onto the filesystem, and how do you defend it?
