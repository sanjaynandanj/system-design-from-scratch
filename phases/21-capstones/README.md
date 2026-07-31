# Phase 21 — 🏆 Capstone Projects

> Stop reading. Start building. Ship all of it.

Eighteen phases of theory buys you exactly nothing until your own code loses a write, deadlocks a queue, or double-sends a message at 2 a.m. These capstones are where the diagrams learn to bleed. Each one is scoped to be genuinely finishable — weekends, not sabbaticals — and each has a Definition of Done, because a capstone that's "basically working" is a capstone you didn't do. Build them in any order, but build them.

## 01. Capstone: A Distributed Key-Value Store

**GOAL:** Build a replicated, partitioned key-value store and watch it survive you killing its nodes.

### What You'll Build
A KV store (GET/PUT/DELETE over HTTP or a simple TCP protocol) that runs as a cluster of 3+ nodes: keys partitioned by consistent hashing, each partition replicated to N nodes, with configurable read/write quorums. A small CLI client and a chaos script that kills and restarts nodes complete the package. Any language; Go and Rust make the concurrency honest.

### Requirements
- Consistent hashing ring with virtual nodes; adding/removing a node reshuffles only its share of keys.
- Replication factor N=3; writes go to N replicas, acknowledged at W; reads at R (configurable — let yourself experiment with R+W vs. N).
- Versioning per key (vector clock or last-writer-wins with hybrid timestamps — implement one, write a paragraph on the other's tradeoff).
- Node failure handling: hinted handoff or read-repair (pick at least one) so a killed-and-revived node converges.
- A persistence layer per node — an append-only log with an in-memory index is enough (or embed your Phase 04 storage engine if you built one).
- Cluster membership via a static config file first; gossip is a stretch goal, not a requirement.

### Milestones
1. Single node: durable GET/PUT/DELETE with an append-only log + hash index; survives restart.
2. Fixed 3-node cluster, client-side consistent hashing, no replication — keys spread correctly (prove it with a distribution histogram).
3. Replication N=3 with W=2, R=2; manual verification that any single node can die with no lost acked writes.
4. Read-repair or hinted handoff: kill a node, write 1,000 keys, revive it, prove convergence with a checksum sweep.
5. Ring rebalancing: add a 4th node live; measure what fraction of keys moved (should be ~1/4, not ~all).
6. Chaos script: random kills every 30 s under sustained load; report lost/stale reads at different R/W settings.

### Stretch Goals
- Gossip-based membership and failure detection (SWIM-lite).
- Merkle-tree anti-entropy sync between replicas.
- A jepsen-style linearizability check with a history checker on a small key range.

### Definition of Done
- [ ] 3-node cluster survives any single node kill with zero lost acked writes at W=2/R=2.
- [ ] Revived node provably converges (checksum sweep passes).
- [ ] Adding a node moves ~1/N of keys, measured and printed.
- [ ] README with your R/W/N experiment results table and one paragraph: "what surprised me."
- [ ] Chaos run of 10 minutes under load completes with a report, not a crash.

### Concepts You'll Cement
Consistent hashing and partitioning (Phase 05), quorum replication and consistency models (Phase 05), storage engines and write-ahead logs (Phase 04), failure detection (Phase 13).

## 02. Capstone: An End-to-End Chat System

**GOAL:** Build a real-time chat where two browsers talk through your infrastructure — and messages survive a server restart mid-conversation.

### What You'll Build
A WhatsApp-shaped system in miniature: a WebSocket gateway holding client connections, a session registry mapping users to gateway instances, per-conversation message ordering, offline delivery via per-user inboxes, and a minimal web client (ugly is fine; correct is mandatory). Run at least two gateway instances behind a load balancer so cross-instance routing is real, not theoretical.

### Requirements
- 1:1 and small group chats; messages get per-conversation monotonic sequence numbers assigned server-side.
- Two+ gateway instances: a message from a user on gateway A reaches a user on gateway B (via a session registry in Redis + pub/sub or an internal RPC).
- At-least-once delivery with client-side dedup by message ID; client acks; unacked messages redelivered on reconnect.
- Offline flow: recipient disconnected → message parks in their inbox (DB or Redis) → delivered on reconnect, in order.
- Delivery receipts (sent/delivered) and a typing indicator (ephemeral — must NOT touch the durable path).
- Reconnect storm safety: client reconnects resume from a cursor, never replay the whole history.

### Milestones
1. Single gateway, two browser tabs, live 1:1 messages over WebSockets. No persistence yet.
2. Durable messages + sequence numbers; kill the server mid-chat, restart, both clients recover full ordered history from their cursors.
3. Second gateway instance + session registry; prove cross-instance delivery by pinning two clients to different instances.
4. Offline inbox: close a tab, send 50 messages, reopen — all 50 arrive, ordered, exactly once from the client's view.
5. Receipts + typing indicators on the ephemeral channel.
6. Load test: 1K simulated clients (a script, not 1K laptops), measure delivery p50/p99 and find your first bottleneck.

### Stretch Goals
- Group chats to 200 members with server-side fan-out and per-member cursors.
- Presence (online/last-seen) with debounced transitions.
- End-to-end encryption for 1:1 chats (libsodium; understand why groups get hard).

### Definition of Done
- [ ] Cross-instance delivery demonstrably works (logs or a demo video showing which gateway each client used).
- [ ] Kill-mid-conversation test: zero lost, zero duplicated, zero reordered messages from either client's view.
- [ ] Offline batch of 50 arrives ordered and deduped.
- [ ] Typing indicators generate zero database writes (prove it with query logs).
- [ ] Load-test report with p50/p99 delivery latency and the identified bottleneck.

### Concepts You'll Cement
WebSockets and long-lived connections (Phase 02), message ordering and delivery semantics (Phases 05, 12), pub/sub routing (Phase 12), the chat case study made real (Phase 17-06).

## 03. Capstone: A URL Shortener, Deployed

**GOAL:** Ship the classic to a public URL, with monitoring, and let the internet actually hit it.

### What You'll Build
The full Phase 17-01 design, deliberately small but *production-shaped*: an API that shortens, a redirect path with a cache, a real domain with TLS, dashboards, alerts, and a load test that proves your p99. The point of this capstone is not the shortener — it's every unglamorous thing around it: deploys, monitoring, backups, and the discipline of an SLO.

### Requirements
- POST /shorten and GET /:code with 302 redirects; base62 codes from a pre-allocated range scheme (no naive random-retry).
- Deployed publicly (any cloud/free tier/VPS) behind TLS on a domain you own; deploys are one command or one push, repeatable.
- Redis (or equivalent) cache on the redirect path; measure and report the hit ratio under load.
- Metrics: request rate, error rate, latency histograms (p50/p95/p99), cache hit ratio — on a Grafana/equivalent dashboard.
- One real alert (e.g., p99 > 200 ms for 5 min, or error rate > 1%) that pages/emails you. Trigger it on purpose once.
- Database backups: automated, and — this is the part everyone skips — restored once, successfully, into a scratch environment.
- Click analytics recorded asynchronously (queue or buffered writer), never on the redirect's critical path.

### Milestones
1. Local end-to-end: shorten + redirect + tests for code generation and collisions.
2. Deployed with TLS on your domain; a link you text to a friend works.
3. Cache + metrics; dashboard shows live traffic with cache hit ratio.
4. Load test (k6/vegeta/wrk): find max sustainable RPS on your instance, record p99 with and without cache — a two-row table that teaches more than a book chapter.
5. Alerting + backup/restore drill; kill the app manually and watch the alert fire.
6. Write the postmortem-style README: architecture, SLO, load numbers, "what would break first at 100×."

### Stretch Goals
- Custom vanity codes with reserved-word protection.
- A second region or second instance with a health-checked failover (even DNS-based).
- Abuse protection: rate limiting per IP (dogfood Capstone 07's flags or Phase 17-03's limiter).

### Definition of Done
- [ ] Public HTTPS URL that shortens and redirects, right now.
- [ ] Dashboard with the four golden signals visible under live load.
- [ ] Load test table: RPS + p99, cache on vs. off.
- [ ] Alert demonstrably fired once; backup demonstrably restored once.
- [ ] README with SLO and the 100× analysis.

### Concepts You'll Cement
The full request path from DNS to DB (Phases 01–03), caching (Phase 06), observability and SLOs (Phase 13), deployment reality no phase can teach — and the case study you can now compare against your own p99 (Phase 17-01).

## 04. Capstone: A Metrics Pipeline

**GOAL:** Build the pipeline that would monitor your other capstones — ingest, aggregate, store, query, graph.

### What You'll Build
A miniature time-series pipeline: an ingest endpoint receiving counter/gauge metrics, a streaming aggregator rolling them into 10-second and 1-minute windows, a storage layer with downsampling and retention, and a query API with a rudimentary graphing UI (or Grafana pointed at your API — teaching Grafana your query contract counts as building the contract). Then close the loop: instrument one of your other capstones and watch it on your own dashboard.

### Requirements
- Ingest: HTTP endpoint accepting batched metric points (name, tags, value, timestamp); handles out-of-order arrival within a bounded window.
- A real queue (Kafka/Redpanda/NATS) between ingest and aggregation — decoupling is the lesson; direct writes are the anti-lesson.
- Aggregator: windowed rollups (sum/avg/max/p95 via a sketch or sorted sample) into 10 s buckets; late events within 60 s update the bucket, later ones are counted and dropped (expose that counter — meta!).
- Storage: buckets keyed by (metric, tags-hash, window); 10 s data retained 24 h, downsampled to 1 min for 30 days; expiry actually runs.
- Query API: range queries with aggregation (`avg of cpu.load where host=web-1, last 6 h, step 1 m`) returning series suitable for graphing.
- Cardinality guardrail: reject or clamp metrics whose tag combinations explode past a configured limit (learn *why* by breaking it first).

### Milestones
1. Ingest → queue → a consumer that just prints; a load generator emitting fake metrics from 20 fake hosts.
2. Windowed aggregation with correct handling of a deliberately shuffled, late-arriving event stream (write the test first).
3. Storage + expiry; prove downsampling by querying the same range at both resolutions.
4. Query API + graphs; a dashboard showing your fake fleet.
5. Instrument a real capstone (03 is ideal) with a client library you write (counters + timers, batched, non-blocking).
6. Kill the aggregator mid-stream, restart, verify buckets are correct (consumer offsets + idempotent upserts = your exactly-once story).

### Stretch Goals
- Alerting: threshold rules evaluated on the stream with a webhook/email action.
- Hot-key handling: salt-and-merge two-stage aggregation for one metric doing 50% of volume.
- A PromQL-flavored subset parser for your query API.

### Definition of Done
- [ ] Shuffled/late event test passes; dropped-too-late counter is itself graphable.
- [ ] Aggregator kill-and-restart produces identical buckets to an uninterrupted run (diff proves it).
- [ ] Both retention tiers queryable; expiry verified after a time-warped test run.
- [ ] A real capstone's live traffic visible on your dashboard via your own client library.
- [ ] Cardinality limit demonstrably enforced.

### Concepts You'll Cement
Streams and windowed aggregation (Phase 12), event time vs. processing time and exactly-once sinks (Phases 12, 17-16), time-series storage and downsampling (Phases 04, 11), observability from the builder's side (Phase 13).

## 05. Capstone: A Mini CDN

**GOAL:** Build a two-node edge cache in front of a real origin and measure — with numbers — why CDNs exist.

### What You'll Build
A caching reverse proxy you write yourself (no nginx cache modules doing the homework), deployed as two "edge" instances in different regions (or two cheap VPSs far apart), fronting an origin server that serves files. Plus routing logic to send clients to the nearer edge, correct HTTP cache semantics, an invalidation API, and a latency report comparing edge vs. origin from two vantage points. This is the capstone with the most satisfying before/after chart.

### Requirements
- Edge proxy: serves from local cache on hit; on miss, fetches from origin, stores, serves — with request coalescing (100 concurrent misses for one file = exactly 1 origin fetch; this is the hardest requirement and the best one).
- Honor Cache-Control (max-age, no-store) and serve conditional requests (ETag/If-None-Match → 304) both edge→client and edge→origin (revalidation).
- Bounded cache with LRU (or LFU) eviction by bytes, not object count; eviction metrics exposed.
- Two edges + one origin, geographically separated; routing via GeoDNS, a tiny redirect service, or documented /etc/hosts vantage testing — honesty about the hack is fine, the two-vantage measurement is not optional.
- Invalidation: an API that purges a path across all edges (fan-out purge), plus support for versioned/hashed filenames as the better alternative — implement both, use the measurement section to argue which you'd keep.
- Per-edge stats endpoint: hit ratio, bytes served, origin fetches, evictions.

### Milestones
1. Single-edge proxy with correct hit/miss/store and Cache-Control honoring; unit tests with a mock origin.
2. Request coalescing under a concurrency test (spawn 100 simultaneous first-requests; assert origin saw 1).
3. LRU eviction under a byte budget; verify with a working-set-larger-than-cache test.
4. Second edge + routing; measure client→edge vs. client→origin latency from two vantage points (friend abroad, cloud shell, or a VPN).
5. Invalidation API with multi-edge purge; demonstrate stale-then-purged-then-fresh.
6. The report: a table of p50/p95 latencies (edge-hit / edge-miss / origin-direct) from both vantages, hit ratios, and origin traffic reduction.

### Stretch Goals
- Stale-while-revalidate and negative caching (cache 404s briefly).
- Tiered caching: edges fetch through a shared "regional" cache to collapse origin load further.
- Range request support (byte-range serving for large files, cached in segments).

### Definition of Done
- [ ] Coalescing test passes: 100 concurrent misses → 1 origin fetch.
- [ ] Conditional requests work both hops (curl transcript in README showing a 304).
- [ ] Eviction respects the byte budget under sustained pressure.
- [ ] Purge propagates to all edges; demonstrated with a timed transcript.
- [ ] Latency report table from two real vantage points, with the origin-offload percentage.

### Concepts You'll Cement
HTTP caching semantics (Phases 02, 06), cache eviction and thundering herds (Phase 06), geographic latency reality (Phase 02), the content-delivery half of Instagram/YouTube (Phases 17-08, 17-09).

## 06. Capstone: A Distributed Job Scheduler

**GOAL:** Build a scheduler that runs jobs on time, exactly-once-ish, across workers that keep dying — because they will.

### What You'll Build
A cron-with-consequences service: clients submit one-shot and recurring jobs via API; a scheduler tier decides what's due; a worker fleet claims and executes jobs (shell commands or HTTP callbacks) with leases, heartbeats, retries, timeouts, and a dead-letter state; a small dashboard shows job history. The centerpiece invariant: a job due at T runs once even when you kill the scheduler at T-1s or the worker at T+1s.

### Requirements
- Job API: submit/cancel/inspect; one-shot (`run_at`) and recurring (cron expression) jobs; per-job timeout, max retries, and backoff policy.
- Durable job store (any SQL DB): every state transition (pending → claimed → running → succeeded/failed/dead) is a durable, auditable row change.
- Worker claiming via atomic lease: `UPDATE ... SET claimed_by, lease_until WHERE state='pending' AND due <= now()` semantics — two workers must never both win (write the concurrency test that proves it).
- Leases + heartbeats: a worker that dies mid-job has its lease expire; the job is retried elsewhere; a job that *completed* but couldn't report must not silently rerun without idempotency protection — give jobs an execution ID and document the at-least-once contract honestly.
- Recurring jobs: next occurrence enqueued on completion (or on schedule — pick, and defend against drift and against overlap of slow jobs with their own next run: `concurrency: forbid|allow`).
- Misfire policy: scheduler down for 10 min — configurable per job: run-once-now, run-all-missed, or skip.
- Priorities and per-queue concurrency limits (max N simultaneous jobs of class X).

### Milestones
1. Single scheduler + single worker + durable store: one-shot jobs run on time; history recorded.
2. Multi-worker claiming with the lease race test (spawn 10 workers, 1 job, assert exactly 1 execution).
3. Failure handling: kill a worker mid-job → lease expiry → retry with backoff → dead-letter after max attempts. All visible in job history.
4. Recurring jobs with cron parsing, drift-free scheduling, and the overlap policy working (a 90 s job on a 60 s schedule behaves as configured).
5. Scheduler HA: two scheduler instances (leader election via DB lock or lease); kill the leader, the follower takes over, the misfire policy handles the gap.
6. Dashboard + load test: 10K due-at-once jobs (the thundering herd), measure dispatch latency distribution.

### Stretch Goals
- Job dependencies (DAG: job B runs after A succeeds) — congratulations, you're building Airflow.
- Cron jitter and rate-smoothing for the herd of `0 0 * * *` jobs.
- Exactly-once execution for idempotent HTTP jobs via execution-ID deduplication at the callee.

### Definition of Done
- [ ] Lease race test: N workers, 1 job, exactly 1 execution — repeatedly, under CI.
- [ ] Kill-worker and kill-leader chaos tests pass with documented (not hand-waved) semantics.
- [ ] Recurring job drift measured < 1 s/day; overlap policies both demonstrated.
- [ ] Misfire policies demonstrated after a deliberate 10-minute scheduler outage.
- [ ] 10K-job herd dispatch report with p99 dispatch delay.

### Concepts You'll Cement
Leases, leader election, and distributed locking (Phase 05), delivery semantics and idempotency (Phase 12), state machines and auditability (Phases 13, 17-13), the queueing theory of thundering herds (Phases 01, 12).

## 07. Capstone: A Feature-Flag Service

**GOAL:** Build the service every company rebuilds badly — flags evaluated in microseconds, updated in seconds, safe under total outage.

### What You'll Build
A feature-flag platform: a control-plane API + minimal UI for defining flags (boolean, percentage rollout, attribute targeting), an evaluation SDK (a real library, in one or two languages) that applications embed, and a distribution layer that pushes flag changes to SDKs in seconds. The defining constraints: evaluation is local (no network call per check — ever), rollouts are sticky (user 123 stays in the 10% as it grows to 20%), and an SDK that can't reach your service keeps working.

### Requirements
- Flag types: on/off, percentage rollout, and rules on context attributes (`user.country == "CA" AND user.plan == "pro"`), with rule ordering and a default.
- SDK evaluates locally against an in-memory ruleset — a flag check is a pure function call, target < 10 µs, benchmarked.
- Sticky bucketing: `hash(flag_key + user_key) % 10000` style — deterministic across SDK instances and languages; growing 10%→20% keeps the original 10% enrolled (test this property explicitly).
- Distribution: SDKs get updates via SSE/streaming (with polling fallback); change-to-effect latency < 5 s, measured.
- Resilience: SDK starts with last-known-good ruleset from a local cache file and hardcoded defaults; total control-plane outage degrades to stale flags, never to errors or blocking startup.
- Audit log: who changed which flag, when, from what to what — flags cause incidents, and this log is how you'll find out.
- Environments (dev/prod) with separate SDK keys.

### Milestones
1. Control plane: flag CRUD + rules engine + storage; golden-file tests for rule evaluation.
2. SDK v1: fetch ruleset, evaluate locally; the bucketing determinism test (two SDK instances, 100K users, identical assignments).
3. Streaming updates: flip a flag in the UI, see an app's behavior change < 5 s later without restart, latency measured and logged.
4. Resilience drill: kill the control plane; restart the app; it boots from cached ruleset and serves — then reconnects and catches up.
5. The percentage-growth stickiness test + a second-language SDK (or a spec + cross-language test vectors proving the hash contract).
6. Dogfood: gate a feature in one of your other capstones behind your own flags, do a 10%→50%→100% rollout, then a kill-switch flip mid-load-test.

### Stretch Goals
- Flag prerequisites (flag B only evaluates if flag A is on) and mutually exclusive experiment groups.
- Evaluation event export (who saw what variant) into your Capstone 04 metrics pipeline — that's an A/B testing platform now.
- Scheduled rollouts (auto-advance 10%→100% over 24 h with an auto-halt on an error-rate metric).

### Definition of Done
- [ ] Benchmark: p99 local evaluation < 10 µs, in the README.
- [ ] Determinism + stickiness property tests pass (including growth 10%→20%).
- [ ] Measured flip-to-effect latency < 5 s over streaming.
- [ ] Control-plane-down drill: app restarts and serves from cache, catches up on recovery.
- [ ] Audit log answers "who turned on the flag that broke prod?" in one query.
- [ ] A real capstone demonstrably dogfooding flags, kill-switch included.

### Concepts You'll Cement
Push vs. pull distribution and streaming (Phases 02, 12), consistent hashing's cousin — deterministic bucketing (Phase 05), graceful degradation and last-known-good design (Phase 13), control plane vs. data plane separation (Phases 10, 13).

## 08. Capstone: The Grand Design (Your System, Defended)

**GOAL:** Design a system of your own choosing at full depth, write the defense document, and survive a hostile review — the closest thing to a thesis this curriculum has.

### What You'll Build
Not code this time: a complete design package for a system *you* pick — ideally something you actually want to build, from your own product ideas or day job. Two deliverables: a **design document** (the kind a senior engineer circulates before a big build) and a **written defense** that pre-empts the hardest objections. Then you present it — live, to at least one human who has been explicitly told to attack it. Choose a system with real teeth: multiple data types, a scaling axis that hurts, at least one correctness-critical flow. "A todo app" is disqualified; "offline-first collaborative todo with sync and sharing" is very much qualified.

### Requirements
- **Design doc** (3,000–5,000 words + diagrams): problem statement and non-goals; functional/non-functional requirements; capacity estimates with arithmetic shown; high-level architecture; data model and API sketches; 3+ deep dives into the genuinely hard sub-problems; failure-mode analysis (what breaks, blast radius, recovery); a phased build plan (v1 → v2 → 10×).
- **Defense doc** (1,500+ words): the 5 hardest questions a hostile reviewer would ask — you write them yourself, and they must be *actually hard* — each answered honestly, including at least one "here's where my design is weak and here's what I'd watch."
- Every major decision in the doc carries a stated alternative and a stated cost (Phase 18-05's grammar, in writing).
- At least one decision must be justified *quantitatively* from your capacity estimates ("we shard because X exceeds Y by Z×").
- A live review: 45–60 min, you presenting, reviewer(s) instructed to probe. Record it if you can.

### Milestones
1. Pick the system; write the one-page problem statement + non-goals; get one person to agree it has teeth.
2. Requirements + napkin math; identify the 3 deep-dive-worthy problems *before* designing (if you can't find three hard problems, your system is too soft — go back to milestone 1).
3. Full design doc draft, including failure-mode analysis and the phased build plan.
4. Write the defense doc: red-team yourself for the 5 hardest questions; revise the design where the red-teaming actually broke it (it should — record what changed).
5. The live defense: present, get attacked, take notes, don't be defensive (Phase 18-06 habits under real fire).
6. Post-review revision: a changelog section — "what the review changed and why," the most senior-engineer artifact in the whole document.

### Stretch Goals
- Build the riskiest component as a proof-of-concept and feed measured numbers back into the doc.
- Run the defense twice with different reviewers and diff the attack surfaces they found.
- Publish the whole package (blog/GitHub) — a public, defended design doc is a better interview asset than any certificate.

### Definition of Done
- [ ] Design doc complete per the requirements list, with arithmetic shown and every major decision carrying alternative + cost.
- [ ] Defense doc with 5 genuinely hard self-authored questions, including one admitted weakness with a monitoring plan.
- [ ] Live review held; at least one design change resulted (a review that changes nothing was too gentle — rerun it).
- [ ] Changelog section documenting what the red-team and the review changed.
- [ ] You can present the whole design, cold, in 10 minutes — timed.

### Concepts You'll Cement
All of it. Requirements and estimation (Phase 18), every architecture pattern you choose to deploy (Phases 00–13), the case-study instincts (Phase 17), and the one skill no lesson can hand you: committing to a design in writing, in public, with your name on it — and changing your mind gracefully when someone finds the crack.
