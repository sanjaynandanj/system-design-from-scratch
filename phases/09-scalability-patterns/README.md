# Phase 09 — 📈 Scalability Patterns

> From one server to one million requests per second.

Scalability isn't a product you buy; it's a sequence of increasingly desperate tricks, applied in the right order, each one buying you another 10x. The pattern language is small — go stateless, spread the load, say no politely, precompute the expensive stuff, and cheat with probability when exactness is too pricey. This phase teaches every trick with the mechanism exposed, and ends with you building a rate limiter and a load balancer with your own hands. By the end, "how would you scale this?" stops being a scary interview question and becomes a checklist.

## 01. Vertical vs Horizontal Scaling

**MOTTO:** Scaling up buys you time with money; scaling out buys you a future with complexity.

### The Problem

Your server is pegged at 100% CPU. Two exits: buy a bigger server (vertical, "scale up") or add more servers (horizontal, "scale out"). One is a checkbox in a cloud console; the other is an architecture. Pick wrong in either direction and you've either hit a hard ceiling at the worst moment or paid a distributed-systems tax years before you needed to.

### The Concept

Vertical is upgrading your food truck to a bigger truck: same operation, nothing changes but capacity — until no bigger truck exists. Horizontal is opening more trucks: unlimited in principle, but now you need routing (which truck?), consistency (same menu?), and coordination (shared inventory?).

```
 VERTICAL:   [ 4-core ] → [ 32-core ] → [ 128-core ] → 💰💰💰 → ceiling
 HORIZONTAL: [ s1 ]
             [ s1 ][ s2 ][ s3 ][ s4 ] ... ──▶ needs LB + statelessness
                 └── and one machine's death is now Tuesday, not tragedy
```

Two caps on each: vertical hits the biggest-machine limit and gives zero fault tolerance (one box = one funeral). Horizontal hits **Amdahl's Law** and its distributed cousins — the serial/coordinated fraction of your workload limits speedup no matter how many nodes you add (USL adds: coordination can make more nodes *slower*).

### Build It

1. Measure first: is the bottleneck CPU, RAM, IO, or lock contention? A bigger box doesn't fix a hot mutex.
2. Default playbook: scale *up* the database (they love big machines and hate being distributed), scale *out* the stateless tier (cheap and linear).
3. Before scaling out, clear the prerequisites: no local state (lesson 02), a load balancer (lessons 03–04), externalized sessions and files.
4. Do the arithmetic: cloud pricing is roughly linear in size until the top SKUs, where it spikes — and a 2x machine rarely yields 2x throughput on a contended workload.

### Use It

| | Vertical | Horizontal |
|---|---|---|
| Effort | Trivial | Architectural |
| Ceiling | Biggest SKU | Coordination overhead |
| Fault tolerance | None | Built-in redundancy |
| Cost curve | Superlinear at high end | ~Linear |
| Great for | Databases, quick relief | Stateless services, web tier |

### War Story

Stack Overflow famously served one of the world's biggest Q&A sites for years on a handful of beefy IIS servers and two SQL Server boxes — a monument to vertical scaling plus aggressive caching. Meanwhile Google's foundational papers (GFS, MapReduce) went the other way: oceans of cheap commodity machines with failure treated as routine. Both were right — for their workload, team, and decade.

### Checkpoint

- Why does vertical scaling do nothing for availability?
- What does Amdahl's Law imply about the payoff of adding a 100th server?
- Your Postgres box is at 90% CPU. Argue for scaling up rather than sharding — then name the condition under which that argument expires.

## 02. Stateless Services: The Golden Rule

**MOTTO:** Any request, any server, any time — state lives in stores, not in servers.

### The Problem

Your app keeps login sessions in local memory. Add a second server behind a load balancer and half your users get randomly logged out, mid-checkout, depending on which box the LB picks. Local state welds each user to one machine — killing load balancing, autoscaling, zero-downtime deploys, and crash recovery in one stroke.

### The Concept

A stateless service is a hotel receptionist with a shared computer system: any receptionist can serve any guest because *nothing about the guest lives in the receptionist's head* — it's all in the system. Servers become interchangeable cattle; all state — sessions, uploads, caches worth keeping, job progress — moves to backing services built to hold it.

```
 STATEFUL (fragile):                 STATELESS (cattle):
 user ──▶ [LB] ──▶ [S1: bob's cart]  user ──▶ [LB] ──▶ [S1][S2][S3]  (any one!)
             ╲───▶ [S2: ???]                              │
        sticky sessions required                          ▼
        S1 dies → cart dies                    [Redis: sessions] [S3/DB: files]
```

### Build It

