# Phase 00 — 🧠 Setup & Mental Models

> Learn to think in boxes, arrows, and orders of magnitude.

Before you touch a load balancer, you need a way of *seeing*. System design is not a pile of AWS product names — it's a small set of mental models applied ruthlessly: everything is a box or an arrow, every arrow has a latency and a failure mode, and every number is either negligible or the whole story. This phase installs those models in your head and a lab on your laptop. By the end, you'll estimate a Twitter clone's storage on a napkin and be roughly right — which is the only kind of right that matters at design time.

## 01. What is system design (and why intuition beats memorization)

**MOTTO:** System design is the art of choosing which problems you're willing to have.

### The Problem

You can memorize fifty "design Instagram" videos and still freeze when someone changes one requirement — "actually, reads must be strongly consistent" — because memorized architectures are brittle. The real world never asks the question you rehearsed. Interviewers (and production) probe *why*, and "because the video said so" doesn't survive contact.

### The Concept

Think of system design like structural engineering, not interior decorating. A decorator memorizes what looks good; an engineer knows *why* the beam holds — so when the load changes, they can re-derive the answer. Every system is a set of components (boxes) exchanging data (arrows) under constraints (latency, cost, failure, consistency). Design is navigating tradeoffs between those constraints, because you can never have all of them at once.

```
        Requirements
             |
             v
   +------------------+       You never "solve" a design.
   |  TRADEOFF SPACE  |  <--- You pick a point in this space
   |  cost <-> speed  |       and defend it.
   |  consistency <-> |
   |    availability  |
   +------------------+
```

### Build It

Your reasoning loop, from scratch:

1. **Clarify** — what does the system actually do? For whom? How many of them?
2. **Quantify** — QPS, data size, read/write ratio. Numbers before boxes.
3. **Sketch** — simplest thing that could work. One box, one database.
4. **Break it** — where does it fall over first? At 10x load? On one machine dying?
5. **Fix the bottleneck** — add exactly one component. Repeat step 4.

Every "advanced" architecture is just this loop run many times. Caches, queues, and shards are answers to *specific* breakages, not decoration.

### Use It

| Approach | Strength | Failure mode |
|---|---|---|
| Memorize reference designs | Fast recall | Collapses when requirements shift |
| First-principles reasoning | Handles novel problems | Slower without practiced building blocks |
| Both (this course) | Intuition + vocabulary | Requires actual work. Sorry. |

### War Story

Google's early infrastructure papers — MapReduce (2004), GFS (2003), Bigtable (2006) — weren't invented by pattern-matching to existing designs, because none existed at that scale. Jeff Dean and Sanjay Ghemawat reasoned from hardware costs and failure rates on cheap commodity machines, and those from-scratch derivations became the patterns everyone else now memorizes.

### Checkpoint

- Why does changing a single requirement (e.g., consistency) potentially invalidate an entire memorized architecture?
- What are the five steps of the design reasoning loop, and which one must come before drawing any boxes?
- Give an example of a tradeoff pair you can't maximize simultaneously.

## 02. Thinking in boxes and arrows

**MOTTO:** Every system is boxes that hold state and arrows that can fail.

### The Problem

Engineers drown in detail: which framework, which cloud, which config flag. Meanwhile the design question is usually much simpler — who talks to whom, who remembers what, and what happens when a conversation fails mid-sentence. Without an abstraction that hides the noise, you can't reason about the signal.

### The Concept

Model everything as **boxes** (things that compute or store) and **arrows** (data moving between them). The magic is what you annotate: every box has *state or no state*; every arrow has *latency, bandwidth, and a failure mode*. A stateless box can be cloned freely; a stateful box is where all your design pain lives. An arrow across a datacenter is ~a million times slower than an arrow inside a process — same drawing, wildly different physics.

```
 [Client] --HTTP, ~50ms, can timeout--> [API server]  (stateless: clone at will)
                                           |
                                    SQL, ~1ms, can fail
                                           v
                                       [Database]     (stateful: HERE BE DRAGONS)
```

### Build It

To box-and-arrow any system:

1. List the nouns (users, posts, orders) — they live in stateful boxes.
2. List the verbs (upload, search, pay) — they live in stateless boxes.
3. Draw arrows for every verb's data path, client to storage and back.
4. Annotate each arrow: rough latency, rough volume, what-if-it-fails.
5. Circle every stateful box. Those are your hard problems; everything else is horizontal scaling.

