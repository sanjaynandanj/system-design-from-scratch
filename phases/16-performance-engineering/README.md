# Phase 16 — 🏎️ Performance Engineering

> Milliseconds are money. Percentiles are truth.

Performance work has a reputation for dark arts, but it's the most empirical discipline in this whole curriculum: measure, model, fix, measure again. The traps are all human — optimizing what's easy instead of what's hot, trusting averages that hide the pain, load-testing in ways that mathematically cannot see the problem. This phase gives you the instruments (profilers, flame graphs), the theory (queueing, percentiles), and the levers (pooling, batching, compression, tuning) — then a checklist to keep you honest.

## 01. Profiling and Flame Graphs

**MOTTO:** Guessing where the time goes is how you spend a week optimizing the wrong function.

### The Problem

Your service is slow. Every engineer has a theory — "it's the JSON parsing," "it's the ORM," "it's GC" — and each theory launches a speculative optimization. Intuition about hot spots is notoriously wrong, because the code you *remember writing* isn't the code the CPU *spends time in*. Without measurement, performance work is astrology with commit messages.

### The Concept

A profiler is a census-taker for CPU time. The dominant technique, **sampling**, interrupts the program ~99 times a second and records the call stack each time. Enough samples and the statistics tell you exactly where time concentrates — with a few percent overhead, safe for production (unlike instrumenting profilers, which time every call and can distort the very thing they measure).