1. Sessions → signed tokens (JWT) carried by the client, or a session row in Redis keyed by cookie. Server memory holds nothing user-specific between requests.
2. File uploads → object storage (S3), never local disk.
3. In-process caches are fine only as *disposable* performance hints — correctness must survive their loss.
4. Scheduled/background work → queues and workers, not "the one server with the cron."
5. Litmus tests: Can you kill any instance mid-traffic with zero user impact? Can a request hit S1 then its successor hit S3? If either answer is no, hunt down the hidden state.
6. Sticky sessions (LB pins user → server) are the escape hatch, not the design: they wreck balance, break on scale-in, and complicate deploys.

### Use It

This is Factor VI of Heroku's *Twelve-Factor App* ("Execute the app as one or more stateless processes") and the assumption baked into Kubernetes Deployments, autoscaling groups, and serverless — Lambda *forces* statelessness by giving you no durable box at all. State then concentrates in the stateful tier (DB, Redis, S3), which is exactly where the hard scaling problems belong — and where phases 4–6 already taught you to fight them.

### War Story

The Twelve-Factor App manifesto (2011, Adam Wiggins and colleagues at Heroku) distilled the operational lessons of running thousands of customer apps into twelve rules, with stateless processes as the load-bearing one. It reads as obvious today precisely because it won: every modern platform's scaling model silently assumes it.

### Checkpoint

- Why do sticky sessions undermine both autoscaling and zero-downtime deploys?
- Where can session data live in a stateless design? Give two options and one tradeoff of each.
- An in-process LRU cache: when is it compatible with statelessness, and what's the rule?

## 03. Load Balancing Algorithms

**MOTTO:** Random spreads load; least-connections follows it; two random choices nearly beats them all.

### The Problem

You have N interchangeable servers and a firehose of requests. Naive assignment goes wrong subtly: pure round-robin ignores that requests differ wildly in cost; a slow server keeps receiving its "fair share" while drowning; and with many independent LBs, everyone's "least loaded server" is the same server, which they promptly stampede.

### The Concept

Supermarket checkout strategies:

```
 round robin        → next lane, in rotation, no looking
 weighted RR        → the express lane gets more customers on purpose
 least connections  → join the shortest queue (needs looking at all lanes)
 hash (user → lane) → same customer, same lane every visit (cache warmth!)
 power of two       → glance at just TWO random lanes, join the shorter
```