If your diagram has ten stateful boxes, you didn't design a system, you designed an incident.

### Use It

This abstraction *is* the industry-standard toolkit: C4 diagrams formalize the box hierarchy (context → container → component), sequence diagrams formalize the arrows over time, and "stateless service + managed database" is the default posture of every modern platform (Kubernetes pods are disposable precisely because state is pushed to the arrows' far end).

### War Story

During the 2017 AWS S3 outage, an engineer debugging the billing subsystem mistyped one command and removed far more capacity than intended — and because so many arrows across the internet pointed at that one stateful box (including AWS's own status dashboard, which couldn't display the red icon), a single region's object store took down thousands of sites. Know where your arrows converge.

### Checkpoint

- Why can stateless boxes be cloned freely while stateful boxes cannot?
- What three annotations should every arrow carry?
- In the S3 2017 outage, what property of the global "diagram" turned one box's failure into an internet-wide event?

## 03. Latency numbers every engineer should know

**MOTTO:** A nanosecond and a millisecond differ by a factor of a million — design like you believe it.

### The Problem

Engineers write a loop that makes a network call per item and wonder why 1,000 items take 100 seconds. Without internalized latency numbers you can't smell this bug in review; you find it in production, at 3 a.m., with a customer on the phone.

### The Concept

Here is the canonical table, popularized by Jeff Dean (Google, ~2009 LADIS talk) — "Numbers Everyone Should Know":

```
L1 cache reference ......................... 0.5 ns
Branch mispredict ............................ 5 ns
L2 cache reference ........................... 7 ns
Mutex lock/unlock ........................... 25 ns
Main memory reference ...................... 100 ns
Compress 1K bytes with Snappy ............ 3,000 ns =   3 µs
Send 1K bytes over 1 Gbps network ....... 10,000 ns =  10 µs
Read 4K randomly from SSD .............. 150,000 ns = 150 µs
Read 1 MB sequentially from memory ..... 250,000 ns = 250 µs
Round trip within same datacenter ...... 500,000 ns = 500 µs
Read 1 MB sequentially from SSD ...... 1,000,000 ns =   1 ms
Disk seek ........................... 10,000,000 ns =  10 ms
Read 1 MB sequentially from disk .... 20,000,000 ns =  20 ms
Send packet CA → Netherlands → CA .. 150,000,000 ns = 150 ms
```

Human-scale analogy: if an L1 hit is 1 second, main memory is ~3 minutes, an SSD random read is ~3.5 days, a disk seek is ~7 months, and the transatlantic round trip is ~10 years.

### Build It

Don't memorize fourteen numbers; derive from five anchors:

1. Memory reference: **100 ns**. 2. Datacenter round trip: **0.5 ms**. 3. SSD random read: **~100 µs**. 4. Disk seek: **10 ms**. 5. Cross-continent round trip: **150 ms**.
Everything else is "a bit more" or "a bit less" than an anchor. Then practice the killer question: *how many of X fit in one Y?* E.g., ~5,000 memory references fit in one datacenter round trip — so batching beats chattiness, always.

### Use It

These numbers explain entire product categories: caches exist because memory beats disk by 10³–10⁵; CDNs exist because 150 ms cross-planet beats nothing but 10 ms nearby beats it; batching APIs exist because per-call overhead dwarfs per-byte cost. When someone proposes "just call the service per row," you now have the reflex to say "that's 500 µs × N, so no."

### War Story

Jeff Dean presented these numbers in his 2009 LADIS keynote on building large distributed systems at Google, and they became folklore — ported into interactive "latency numbers every programmer should know" charts that update yearly. The durable insight isn't the digits (SSDs got faster); it's the *ratios*, which have stayed brutal for decades.

### Checkpoint

- Roughly how many main-memory references fit inside one same-datacenter round trip?
- Why is reading 1 MB sequentially from disk (20 ms) only 2x a single disk seek (10 ms), and what does that imply about I/O patterns?
- Your API calls a downstream service once per item for 200 items. Using the table, estimate the added latency in the same datacenter.

## 04. Back-of-the-envelope math

**MOTTO:** Being wrong by 2x is fine; being wrong by 1000x is a career event.

### The Problem

"Will this fit in one Postgres instance?" "Do we need a CDN?" You cannot answer with vibes, and you don't have time for a prototype. Estimation is the cheapest design tool ever invented, and most engineers never practice it.

### The Concept

The trick (Fermi estimation) is decomposition: break a scary unknown into small knowables, multiply, and keep only orders of magnitude. Round aggressively — 86,400 seconds/day is 10⁵, a month is ~2.5 million seconds, a year is ~30 million. Errors partially cancel; your answer lands within 2–3x, which is enough to pick an architecture.

### Build It

Worked example — a Twitter-like app:

```
Assumptions (state them out loud, always):
  300M monthly users, 50% daily     -> 150M DAU
  Each reads 100 tweets/day, writes 0.5

Write QPS:  150M × 0.5 / 10^5 s  ≈ 750 writes/s   (peak ~2x: 1,500)
Read QPS:   150M × 100 / 10^5 s  ≈ 150K reads/s   (peak ~300K)
Read:write ratio ≈ 200:1  ->  this is a CACHING problem, not a DB problem

Storage: 75M tweets/day × ~300 bytes (text+metadata) ≈ 22 GB/day text
  10% have media @ ~1 MB  ->  7.5M × 1 MB ≈ 7.5 TB/day media
  5 years: text ≈ 40 TB (fine), media ≈ 14 PB (object store + CDN, obviously)
```

Three design decisions fell out of arithmetic: cache-heavy read path, ordinary DB for text, blob storage + CDN for media. That's the whole point.

### Use It

| Estimate | Rule of thumb |
|---|---|
| Seconds per day | ~10⁵ (86,400) |
| QPS from DAU | DAU × actions/day ÷ 10⁵; peak = 2–5x average |
| One commodity server | ~10K–100K simple QPS, ~10⁴ connections |
| One modern disk | ~10s of TB; one DB node comfortable at low TBs |

### War Story

Enrico Fermi, watching the 1945 Trinity nuclear test, dropped scraps of paper as the blast wave passed and estimated the yield at ~10 kilotons from how far they blew — remarkably close to the measured ~20 kt, computed from torn paper and arithmetic. Same skill, lower stakes, every design review.

### Checkpoint

- Why is a 200:1 read/write ratio an argument for caching rather than for a bigger database?
- Estimate storage per year for 1M users each uploading one 2 MB photo per week.
- What's the peak-QPS multiplier you should assume over average, and why state assumptions explicitly?

## 05. Powers of two, units, and napkin conversions

**MOTTO:** 2¹⁰ ≈ 10³ is the exchange rate between computer money and human money.

### The Problem

Storage vendors sell TB (10¹²), your OS reports TiB (2⁴⁰), networks measure bits per second, disks measure bytes, and a "million ops" could mean anything. Unit confusion silently corrupts every estimate you make — an 8x error (bits vs bytes) hides comfortably inside sloppy notation.

### The Concept

One conversion rules them all: **2¹⁰ = 1,024 ≈ 10³**. So 2²⁰ ≈ a million (Mi), 2³⁰ ≈ a billion (Gi), 2⁴⁰ ≈ a trillion (Ti) — each off by only 2.4% per step. And burn this in: **network speeds are bits, storage is bytes** — divide link speeds by 8 (call it 10 for napkin math) to get bytes.

```
2^10 = 1,024        ≈ 10^3  (Ki ~ thousand)
2^20 = 1,048,576    ≈ 10^6  (Mi ~ million)
2^30 ≈ 1.07 × 10^9  ≈ 10^9  (Gi ~ billion)
2^32 = 4,294,967,296  <- the wall every 32-bit counter hits
1 Gbps ≈ 125 MB/s   (÷8; use ~100 MB/s on a napkin)
```

### Build It

Napkin toolkit:

1. **Sizes:** char 1 B, int64/pointer 8 B, UUID 16 B, typical DB row 100 B–1 KB, typical JSON API response 1–10 KB, image ~100 KB–5 MB.
2. **Bandwidth sanity:** moving 1 TB over 1 Gbps ≈ 10¹² B ÷ 10⁸ B/s ≈ 10⁴ s ≈ 3 hours. Over the public internet, longer. Hence: shipping disks is sometimes a legitimate protocol.
3. **Counter limits:** int32 overflows at ~2.1 billion (signed) / ~4.3 billion (unsigned); if any counter in your design can plausibly reach billions, use 64 bits *now*.

### Use It

These conversions decide real things: whether replication traffic saturates a NIC, whether a dataset fits in a 256 GiB RAM machine, whether your ID space survives a decade. AWS Snowball — literally trucking disks — exists because the bandwidth arithmetic above is often unflattering.

### War Story

In 2014, "Gangnam Style" exceeded 2,147,483,647 views and maxed out YouTube's signed 32-bit view counter, forcing an upgrade to 64-bit. The same year, the internet's BGP routing table crossed 512K routes and overflowed the TCAM memory defaults in older routers ("512K day"), causing outages worldwide. Powers of two are not trivia; they're walls.

### Checkpoint

- Roughly how long does 10 TB take to transfer over a 1 Gbps link, and what does that suggest about large migrations?
- Why is confusing Gb with GB an 8x error, and where does it typically sneak into designs?
- At what value does a signed 32-bit counter overflow, and name two real systems that hit such a limit.

## 06. Functional vs non-functional requirements

**MOTTO:** Functional requirements say what the system does; non-functional requirements decide what it costs and how it dies.

### The Problem

Two teams build "a checkout service." One serves a boutique with 100 orders/day; the other serves a flash sale with 100K orders/minute. Identical functional spec, unrecognizably different architectures. Skip the non-functional conversation and you'll build the wrong system with perfect fidelity.

### The Concept

Functional requirements are the verbs users can name: post, search, pay. Non-functional requirements (NFRs) are the adverbs: how *fast*, how *many*, how *available*, how *consistent*, how *durable*, how *secure*. Think of a restaurant: the menu is functional; "serves 400 covers on Valentine's Day without the kitchen collapsing" is non-functional — and it, not the menu, dictates the kitchen's design.

```
Functional:      "Users can upload photos"        -> features
Non-functional:  "p99 upload < 2s at 10K conc."   -> architecture
                 "99.99% available"                -> redundancy, $$$
                 "photos never lost"               -> replication, backups
                 "GDPR delete within 30 days"      -> data layout
```

### Build It

Turn vague NFRs into numbers, or they're decoration:

1. **Availability:** count the nines. 99.9% = ~8.8 h down/year; 99.99% = ~53 min; 99.999% = ~5 min. Each nine roughly multiplies cost and complexity.
2. **Latency:** specify percentiles, not averages — "p50 < 100 ms, p99 < 500 ms." Averages hide the users who are having a terrible time.
3. **Scale:** current QPS, expected growth, peak multiplier.
4. **Durability/consistency:** can we lose acknowledged writes (no)? Can reads be a few seconds stale (often yes — say so explicitly).

### Use It

| NFR | Typical mechanism | The bill |
|---|---|---|
| High availability | Replication, failover, multi-AZ | 2–3x infra, ops complexity |
| Low latency | Caching, CDNs, denormalization | Staleness, cache invalidation pain |
| Durability | Multi-copy writes, backups | Write latency, storage cost |
| Strong consistency | Consensus, transactions | Latency, reduced availability in partitions |

### War Story

Healthcare.gov launched in October 2013 functionally complete and non-functionally doomed: designed and tested for a fraction of its launch traffic, it collapsed on day one — reportedly only a handful of users enrolled successfully that first day — and required a months-long rescue effort. The features worked; the system didn't.

### Checkpoint

- Convert 99.95% availability into approximate allowed downtime per year.
- Why must latency requirements be stated as percentiles rather than averages?
- Give one functional and three non-functional requirements for a ride-hailing app's "request a ride" flow.

## 07. How to read (and draw) architecture diagrams

**MOTTO:** A diagram is a claim about reality — make claims precise enough to be wrong.

### The Problem

Most architecture diagrams are wallpaper: forty boxes, undirected lines, three inconsistent meanings for the same arrow, no indication of what happens when anything fails. They impress in slide decks and answer no engineering questions. You need diagrams that can be *interrogated*.

### The Concept

A good diagram fixes three things: **level of zoom**, **arrow semantics**, and **the story of one request**. The C4 model (Simon Brown) formalizes zoom: Context (system + external actors) → Container (deployable units) → Component (modules inside one container). Never mix levels in one drawing — that's how you get a Kubernetes pod next to "The Internet."

```
 Level 1 (Context):   [User] -> [Our System] -> [Stripe]
 Level 2 (Container):
   [Browser] -> [CDN] -> [API GW] -> [App service] -> [Postgres]
                                          |
                                          +--> [Redis cache]
                                          +--> [Queue] -> [Worker]
 Arrows: solid = sync request/response, dashed = async, label = protocol
```

### Build It

1. Pick one zoom level and one primary user journey.
2. Draw the happy path left-to-right (or top-to-bottom), numbered: 1 request in, 2 cache check, 3 DB read...
3. Give arrows direction (who initiates) and labels (protocol + sync/async).
4. Mark state: cylinders or a tag on anything that stores data.
5. Read-test it: can a stranger answer "what happens when the cache dies?" from the drawing alone? If not, annotate.

Reading someone else's diagram, run the same test in reverse: find the entry point, trace one request, find the stateful boxes, ask what each arrow does on failure.

### Use It

Tools: whiteboards and paper (best for thinking), Excalidraw/draw.io (best for sharing), Mermaid/PlantUML (diagrams-as-code, live in the repo, survive refactors). Sequence diagrams complement box diagrams whenever ordering matters — auth flows, payment flows, anything with a race.

### War Story

When Facebook acquired WhatsApp in 2014, WhatsApp served roughly 450 million users with about 32 engineers — an architecture famously simple enough (Erlang, few components, aggressively boring choices) that it *fit on a whiteboard*. Diagram simplicity wasn't a documentation nicety; it was the operational strategy.

### Checkpoint

- What are the three C4 zoom levels mentioned, and why shouldn't one diagram mix them?
- What two properties should every arrow in a serious diagram carry?
- What's the "read-test" that tells you a diagram is complete enough?

## 08. Your lab setup: Docker, tooling, and the playground

**MOTTO:** You don't understand a system until you've broken your own copy of it.

### The Problem

System design rots into trivia unless you can *run* the systems — start a real Postgres, watch a real cache hit ratio, kill a real container mid-request. Installing databases natively turns your laptop into a graveyard of conflicting versions. We need disposable infrastructure.

### The Concept

Docker gives every experiment its own sealed box: an image is a frozen filesystem-plus-config, a container is a running instance, and Compose orchestrates several as one throwaway "datacenter on your laptop." Analogy: containers are shipping containers — standard shape outside, anything inside, trivially loaded, stacked, and discarded.

```
 your laptop
 +---------------------------------------------+
 |  docker compose up                          |
 |  [postgres:16]  [redis:7]  [nginx]  [app]   |
 |      5432         6379       8080           |
 |  docker compose down  ->  all gone, no mess |
 +---------------------------------------------+
```

### Build It

1. Install Docker Desktop (macOS/Windows) or Docker Engine (Linux). Verify: `docker run hello-world`.
2. Create the playground:

```yaml
# playground/docker-compose.yml
services:
  db:
    image: postgres:16
    environment: { POSTGRES_PASSWORD: lab }
    ports: ["5432:5432"]
  cache:
    image: redis:7
    ports: ["6379:6379"]
```

3. `docker compose up -d`, then poke both: `docker exec -it playground-db-1 psql -U postgres`, `docker exec -it playground-cache-1 redis-cli ping`.
4. Install the observation kit: `curl`, `dig`, `python3`, and a load generator (`hey` or `wrk`). Later phases assume these.
5. Practice destruction: `docker kill` a container mid-`psql` and observe the failure from the client side. That reflex — *induce the failure, watch the symptom* — is the whole lab methodology.

### Use It

Everything in this course runs here: sockets labs (Phase 2) against containerized servers, cache experiments against that Redis, replication labs with two Postgres containers. Same workflow the industry uses — Compose for local, Kubernetes for production — so the muscle memory transfers.

### War Story

Docker was unveiled in a five-minute lightning talk by Solomon Hykes at PyCon 2013, as a side project of a struggling PaaS company called dotCloud. Within a few years it had reshaped how the entire industry ships software — a useful reminder that packaging and reproducibility are not "ops details"; they're leverage.

### Checkpoint

- What's the difference between a Docker image and a container?
- Why do we prefer containers over native installs for lab databases?
- What does `docker compose down` guarantee about your machine's state, and why does that matter for experiments?