A **flame graph** (Brendan Gregg's visualization) renders those thousands of stacks as one picture:

```
x-axis: proportion of samples (NOT time order!)  y-axis: stack depth
┌────────────────────────────────────────────────────────┐
│                       main()                            │
├───────────────────────────────┬────────────────────────┤
│        handle_request()       │      background_job()   │
├───────────────┬───────────────┼────────────────────────┤
│  parse_json() │  db_query()   │      compress()         │
├───────────────┤ ┌─────────────┤                        │
│ utf8_decode() │ │ tls_write() │                        │
└───────────────┴─┴─────────────┴────────────────────────┘
Read it: WIDE = expensive. Wide with nothing on top = that function's
own code is hot. Wide plateaus at the top of stacks = your targets.
```

One caveat that catches everyone: a CPU profile only shows where you *burn CPU*. A thread parked waiting on a lock, a database, or a disk is invisible. For latency problems, you also need **off-CPU analysis** (profiling blocked time) or distributed tracing (Phase 13).

### Build It

A minimal sampling profiler is genuinely simple:

```python
import collections, traceback, threading, time

samples = collections.Counter()
def sampler(target_thread, hz=99):
    while running:
        frame = sys._current_frames()[target_thread.ident]
        stack = tuple(traceback.extract_stack(frame))   # capture call stack
        samples[stack] += 1                             # count it
        time.sleep(1 / hz)
# afterwards: fold identical stacks, sort by count → your hot paths
```

1. Sample at a frequency unaligned with your workload's own periodicity (hence 99Hz, not 100) to avoid lockstep bias.
2. Fold stacks (identical stack → count) — this folded format is exactly what flame graph tooling consumes.
3. Profile under *realistic load*; an idle service profiles as "epoll_wait: 100%".
4. Discipline: profile → find widest plateau → fix → profile again. One change at a time, or you can't attribute the win.

### Use It

| Tool | Scope | Note |
|---|---|---|
| perf + FlameGraph scripts | Linux, any native code | The origin toolchain |
| async-profiler / JFR | JVM | Low overhead, prod-safe |
| py-spy / rbspy | Python/Ruby, attach to live process | No code changes needed |
| Parca / Pyroscope / Datadog | Continuous profiling fleet-wide | Always-on: profile *before* the incident |

### War Story

Brendan Gregg invented flame graphs at Netflix-era-adjacent work (first published 2011) while debugging a MySQL performance mystery: the raw profiler output was hundreds of pages of stacks nobody could digest, so he collapsed them into the now-famous interactive SVG. The visualization spread to every language runtime within a few years — a reminder that in performance work, *rendering* the data is half the discovery.

### Checkpoint

- Why is sampling profiling safe for production while instrumenting profilers can distort results?
- A flame graph shows your handler is wide, but the service's latency problem persists and CPU is at 20%. What class of problem is the CPU profile blind to, and what do you reach for?
- Why sample at 99Hz instead of 100Hz?

## 02. Queueing Theory and Little's Law (L = λW)

**MOTTO:** Systems don't degrade linearly — they fall off a cliff, and queueing theory tells you exactly where the edge is.

### The Problem

Your service handles 800 req/s at 50ms just fine. Marketing forecasts 1,000 req/s, capacity math says the CPUs can do 1,100, so you're fine — right? Then at 950 req/s latency quintuples and queues explode, despite utilization being "only" ~86%. Everyone is baffled. Queueing theory is the mathematics of why "we have headroom" and "we are melting" are simultaneously true.

### The Concept

Any server is a checkout line: arrivals (rate **λ**), a server (service time **S**, capacity μ = 1/S), and a queue. Two results run the world:

**Little's Law** — for any stable system, no exceptions, no distribution assumptions:

```
L = λ × W      items in system = arrival rate × avg time in system

e.g. 1,000 req/s × 0.2s avg latency = 200 requests in flight.
Works on ANY boundary you draw: a queue, a service, a thread pool,
your entire company's ticket backlog.
```

**The utilization-latency curve** — because arrivals are random, not evenly spaced, waiting time explodes as utilization ρ = λ/μ approaches 1. For the M/M/1 model, wait scales like ρ/(1-ρ):

```
latency
   │                                    ×
   │                                  ×
   │                               ×          the knee: ~70-80%
   │                          ×  ◀── beyond here, small load
   │                  ×  ×             increases buy huge
   │      ×    ×                       latency increases
   └──×──────────────────────▶ utilization ρ
      50%      70%    80%   90%  →∞ at 100%
ρ=0.5 → wait = 1× service time    ρ=0.9 → 9×    ρ=0.99 → 99×
```

100% utilization isn't a target; it's an asymptote where queues grow without bound. Randomness in arrivals *is* the cost; variance makes it worse (that's the V terms in the more general Kingman formula).

### Build It

1. Apply Little's Law as a consistency check everywhere: thread pool of 100, avg latency 50ms → max sustainable throughput 100/0.05 = 2,000 req/s. If you're targeting 3,000, no tuning will save you — change L or W.
2. Size for the knee: plan capacity so peak-hour ρ ≈ 60-75% per server, not 95%. The "wasted" headroom is what keeps latency flat when variance arrives.
3. Simulate to build intuition (10 lines, worth a semester):

```python
import random
t = q = 0
for _ in range(1_000_000):
    t += random.expovariate(lam)         # next arrival (random!)
    q = max(0, q - (t - last) * mu); last = t
    q += 1                                # join queue; track q over time
# plot avg q vs lam/mu and watch the hockey stick appear
```

4. Remember queues hide in every layer: accept backlogs, thread pools, connection pools, disk queues, downstream services. The system's latency cliff is wherever the *first* ρ hits the knee.

### Use It

| Application | The queueing insight |
|---|---|
| Autoscaling targets | Scale on ~70% utilization, not 90 — you're buying distance from the asymptote |
| Concurrency estimation | Little's Law converts latency targets ↔ pool sizes ↔ throughput |
| USL (Universal Scalability Law) | Extends the model with contention + coherence costs across nodes |

### War Story

Little's Law was proven by John Little in 1961 and is beloved precisely because it's assumption-free — it holds for any stable queueing system regardless of arrival or service distributions. Sixty years later it's still the fastest sanity check in systems engineering: when someone's claimed throughput, concurrency, and latency numbers don't satisfy L = λW, at least one of the numbers is wrong, every time.

### Checkpoint

- A service shows 400 in-flight requests at 2,000 req/s. What's the average latency, and which law did you just use?
- Why does average wait time explode near 100% utilization even though the server "can" process every request?
- Your thread pool has 50 threads and downstream calls average 100ms. What's the throughput ceiling, and what are your two levers to raise it?

## 03. Tail Latency: The Tyranny of p99

**MOTTO:** Your average user never experiences your average latency — they experience your tail, repeatedly.

### The Problem

Dashboard says average latency 40ms. Users say the app is janky. Both are right: the mean is dragged down by a sea of fast requests, while p99 = 900ms means one request in a hundred crawls. And your *heaviest users* — the ones making the most requests — hit that 1-in-100 constantly. Averages are for billing; percentiles are for truth.

### The Concept

The killer is **fan-out amplification**. Modern requests fan out to many backends and wait for the slowest one — so the parent's latency is the *max* of the children, and max is a tail-seeking function:

```
P(all N calls are fast) = p^N, where p = per-call probability of "fast"

Each backend: 99% of calls under 100ms  (looks great alone!)

Fan-out   P(whole request under 100ms)
   1        0.99            = 99.0%
  10        0.99^10         ≈ 90.4%
 100        0.99^100        ≈ 36.6%   ← the p50 of the PARENT is now
                                        governed by the p99 of children!
For 100-way fan-out, a backend's 1-in-100 slowness becomes
the FRONT PAGE experience 2 times out of 3.
```

Analogy: a relay team of 100 runners — the team's time is ruined if *any one* runner trips, so the probability someone trips approaches certainty as the team grows. This is why Dean & Barroso titled their paper "The Tail at Scale": scale converts rare slowness into common slowness.

### Build It

Defensive patterns, from the same paper and a decade of practice:

1. **Hedged requests**: send the request; if no reply by ~p95, send a duplicate to another replica, take the first answer. Cost: a few % extra load. Benefit: the tail collapses toward p95. Cancel the loser (**tied requests**) to reclaim the wasted work.
2. **Timeouts + budgets**: every hop gets a deadline derived from the top-level budget; a 2s call serving a 500ms SLO is structurally pointless work.
3. **Shave the sources of tail**: GC pauses (Lesson 09), queueing at high ρ (Lesson 02), cold caches, slow disks, noisy neighbors, lock contention. Tail latency is a *symptom index* for everything else in this phase.
4. **Partial results beat late results** where the product allows: return 98 of 100 shards' search results at deadline rather than waiting for stragglers.
5. Measure honestly: percentiles must be computed from full distributions (histograms like HDRHistogram/t-digest) — you cannot average percentiles across hosts or windows; p99s don't add, distributions do.

```
hedged request timeline:
t=0    ──▶ replica A ............(slow, in its p99 tail)
t=p95  ──▶ replica B ──▶ reply at t=p95+median  ✓ served
tail cost: ~5% duplicate load for ~10× better p99.9
```

### Use It

| Technique | Where you've seen it | Cost |
|---|---|---|
| Hedging / speculative retry | gRPC hedging config, Cassandra rapid read protection | Extra load; needs idempotent reads |
| Deadline propagation | gRPC deadlines, context cancellation | Requires discipline at every hop |
| Load-balancer choice-of-2 + outlier ejection | Envoy | Routes around slow instances automatically |

### War Story

Dean and Barroso's "The Tail at Scale" (CACM, 2013) reported a Google measurement that has become the canonical fan-out example: a server with 10ms p50 and 1s p99, fanned out 100 ways, yields a *service-level* p50 governed by stragglers — and hedged/tied requests cut tail latency dramatically for ~2-5% extra load. The paper reframed tail latency from "edge case" to the central engineering problem of large fan-out systems.

### Checkpoint

- Each of 50 backends answers under 100ms 99% of the time. What fraction of fan-out-to-all-50 requests complete under 100ms, and what's the formula?
- Why is averaging the p99 values reported by 20 hosts statistically meaningless, and what should be aggregated instead?
- Explain hedged requests: when do you fire the hedge, why at that threshold, and what property must the operation have?

## 04. Connection Pooling

**MOTTO:** The most expensive part of many requests is saying hello — so stop saying it every time.

### The Problem

A "simple" database query at 2ms of actual work can cost 50ms+ if the connection is fresh: TCP handshake (1 RTT), TLS handshake (1-2 RTTs), then database authentication and session setup — for Postgres, a forked backend *process* per connection. Do this per request and you've multiplied latency, throttled throughput, and DDoS'd your own database with hellos. Connections are expensive to make, cheap to keep, and finite to hold.

### The Concept

A connection pool is a taxi rank, not a dealership: instead of building a car per trip (open/close per request), a fixed fleet waits in line; you borrow one, ride, and return it for the next passenger.

```
   app threads                     POOL (max=20)                    DB
  ┌─────────┐   borrow   ┌──────────────────────────┐   20 warm
  │ req ────┼──────────▶ │ [c1][c2][c3]...[c20]     │ ══════════▶ (Postgres:
  │ req ────┼──────────▶ │ idle → handed out → back │  persistent    each conn
  │ req ────┼──▶ WAIT ─▶ │ (pool empty? queue with  │  connections   = a process
  └─────────┘            │  a timeout — see L02!)   │                + memory)
                         └──────────────────────────┘
Little's Law strikes again: pool_size = throughput × avg_hold_time
  e.g. 2,000 qps × 5ms hold = 10 connections needed. That's all.
```

The counterintuitive truth: the right pool is *small*. The database has limited cores; hundreds of connections don't add capacity, they add context-switching, memory, and lock contention. Beyond roughly core-count-scaled parallelism, more connections make everything slower.

### Build It

Pool mechanics worth internalizing:

```python
class Pool:
    def acquire(self, timeout):
        conn = self.idle.pop_or_wait(timeout)      # bounded wait → fail fast
        if conn.age > MAX_LIFETIME or not conn.validate():  # kill stale/dead
            conn = self.open_new()                 # (LBs/firewalls silently
        return conn                                #  drop idle TCP conns)
    def release(self, conn, had_error):
        conn.reset_session_state()                 # tx aborted? temp settings?
        self.idle.push(conn) if not had_error else conn.close_and_replace()
```

1. Size with Little's Law (throughput × hold time), then cap near what the DB comfortably serves — the PostgreSQL community's rough starting heuristic is on the order of `cores × 2` for CPU-bound work, plus allowance for I/O waits. Measure, don't worship formulas.
2. Always bound the acquire wait — an unbounded pool wait converts DB slowness into unbounded request queueing upstream (Lesson 02's cliff, relocated).
3. Reset session state on release; a leaked `SET ROLE` or open transaction is a security bug wearing a performance costume.
4. Recycle connections on max-lifetime to survive failovers and middlebox idle-kills.
5. At serverless/microservice scale (1,000 clients × pool of 10 = 10,000 connections), pool *centrally* with a proxy: PgBouncer, RDS Proxy.

### Use It

| Tool | Layer | Note |
|---|---|---|
| HikariCP | JVM in-app pool | Benchmark-obsessed; excellent defaults |
| PgBouncer | Server-side proxy pool | Transaction-mode pooling multiplexes thousands of clients onto tens of conns |
| Envoy/HTTP keep-alive & h2 | Same idea for HTTP | HTTP/2 multiplexing = pooling built into the protocol |

### War Story

The HikariCP wiki's "About Pool Sizing" essay became minor legend for its demonstration (with an Oracle video) that *reducing* a pool from ~2,000+ connections to a few dozen took a struggling system from multi-second waits to sub-millisecond — the opposite of every panicked instinct. "You want a pool ~10× smaller than you think" is now standard lore, and PgBouncer's whole existence — multiplexing thousands of client connections onto a few dozen real Postgres backends — is the same insight productized.

### Checkpoint

- Enumerate what a fresh TLS database connection costs before the first query executes, and why Postgres specifically makes connections heavy.
- Use Little's Law to size a pool for 4,000 qps with 3ms average connection hold time. Why might you still cap it lower than "as big as fits"?
- Why must pool acquisition have a timeout, and what does the failure look like when it doesn't?

## 05. Batching and Pipelining

**MOTTO:** Per-item overhead is a tax — batching files jointly, pipelining stops waiting in line to pay.

### The Problem

Every operation carries fixed overhead independent of payload: a syscall, a network round trip, packet headers, an fsync, a lock acquisition. Send 1,000 items one at a time over a 1ms RTT link and you pay 1,000ms of pure round-trip tax for maybe 1ms of actual data transfer. The overhead dwarfs the work — and the fix is to change the *shape* of the conversation, not the speed of the network.

### The Concept

Two distinct tools, often confused:

- **Batching** = one truck instead of 1,000 couriers: amortize fixed cost over many items. Pay the tax once per *batch*.
- **Pipelining** = don't wait for each courier to return before sending the next: keep many requests in flight, overlapping round trips. Pay the taxes *concurrently*.

```
SERIAL:     ──req1──▶◀─resp1── ──req2──▶◀─resp2──      total ≈ N × RTT
BATCH:      ──[req1..reqN]──▶ ◀──[resp1..respN]──      total ≈ 1 × RTT + N×work
PIPELINE:   ──req1──▶
            ──req2──▶  ◀─resp1──
            ──req3──▶  ◀─resp2──                       total ≈ RTT + N×service
                       ◀─resp3──                       (in-flight window = LxW!)
```

The tradeoff is always the same triangle: **throughput up, per-item latency up** (items wait for the batch to fill), **complexity up** (partial failures: item 7 of 100 failed — now what?). Batching converts latency into throughput; whether that's a good trade depends on which SLO you're serving.

### Build It

The canonical mechanism — batch by size *or* time, whichever hits first:

```python
async def batcher(queue, max_size=100, max_wait_ms=5):
    while True:
        batch = [await queue.get()]                    # block for first item
        deadline = now() + max_wait_ms
        while len(batch) < max_size and now() < deadline:
            item = queue.get_nowait_or_until(deadline) # fill greedily
            if item is None: break
            batch.append(item)
        flush(batch)   # one syscall / one INSERT..VALUES(..),(..) / one produce
```

1. `max_wait` bounds worst-case added latency (an item never waits more than 5ms); `max_size` bounds memory and downstream chunk size. Tune both against your latency budget.
2. Handle partial failure explicitly: per-item status in responses, idempotent items so a batch can be retried, or split-and-retry (bisect the batch to isolate the poison item).
3. Pipelining mechanics: fixed window of in-flight requests + correlation IDs to match responses; this is literally how HTTP/2 streams, Redis pipelining, and Kafka's `max.in.flight` work. Note ordering: >1 in flight + retries can reorder — if order matters, you need idempotence or sequencing.
4. Natural batch points hiding in your stack: `INSERT ... VALUES (...),(...)` vs row-at-a-time; group commit (one fsync for many transactions — how databases survive fsync cost); Nagle's algorithm (TCP's built-in batcher — and why latency-sensitive apps set TCP_NODELAY); GPU inference batching.

### Use It

| System | Batching/pipelining knob | Tradeoff |
|---|---|---|
| Kafka producer | `linger.ms` + `batch.size` | Deliberately adds ms of latency to multiply throughput |
| Redis | `MULTI`/pipeline mode | Client complexity; big wins on RTT-bound workloads |
| GraphQL DataLoader | Coalesces N+1 loads into one batched query | Per-request-tick batching window |

### War Story

Kafka's design docs are unusually candid that its throughput comes substantially from batching at every layer — producer `linger.ms` accumulation, batched compression, sequential batched writes, and zero-copy batched sends — an explicit "trade a few milliseconds for order-of-magnitude throughput" philosophy. Meanwhile Nagle's algorithm (1984), TCP's automatic small-packet batcher, interacting with delayed ACKs became networking's most famous latency footgun — the reason `TCP_NODELAY` appears in virtually every latency-sensitive codebase.

### Checkpoint

- Distinguish batching from pipelining: what cost does each attack, and how does each change per-item latency?
- Why does a batcher need *both* a size limit and a time limit? What goes wrong with each alone?
- Your batch insert of 500 rows fails on one bad row. Describe two recovery strategies and the property items need for safe retry.

## 06. Compression Tradeoffs (gzip vs zstd vs lz4)

**MOTTO:** Compression is buying bandwidth with CPU — check the exchange rate before every purchase.

### The Problem

Bytes cost money and time everywhere they move or rest: network egress bills, cross-AZ tolls, disk capacity, cache RAM (fewer bytes = more entries = higher hit rate), replication lag. Compression shrinks all of it — but the CPU to compress isn't free, and on a fast link an expensive compressor can make the *end-to-end* transfer slower than sending raw. The question is never "compress?" but "which algorithm, at which level, for this speed of pipe?"

### The Concept

Every compressor sits on a ratio-vs-speed frontier. The break-even rule of thumb:

```
compression wins end-to-end when:
   time_to_compress + compressed_bytes/link_speed  <  raw_bytes/link_speed
→ the SLOWER the link (or pricier the byte), the MORE compression you buy;
  on very fast links, only very fast compressors pay for themselves.

ballpark frontier (text-like data; levels shift the dots along curves):
             ratio ▲            xz/brotli-11 ● (archival, CDN precompress)
                   │        zstd-19 ●
                   │     zstd-3 ●        ← the modern default: ~gzip ratio
                   │   gzip-6 ●            at several× the speed
                   │ lz4 ●               ← speed demon: GB/s-class, modest ratio
                   │ snappy ●
                   └──────────────────────▶ compression speed
```

Two structural notes: decompression is usually much faster than compression (great for write-once-read-many: compress hard once, serve cheap forever), and **small payloads compress poorly** — a 300-byte JSON blob may grow with a per-message dictionary… unless you use zstd's trained-dictionary mode, built exactly for that.

### Build It

1. Benchmark on *your* data — ratios vary wildly by content (JSON/logs: great; JPEG/encrypted: incompressible, skip it by content-type).

```python
for algo in [gzip6, zstd3, zstd19, lz4]:
    t0 = clock(); c = algo.compress(sample); t1 = clock()
    algo.decompress(c)  # time this too
    report(algo, ratio=len(sample)/len(c),
           mbps_c=len(sample)/(t1-t0),
           e2e=lambda link: (t1-t0) + len(c)/link)   # the number that matters
```

2. Pick by asymmetry of the path: hot RPC on 10GbE → lz4/snappy or nothing; API responses to internet clients → gzip/brotli (universal client support); storage, backups, Kafka topics, columnar files → zstd at mid-high level; static assets → precompress once with brotli-11 at build time.
3. Levels are a dial, not a fate: zstd spans "nearly lz4" to "nearly xz" in one algorithm — often the operational simplification is "zstd everywhere, tune the level."
4. Compression interacts with the rest of the stack: compress *before* encrypting (ciphertext is incompressible); columnar + type-specific encodings (delta, RLE) before general-purpose compression is why Parquet crushes CSV.
5. Security corner: compressing attacker-influenced data alongside secrets leaked information via ciphertext *length* (the CRIME/BREACH attacks on TLS compression) — the reason TLS-level compression is dead.

### Use It

| Algorithm | Sweet spot | Watch out |
|---|---|---|
| gzip (DEFLATE, 1990s) | Universal HTTP compatibility | Outperformed by zstd on both axes |
| zstd (Meta, 2016) | New default for storage/streaming/internal RPC | Client support younger than gzip's |
| lz4 | GB/s-class paths: caches, WALs, Kafka hot topics | Modest ratio — it's buying speed |
| brotli | Precompressed web static assets | Slow at max level: compress at build, not request |

### War Story

Zstandard, released by Meta (Yann Collet, also lz4's author) in 2016, broke the assumed tradeoff by matching gzip's ratio at several times the speed with a tunable range covering most of the frontier — and within a few years it was in the Linux kernel, Kafka, Parquet's ecosystem, RocksDB deployments, and an RFC (8478/8878) for HTTP. It's the rare systems story where "just switch the algorithm" genuinely delivered double-digit fleet-wide savings for many adopters.

### Checkpoint

- Write the end-to-end inequality that decides whether compressing before sending is worth it, and explain why faster links argue for lighter compression.
- Why do small payloads compress badly, and which zstd feature specifically targets that case?
- You're choosing compression for (a) an internal 25GbE RPC path, (b) S3-archived logs, (c) public web assets. Pick and justify each.

## 07. Capacity Planning

**MOTTO:** Hope is not a provisioning strategy — model the load, measure the ceiling, mind the gap.

### The Problem

The launch, the marketing spike, the Monday-morning peak: capacity questions arrive with deadlines. Answer wrong in one direction and you burn money on idle fleets; wrong in the other and you're writing an outage retro titled "we knew the launch date for six months." Most teams operate with no number for "how much can one instance actually handle?" — which makes every scaling decision a vibe.

### The Concept

Capacity planning is bridge engineering for traffic: rated load per pillar (measured, not guessed), forecast traffic (with seasonality and spikes), and a safety margin justified by queueing math rather than fear.

```
The capacity pipeline:
FORECAST demand ──▶ MEASURE unit capacity ──▶ COMPUTE fleet ──▶ VALIDATE
 peak RPS incl.      max RPS per instance      N = peak_load /    load test the
 growth, seasonality  while meeting SLO         (unit_cap ×       actual fleet
 launches, virality   (found by load test,       target_util)     (Lesson 08)
 + p99 of history,     NOT by specs sheet)       + failure
 not the average                                  headroom
```

Two non-negotiable margins stack on top of raw demand math: the **utilization knee** from Lesson 02 (plan for ~60-75% at peak, because latency explodes past it) and **failure headroom** — N+1 (or N+2) per failure domain, because you must hold SLO while a node or an entire AZ is dark.

### Build It

1. Define unit capacity empirically: ramp load on one production-identical instance until an SLO breaks (p99 > target, error rate > target); the last-good throughput is your unit capacity. Redo this per release — code changes silently move it.
2. Forecast from the peak, not the mean: base = p99 of historical daily peaks; multiply by growth trend; overlay known events (launches, sales) as explicit scenarios.
3. Fleet math, honestly annotated:

```
N = ceil( peak_rps / (unit_capacity × target_util) ) + failure_headroom
  = ceil( 90,000  /  (1,500 × 0.7) )  + N+1-per-AZ
  = 86 + headroom   ← every term measured or justified, none vibed
```

4. Trace the *whole* dependency chain: your stateless tier autoscales in seconds; the database, connection pools (Lesson 04), and downstream vendors don't. Capacity is set by the slowest-scaling bottleneck — find it before the spike does. And model **scale-up lag**: if instances take 3 minutes to boot and traffic doubles in 1, autoscaling alone loses; pre-scale for known events.
5. Close the loop: alert when observed peak crosses ~60% of proven fleet capacity — that's your buy-more trigger with lead time built in.

### Use It

| Tool/Practice | Role | Note |
|---|---|---|
| Load testing (Lesson 08) | Establishes unit & fleet ceilings | The only source of truth for capacity numbers |
| Prophet-style forecasting / plain seasonal regression | Demand curves | Fancy models lose to good peak-history hygiene |
| Autoscaling (HPA, ASG) | Absorbs the unforecastable | Doesn't absolve planning: lag, quotas, DB limits remain |

### War Story

Healthcare.gov's October 2013 launch is the canonical capacity postmortem: reporting at the time indicated the system had been tested at a fraction of launch load, then met ~250,000 concurrent users against expectations sized far lower — collapsing within hours, with only a handful of successful enrollments on day one. The rescue effort's lessons read like this lesson's outline: measure unit capacity, load test the real fleet, find the true bottleneck (it was downstream identity/data dependencies as much as web tier), and stage the ramp.

### Checkpoint

- Why is unit capacity defined as "max throughput *while meeting SLO*" rather than max throughput before crashing?
- Your service needs 60,000 RPS peak; an instance sustains 1,200 RPS within SLO. Compute the fleet with 70% target utilization and N+1 across 3 AZs, showing each term.
- Name three capacity constraints that autoscaling your stateless tier does nothing to relieve.

## 08. Load Testing That Means Something

**MOTTO:** Most load tests are the system testing itself under conditions that flatter it — real users don't politely wait their turn.

### The Problem

Team runs a load test: 100 virtual users in a loop, p99 looks great, ship it. Production melts at half the tested throughput. The test wasn't unlucky — it was *structurally incapable* of seeing the problem, because of two classic sins: closed-loop generation (virtual users wait for each response before sending again, so the load generator slows down exactly when the system struggles) and coordinated-omission-corrupted measurement. Bad load tests are worse than none: they issue confident wrong answers.

### The Concept

**Open vs closed loop** is about who controls arrival rate:

```
CLOSED LOOP (k virtual users, send→wait→send):
  system slows → users stuck waiting → arrival rate DROPS →
  back-pressure mercy that real internet traffic never grants.
  In-flight is capped at k. You measured a polite queue, not a flood.

OPEN LOOP (arrivals on a fixed schedule, e.g. Poisson at λ):
  system slows → requests keep arriving anyway → queues grow →
  you observe the REAL failure mode: latency + backlog explosion.
```

Closed loop *does* model systems with genuinely bounded concurrency (a fixed worker pool draining a queue, k long-session users); the crime is defaulting to it while claiming to simulate independent internet arrivals.

**Coordinated omission** (Gil Tene's term) is the measurement-side twin: if the generator stalls behind a slow response and skips the sends it *should* have made, the samples that would have recorded terrible latency are simply… missing. A 10s server freeze during which 1,000 requests "would have" waited records as *one* bad sample instead of a thousand — your p99 becomes fiction.

### Build It

1. Generate open-loop: schedule send times in advance (Poisson or constant rate), fire on schedule regardless of outstanding responses.
2. Measure against the *intended* schedule — this single change un-hides the tail:

```python
for i, t_sched in enumerate(schedule):           # fixed timestamps, decided
    wait_until(t_sched)                          #   before the test starts
    t0 = now()   # if we're late, t0 > t_sched: the generator itself stalled
    resp = send(req)
    record(latency = now() - t_sched)            # ← from SCHEDULED time, so
                                                 #   queue-wait during stalls
                                                 #   is counted, not omitted
```

3. Report percentiles from full histograms (HDRHistogram); never averages, never averaged percentiles (Lesson 03).
4. Realism checklist: production-shaped data (cardinality, sizes — cache hit rates lie otherwise), warmed caches and JITs (Lesson 09) unless you're *testing* cold start, ramp profiles + spike tests + soak tests (hours-long, to catch leaks and slow degradation), and test *through* the real entry path (LB, TLS) not localhost.
5. Find the ceiling by stepping λ upward until SLO breaks — that break point is the unit capacity Lesson 07 consumes. Ensure the *generator* isn't the bottleneck (run it distributed; watch its CPU).

### Use It

| Tool | Loop model | Note |
|---|---|---|
| wrk2 | Open-loop, constant rate, HdrHistogram | Built specifically to fix coordinated omission in wrk |
| k6 / Locust | Closed by default; open via arrival-rate executors | Read the executor docs or inherit the sin |
| Vegeta | Open-loop rate-based | Simple, correct-by-default shape |

### War Story

Gil Tene (Azul Systems) spent years evangelizing coordinated omission in his "How NOT to Measure Latency" talks, demonstrating that most benchmark tools of the era understated high percentiles by *orders of magnitude* — and shipped HdrHistogram plus wrk2 as the corrective toolchain. The talks changed industry practice: "does your load tool handle coordinated omission?" is now a standard filter question, and constant-throughput open-loop modes exist in most serious tools because of it.

### Checkpoint

- Explain mechanically why a closed-loop generator's arrival rate drops exactly when the system degrades, and what failure mode this hides.
- A server freezes for 5 seconds during a test at 1,000 req/s. Compare what a coordinated-omission-blind tool records versus a schedule-based tool.
- When is a closed-loop model actually the *correct* simulation? Give a concrete system.

## 09. Runtime Tuning: GC, JIT, and Friends

**MOTTO:** Your code shares the CPU with an invisible roommate — the runtime — and sometimes the roommate throws parties.

### The Problem

You profiled the code, sized the pools, shaved the fan-out — and p99 still spikes every few minutes with nothing in *your* code to blame. The culprit is the runtime itself: garbage collection pausing the world, a JIT compiler still warming up after deploy, or allocation pressure turning into CPU tax. Managed runtimes (JVM, Go, .NET, V8, Python) trade developer productivity for a background machinery whose scheduling *is* part of your latency distribution.

### The Concept

**GC** is a cleaning crew for a busy restaurant. Options: close the restaurant to clean (stop-the-world: throughput-efficient, latency-awful), clean while serving (concurrent: small steady tax on every table, tiny pauses), or exploit the fact that most plates are abandoned quickly (generational: collect the young area often and cheaply, the old area rarely). Modern collectors mix all three.

```
GC latency signature — the runtime IS your tail:
latency │      ▂      ▂      ▂        ← periodic p99.9 spikes
        │▁▁▁▁▁▁█▁▁▁▁▁▁█▁▁▁▁▁▁█▁▁▁▁     at GC-cycle cadence
        └────────────────────────▶ t
Tuning axes: pause time ↔ throughput ↔ memory footprint (pick 2)

JIT warmup — the deploy-time cliff:
perf    │        ┌──────────────      interpreted → profiled → compiled
        │   ┌────┘                    → optimized (+ occasional
        │───┘  ← cold: 10-100× slower    DE-optimization hiccups)
        └────────────────────────▶ time since process start
        ⇒ every deploy/scale-out ships a temporarily slow instance
```

**JIT** runtimes (JVM, V8, .NET) start by interpreting, then compile hot paths using observed behavior — so peak performance arrives minutes after boot, and benchmarks that skip warmup measure the interpreter, not your service.

### Build It

Tuning discipline — observation before knobs:

1. Turn on runtime telemetry first: GC logs/metrics (pause durations, frequency, heap before/after) and correlate pause timestamps against latency spikes. No correlation → stop tuning GC, your problem is elsewhere.
2. The cheapest "GC tuning" is allocating less: object pooling on hot paths, avoiding accidental per-request garbage (boxing, string concat in loops, defensive copies). Allocation rate drives GC frequency directly.
3. Pick the collector for the SLO, then size the heap: throughput-batch work → parallel STW collectors; latency-sensitive services → concurrent low-pause collectors (JVM G1/ZGC — ZGC targets sub-millisecond pauses even on large heaps; Go's collector is concurrent by design, tuned by `GOGC`/`GOMEMLIMIT`, trading CPU for its small pauses).
4. Defeat warmup at the fleet level: warm instances before they take traffic (readiness gate + synthetic warmup requests replaying real request shapes), slow-start in the LB, or snapshot/AOT approaches (CRaC, Lambda SnapStart, GraalVM native-image, AOT compilation) that ship pre-warmed state.
5. Beyond GC/JIT, the same "invisible roommate" audit applies to: container CPU limits interacting with runtime thread heuristics (a JVM seeing 32 host cores inside a 2-core cgroup sizes its GC threads catastrophically wrong — set the runtime's CPU count explicitly), THP/NUMA effects, and CFS throttling showing up as mystery millisecond stalls.
6. Change one flag at a time, under Lesson-08-grade load, judging by p99/p99.9 — never by average throughput alone.

### Use It

| Runtime | Latency lever | Note |
|---|---|---|
| JVM | G1 (default) → ZGC/Shenandoah for low pause | Richest telemetry (JFR) and knob set |
| Go | `GOGC`, `GOMEMLIMIT` | Few knobs by philosophy; allocation reduction is the main lever |
| Node/V8 | Heap limits; mind the single-threaded event loop | A long GC *or* a long callback blocks everything |

### War Story

Discord's engineering team published a widely-read 2020 account of rewriting their Read States service from Go to Rust: the Go version showed latency spikes at a regular cadence tied to the garbage collector's periodic behavior on a huge live cache, resisting tuning; the Rust rewrite (no GC) flattened the spikes and cut latency dramatically. The honest moral isn't "GC bad" — it's that at certain scales the runtime's background behavior becomes a first-order design constraint, worth changing languages over.

### Checkpoint

- Why does a generational collector spend most of its effort on recently allocated objects, and what empirical observation justifies it?
- Your JVM service is slow for ~3 minutes after every deploy. Explain the mechanism and two fleet-level mitigations.
- A containerized JVM with a 2-CPU limit on a 64-core host performs terribly. What is the runtime getting wrong, and how do you fix it?

## 10. The Performance Review Checklist

**MOTTO:** Performance isn't a heroic rescue — it's a checklist run before the ship leaves, every time.

### The Problem

Everything in this phase decays into folklore unless it's operationalized. Performance regressions ship because nobody asked the boring questions at design review; incidents recur because the p99 dashboard existed but no one owned the number. The last lesson is the meta-lesson: compress Phases 01-16's performance wisdom into questions cheap enough to ask *every time* — because the expensive version is asking them during the outage.

### The Concept

Aviation didn't reduce crashes with braver pilots; it used checklists — externalized memory that makes expertise routine. A performance review is the same artifact for systems: a fixed question list run at design time, pre-launch, and per major change, where every answer must be a *number or a link*, never an adjective.

```
The review loop:
DESIGN ──▶ questions 1-4 (budgets, model, load math)
BUILD  ──▶ questions 5-7 (measure, pool/batch/cache audit)
LAUNCH ──▶ questions 8-9 (load test, runtime & headroom)
OPERATE ─▶ question 10 (regression guardrails) ──▶ back to DESIGN
"fast" is an adjective. "p99 = 87ms at 2,400 RPS on 2025-xx-xx's
 load test, budget 150ms" is an answer.
```

### Build It

The checklist. Every item names its lesson — this is the phase, folded:

1. **Budget:** What's the end-to-end latency SLO (p50/p99), and how is it apportioned across hops? Does every downstream call carry a deadline within budget? *(L03)*
2. **Load model:** Peak RPS (p99 of peaks, plus growth and events)? Payload sizes? Fan-out degree per request — and what does p^N say about your tail? *(L03, L07)*
3. **Queueing math:** For each pool/queue/service: expected ρ at peak? Anything planned above ~75%? Little's Law check: do latency, concurrency, and throughput targets even cohere? *(L02)*
4. **Ceiling:** Measured unit capacity within SLO, on current build? Fleet math with target utilization and N+1 headroom written out? Slowest-scaling bottleneck identified? *(L07)*
5. **Profile:** Flame graph from realistic load reviewed? Widest plateau known and either optimized or consciously accepted? Off-CPU/trace story for latency, not just CPU? *(L01)*
6. **Connection & call hygiene:** All cross-service/database calls pooled, with bounded acquire timeouts and sane pool sizes (Little's Law, not vibes)? N+1 call patterns hunted? Batching/pipelining applied where round-trip tax dominates — with partial-failure handling? *(L04, L05)*
7. **Bytes:** Compression chosen per path via the end-to-end inequality (not habit)? Caches sized in entries-after-compression? Incompressible content skipped? *(L06)*
8. **Proof under load:** Open-loop, coordinated-omission-safe load test at forecast peak *and* at 2× peak, through the real entry path, with soak? Break point recorded? *(L08)*
9. **Runtime:** GC pauses correlated against p99.9? Warmup handled at deploy (warm-before-traffic or AOT/snapshot)? Container limits aligned with runtime thread/heap sizing? *(L09)*
10. **Guardrails:** p99-by-endpoint dashboards with alerts on *budget*, not on averages? Load test in CI or scheduled, diffed against last release? A named owner for each SLO number?

Run it as a document, answers inline, links to evidence. Any "we don't know yet" is fine — *unnoticed* unknowns are the failure.

### Use It

| Practice | Embodiment | Note |
|---|---|---|
| SRE production-readiness reviews | Google SRE book's launch reviews | The checklist as an org-level gate |
| Performance budgets in CI | Latency/size budgets failing builds | Turns question 10 into a robot |
| DiRT/game days | Testing the 2× and failure scenarios | Validates headroom claims empirically |

### War Story

The checklist-as-safety-device has its own founding legend: after the 1935 crash of Boeing's Model 299 prototype (pilot error — a control lock left engaged, by one of the Army's most experienced test pilots), Boeing introduced the pre-flight checklist rather than demanding more careful pilots; the B-17 went on to fly safely at massive scale. Atul Gawande's *The Checklist Manifesto* carried the idea to surgery and engineering: expertise doesn't eliminate omission — routine does.

### Checkpoint

- Why must every checklist answer be "a number or a link"? Give an example of an adjective answer and its acceptable replacement.
- Which three checklist items would have caught a service that melts at launch because its database connection pool saturates? Trace the catch for each.
- What distinguishes an acceptable "we don't know yet" from a dangerous one in a performance review?