The stunner is **power-of-two-choices** (Mitzenmacher's thesis, 1996): with random placement into n bins, the max load is ~O(log n / log log n); merely *comparing two random bins* drops it to O(log log n) — an exponential improvement bought with one extra glance. It also dodges the stampede: different LBs sample different pairs.

### Build It

```python
import random, hashlib
from itertools import cycle

class LB:
    def __init__(self, servers):
        self.servers = servers
        self.rr = cycle(servers)
        self.conns = {s: 0 for s in servers}      # updated on start/finish

    def round_robin(self):       return next(self.rr)
    def least_conn(self):        return min(self.servers, key=self.conns.get)
    def hashed(self, key):       # same key -> same server (until N changes; see consistent hashing)
        return self.servers[int(hashlib.md5(key.encode()).hexdigest(), 16) % len(self.servers)]
    def p2c(self):               # power of two choices
        a, b = random.sample(self.servers, 2)
        return a if self.conns[a] <= self.conns[b] else b
```

Weighted variants scale each server's share by capacity (smooth weighted RR avoids bursts to the big server). Real LBs layer on health checks: an instance failing probes leaves the pool automatically.

### Use It

| Algorithm | Shines when | Weakness |
|---|---|---|
| RR / weighted RR | Uniform, cheap requests | Blind to slow servers |
| Least connections | Long-lived, variable work | Herd behavior across LBs; needs state |
| Hash / consistent hash | Cache locality, session affinity | Hot keys; resharding churn |
| Power of two choices | Almost everywhere | Slightly worse than perfect least-conn with one LB |

NGINX and HAProxy ship all of these; Envoy defaults to P2C for exactly the reasons above; AWS ALB uses round robin or least-outstanding-requests.

### War Story

Michael Mitzenmacher's 1996 PhD thesis "The Power of Two Choices in Randomized Load Balancing" proved the exponential gap between one choice and two. It sat as elegant theory until planet-scale LBs met the herd problem — then P2C became the pragmatic industry default, one of the cleanest cases of a thesis result shipping essentially unchanged into production config files.

### Checkpoint

- Why can plain round-robin overload a degraded server, and which two algorithms fix that?
- Explain the herd problem with least-connections across many LB instances, and why P2C sidesteps it.
- When is hash-based balancing worth its hot-key risk?

## 04. L4 vs L7 Load Balancing

**MOTTO:** L4 forwards envelopes; L7 opens the mail and routes by what it says.

### The Problem

"Load balancer" names two very different machines. One shovels TCP bytes to backends without understanding them — brutally fast, totally blind. The other terminates the connection, parses HTTP, and can route `/api/*` here and `/video/*` there — smart, but it pays for the smarts in CPU and latency. Choosing requires knowing what each layer can *see*.

### The Concept

L4 (transport layer) sees only `(src IP, src port, dst IP, dst port, protocol)` — a mail sorter routing by zip code, never opening envelopes. L7 (application layer) is a receptionist who reads the letter: URL path, Host header, cookies, gRPC method — and can rewrite it, too.

```
 L4:  client ──TCP──▶ [LB: NAT/passthrough] ──TCP──▶ backend
        (one logical connection; LB may not even see responses — DSR)

 L7:  client ──TLS──▶ [LB: terminate, parse HTTP] ──new conn──▶ backend
                        ├─ /api/*   → api-pool
                        ├─ /static/*→ cdn-pool
                        └─ Host: b2b.example.com → tenant-pool
```

Because L7 terminates TLS, it enables header injection (`X-Request-Id`), compression, caching, WAF rules, retries, and canary routing ("5% of traffic → v2") — and because it does, it must hold certificates and touch plaintext.

### Build It

1. L4 mechanics: hash the 5-tuple (or use conn tracking) → pick backend → rewrite destination (NAT) or tunnel; same flow always hits the same backend. Millions of connections per box; often implemented in kernel (IPVS/eBPF) or hardware.
2. L7 mechanics: accept + terminate TLS → read request → apply route table → open/reuse a *pooled* backend connection → proxy bytes both ways → emit rich metrics (status codes, latency percentiles — L4 can't even see a 500).
3. Standard production stack: L4 tier for raw fan-in and DDoS absorption → L7 tier for routing brains → services. Client IP survives termination via `X-Forwarded-For` (HTTP) or the PROXY protocol (TCP).

### Use It

| | L4 | L7 |
|---|---|---|
| Sees | IPs/ports | Full request |
| Speed/scale | Extreme | Merely high |
| Routing | Per-connection | Per-request, content-based |
| TLS | Passthrough | Terminates |
| Examples | AWS NLB, IPVS, Maglev-style | AWS ALB, NGINX, Envoy, HAProxy |

Non-HTTP protocols (raw TCP, game traffic, databases) and passthrough-TLS requirements force L4; microservice routing, canaries, and observability demand L7. Most real systems run both.

### War Story

Google's Maglev paper (NSDI 2016) revealed their software L4 balancer: commodity servers pushing ~10Gbps of small packets *each*, using consistent hashing so connections survive both backend changes and Maglev restarts — proving software on plain machines could replace dedicated LB hardware at planetary scale. The design pattern (ECMP into consistent-hashing L4, then L7 proxies) is now the reference architecture across the industry.

### Checkpoint

- Why is "route /api to pool A" physically impossible for a pure L4 balancer?
- What operational responsibilities appear the moment your LB terminates TLS?
- Sketch the two-tier L4→L7 architecture and state what each tier absorbs.

## 05. Rate Limiting Algorithms

**MOTTO:** Every public endpoint has a rate limit — yours is either designed or discovered during the outage.

### The Problem

One buggy client retry-loops at 5,000 req/s; a scraper harvests your API; a partner's batch job lands at midnight sharp. Without limits, they spend your capacity and everyone else's requests queue behind them. You need a cheap, per-key gate that answers "allow or reject?" in microseconds — with well-understood burst behavior.

### The Concept

Four classic gates:

```
 TOKEN BUCKET   tokens drip in at rate r, cap B; request costs 1 token
                → steady rate r, bursts up to B allowed  ✓ the default
 LEAKY BUCKET   requests enter a queue draining at fixed r
                → perfectly smooth output, bursts wait or spill
 FIXED WINDOW   counter per clock window (100 req/min)
                → cheap; but 100 at 11:59:59 + 100 at 12:00:01 = 200/2s ✗
 SLIDING WINDOW count in the trailing 60s (log = exact, or weighted
                approximation of prev+curr windows = cheap and close)
```

Token bucket is a bus pass that accrues credits: unused credit rolls over (up to a cap), so idle users get a polite burst allowance — usually exactly the behavior you want.

### Build It

The lazy-refill trick — no timers, no background threads; refill on demand:

1. Store per key: `tokens`, `last_refill_ts`.
2. On request: `tokens = min(B, tokens + (now - last) * r)`; `last = now`.
3. If `tokens >= 1`: decrement, allow. Else reject with **429**, plus `Retry-After` so clients back off correctly.
4. Distributed version: state in Redis, steps 2–3 in a Lua script (atomic — no read-modify-write race between app servers). Or shard limits per node and accept small overshoot.
5. Choose keys deliberately: per API key, per user, per IP (careful: NAT), per endpoint — often layered.

### Use It

| Algorithm | Burst handling | Memory | Use |
|---|---|---|---|
| Token bucket | Allows up to B | O(1)/key | APIs (the default) |
| Leaky bucket | Smooths/queues | O(queue) | Traffic shaping, outbound calls |
| Fixed window | 2x edge spike | O(1)/key | Rough quotas, billing periods |
| Sliding window | Accurate | O(1) approx / O(n) exact | Fairness-sensitive limits |

NGINX `limit_req` is leaky-bucket flavored; Stripe has publicly described Redis+Lua token buckets; cloud API gateways (AWS, GCP) quote their throttles in token-bucket terms (rate + burst).

### War Story

GitHub's REST API has enforced token-style limits with `X-RateLimit-*` response headers for over a decade, turning rate limiting into a *published contract* clients can program against — the industry's model for doing throttling transparently instead of mysteriously. The wrong way is famous too: any provider that returns opaque 500s under load teaches its clients to retry harder, manufacturing its own DDoS.

### Checkpoint

- Show the fixed-window boundary exploit with numbers, and name the algorithm that fixes it cheapest.
- In a token bucket, what do r and B independently control?
- Why must the Redis check-and-decrement be atomic, and what implements that?

## 06. Backpressure: Saying No Gracefully

**MOTTO:** A system that can't say "not right now" will eventually say nothing at all.

### The Problem

Producers outpace a consumer. The buffer between them grows; latency climbs from 100ms to 30s; clients time out and *retry* — adding load to a drowning system while the work it finishes is already useless to the callers who gave up. Unbounded queues don't prevent collapse; they schedule it, with interest.

### The Concept

Backpressure is resistance flowing *upstream*: the slow stage tells the fast stage to ease off, all the way back to the origin. A crowded bar doesn't let everyone in to suffocate — the doorman holds a line outside, and people who see the line go elsewhere. Slow, visible refusal at the edge beats silent collapse in the middle.

```
 no backpressure:  source ══▶ [∞ buffer grows...] ─▶ worker  → OOM / zombie latency
 backpressure:     source ◀── "slow down" ── [bounded buf] ─▶ worker
                     │
                     └─▶ options at the full boundary:
                         BLOCK (wait) · DROP (shed) · REJECT (429/503 + Retry-After)
```

Little's Law is the diagnosis tool: L = λW. Queue length L exploding at fixed arrival rate λ means wait W is exploding too — a long queue *is* high latency, made visible.

### Build It

1. Bound every buffer: thread pools, channel sizes, connection pools, inflight-request counts. "Unbounded" is a bug spelled optimistically.
2. Pick the full-buffer policy per stage: block the producer (fine internally), shed load (fine for droppable telemetry), or reject with a retryable status + `Retry-After` (right for edges).
3. Prefer *pull* systems where consumers set the pace — Kafka consumers poll at their own speed; Reactive Streams codifies it as `request(n)` demand signaling; TCP itself does it with the receive window (`rwnd`): the original backpressure.
4. Add **admission control** at the front door: if estimated wait exceeds the client timeout, reject *immediately* — completing a request after its caller hung up is pure waste.
5. Pair with circuit breakers client-side so rejected callers back off instead of hammering.

### Use It

TCP flow control, Reactive Streams (RxJava/Reactor semantics), Go's bounded channels, Envoy/gRPC max-concurrent-streams, and queue-limit knobs on every serious server. The SRE playbook term is *load shedding*; the anti-pattern it prevents is the **metastable failure** / retry storm, where a recovered system is instantly re-drowned by its own clients' queued retries.

### War Story

The AWS Builders' Library essay "Using load shedding to avoid overload" (David Yanacek) describes the death spiral pattern from Amazon's own operational history: as latency passes client timeouts, *goodput* (useful completed work) drops toward zero even while the server runs at 100% throughput — it's diligently completing orphaned requests. The cure is deliberately serving fewer requests to serve them within their deadlines.

### Checkpoint

- Why is an unbounded queue strictly worse than a bounded queue that rejects?
- Explain goodput vs throughput, and how a system can have full throughput and zero goodput.
- Where does TCP implement backpressure, and what signal does it use?

## 07. Autoscaling: Policies and Pitfalls

**MOTTO:** Autoscaling is a thermostat for capacity — and like a thermostat, it's dumb, laggy, and needs margins.

### The Problem

Static capacity is a two-sided loss: provision for the peak and you burn money at 3 a.m.; provision for the average and you fall over at the peak. Autoscaling promises capacity that tracks load — but it's a feedback controller with minutes of lag bolted onto traffic that spikes in seconds, and misconfigured feedback controllers *oscillate*.

### The Concept

A thermostat: sense (metric) → compare (target) → actuate (add/remove instances) → wait for effect (boot time) → repeat. Everything hard about autoscaling is in the "wait": scaling out takes 1–5+ minutes (boot, pull, warm caches, pass health checks), so the controller is always steering with stale data.

```
 load  ▲      ╭──spike──╮
       │     ╱           ╲                    ← traffic moves in seconds
 cap   │....╱─┐        ┌──╲....               ← capacity moves in minutes
       │      └─ lag! ─┘        ← this gap = your 5xx errors
       └───────────────────────▶ t
 defenses: headroom target (~60-70%), scale-out fast / scale-in slow,
           cooldowns, min instances, predictive/scheduled scaling
```

### Build It

1. **Metric**: CPU is the lazy default; requests-per-instance or queue depth usually track user pain better. For worker fleets, scale on backlog: `desired = ceil(queue_depth / per_instance_throughput)`.
2. **Target tracking** beats step rules: "hold CPU near 65%" — the 35% headroom is the buffer that absorbs load during boot lag.
3. **Asymmetry**: scale out aggressively (add 50% at once), scale in timidly (remove 10%, long cooldown). Adding too much wastes cents; removing too much causes an incident.
4. **Pitfalls checklist**: flapping (thresholds too close → add cooldowns/hysteresis); scaling on the wrong metric (CPU fine while connection pool is exhausted); the *downstream squeeze* (10x web tier pointed at the same poor database — autoscaling forwards the stampede); cost runaways (set max); and metric death spirals (unhealthy hosts leave the pool → survivors' CPU rises → scale-out of more instances that fail the same way).
5. For known cliffs (product launch, 9 a.m. login wave), use scheduled/predictive scaling — reacting is already too late.

### Use It

AWS Auto Scaling Groups (target tracking, predictive), Kubernetes HPA (metric-based pod scaling; VPA for right-sizing; cluster autoscaler for nodes), serverless (scaling *is* the platform, with cold starts as the lag tax). Universal knobs: min (never scale to a size that can't absorb a surprise), max (never scale to a size that bankrupts you).

### War Story

Every retail engineering blog tells the same story in different clothes: the Black Friday / flash-sale spike that outran reactive autoscaling, because a 10x surge in 60 seconds meets instances that take 3 minutes to boot. The survivors' consensus: pre-scale on schedule for known events, keep real headroom for unknown ones, and treat autoscaling as cost optimization for the slow curves — not as your surge protection.

### Checkpoint

- Why does boot lag force you to target ~65% utilization instead of 90%?
- Why should scale-out and scale-in policies be asymmetric?
- Your web tier autoscales beautifully and the site still falls over. Name two places the bottleneck moved to.

## 08. The Database Scaling Playbook

**MOTTO:** Indexes, then replicas, then cache, then shard — each step only after the previous one is exhausted.

### The Problem

The database is nearly always the first thing to die: it's stateful (can't just clone it like an app server), it's shared (every feature's queries land there), and it's easy to abuse (one missing index = 10,000x more IO). Panicking straight to "we must shard" commits you to the most expensive option while a `CREATE INDEX` was sitting right there.

### The Concept

An escalation ladder — each rung is ~10x more operational pain than the last, so you climb only when forced:

```
 1. INDEXES & QUERY TUNING   free 10-1000x. EXPLAIN first, always.
 2. READ REPLICAS            scale reads; writes still single-node
 3. CACHE                    keep repeat reads off the DB entirely
 4. VERTICAL BUMP            (cheap interlude — buy the bigger box)
 5. SHARD                    scale writes; pay with complexity forever
```

Rungs 2–3 exploit the near-universal skew: most apps read 10–1000x more than they write. Only genuine *write* saturation (or data too big for one box) justifies rung 5.

### Build It

1. **Indexes**: `EXPLAIN ANALYZE` the slow-query log; kill sequential scans on big tables; use composite indexes matching your `WHERE`+`ORDER BY`; remember each index taxes every write. Also: fix N+1 queries — no index saves you from 500 round trips.
2. **Read replicas**: async replication → route reads to replicas, writes to primary. New problem: **replication lag** — read-your-own-writes breaks. Mitigations: pin post-write reads to primary for N seconds, or session "seen-LSN" tokens.
3. **Cache** (phase 6 in anger): cache-aside with TTLs on hot reads; protect against stampedes; accept staleness explicitly.
4. **Shard**: pick a partition key that (a) spreads load evenly and (b) matches your dominant access pattern — usually tenant/user ID. Consequences signed for at the register: no cross-shard joins or transactions, scatter-gather queries, hot-shard rebalancing, resharding migrations. Prefer hash-on-key with consistent hashing or directory-based lookup (phase 5 covers the mechanics).
5. At every rung, re-measure. The bottleneck moves; the playbook restarts.

### Use It

| Rung | Tools |
|---|---|
| Indexes | EXPLAIN, pg_stat_statements, slow-query log |
| Replicas | Postgres/MySQL streaming replication, RDS read replicas, ProxySQL/pgbouncer routing |
| Cache | Redis, Memcached |
| Shard | Vitess (YouTube-born, MySQL), Citus (Postgres), app-level sharding; or "NewSQL" (Spanner, CockroachDB) that shards for you |

### War Story

YouTube scaled MySQL through exactly this ladder, and when they finally had to shard, they built the routing/resharding layer as software — Vitess — which they open-sourced and which now also runs Slack's and GitHub's* MySQL fleets (*GitHub adopted Vitess for parts of its infrastructure). The lesson isn't "use Vitess"; it's that even YouTube-scale traffic went through replicas-and-caching first, and sharding was the last resort productized.

### Checkpoint

- Why does adding read replicas do nothing for write throughput?
- What is replication lag, and give one concrete fix for the "I posted a comment and it vanished" bug it causes.
- Name two capabilities you permanently give up (or must re-implement) when you shard.

## 09. Fan-Out: Push vs Pull

**MOTTO:** Precompute for the many, compute-on-read for the mighty.

### The Problem

A social feed: each user follows hundreds of accounts and expects a merged, ranked timeline in ~100ms. Compute it at read time and you're doing a scatter-gather over hundreds of authors per page load. Precompute it at write time and one celebrity posting to 100M followers triggers 100M timeline inserts — for a single tweet. Both pure strategies die; they just die at opposite ends.

### The Concept

- **Push (fan-out on write)**: when Alice posts, insert the post ID into every follower's precomputed inbox. Reads are a cheap list fetch. Like mailing a newsletter to every subscriber's mailbox.
- **Pull (fan-out on read)**: store the post once; when Bob opens the app, fetch recent posts from everyone he follows and merge. Like Bob walking the newsstand row himself.

```
 PUSH: post ─▶ [fanout workers] ─▶ inbox(u1), inbox(u2)...inbox(uN)   write O(N), read O(1)
 PULL: post ─▶ [author timeline] ◀── merge at read ◀── follower       write O(1), read O(follows)

 HYBRID (what everyone actually ships):
   normal author (N small)  → PUSH to follower inboxes
   celebrity (N huge)       → don't fan out; followers PULL & merge at read
```

### Build It

1. Inboxes live in something cheap to append and range-read: Redis lists/sorted-sets or a wide-column store — capped (say, latest 800 entries) since nobody scrolls forever.
2. Fan-out runs async via queue workers (phase 7!): the post write returns fast; inbox delivery is eventually consistent, and a few seconds of delay is invisible in a feed.
3. Set a celebrity threshold (e.g., >100k followers): their posts skip fan-out. Read path = fetch inbox + fetch celebrity authors' recent posts + merge + rank.
4. Extra wrinkles you'll meet: unfollow (lazily filter at read vs eagerly delete), delete-post (tombstone check at read beats 100M deletes), inactive users (don't push to accounts dormant for months — pull on their return).

### Use It

Twitter's timeline is the canonical hybrid; Instagram and feed-style products follow the same shape. The pattern generalizes far beyond feeds: notification delivery, materialized views vs query-time joins, CDN pre-warm vs cache-on-miss — always the same ledger: write amplification vs read amplification, weighted by your read/write ratio and your skew.

### War Story

Twitter's engineers have discussed the architecture publicly for years (notably Raffi Krikorian's "Timelines at Scale" talk, 2012–13): home timelines are precomputed in a Redis-backed store by fan-out workers, delivering a large multiple of write amplification in exchange for O(1) reads — with the highest-follower accounts special-cased out of fan-out and merged at read time. The celebrity problem is real enough that it named the pattern.

