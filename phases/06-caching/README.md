# Phase 06 — ⚡ Caching

> The two hardest problems: naming, caching, and off-by-one errors.

Caching is the closest thing systems engineering has to a cheat code: answer the question before doing the work, and suddenly your database sleeps through the traffic spike. But every cache is a copy, and every copy can lie — stale reads, stampedes, and invalidation bugs are the tax on free speed. This phase teaches you to collect the speed and dodge the tax. By the end you'll build an O(1) LRU cache with your own hands and understand why Phil Karlton's joke in the tagline never stops being funny.

## 01. Why caching works: locality and the 80/20 rule

**MOTTO:** The future looks suspiciously like the recent past — bet on it.

### The Problem

Your database answers a query in 5ms. At 50,000 requests/sec, that's 250 CPU-seconds of work per wall-clock second — a farm of database servers grinding out answers that are *mostly identical*. The same hot articles, the same user sessions, the same product pages, recomputed millions of times. Paying full price for repeated questions is the single most common performance sin.

### The Concept

Caching works because access patterns are not uniform — they're wildly, reliably skewed. Two flavors of **locality** do the heavy lifting: *temporal* (what was just accessed will be accessed again — today's viral post) and the Zipfian **80/20 rule** (a tiny fraction of keys gets the vast majority of traffic; in real workloads it's often closer to 90/10). A small, fast copy of the hot set absorbs most requests.

```
Requests by key popularity (Zipf):
#1  ████████████████████████████  ← a few celebrities...
#2  ██████████████
#3  █████████
#10 ███
#1000 ▏                          ← ...and a long, cold tail

Cache the top 1% of keys → serve ~most of the traffic from RAM.
```

The math that governs everything: `avg_latency = hit_rate × t_cache + (1 − hit_rate) × t_miss`. And the memory hierarchy sets the stakes: L1 ~1ns, RAM ~100ns, SSD ~100µs, cross-datacenter ~ms — each layer is a cache for the one below.

### Build It

1. Measure before caching: log key frequencies for a day; plot the distribution. No skew → caching won't save you (uniform random access is the cache-killer).
2. Size for the **working set**, not the dataset: the hot 1–5% of keys, not all of them.
3. Compute the win: 95% hit rate on a 1ms cache vs 20ms DB = 0.95×1 + 0.05×20 = **1.95ms average** — a 10× improvement, and the DB sees 20× fewer queries.
4. Now compute the fragility: the same math says going from 95%→90% hit rate *doubles* your database load. Hit rate is a load-bearing number; alert on it.
5. Know what you're buying with what: caching trades memory and *freshness* for latency and origin offload. The freshness bill arrives in Lesson 07.

### Use It

| Layer | Cache | Typical latency |
|---|---|---|
| CPU | L1/L2/L3 | ns |
| App process | in-memory dict/Caffeine | ~100ns |
| Fleet-shared | Redis/Memcached | ~0.2–1ms |
| Edge | CDN | ~10–50ms to user |
| Client | browser cache | 0 network |

Every layer is the same idea; only the eviction policy and invalidation story change.

### War Story

Facebook's 2013 paper "Scaling Memcache at Facebook" (NSDI) revealed the scale of the bet: billions of requests per second served from memcached fleets, with the databases surviving *only because* the cache absorbed the overwhelming majority of reads. The paper is this phase's syllabus in field-report form — leases, stampedes, invalidation pipelines — written by the people who hit every failure mode first at world scale.

### Checkpoint

- Why does a uniform random access pattern make caching nearly useless, regardless of cache size?
- Your cache hit rate drops from 98% to 96%. Why might the database team page you about a 2% change?
- What's the difference between the working set and the dataset, and which one sizes the cache?

## 02. Cache patterns: aside, through, back, ahead

**MOTTO:** The pattern you pick decides who does the work and who eats the loss.

### The Problem

"Add a cache" is not a design. Who fills the cache — the application or the cache itself? Do writes go to the cache, the database, or both? What happens when the cache dies with un-persisted data inside? Four canonical patterns answer these questions differently, and mixing them up produces either stale data or lost data.

### The Concept

Think of a barista (cache) fronting a slow roastery (database):

```
CACHE-ASIDE      app checks shelf; on miss, app fetches from
 (lazy)          roastery and stocks the shelf itself
READ-THROUGH     app only ever talks to barista; barista
                 fetches from roastery on miss
WRITE-THROUGH    every order written to shelf AND roastery,
                 synchronously — slow writes, safe data
WRITE-BACK       write to shelf only; barista batches deliveries
 (write-behind)  to roastery later — fast writes, risky shelf
WRITE-AHEAD/     stock the shelf BEFORE the rush (warming,
 REFRESH-AHEAD   predictive refresh before TTL expiry)
```

### Build It

Cache-aside, the pattern you'll write 100 times — with its two classic mistakes:

1. Read path: `get(key)` → hit? return. Miss? read DB, `set(key, value, ttl)`, return.
2. Write path: write DB, then **delete** (don't update!) the cache key. Updating risks writing a stale value computed from a pre-write read; delete forces a fresh reload.
3. Mistake #1 — write cache *before* DB commit: a rollback leaves the cache confidently wrong.
4. Mistake #2 — the race: reader misses, reads DB (old value); writer updates DB, deletes cache; reader then sets its stale value with a long TTL. Rare but real; mitigations: short TTLs as a backstop, or versioned/CAS sets.
5. Write-back checklist, if you dare: replicate the cache (data exists *only* there until flush), bound the flush lag, and answer "what breaks if this buffer dies?" before enabling it. This is how CPU caches and many storage engines work — with battery-backed rigor.

### Use It

| Pattern | Best for | Failure cost |
|---|---|---|
| Cache-aside | general reads (the default) | stale window, miss latency |
| Read-through | uniform access, simpler apps | library/provider coupling |
| Write-through | read-heavy, must-be-fresh reads | slower writes |
| Write-back | write-heavy bursts (counters, metrics) | **data loss** on cache death |
| Refresh-ahead | predictable hot keys, TTL cliffs | wasted refreshes if predictions miss |

DAX (DynamoDB Accelerator) is read-through/write-through as a product; Redis with app logic is usually cache-aside; CPU L1/L2 are write-back with hardware guarantees.

### War Story

The delete-vs-update subtlety is a rite of passage: a fintech startup once cached account balances with update-on-write, and a rollback-after-cache-update plus a race under load left customers staring at money that didn't exist — the incident review's one-line fix was "write DB first, then *invalidate*." The pattern is folklore because nearly every team has a version of this story.

### Checkpoint

- In cache-aside, why is delete-on-write safer than update-on-write?
- Which pattern can lose committed-from-the-user's-perspective data, and what two safeguards make it tolerable?
- Trace the stale-set race in cache-aside: what interleaving of reader and writer produces a long-lived stale entry?

## 03. Eviction policies: LRU, LFU, and friends

**MOTTO:** A cache is defined less by what it keeps than by what it dares to throw away.

### The Problem

The cache is full — it's *supposed* to be full; empty cache RAM is wasted RAM. Every new entry now requires evicting an old one, and the choice is a prophecy: evict something needed in 10ms and you bought a miss; evict something never needed again and it was free. Picking the victim well is the entire intellectual content of caching's second half.

### The Concept

The theoretical optimum (Bélády's algorithm, 1966): evict the entry whose next use is *farthest in the future*. It requires clairvoyance, so real policies are bets on different prophecies:

```
LRU   "longest unused → least likely needed"   recency bet
LFU   "rarely used → rarely needed"            frequency bet
FIFO  "oldest → stalest"                       no bet, cheap
Random "¯\_(ツ)_/¯"                            shockingly OK

LRU's nightmare — the sequential scan:
  cache size 3, access A B C D A B C D ...
  every access evicts exactly what's needed next. 0% hits.
  (One nightly batch job table-scans → wipes your hot set.)
```

LFU's nightmare is the opposite: yesterday's viral post has a huge count and squats in the cache forever ("cache pollution") unless frequency *ages* (decays over time).

### Build It

1. **LRU:** hash map + doubly linked list; move-to-front on access, evict the tail. O(1) everything. (You'll build it in Lesson 10.)
2. **LRU-K / segmented LRU:** demand *two* touches before an entry earns protected status — one-hit-wonders (scans!) die in the probation segment. This one tweak fixes most of LRU's nightmare.
3. **LFU with aging:** counters that halve periodically, so old fame decays.
4. **TinyLFU / W-TinyLFU (Caffeine):** keep approximate frequency in a Count-Min Sketch (tiny memory); on admission, the *candidate must beat the victim's* frequency to get in at all — an admission policy, not just eviction. Near-optimal hit rates in practice.
5. **Redis's trick:** true LRU needs a global list; Redis instead *samples* N random keys (default 5) and evicts the least-recent among them — approximate LRU at a fraction of the bookkeeping, and the paper-worthy insight is that it's nearly as good.

### Use It

| Policy | Used by | Watch out |
|---|---|---|
| LRU (approx) | Redis, page caches, browsers | scan pollution |
| W-TinyLFU | Caffeine (JVM) | complexity |
| SLRU / segmented | memcached, many CDNs | tuning segment sizes |
| TTL + LRU hybrid | almost everyone | TTL ≠ eviction (freshness vs space — different jobs!) |

Redis exposes the menu directly: `maxmemory-policy allkeys-lru | allkeys-lfu | volatile-ttl | allkeys-random ...` — a config line that is secretly this whole lesson.

### War Story

Bélády's 1966 IBM paper proved the clairvoyant optimum that every real policy is measured against — and decades of research later, the ARC paper (IBM, 2003) and W-TinyLFU (2015) were still finding meaningful hit-rate wins over plain LRU, which is why your JVM's Caffeine cache outperforms the LinkedHashMap you almost used. Sixty years on, "what to evict" remains a live research area.

### Checkpoint

- Construct the smallest access pattern where LRU achieves 0% hits but LFU does well.
- What is cache pollution under LFU, and what mechanism cures it?
- Why does Redis's sampled eviction exist, and what does true LRU cost that Redis refuses to pay?

## 04. Redis internals

**MOTTO:** One thread, in-memory data structures, and the audacity to be enough.

### The Problem

You know Redis as "the cache." But treating it as a dumb key-value shelf wastes the interesting 80%: why is a (mostly) single-threaded server serving hundreds of thousands of ops/sec? How does in-memory data survive restarts? What actually happens when memory runs out mid-write? Using Redis well requires knowing what it is under the hood.

### The Concept

Redis is a data-structure server: not `get/set` on strings, but lists, hashes, sets, sorted sets, streams, bitmaps, HyperLogLogs — served from RAM by an **event loop**. Single-threading is a feature: no locks, no races, every command atomic by construction. Commands are so fast (RAM + O(1)/O(log N) structures) that one core saturates the network before it saturates itself.

```
clients ──> epoll event loop ──> execute command (atomic, alone)
                                   │
     ┌─ persistence ───────────────┤
     │  RDB: periodic fork() → child snapshots (copy-on-write)
     │  AOF: append every write command; fsync per policy
     └─ replication: async stream of the write commands
```

### Build It

1. **Event loop:** one thread multiplexes all sockets (epoll/kqueue); each command runs to completion. Corollary: one slow command (`KEYS *`, `SMEMBERS` on 10M items) blocks *everyone* — Redis's famous foot-gun. (Redis 6+ moved I/O to helper threads; command execution stays single-threaded.)
2. **Encodings:** small collections are stored as packed arrays (listpack/ziplist) and silently upgrade to hash tables/skip lists as they grow — memory frugality via adaptive representation. Sorted sets = skip list + hash map.
3. **Persistence:** RDB snapshots via `fork()` — copy-on-write means the child sees a frozen image while the parent keeps serving (cost: memory spikes under heavy writes). AOF logs every write command — Phase 4's WAL wearing a Redis costume; `appendfsync everysec` is the popular durability/speed compromise. Rewrites compact the AOF.
4. **Expiry:** lazy (checked on access) + active (periodic random sampling of keys with TTLs) — expired keys can linger invisibly.
5. **Memory pressure:** at `maxmemory`, the Lesson-03 eviction policies engage — or with `noeviction`, writes fail. Know which one you configured *before* the incident.
6. **Cluster:** 16384 hash slots, keys routed by CRC16(key) mod 16384, resharding moves whole slots (Phase 5, Lesson 06 in miniature).

### Use It

| Capability | Structure |
|---|---|
| Leaderboards | sorted sets (ZADD/ZRANGE) |
| Rate limiting | INCR + EXPIRE, or Lua for atomicity |
| Distributed locks | SET NX EX (+ caveats; Redlock debates) |
| Queues/streams | lists (BRPOP), Streams (consumer groups) |
| Unique counts at scale | HyperLogLog (~12KB for ~1% error) |

Rule: if you're storing JSON blobs and parsing them client-side to update one field, you wanted a hash. Use the structures.

### War Story

Salvatore Sanfilippo ("antirez") wrote Redis in 2009 to speed up a startup's real-time analytics and ran the project largely as a solo maintainer for a decade — an entire industry's cache layer resting on one person's C code and famously readable comments. He stepped down from maintainership in 2020; the subsequent licensing turbulence (and the Valkey fork in 2024, backed by the Linux Foundation) made Redis a case study in open-source governance as well as engineering.

### Checkpoint

- Why does single-threaded execution make every Redis command atomic, and what's the dark side of that design?
- Contrast RDB and AOF: what can each lose, and what does each cost at runtime?
- Why is `KEYS *` in production a career-limiting command, and what should be used instead?

## 05. Memcached vs Redis

**MOTTO:** One is a Swiss Army knife; the other is a single, perfect blade.

### The Problem

Two mature, battle-proven in-memory caches; every architecture review asks which. The lazy answer is "Redis, it does more." But "does more" is not "is better for this job" — Memcached's ruthless minimalism buys real advantages (simplicity, multithreading, flat predictable memory), and knowing when those matter is the actual skill.

### The Concept

Memcached is a valet stand: tickets in, coats out, blazing fast, zero opinions — and it does nothing else, by design (that's the philosophy, stated in its own docs since 2003). Redis is a workshop: structures, persistence, replication, scripting — a toolbox that can *also* hang coats.

```
                Memcached            Redis
Threads         multithreaded        single-threaded core
Values          opaque blobs         rich data structures
Persistence     none, ever           RDB / AOF optional
Replication     none built in        built in (+ Sentinel/Cluster)
Memory          slab allocator,      per-structure encodings,
                low overhead, flat   fragmentation possible
Scale-out       client-side hashing  Redis Cluster (16384 slots)
                (ketama rings!)
Eviction        LRU per slab class   pluggable policies
```

### Build It

Decide like an engineer — walk the checklist:

1. **Pure ephemeral cache** (HTML fragments, DB rows, sessions-you-can-lose)? Memcached's multithreading exploits big multi-core boxes with zero tuning; a restart just means a cold cache. Its slab allocator (fixed-size chunk classes) trades some memory to *eliminate* fragmentation surprises.
2. **Need any structure** — counters with expiry, leaderboards, queues, pub/sub, atomic multi-step ops (Lua)? Redis, no contest.
3. **Cache warm-up is expensive** (cold cache = database meltdown)? Redis persistence/replication turns restarts from incidents into non-events. Memcached's answer is "don't restart everything at once."
4. **Very large values / very high throughput on one box?** Memcached's threading historically wins raw multi-core throughput; Redis answers with multiple instances per host or Cluster.
5. Either way, client-side consistent hashing (Phase 5, Lesson 05!) across N nodes is how Memcached fleets scale — the ring you built is literally this.

### Use It

| Scenario | Pick |
|---|---|
| Session cache behind stateless web tier | either; Memcached if truly disposable |
| Rate limiter, leaderboard, locks | Redis |
| Massive flat lookaside cache (FB-style) | Memcached |
| Cache that must survive restart | Redis |
| "We might need queues later" | Redis (resist using it as your only queue) |

Reality check: many shops run Redis for everything simply to operate one system — a legitimate ops-simplicity argument that beats micro-benchmarks.

### War Story

Memcached was created in 2003 by Brad Fitzpatrick to keep LiveJournal's databases alive, and its greatest testimonial is Facebook's memcached fleet (the NSDI 2013 paper from Lesson 01) — arguably the largest cache deployment ever described publicly, built on the "simple opaque blobs, client-side smarts" philosophy. Redis, six years younger, won the default-choice crown; Memcached still quietly serves a staggering share of the web's lookaside traffic.

### Checkpoint

- Name two concrete workloads where Memcached is the *stronger* choice, and why.
- How does each system approach multi-node scale-out, and where does the intelligence live in each?
- Why can "no persistence" be an availability *risk* for a cache, not just a durability footnote?

## 06. CDNs: caching at the edge of the world

**MOTTO:** The fastest request is the one that never crosses an ocean.

### The Problem

Your servers are in Virginia. Your user is in Jakarta. Every image, script, and video chunk pays a ~200ms+ round trip — and no amount of server tuning fixes the speed of light. Worse, a viral moment sends a million users after the same files, and your origin melts serving identical bytes. Both problems have one answer: put copies *near the users*.

### The Concept

A CDN is a chain of convenience stores fronting one distant warehouse. Each store (edge PoP — point of presence) stocks whatever locals actually buy; only a stock-out (cache miss) triggers a warehouse trip. Users are steered to the nearest store automatically — via anycast (one IP, BGP routes you to the closest PoP) or DNS-based mapping.

```
user (Jakarta) ─5ms─> edge PoP Jakarta ──miss?──> regional/shield PoP
                        │ hit: done                    │ miss?
                        v                              v
                     cached copy               origin (Virginia)

Tiered caching: N edges collapse onto 1 shield → origin sees ~1 miss,
not N. (Request coalescing at the shield — Lesson 08 foreshadowed.)
```

The control knobs are HTTP itself: `Cache-Control: max-age`, `s-maxage`, `ETag`/revalidation, `Vary`, and `stale-while-revalidate`.

### Build It

1. **Cache key** = URL (+ selected headers via `Vary`). Corollary: cache-bust by *changing the URL* — `app.a1b2c3.js` with `max-age=31536000, immutable` — deploys become instant and invalidation-free.
2. **HTML/API** gets the opposite treatment: short TTLs or `no-cache` + ETag revalidation (a 304 is cheap), because it changes and personalizes.
3. **`stale-while-revalidate`:** serve the stale copy instantly, refresh in the background — users never wait on a revalidation. **`stale-if-error`:** a stale page beats an error page when the origin is down; the CDN becomes an availability layer, not just a speed layer.
4. **Tiered/shield caching:** point edges at a designated shield PoP near the origin, collapsing global miss traffic to ~one origin fetch per object.
5. **Purge paths:** modern CDNs offer fast tag-based purges ("purge everything tagged product-123") — design your tags before you need them.
6. Never cache without `Vary`-discipline: caching a page that varied by `Cookie` without saying so = serving one user's private page to another. This exact class of bug has caused real-world data leaks.

### Use It

| Provider | Notes |
|---|---|
| Cloudflare | anycast everywhere, generous free tier, workers at edge |
| Akamai | the original (1998), enormous enterprise footprint |
| Fastly | instant purge (~150ms global), VCL programmability |
| CloudFront | AWS-native, origin shield option |

Modern CDNs also run code at the edge (Workers, Lambda@Edge) — caching's endgame is moving *compute* to the data's copy.

### War Story

Akamai was founded in 1998 out of MIT — directly commercializing the consistent-hashing research from Phase 5, Lesson 05 — after the web's early "flash crowd" events made it obvious origins couldn't survive their own popularity. The modern mirror image: on June 8, 2021, a Fastly configuration bug triggered by a single customer's valid change briefly took down enormous swaths of the internet (Reddit, Amazon, gov.uk, major news sites) — a reminder that the edge is now load-bearing infrastructure, and its blast radius is the whole web.

### Checkpoint

- Why does content-hashed-filename + immutable caching eliminate the invalidation problem for static assets?
- What do `stale-while-revalidate` and `stale-if-error` each optimize for?
- Explain how a missing `Vary` header can leak one user's data to another through a CDN.

## 07. Cache invalidation (the hard problem)

**MOTTO:** Every cached value is a promise; invalidation is keeping it.

### The Problem

The data changed. Somewhere, copies of the old value are still being served — in Redis, in a CDN PoP, in a process-local dict, in a user's browser. "There are only two hard things in computer science: cache invalidation and naming things" (Phil Karlton) is funny because it's true: invalidation is a *distributed consistency* problem wearing a performance optimization's clothes. Every copy you made in Lessons 01–06 is now your liability.

### The Concept

A cached value is a printed newspaper: correct at press time, aging ever since. You have exactly three honest strategies, and every real system is a blend:

```
1. EXPIRE   (TTL)      "trust it for 60s, then re-check"
                        → bounded staleness, zero coordination
2. INVALIDATE (purge)   "when truth changes, hunt down copies"
                        → fresh, but you must find EVERY copy,
                          and delivery of the purge can fail
3. VERSION  (new key)   "never change a value; change its NAME"
                        → old copies become irrelevant, not wrong
                          (the CDN asset-hash trick, generalized)
```

The failure taxonomy: missed invalidation (stale forever), reordered invalidation (purge arrives before the write is visible → recache stale), and the Lesson-02 race (read-then-set interleaves with write-then-delete).

### Build It

1. **Layer TTLs as a backstop under everything** — even "we purge on write" systems. A TTL converts every invalidation bug from "stale forever" to "stale for ≤N seconds." Choose N per key class from a business question: "how stale is acceptable?" is a product decision, not an infra one.
2. **Purge from the source of truth, not the app:** subscribe to the database's change stream (CDC — Debezium reading the WAL/binlog) and invalidate from there. Apps forget code paths; the WAL doesn't lie. This closes the "some other service wrote the DB directly" hole.
3. **Version where possible:** key = `user:42:v{version}` with the version stored (and bumped) transactionally with the data; readers fetch version, then value. Stale *values* can't be served because they're never looked up — you traded invalidation for one extra (cacheable, short-TTL) version lookup.
4. **Order matters:** write DB → then invalidate. And handle the recache race with short TTLs, CAS/lease tokens (Lesson 08's leases fix this too), or tolerate-and-bound.
5. **Multi-layer:** invalidation must cascade (DB → Redis → CDN tag purge → `Cache-Control` for browsers). Design the cascade explicitly; the layer you forget is the layer users screenshot.

### Use It

| Strategy | Exemplars |
|---|---|
| TTL everywhere | DNS (the original TTL system), most Redis usage |
| CDC-driven purge | Facebook's memcached invalidation pipeline (McSqueal), Debezium consumers |
| Versioned keys | CDN asset hashing, generation-numbered cache keys |
| Tag-based purge | Fastly surrogate keys, Cloudflare cache tags |

### War Story

Facebook's memcache papers describe invalidation as a first-class pipeline: a daemon tails MySQL commit logs and fans out deletes to the caching tier, because relying on application code to remember every invalidation had already failed at their scale. And the quip itself is real lineage: Phil Karlton was a Netscape/SGI engineer, and colleagues have confirmed the quote's attribution — the industry's most-cited joke is also its most accurate architecture review.

### Checkpoint

- Why should a TTL back even a "we always purge on write" design?
- What problem does CDC-driven invalidation solve that app-driven invalidation structurally cannot?
- How does key versioning sidestep the purge-delivery problem entirely, and what new lookup does it introduce?

## 08. Thundering herds and cache stampedes

**MOTTO:** One key expires; a thousand requests sprint to ask the database the same question.

### The Problem

Your homepage data is cached with a 60s TTL and served 10,000 times per second. The TTL expires. In the next 50ms, five hundred requests all miss, and *all five hundred* independently run the expensive query — the database, sized for a world where this query runs once a minute, gets it five hundred times in one breath. This is a cache stampede, and it can take down a system that was "fine" seconds earlier. The cruel part: the more popular the key, the worse the herd.

### The Concept

A pot of coffee empties in a busy office. Sane behavior: one person brews while everyone else waits by the machine (or sips their existing dregs). Stampede behavior: all thirty people independently drive to the store to buy beans. The fixes are all variations on "elect one brewer":

```
t=59.9s  cache hit, hit, hit...          (10k rps, all happy)
t=60.0s  KEY EXPIRES
t=60.0s  MISS ×500 ─────────────> DB ×500   💥 the herd
                     vs.
t=60.0s  MISS ×500 → 1 acquires lock → 1 DB query
                   → 499 wait (or get stale value) → all served
```

### Build It

Four compatible mechanisms — production systems stack them:

1. **Request coalescing / single-flight:** dedupe concurrent identical misses; one flies, the rest await its result. (Go's `singleflight` package; CDNs do this per-PoP as "request collapsing.")
2. **Lock-and-stale:** on miss, `SET lock:key NX EX 10`; the winner recomputes, losers serve the *stale* value (keep it soft-expired rather than deleted) or briefly wait. Nobody piles onto the DB.
3. **Probabilistic early expiration (XFetch):** each reader independently decides, with probability increasing as expiry approaches (scaled by recompute cost: `now − β·Δ·ln(rand()) ≥ expiry`), to refresh *early*. Statistically one refresher, no lock, no synchronized cliff. (Vattani, Chierichetti & Lowenstein, "Optimal Probabilistic Cache Stampede Prevention," VLDB 2015.)
4. **TTL jitter:** never give a cohort of keys the same lifetime — `ttl = base + rand(0, 10%)` — or keys cached together (deploy! cache flush!) expire together forever, a synchronized mass herd. Corollary: never mass-flush a hot cache; warm it first.
5. **Facebook's leases:** on a miss, memcached hands the *first* client a lease token; only the token-holder may set the value, others briefly wait/reuse stale. Bonus: leases also serialize the Lesson-02/07 stale-set race. One mechanism, two bugs dead.

### Use It

| Mechanism | Where you'll meet it |
|---|---|
| Single-flight | Go `singleflight`, GraphQL dataloaders |
| Request collapsing | Varnish (`req.hash_ignore_busy`), Fastly, Nginx `proxy_cache_lock` |
| Leases | Facebook memcache (NSDI '13) |
| stale-while-revalidate | CDNs, HTTP RFC 5861 — herd prevention as a header |
| Jitter | every well-run TTL scheme, and (same idea) retry backoff |

### War Story

The Facebook memcache paper (NSDI 2013) reports that leases were introduced precisely because popular keys' misses produced database-crushing herds, and that the technique cut peak DB query rates dramatically during hot-key churn. The same paper's "thundering herd" section is why every caching library written since ships a single-flight primitive — one company's incident review became everyone's default.

### Checkpoint

- Why do stampedes hit the *most popular* keys hardest, and why does that make them a stability (not just latency) problem?
- How does probabilistic early expiration prevent a herd with no locks and no coordination?
- Your deploy script flushes the cache, and every deploy causes a five-minute brownout. Name two fixes from this lesson.

## 09. Hot keys and cache skew

**MOTTO:** When one key gets famous, one server does all the work.

### The Problem

Consistent hashing spread your keys beautifully — but it spreads *keys*, not *traffic*. A celebrity posts; one cache key now receives a million reads per second, and the single shard that owns it saturates its NIC and CPU while its nine siblings nap. Sharding cannot help, because you cannot shard *one key*. This is the hot-key problem, and it's Zipf's law (Lesson 01) turning on its creator: the same skew that makes caching work makes one server suffer.

### The Concept

One bank teller happens to hold the only copy of a form everyone suddenly needs. Adding more tellers does nothing — the queue is at *that* window. Fixes: photocopy the form to every window (replicate), hand copies out in the lobby before people reach a window (local cache), or split the crowd by last digit of their ID into ten lines that each get a copy (key splitting).

```
hash ring, 10 nodes, uniform keys... except one:
node1 ▓▓            node2 ▓▓▓        node3 ▓▓
node4 ██████████████████████████████ ← owns "post:viral123"
node5 ▓▓            ...              node10 ▓▓

Splitting:  post:viral123#0 ... post:viral123#9
            readers pick a random replica → load ÷ 10
            writers must update all 10 (fine: reads ≫ writes)
```

### Build It

1. **Detect first:** you can't fix what you can't see. Sample key frequencies (count-min sketch, or `redis-cli --hotkeys`), alert on per-shard QPS/bandwidth skew, and log top-N keys per minute.
2. **L1 local cache:** a tiny in-process cache (even 1–5s TTL) in front of the shared tier absorbs *most* of a hot key's reads — a 1s TTL caps each app instance at 1 read/sec/key regardless of popularity. Cost: up to 1s staleness and per-instance memory. This is the highest-leverage fix and usually the first.
3. **Key replication/splitting:** write `key#0..key#N−1`; readers pick `key#rand(N)`. Reads divide by N; writes multiply by N — perfect for read-hot, wrong for write-hot.
4. **Write-hot keys** (a viral post's like-counter) need a different trick: shard the *counter* into N sub-counters, increment one at random, sum on read — or batch increments in-process and flush periodically.
5. **Bound the blast radius:** per-key rate limits / load shedding so one famous key degrades *its* endpoint, not the whole cache tier. (This mirrors Phase 5, Lesson 04's celebrity problem — same disease, cache-tier symptoms.)

### Use It

| Mitigation | Embodiment |
|---|---|
| L1 + L2 tiers | in-process Caffeine/dict over Redis — near-universal at scale |
| Client-side hot replication | DynamoDB adaptive capacity (automatic), Twitter/X-style hot key handling in cache clients |
| Sharded counters | classic pattern in Bigtable/Datastore docs since the 2000s |
| Hot-key detection | `redis-cli --hotkeys`, sampling sketches in proxy layers |

### War Story

Hot keys are a hardy perennial of large-site postmortems: a celebrity death, a world-cup goal, or one viral tweet concentrates the planet's attention on a handful of cache keys within seconds, and engineering blogs from major social platforms describe layering exactly these defenses — local caches, key replication, and sharded counters — after single cache shards were overwhelmed by traffic no rebalancer could redistribute. The load balancer's blind spot is always the same: you can't rebalance one key.

### Checkpoint

- Why does adding cache servers do nothing for a single hot key?
- A 1-second in-process cache seems trivially small — why is it devastatingly effective against hot keys?
- Read-hot and write-hot keys need different fixes. Give the fix for each and say why they don't interchange.

## 10. Build an LRU cache from scratch

**MOTTO:** A dict for finding, a linked list for forgetting — O(1) both ways.

### The Problem

The classic closing exercise, and the most-asked systems interview question in existence: a fixed-capacity cache where `get` and `put` both run in O(1), evicting the least-recently-used entry when full. The tension: a hash map finds in O(1) but has no order; a list keeps order but finds in O(N). The answer is to run both, pointing at the same nodes.

### The Concept

A librarian's returns cart with a strict rule: any book touched goes to the front; when the cart is full, the book at the back — untouched the longest — goes to storage. The dict is the catalog saying exactly where each book sits (no searching); the doubly linked list *is* the cart (O(1) to unhook a book from anywhere and re-hang it at the front — that's why it must be *doubly* linked: unhooking needs the neighbor on each side).

```
 head (MRU)                                  tail (LRU)
  ┌───┐   ┌───┐   ┌───┐   ┌───┐
  │ D │◄─►│ A │◄─►│ C │◄─►│ B │   ← evict B when full
  └───┘   └───┘   └───┘   └───┘
    ▲       ▲       ▲       ▲
  dict: { D:•,    A:•,    C:•,    B:• }   (key → node, O(1))

get(A): unhook A, re-hang at head. Two pointer surgeries. O(1).
```

### Build It

```python
class Node:
    __slots__ = ("key", "val", "prev", "next")
    def __init__(self, key=None, val=None):
        self.key, self.val, self.prev, self.next = key, val, None, None

class LRUCache:
    def __init__(self, capacity: int):
        self.cap, self.map = capacity, {}
        self.head, self.tail = Node(), Node()     # sentinels: no edge cases
        self.head.next, self.tail.prev = self.tail, self.head

    def _unlink(self, n):
        n.prev.next, n.next.prev = n.next, n.prev

    def _push_front(self, n):
        n.prev, n.next = self.head, self.head.next
        self.head.next.prev = n
        self.head.next = n

    def get(self, key):
        if key not in self.map: return None
        n = self.map[key]
        self._unlink(n); self._push_front(n)      # touch = move to front
        return n.val

    def put(self, key, val):
        if key in self.map:
            n = self.map[key]; n.val = val
            self._unlink(n); self._push_front(n)
            return
        if len(self.map) >= self.cap:             # evict LRU
            lru = self.tail.prev
            self._unlink(lru); del self.map[lru.key]
        n = Node(key, val)
        self.map[key] = n; self._push_front(n)

c = LRUCache(2)
c.put("a", 1); c.put("b", 2); c.get("a")   # touch a → b is now LRU
c.put("c", 3)                               # evicts b
assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3
```

Design notes worth internalizing: **sentinel head/tail nodes** delete every empty/one-element edge case; the node must store its own `key` so eviction can clean the dict; `__slots__` cuts per-node memory. Extensions: add TTL per node (check-on-get + lazy purge — Lesson 04's Redis expiry in miniature), thread safety (one lock around both structures; note Python's `OrderedDict.move_to_end` and `functools.lru_cache` ship this whole lesson in the standard library), and upgrade the eviction to segmented-LRU from Lesson 03.

### Use It

You have now built, in miniature, the exact mechanism inside `functools.lru_cache`, Java's `LinkedHashMap` access-order mode, browser caches, database buffer pools (Phase 4, Lesson 01 — the buffer pool's eviction is this code with pages for values), and — modulo the sampling trick you now understand from Lesson 04 — Redis itself. One dict, one list, the whole industry.

### War Story

"Design an LRU cache" (LeetCode 146) is possibly the most-asked data-structure design question in tech interviewing history — and unusually for interview trivia, it's *earned*: this exact structure runs in essentially every OS page cache, JVM, browser, and cache server on the planet. Bélády studied eviction at IBM in 1966; sixty years later, candidates whiteboard his problem's most practical answer several thousand times a day.

### Checkpoint

- Why must the linked list be doubly linked — exactly which operation breaks with a singly linked list?
- Why does each node store its key, and what specifically goes wrong at eviction time without it?
- Your `get` is O(1) but a teammate's version using a Python list + `remove()` "also works." What's its true complexity and why?