### Checkpoint

- Express push and pull costs in big-O per post and per feed-read, and identify which variable each strategy fears.
- Why is asynchronous fan-out acceptable for feeds when it wouldn't be for a bank balance?
- In the hybrid model, describe the full read path for a user following 300 normals and 2 celebrities.

## 10. Bloom Filters and Probabilistic Data Structures

**MOTTO:** Trade a pinch of certainty for a mountain of memory.

### The Problem

"Have I seen this URL before?" across 10 billion URLs. "How many distinct visitors today?" across a firehose. Exact answers need hash sets holding every element — hundreds of GB. But your actual requirement is "roughly right, tiny, and fast" — and there's a family of structures that buys exactly that with controlled, one-sided error.

### The Concept

A **Bloom filter** is a bouncer with a fuzzy memory for faces: he *never* forgets someone he's seen (no false negatives), but occasionally "recognizes" a stranger (false positives). Mechanically: a bit array of m bits and k hash functions; insert sets k bits, query checks k bits.

```
 insert("cat"): h1→2, h2→9, h3→13     bits: 0010000001000100...
 query("dog"):  h1→2, h2→5 → bit 5 is 0 → DEFINITELY NOT PRESENT
 query("owl"):  all k bits happen to be 1 → PROBABLY present (maybe false +)

 tuning: ~10 bits/element + k≈7 hashes ⇒ ~1% false positives. Ten. Bits. Per. Element.
```

Cousins: **Count-Min Sketch** — a 2D counter array (k rows, one hash each); increment k cells, read the *min* — approximate frequency counts that only ever over-estimate. **HyperLogLog** — estimates distinct-count from the maximum number of leading zero bits seen per bucket (a hash with many leading zeros is rare, so seeing one implies many distinct values); counts billions of uniques in ~1.5KB at ~2% error.

### Build It

```python
import hashlib

class Bloom:
    def __init__(self, m, k):
        self.m, self.k, self.bits = m, k, bytearray(m // 8 + 1)
    def _hashes(self, item):
        h = hashlib.sha256(item.encode()).digest()
        h1, h2 = int.from_bytes(h[:8], "big"), int.from_bytes(h[8:16], "big")
        return [(h1 + i * h2) % self.m for i in range(self.k)]   # double hashing: k hashes from 2
    def add(self, item):
        for b in self._hashes(item): self.bits[b // 8] |= 1 << (b % 8)
    def might_contain(self, item):
        return all(self.bits[b // 8] >> (b % 8) & 1 for b in self._hashes(item))
```

Sizing: false-positive rate ≈ (1 − e^(−kn/m))^k; optimal k = (m/n)·ln 2. Limits to respect: no deletion from a vanilla Bloom (bits are shared — use counting Bloom or cuckoo filters), and no enumeration of members ever.

### Use It

| Structure | Question | Error mode | Famous user |
|---|---|---|---|
| Bloom filter | membership? | false positives only | LSM stores (Cassandra, RocksDB) skip SSTables that can't contain the key |
| Count-Min | frequency? | overcount only | heavy-hitter / trending detection |
| HyperLogLog | how many distinct? | ~2% either way | Redis `PFCOUNT`, analytics uniques |

Also: CDNs caching only on second request (Bloom of first-seens), safe-browsing style local prefilters, and crawlers deduping URLs.

### War Story

Burton Bloom published the filter in 1970 ("Space/Time Trade-offs in Hash Coding with Allowable Errors") — half a century later it's load-bearing in nearly every LSM-tree database, quietly eliminating disk reads for absent keys. HyperLogLog (Flajolet et al., 2007) got its production close-up when Redis added `PFADD`/`PFCOUNT` (the "PF" honors Philippe Flajolet), and Google's "HyperLogLog in Practice" paper (2013) described hardening it for BigQuery-scale counting.

### Checkpoint

- Why does a Bloom filter's one-sided error (no false negatives) make it perfect as a *pre-filter* in front of an expensive lookup?
- Why can't you delete from a standard Bloom filter, and what variant permits it?
- Your product needs exact daily uniques for billing. HyperLogLog: yes or no, and why?

## 11. Build a Rate Limiter From Scratch

**MOTTO:** Two floats per user — that's the whole secret.

### The Problem

Lesson 05 gave you the theory; production wants code. Requirements: per-key token bucket, O(1) memory per key, microsecond decisions, no background refill threads, thread-safe, and honest `Retry-After` hints. Build it, test the burst behavior, then distribute it.

### The Concept

The insight that removes all machinery: you don't need a timer topping up buckets — tokens are a *function of elapsed time*. Refill lazily at request time: `tokens += (now − last_checked) × rate`, capped at burst. The bucket is just `(tokens, last_ts)`. Two floats.

```
 t=0.0  bucket: 5.0/5   ████████ burst of 5 → all allowed, tokens: 0.0
 t=0.1  request        → refill 0.1s×2/s = +0.2 → 0.2 tokens → REJECT (retry in 0.4s)
 t=0.6  request        → refill +1.0 → 1.2 → allow → 0.2
 (rate r=2/s: sustained pace;  burst B=5: forgiveness for idleness)
```

### Build It

```python
import time, threading

class TokenBucket:
    def __init__(self, rate: float, burst: float):
        self.rate, self.burst = rate, burst
        self.tokens, self.last = burst, time.monotonic()   # start full; MONOTONIC, never wall clock
        self.lock = threading.Lock()

    def allow(self, cost: float = 1.0):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= cost:
                self.tokens -= cost
                return True, 0.0
            return False, (cost - self.tokens) / self.rate   # honest Retry-After seconds

class RateLimiter:
    def __init__(self, rate=10, burst=20):
        self.buckets, self.lock = {}, threading.Lock()
        self.rate, self.burst = rate, burst
    def check(self, key: str):
        with self.lock:
            b = self.buckets.setdefault(key, TokenBucket(self.rate, self.burst))
        return b.allow()

limiter = RateLimiter(rate=10, burst=20)
ok, retry_after = limiter.check("api_key_123")
# → HTTP 200, or HTTP 429 with Retry-After: math.ceil(retry_after)
```

Exercises: (1) verify burst semantics — 20 instant allows, then ~10/s; (2) evict idle buckets (an LRU or periodic sweep — unbounded keys is a memory leak shaped like a dict); (3) add per-endpoint costs (`cost=5` for the expensive search route); (4) port `allow()` into a Redis Lua script — `HGETALL`, compute, `HSET`, all atomic server-side — and you have the Stripe-style distributed limiter.

### Use It

This exact shape ships everywhere: Guava's `RateLimiter`, Envoy's local rate limit filter, Go's `golang.org/x/time/rate`. The Redis-Lua port is the standard multi-node answer; the alternative — per-node limits summing to the global budget — trades accuracy for zero coordination.

### War Story

Stripe's engineering blog ("Scaling your API with rate limiters," 2017) described running exactly this: Redis-backed token buckets plus concurrency limiters, and — the underrated detail — *shadow mode first*: log would-be rejections without enforcing, tune thresholds against reality, then flip on enforcement. Limits deployed blind at guessed thresholds throttle your best customers on day one.

### Checkpoint

- Why must the bucket use a monotonic clock, and what specific bug does a wall clock introduce?
- Where in the code do "sustained rate" and "burst tolerance" live, and how would you observe each in a test?
- What breaks when this in-process limiter meets 12 app servers, and what are the two standard fixes?

## 12. Build a Load Balancer From Scratch

**MOTTO:** A load balancer is a proxy, a picker, and a health checker in a trench coat.

### The Problem

Capstone time. Lessons 03–04 covered picking algorithms and layers; now assemble a working L7 balancer: accept requests, choose a healthy backend (round-robin or least-connections), forward, count in-flight connections honestly, and stop sending traffic to dead backends — the essential anatomy of NGINX/HAProxy in ~70 lines of Python.

### The Concept

Three loops sharing one piece of state (the backend pool):

```
                    ┌──────────── LB ────────────┐
 client ──req──▶    │ [1] picker: choose backend │ ──proxied req──▶ [B1]
        ◀──resp──   │ [2] proxy: forward + count │                  [B2]
                    │ [3] health loop (async):   │ ──/health──▶     [B3 ✗ OUT]
                    │     probe, evict, restore  │
                    └────────────────────────────┘
 invariant: conns[b] incremented BEFORE forwarding, decremented in finally:
 (lie about in-flight counts and least-conn becomes least-truthful)
```

### Build It

```python
import itertools, threading, time, requests

class Pool:
    def __init__(self, backends):
        self.backends = list(backends)
        self.healthy = set(backends)
        self.conns = {b: 0 for b in backends}
        self.rr = itertools.cycle(self.backends)
        self.lock = threading.Lock()

    def pick_rr(self):
        with self.lock:
            for _ in range(len(self.backends)):          # skip unhealthy, at most one full lap
                b = next(self.rr)
                if b in self.healthy: return b
        raise RuntimeError("no healthy backends")        # 503 territory

    def pick_least_conn(self):
        with self.lock:
            live = [b for b in self.backends if b in self.healthy]
            if not live: raise RuntimeError("no healthy backends")
            return min(live, key=lambda b: (self.conns[b], b))

    def health_loop(self, interval=2.0):
        while True:
            for b in self.backends:
                try:
                    up = requests.get(f"{b}/health", timeout=1.0).status_code == 200
                except requests.RequestException:
                    up = False
                with self.lock:
                    (self.healthy.add if up else self.healthy.discard)(b)
            time.sleep(interval)

def handle(pool, method, path, body=None, headers=None):
    b = pool.pick_least_conn()
    with pool.lock: pool.conns[b] += 1
    try:
        return requests.request(method, f"{b}{path}", data=body,
                                headers=headers, timeout=5.0)
    finally:
        with pool.lock: pool.conns[b] -= 1

pool = Pool(["http://127.0.0.1:9001", "http://127.0.0.1:9002", "http://127.0.0.1:9003"])
threading.Thread(target=pool.health_loop, daemon=True).start()
# wrap handle() in any HTTP server (http.server / Flask) and you have an L7 LB
```

Exercises, escalating: (1) run 3 `python -m http.server` backends, kill one mid-load, watch traffic reroute within ~2s; (2) add passive health (N consecutive proxy failures → evict) alongside active probes; (3) require M consecutive probe *successes* before restoring a backend (flap damping); (4) add retry-on-failure to a *different* backend — but only for idempotent methods (GET yes, POST no — you learned why in phase 7); (5) implement P2C from lesson 03 in three lines and A/B it against least-conn under skewed load.

### Use It

Every piece maps upward: `health_loop` → NGINX health checks / ALB target health; `conns` → HAProxy's `leastconn` state; the pick-then-forward-then-decrement dance → what Envoy does per request with vastly better concurrency machinery (thread-local pools, connection reuse, outlier detection = your exercise 2, productized). What the toy omits is the hard 20%: connection pooling, streaming bodies, TLS, zero-downtime config reload, and surviving 100k concurrent connections.

### War Story

HAProxy — started by Willy Tarreau around 2000 as a small event-driven proxy — grew into the LB fronting a substantial slice of the internet (GitHub and Airbnb are among its publicly known users), all from the loop you just wrote: accept, pick, forward, count, probe. Envoy repeated the trick at Lyft in 2016 and became the data plane of the service-mesh era. The pattern is small; the polish is the product.

### Checkpoint

- Why must the connection count be decremented in a `finally` block, and what does least-conn degrade into if you leak counts?
- Why should automatic retries be restricted to idempotent requests?
- What's the argument for requiring M consecutive successes before restoring an evicted backend?
