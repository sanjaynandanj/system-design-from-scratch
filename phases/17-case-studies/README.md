# Phase 17 — 🏗️ Case Studies — Design the Classics

> Every famous system, taken apart and rebuilt on a whiteboard.

You've spent sixteen phases collecting parts: storage engines, queues, caches, consensus. Now we bolt them together into the systems that made those parts famous. Each case study below is a full dress rehearsal — requirements, napkin math, architecture, and the two or three sub-problems that actually decide whether your design survives. Do these on a real whiteboard, out loud, before you read the answer. That's the whole trick.

## 01. Design a URL Shortener

**MOTTO:** A URL shortener is a tiny key-value store wearing a trench coat — the entire design is "how do I generate keys without coordination?"

### Requirements
- **Functional:** shorten a long URL to a ~7-char code; redirect on GET; optional custom aliases; optional expiry.
- **Non-functional:** redirect latency < 100 ms p99; 100:1 read/write ratio; high availability (a dead redirect is a broken internet); codes must not be guessable in sequence (or must be, if you don't care — say which).

### Napkin Math
- 100M new URLs/month ≈ 100M / 2.6M sec ≈ **40 writes/sec**.
- 100:1 reads → **4,000 redirects/sec**, peak maybe 3× → 12K QPS.
- Retention 5 years → 100M × 60 months = **6B records**.
- ~500 bytes/record (long URL + code + metadata) → 6B × 500 B = **3 TB**. One beefy box could hold this; we shard for availability, not size.
- Keyspace: base62, 7 chars → 62⁷ ≈ **3.5 trillion codes**. 6B used = 0.17% full. Plenty.

### High-Level Design
```
client ──> LB ──> API servers ──┬──> Key Generation Service (pre-minted key ranges)
                                └──> DB (code → long_url), sharded by code
client ──> LB ──> Redirect servers ──> cache (hot codes) ──> DB on miss
                                          │
                                          └──> async analytics (Kafka → aggregator)
```
- **API servers**: stateless; take a long URL, grab a fresh code, write the mapping.
- **Key Generation Service (KGS)**: pre-generates unique codes in batches; each API server leases a range (e.g., 10K codes) so writes need zero cross-node coordination.
- **Cache**: redirects follow a power law; a few GB of Redis absorbs ~90% of reads.
- **Analytics** is async — never make the redirect wait for a click-log write.

### Deep Dives
- **ID generation.** Three options. (1) *Random + retry*: generate 7 random base62 chars, insert, retry on collision — at 0.17% occupancy, collisions are rare, but retries are ugly under load. (2) *Counter + base62 encode*: a global counter (or Snowflake-style node+timestamp+sequence) encoded to base62 — no collisions ever, but sequential codes leak creation volume and are enumerable. (3) *Pre-minted KGS*: generate keys offline, hand out ranges. If a server dies holding a leased range, you lose ≤10K codes out of 3.5T. Who cares. KGS wins.
- **301 vs 302.** A 301 (permanent) lets browsers cache the redirect — great for your load, terrible for analytics and expiry, since you never see the second click. Use **302** if clicks are the product; 301 if scale is.
- **Hot keys.** One viral link can be 10% of all traffic. Cache-aside with a short TTL handles it; for true celebrity links, replicate the entry into an in-process cache on every redirect server.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Key generation | Pre-minted KGS ranges | Global counter | No single point of coordination on the write path |
| Redirect status | 302 | 301 | Keep analytics + expiry; pay ~2× redirect traffic |
| Storage | Sharded KV (e.g., DynamoDB/Cassandra) | Single Postgres | 3 TB fits Postgres, but KV gives easy multi-region HA |
| Consistency | Eventual for reads | Strong | A 100 ms replication lag on a brand-new link is invisible |

### Checkpoint
1. Your KGS is down. Can users still shorten URLs? What's your degradation story?
2. A customer wants vanity URLs (`sho.rt/nike`). What changes in the write path and the collision story?
3. How would you delete a phishing link *everywhere*, including from browser caches that saw a 301?

## 02. Design Pastebin

**MOTTO:** Pastebin is the URL shortener with a body — the moment values stop fitting in a DB row, you split metadata from blobs.

### Requirements
- **Functional:** create a text paste, get a short link; view raw or rendered; expiry (10 min / 1 day / never); private/unlisted pastes.
- **Non-functional:** read-heavy (~5:1); paste size up to 10 MB; durable — "never" means never; view latency < 200 ms p99.

### Napkin Math
- 10M pastes/day ≈ 10M / 86,400 ≈ **115 writes/sec**; 5:1 → **~580 reads/sec**.
- Average paste 10 KB → 10M × 10 KB = **100 GB/day** ≈ 36.5 TB/year ≈ **~180 TB over 5 years**.
- Metadata row ~300 B → 10M × 300 B = 3 GB/day; ~5.5 TB over 5 years. Metadata fits a boring relational DB; content does not.
- Bandwidth: 580 reads/s × 10 KB ≈ **6 MB/s** — trivially small. This system is about storage lifecycle, not throughput.

### High-Level Design
```
client ──> LB ──> API ──┬──> metadata DB (paste_id, owner, expiry, blob_key)
                        └──> object store (S3): blob per paste
client ──> CDN ──> object store (public pastes served straight from edge)
                 cron/worker ──> expiry sweeper (delete blobs + rows past TTL)
```
- **Metadata DB** answers "does this paste exist, is it expired, where's the body?"
- **Object store** holds bodies; it's cheaper per GB than any database and infinitely scalable for this shape.
- **CDN** fronts public pastes — they're immutable, the perfect cache candidate.
- **Expiry sweeper** deletes lazily; the read path also checks expiry so a paste is *logically* gone the second it expires even if bytes linger.

### Deep Dives
- **Small-paste optimization.** 90% of pastes are < 10 KB. A round-trip to S3 for 2 KB of text is wasteful. Store bodies ≤ some threshold (say 64 KB) inline in the metadata row; overflow to the object store above it. Measure the threshold, don't guess it.
- **Expiry at scale.** Don't run `DELETE WHERE expires_at < now()` over 6B rows. Partition metadata by expiry bucket (daily tables/partitions) and drop whole partitions; or lean on native TTLs (DynamoDB TTL, S3 lifecycle rules) and treat the sweeper as reconciliation.
- **Abuse.** Pastebin is where credentials go to die. You need hash-based dedup (same blob uploaded 10K times = one object, refcounted), rate limits per IP, and an async scanning pipeline that can tombstone a paste without deleting evidence.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Body storage | Object store + inline small pastes | All in DB | DB storage is 10× the cost; blobs kill page cache |
| Expiry | Lazy check on read + partition drops | Eager per-row deletes | O(1) partition drop beats billions of tombstones |
| Public reads | CDN, immutable cache | Origin every time | Pastes never change; cache-control: immutable |
| Dedup | Content-hash refcount | Store duplicates | Cuts storage ~30% and makes abuse takedown atomic |

### Checkpoint
1. A private paste's URL leaks. Is "unlisted" your only defense? Design real access control.
2. A user edits a paste. What breaks in your CDN + immutability story, and how do you fix it?
3. Legal demands a paste be removed within 15 minutes, globally. Walk the deletion path end to end.

## 03. Design a Distributed Rate Limiter

**MOTTO:** A rate limiter trades a tiny bit of accuracy for a huge amount of availability — decide which side of that trade you're on before you write code.

### Requirements
- **Functional:** limit requests per key (user, IP, API key) against configurable rules (e.g., 100 req/min); return 429 + Retry-After; rules updatable without deploys.
- **Non-functional:** adds < 2 ms p99 to each request; survives limiter-store outages (fail open or closed — pick!); works across a fleet of stateless API servers; near-accurate under burst.

### Napkin Math
- Fleet handles **1M req/sec**; every request = 1 limiter check → 1M checks/sec.
- 100M active keys × ~40 bytes of counter state (key hash + count + window ts) ≈ **4 GB** — fits comfortably in a small Redis cluster.
- Per-check budget: at 2 ms and 1M/s you cannot afford a cross-region hop (~50+ ms). Limiter state must be **same-region, in-memory**.
- Redis at ~100K ops/sec/node → 1M checks/sec needs **~10 shards** (plus headroom), keys hash-partitioned.

### High-Level Design
```
request ──> API gateway ──> local token cache (per-node, tiny TTL)
                             │ miss/expired
                             ▼
                        Redis cluster (sharded counters, Lua for atomicity)
                             ▲
             rules service ──┘ (pushes limit configs to gateways)
```
- **Gateway middleware** does the check inline; the algorithm runs as a Lua script in Redis so read-modify-write is atomic.
- **Sharded Redis** partitions counters by key hash — one key's counter always lands on one shard, so no cross-shard coordination.
- **Local cache** short-circuits keys that are already hard-blocked, saving a network hop on abusive traffic (the traffic you most want to reject cheaply).
- **Rules service** hot-reloads limits; rules live in config, not code.

### Deep Dives
- **Algorithm choice.** *Fixed window* is trivial but allows 2× bursts at window edges (100 at 11:59:59 + 100 at 12:00:00). *Sliding window log* is exact but stores a timestamp per request — memory scales with traffic. The sweet spot: **sliding window counter** (weight previous window by overlap) or **token bucket** (allows controlled bursts, one counter + one timestamp per key). Token bucket is what most gateways ship.
- **Race conditions.** Two gateway nodes read count=99, both increment, both allow: limit broken. Fix: the check-and-increment must be one atomic operation — Redis Lua script or `INCR`-then-check. Never GET-compute-SET.
- **Fail open or fail closed?** Redis is down: do you let everything through (protects UX, invites abuse) or block everything (protects backend, causes an outage)? Rule of thumb: fail **open** for user-facing limits, fail **closed** for expensive internal ops (password attempts, payments). Say this out loud in the interview; it's the question they're fishing for.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Algorithm | Token bucket | Sliding window log | O(1) memory per key; bursts are a feature |
| State | Central Redis shards | Per-node local counters | Local is faster but limits become `N_nodes ×` inaccurate |
| Accuracy | ~exact, atomic Lua | Async batched sync | 2 ms budget allows one hop; batching only if it didn't |
| On store failure | Fail open (user APIs) | Fail closed | Availability > perfect limiting for most endpoints |

### Checkpoint
1. Marketing wants "1,000 req/day" limits. What changes vs. per-minute limits (hint: window length vs. memory vs. recovery-after-crash)?
2. How do you rate-limit *globally* across 3 regions without adding cross-region latency to every request?
3. A single API key (a big customer) does 200K req/sec — your hottest Redis shard melts. Fix it.

## 04. Design a Notification System

**MOTTO:** A notification system is a fan-out machine with a conscience — delivery is easy; *not* over-delivering is the hard part.

### Requirements
- **Functional:** send push (APNs/FCM), SMS, and email; triggered by events or campaigns; per-user preferences and opt-outs; templating; scheduled sends.
- **Non-functional:** at-least-once delivery with dedup (users hate double-buzz more than no-buzz); OTP-class messages < 5 s; campaign throughput in millions/hour without starving transactional sends; provider outages must not lose messages.

### Napkin Math
- 100M users × 10 notifications/day = **1B/day** ≈ 1e9 / 86,400 ≈ **11,600/sec average**, peak 5× ≈ **58K/sec**.
- Message record ~200 B → 1B × 200 B = **200 GB/day** of log/state; 30-day retention ≈ 6 TB.
- Third-party ceilings: APNs/FCM are effectively unbounded; SMS providers throttle (say 10K/sec across accounts) — SMS needs its own queue with its own backpressure.
- Campaign burst: 50M-recipient blast should drain in 1 hour → **~14K sends/sec** sustained from the campaign lane alone.

### High-Level Design
```
event producers ──> notification service ──> Kafka topics
   (order shipped,        (validate, prefs,     ├─ push.txn  ─> push workers ─> APNs/FCM
    campaign engine)       template, dedup)     ├─ sms.txn   ─> sms workers  ─> Twilio et al.
                                                ├─ email     ─> email workers ─> SES
                                                └─ *.bulk    ─> (separate, lower-priority lanes)
                          delivery status ◄── provider callbacks/receipts ──> status store + retries
```
- **Notification service** is the single front door: checks preferences/opt-outs, renders templates, assigns a dedup key, drops the message onto the right topic.
- **Per-channel, per-priority queues**: transactional and bulk never share a lane, so a campaign can't delay your OTP.
- **Channel workers** hold provider credentials, do provider-specific batching, and honor provider rate limits.
- **Status store** tracks per-message state (queued → sent → delivered/failed) and drives retries with exponential backoff onto a retry topic; terminal failures go to a DLQ.

### Deep Dives
- **Exactly-once-ish delivery.** True exactly-once through a third party doesn't exist. You get at-least-once from queues + retries; add an **idempotency key** per logical notification and have workers check-and-set it (Redis SETNX with TTL) before calling the provider. Duplicate sends drop to ~zero; the window that remains (crash between provider call and mark) is the honest answer.
- **Device token hygiene.** Push tokens go stale constantly (app reinstalls, phone upgrades). Feed APNs/FCM feedback (invalid-token errors) back into the token store *immediately* — sending to dead tokens wastes quota and, at Apple's scale, gets you throttled.
- **Priority + backpressure.** When a provider slows down, the queue backs up. Bulk lanes must shed or delay; transactional lanes get the remaining provider budget first. Implement as separate topics with weighted worker pools, not priorities inside one queue (most queues fake priority badly).

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Delivery semantics | At-least-once + idempotency keys | Best-effort at-most-once | Losing an OTP is worse than the dedup machinery |
| Queue layout | Topic per channel × priority | One big queue | Isolation: bulk can't starve transactional |
| Prefs check | At enqueue time | At send time | Cheaper; accept rare "opted out mid-flight" sends |
| Retry policy | Exp backoff + DLQ | Retry forever | A 3-day-late "your ride is here" is worse than nothing |

### Checkpoint
1. A campaign to 50M users was triggered twice by a bad deploy. Which layer stops the double-send, and what's the blast radius if it doesn't?
2. Twilio goes down for 2 hours. Walk through what happens to in-flight SMS and how you'd add a fallback provider.
3. Product wants "notification batching" (digest instead of 10 pings). Where does that logic live in your architecture?

## 05. Design a News Feed

**MOTTO:** Feeds are a precomputation bet — you pay at write time (fan-out) or at read time (fan-in), and celebrities force you to pay both.

### Requirements
- **Functional:** users post; users follow; GET /feed returns a ranked/chronological merge of followees' posts; infinite scroll with cursors; new-post latency to followers < ~1 min.
- **Non-functional:** feed load < 200 ms p99; read-heavy by ~50:1; eventual consistency fine (a post appearing 30 s late is invisible); no lost posts.

### Napkin Math
- 300M DAU, 10 feed loads/day → 3B reads/day ≈ **35K QPS average**, peak ~100K.
- Posts: 20% of DAU post once/day → 60M posts/day ≈ **700 writes/sec**.
- Fan-out: 700 posts/s × 200 avg followers = **140K feed-cache inserts/sec** — this, not the 700, is your write load. This is the whole lesson.
- Feed cache: 300M users × 500 post IDs × ~24 B (post_id + score) ≈ 12 KB/user ≈ **3.6 TB** of Redis. Sharded, replicated — real money, still feasible.

### High-Level Design
```
post ──> post service ──> posts DB
              │
              └──> Kafka ──> fanout workers ──> feed cache (Redis: uid → [post_ids])
                                  │ (skip if author is a celebrity)
read ──> feed service ──┬──> feed cache (precomputed IDs)
                        ├──> celebrity posts (pulled live from follow list ∩ celeb index)
                        └──> hydrate: post service + user service (batch), rank, return page
```
- **Fan-out workers** read the author's follower list and push the post ID into each follower's cached feed (capped list, e.g., latest 500).
- **Feed service** merges two sources at read time: the precomputed list (normal follows) and a live pull of recent posts from followed celebrities. Then hydrates IDs into full posts via batched lookups.
- **Cursor pagination** by (score/timestamp, post_id) — never OFFSET.

### Deep Dives
- **Push vs. pull vs. hybrid.** Pure push: precompute everyone's feed at write time — reads are O(1), but Lady Gaga posting means 100M cache writes for one tweet. Pure pull: at read time, fetch recent posts from all N followees and merge — writes are O(1), but a 1,000-followee user triggers 1,000 lookups per refresh. **Hybrid**: push for normal users, pull for authors above a follower threshold (say 100K). Merge at read. Every real feed does this.
- **Ranking without wrecking latency.** Chronological is a sort. ML ranking wants features per candidate post. Budget it: retrieve ~500 candidates from cache, score with a lightweight model in one batched call (< 50 ms), return top 20. Heavy models re-rank asynchronously for the *next* page.
- **Consistency corner cases.** User posts then immediately refreshes and doesn't see their own post — feels like data loss. Fix cheaply: always union "my own recent posts" into my feed at read time. Deletes: lazily filter tombstoned IDs at hydration rather than chasing them through 200 feed caches.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Fan-out | Hybrid push/pull | Pure push | Celebrity fan-out is O(followers) = pathological |
| Feed storage | Redis ID lists, capped | Full posts in cache | IDs are 50× smaller; hydration is a cheap batch get |
| Ordering | Score cursor pagination | OFFSET pagination | Feeds mutate between pages; offsets skip/dup posts |
| Post visibility | Eventual (~seconds) | Read-your-writes globally | Only the author notices; special-case the author |

### Checkpoint
1. Exactly where is the celebrity threshold, and what data would you collect to set it?
2. A fan-out worker crashes mid-fan-out: 40% of followers got the post. What's your repair story?
3. Product adds "close friends" visibility. Trace a post's fan-out with a visibility predicate attached.

## 06. Design a Chat System (WhatsApp)

**MOTTO:** Chat is a routing problem disguised as a storage problem — the hard part is finding the socket a user is currently behind.

### Requirements
- **Functional:** 1:1 and group messages (≤ 1,024 members); delivery + read receipts; online presence; media; message sync across a user's devices; offline delivery.
- **Non-functional:** delivery < 500 ms when both online; at-least-once with client dedup (never lose a message); end-to-end encryption (server routes ciphertext); connections survive flaky mobile networks.

### Napkin Math
- 1B DAU, ~100B messages/day ≈ 1e11 / 86,400 ≈ **1.2M messages/sec average**, peak ~3M/s (New Year's is real).
- Connections: ~500M concurrent. At ~1M idle conns/box (epoll + small per-conn state), that's **~500 chat servers** just for connection holding.
- Message ~100 B ciphertext + metadata → if stored until delivered (median delivery seconds), steady-state queue is small; the *offline* tail (say 5% undelivered for a day) = 5B × 100 B = **500 GB** hot queue. Trivial.
- Media: 10% of messages carry ~200 KB → 1e10 × 200 KB = **2 PB/day** through the media path (object store + CDN, never through chat servers).

### High-Level Design
```
mobile A ══ websocket ══ chat server 1 ─┐
                                        ├─ session store (user → server, presence)
mobile B ══ websocket ══ chat server 7 ─┘        │
        chat srv 1 ──> route lookup ──> chat srv 7 ──> push to B's socket
                └──> offline queue (per-user inbox) when B unreachable ──> APNs/FCM wake
        media: client ──> presigned URL ──> object store; message carries the key
```
- **Chat servers** hold long-lived WebSocket/custom-protocol connections; they're stateful (the connection) but dumb (no message logic).
- **Session store** (Redis) maps user → current chat server; heartbeats keep it fresh; this is the routing table of the whole system.
- **Per-user inbox** (a Cassandra-style wide row or per-user queue) buffers messages for offline users/devices; deleted after all devices ack. WhatsApp famously stores *undelivered* messages only.
- **Push notification** wakes the app when there's no live socket.

### Deep Dives
- **Message ordering.** There is no global clock. Per-conversation ordering is what users need: assign a per-conversation monotonic sequence at the *inbox/conversation owner shard* (single writer per conversation), and clients render by (seq, sender_ts) with client-side buffering of gaps. Cross-conversation ordering: nobody cares — say so.
- **Presence without melting.** Naive presence: every connect/disconnect fans out to all contacts — 500M conns flapping on mobile networks is a storm. Fixes: debounce transitions (only publish if state stable > 10 s), fan out lazily (send presence only to contacts who currently have the chat open / subscribed), and let clients poll on chat-open as a fallback.
- **Multi-device sync.** Each device has its own inbox cursor. A message to a user fans out to N device queues; receipts are per-device, "delivered" is the OR, "read" is the OR with the earliest read timestamp. E2EE makes this spicy: with Signal-style sessions, sender encrypts per device (or uses sender keys for groups).

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Transport | Persistent WebSocket | Long polling | 100× fewer requests; needed for sub-second delivery |
| Server-side storage | Undelivered only | Full history server-side | Privacy + storage; history lives on devices/backups |
| Ordering | Per-conversation seq, single writer | Global timestamps | Clock skew breaks ordering; per-convo is what UX needs |
| Group fan-out | Server-side copy per member inbox | Client sends N times | One upload; server multiplies; sender keys keep E2EE |

### Checkpoint
1. Chat server 7 dies with 1M connections. Walk through reconnection: how fast is the routing table repaired, and what happens to messages sent to those users during the gap?
2. Group of 1,024: one member is offline for a week. Where does the group's week of messages live, and what's the cost model?
3. How do read receipts work when the reader has 3 devices and one of them is a laptop that's been closed for a day?

## 07. Design Twitter/X

**MOTTO:** Twitter is the news feed problem at maximum hostility — tiny writes, colossal fan-out, and the timeline must feel instant anyway.

### Requirements
- **Functional:** post tweets (280 chars + media); follow; home timeline (merged, ranked); likes/retweets/replies with live-ish counts; search and trending.
- **Non-functional:** timeline < 200 ms p99; ~50:1 read-to-write; posts visible to followers in seconds; counts may be approximate; no lost tweets, ever.

### Napkin Math
- 500M tweets/day ≈ 5e8 / 86,400 ≈ **5,800 tweets/sec**, peak ~20K/s.
- 200M DAU × 20 timeline loads = 4B loads/day ≈ **46K QPS**, peak ~150K.
- Fan-out: 5,800 tweets/s × ~200 median-ish followers = **~1.2M timeline-cache writes/sec** (celebrities excluded — see deep dive).
- Storage: tweet row ~300 B (text, ids, ts) → 500M × 300 B = **150 GB/day**, ~55 TB/year — small! Media and indexes dwarf the tweets themselves.
- Timeline cache: 200M active users × 800 entries × 20 B ≈ **3.2 TB** Redis.

### High-Level Design
```
tweet ──> write API ──> tweets DB (sharded by tweet_id)
             │──> Kafka ─┬─> fanout workers ──> home-timeline cache (uid → tweet_ids)
             │           ├─> search indexer (inverted index)
             │           └─> trends/counters pipeline (stream aggregation)
read ──> timeline svc ──> timeline cache + celeb pull ──> hydrate (tweets, users, counts) ──> rank ──> page
```
- Same skeleton as the news feed (Lesson 05) — the differences are all in degree: bigger fan-out skew, heavier counters, plus search/trends as first-class stream consumers.
- **Counters** (likes/retweets) are sharded counters aggregated in the stream layer; the read path shows cached, slightly-stale values.
- **Search** consumes the same firehose; tweets are indexed within seconds (this was the actual "Earlybird" design).

### Deep Dives
- **The celebrity problem, quantified.** 100M followers × one tweet = 100M cache writes. At 1M writes/sec that's 100 *seconds* of the entire fan-out fleet for one tweet — and Cristiano tweets more than once. So: authors above a threshold are flagged; their tweets skip fan-out and are *pulled* at read time (each timeline read checks "which celebs do I follow → any new tweets?" against a tiny hot set, then merges). The hybrid is not an optimization; it's the only design that works.
- **Counting at scale.** A like is a (user, tweet) edge plus a counter bump. Naive `UPDATE count = count + 1` on a viral tweet serializes on one row. Instead: likes append to a stream; a streaming job aggregates per-tweet deltas per second and folds them into a counter store; reads get eventually-correct counts. The (user, tweet) edge table (for "did I like this?") is sharded by user — that read is per-viewer, not per-tweet.
- **Timeline ranking budget.** Retrieve ~800 candidate IDs (cached fan-out + celeb pull + a few injected recommendations), hydrate in batched multigets, score with a light model, return 20. Every millisecond here is p99 timeline latency; heavyweight ML runs offline to precompute per-user features, not per-request.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Fan-out | Hybrid push/pull (celeb threshold) | Pure push | 100M-follower fan-out is quadratic pain |
| Counts | Streamed, approximate | Transactional counters | Serialized hot rows can't do 20K likes/sec on one tweet |
| Tweet IDs | Snowflake (time-ordered) | Auto-increment | K-sorted IDs give free chronological merge + sharding |
| Timeline consistency | Eventual, seconds | Strong | Nobody can tell; author sees own tweets via read union |

### Checkpoint
1. Retweets: copy the tweet into timelines, or reference it? What breaks (edits? deletes? counts?) under each?
2. The World Cup final ends: writes spike 10× in one minute. Which component falls over first, and what's the graceful degradation?
3. How would you build "views count" (shown on every tweet, updated live) without adding a write per impression to your main store?

## 08. Design Instagram

**MOTTO:** Instagram is a metadata system strapped to a blob-delivery system — design them separately or both will be bad.

### Requirements
- **Functional:** upload photos/videos with captions; follow graph; home feed; stories (24 h TTL); explore/discover; likes + comments.
- **Non-functional:** feed images render < 200 ms perceived; uploads durable before ack; read-heavy ~100:1 on media; global audience → CDN mandatory; graceful quality degradation on slow networks.

### Napkin Math
- 500M DAU; 100M uploads/day ≈ **1,160 uploads/sec**, peak ~4K/s.
- Original ~2 MB average → 100M × 2 MB = **200 TB/day** ingest; plus ~3 derived renditions ≈ 100 TB → **~300 TB/day** total; ~110 PB/year. Object storage economics decide this product's margins.
- Views: 500M DAU × 50 images × 200 KB (compressed rendition) = 2.5e10 × 200 KB = **5 PB/day** egress ≈ 58 GB/s ≈ **~460 Gbps** average — with >90% served by CDN edge, or you're bankrupt.
- Metadata: 100M posts/day × 500 B = 50 GB/day — a rounding error next to media. Two very different systems; one product.

### High-Level Design
```
upload ──> API ──> object store (original, ack after durable write)
                      │──> Kafka ──> processing workers (resize, transcode, thumbnail, safety scan)
                      │                   └──> renditions to object store ──> CDN
                      └──> metadata DB (post row: user, caption, media keys, ts)
feed ──> feed svc (hybrid fan-out, as in 05) ──> post metadata ──> CDN URLs per rendition
stories ──> stories cache (Redis, TTL 24 h) ──> viewers list per story
```
- **Ack after original is durable**, process asynchronously — the post can appear with a low-res placeholder while renditions finish.
- **Processing workers** emit multiple renditions (thumbnail / feed / full; several video bitrates) so clients fetch exactly what the screen needs.
- **Stories** are a separate, gloriously simple system: TTL'd cache entries, no permanent index, viewers tracked in a per-story set. Let TTL do the deleting.
- Feed mechanics are Lesson 05's hybrid fan-out; don't redesign them, reuse them.

### Deep Dives
- **Media pipeline.** Upload → durable original → fan out processing jobs → renditions → CDN warm. Failure at any stage must be retryable, so jobs are idempotent (keyed by media_id + rendition). Video is the expensive one: transcoding a 60 s video into 4 bitrates costs ~minutes of CPU; the queue for it is the system's biggest compute line item. Serve the poster frame instantly, backfill bitrates.
- **Feed image latency.** p99 "feed feels fast" is won by: CDN with high hit ratio (immutable renditions, content-hashed URLs, infinite cache), client prefetching the next screenful of image URLs, and progressive/low-quality-image-placeholder loading. The backend's job is to hand out the *right rendition URL* per device + network hint.
- **The like counter, again, but worse.** Instagram's viral posts collect tens of millions of likes. Same streamed-counter pattern as Twitter, plus an important read trick: below a threshold show exact counts, above it show "1.2M" — rounding buys you enormous slack in counter freshness.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Media storage | Object store + CDN, content-hashed | DB blobs / own servers | Immutable + hash = infinite cacheability |
| Processing | Async, ack early | Sync transcode on upload | Upload UX can't wait minutes; placeholders bridge |
| Renditions | Pre-generate fixed set | Resize on-the-fly at edge | Predictable cost; on-the-fly for long-tail sizes only |
| Stories storage | TTL'd cache, ephemeral | Same store as posts | TTL-native storage makes "disappearing" free |

### Checkpoint
1. A user uploads on a subway connection and the app dies at 80%. Design resumable uploads.
2. Explore/discover needs candidates you *don't* follow. Where does that pipeline plug into this architecture?
3. Copyright strike: one video must vanish globally, including CDN edges, in minutes. What's the purge path and its SLA?

## 09. Design YouTube

**MOTTO:** YouTube is a factory bolted to a firehose — an ingestion/transcode pipeline on one side, a planet-scale CDN on the other, and metadata in the middle pretending to be the hard part.

### Requirements
- **Functional:** upload video (up to hours long); watch with adaptive quality; search; comments/likes; recommendations; live streaming (mention, scope out).
- **Non-functional:** start playback < 1–2 s ("time to first frame"); no buffering on stable networks (adaptive bitrate); uploads durable immediately, watchable in minutes; view counts approximate; availability over consistency everywhere except ownership/monetization.

### Napkin Math
- Uploads: ~500 hours/minute = **720,000 hours/day**. At ~3 GB/hour source ≈ **2.1 PB/day** raw ingest; transcoded renditions add ~1–1.5× → **~5 PB/day** written.
- Watch: ~1B hours/day → 1e9 × 3,600 = 3.6e12 streaming-seconds / 86,400 ≈ **42M average concurrent viewers**; at ~3 Mbps average ≈ **~125 Tbps** aggregate egress. This is why Google builds edge caches into ISPs.
- Transcode compute: 720K hours/day at ~1× realtime per rendition × 5 renditions ≈ 3.6M compute-hours/day ≈ **150K machines** busy full-time. Chunked parallel transcoding is not optional.
- Metadata: ~500M new rows/day (videos, comments) — big, but ordinary sharded-DB territory.

### High-Level Design
```
upload ──> upload svc (resumable, chunked) ──> raw store
                └──> DAG scheduler ──> split into ~10s segments ──> transcode workers (per segment × rendition)
                                              └──> assembled renditions + manifests (DASH/HLS) ──> origin store
watch ──> player ──> manifest ──> CDN edge (segment cache) ──> origin on miss
                └──> metadata API (title, counts) ──> view-count stream pipeline
```
- **Chunked uploads**: client splits the file, uploads segments in parallel, resumes on failure.
- **DAG pipeline** (this is real: it's a graph of tasks — inspect → split → transcode segments in parallel → assemble → thumbnail → safety scan). Splitting a 2-hour video into 10 s segments turns a 10-hour transcode into minutes of parallel work.
- **Adaptive bitrate (ABR)**: each video becomes N renditions × M segments plus a manifest; the *player* picks the rendition per segment based on measured bandwidth. The server is dumb; the client adapts.
- **CDN** serves segments; popular videos live at the edge, the long tail on origin.

### Deep Dives
- **Transcoding as a distributed job system.** Segment-level parallelism, idempotent tasks (segment × rendition), a scheduler with priorities (a creator with 10M subs jumps the queue; a 0-view backlog video waits), spot/preemptible compute for cost. Design it like Lesson 19-06's job scheduler, because it is one.
- **Time to first frame.** The player fetches manifest + first segments of a *low* rendition first (fast start), then ratchets quality up. Keep manifests tiny, put the first segments in the hottest cache tier, and let popular videos' opening segments live basically everywhere.
- **View counting.** A "view" per watch at 5B+ views/day cannot be a DB increment. Views flow into the stream pipeline; per-video counts are aggregated in windows and pushed to a counter cache; monetized views get a stricter, slower, fraud-filtered pipeline. Two pipelines, two SLAs — display counts are marketing, monetized counts are money.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Transcode granularity | Per-segment parallel | Whole-file | Minutes vs. hours to publishable; retry blast radius tiny |
| Quality adaptation | Client-side ABR (HLS/DASH) | Server-picked bitrate | Client sees its own bandwidth; server can't |
| Storage tiers | Hot edge / warm origin / cold archive | One tier | 80% of watches hit ~1% of videos; tier or overpay |
| View counts | Streamed approximate + audited monetized path | Exact everywhere | Exactness only matters where money does |

### Checkpoint
1. A video goes from 10 views/day to 10M views/hour after a celebrity shares it. Trace the caching layers' reaction, second by second.
2. Where do thumbnails, captions, and preview-on-hover sprites fit into the pipeline DAG?
3. Live streaming: which parts of your VOD design survive, and which must be rebuilt?

## 10. Design Dropbox / Google Drive

**MOTTO:** File sync is a metadata consensus problem — the bytes are easy; agreeing on *which version everyone has* is the product.

### Requirements
- **Functional:** upload/download files; sync across devices automatically; share files/folders with permissions; version history; offline edits that reconcile.
- **Non-functional:** never lose or corrupt a file (durability is the brand); small-edit sync in seconds; bandwidth-efficient (don't re-upload 4 GB for a 1-byte change); consistent conflict story (no silent overwrites).

### Napkin Math
- 500M users × ~5 GB average stored = **2.5 EB** logical. Dedup + compression commonly saves ~30–40% → ~1.6 EB physical. Exabytes: this is object-storage-plus-erasure-coding territory.
- 100M DAU × 10 file changes/day = 1B sync events/day ≈ **11,600/sec**, peak ~50K/s — the metadata plane's load.
- Block size 4 MB: a 400 MB file = 100 blocks; a 1-byte edit re-uploads **1 block (4 MB), not 400 MB**.
- Notification fan-out: each change pings the user's other devices (~3) → ~35K pushes/sec. Long-lived connections, not polling — 100M devices polling every 10 s would be 10M QPS of nothing.

### High-Level Design
```
client (watcher + chunker + local index)
   │ content-hash blocks (4 MB)
   ├──> block service ──> "which hashes do you already have?" ──> object store (blocks, content-addressed)
   ├──> metadata service ──> file journal (namespace_id, path, version, [block hashes])
   └◄── notification service (long poll/SSE: "namespace changed, sync!")
share ──> sharing/permissions service ──> namespace membership + ACLs
```
- **Client does the smart work**: watches the filesystem, splits files into blocks, hashes them, and asks the server which blocks it needs to send (dedup happens *before* upload).
- **Block store** is content-addressed (key = hash): identical blocks across users/files stored once, refcounted.
- **Metadata journal** is the source of truth: an append-only, versioned log per namespace. A "file" is a metadata row pointing at an ordered list of block hashes.
- **Notification service** tells other devices "your namespace moved from version N to N+3"; they fetch the journal delta and then just the missing blocks.

### Deep Dives
- **Delta sync + dedup.** Content-defined chunking (rolling hash) beats fixed 4 MB blocks when bytes are *inserted* (fixed blocks all shift and re-hash; content-defined boundaries realign). Interviewers love this distinction. Dedup also means upload of a popular file (that ISO everyone has) is instant — hash matches, zero bytes sent.
- **Conflicts.** Two devices edit the same file offline. Do NOT merge silently. The journal's compare-and-swap (write at version N+1 only if you built on N) detects the loser, whose copy becomes "report (conflicted copy, device B)". Both versions survive; humans resolve. Boring, correct, exactly what Dropbox does.
- **Sharing semantics.** A shared folder is its own namespace mounted into each member's tree. That makes permissioning and sync scoping clean — one journal per shared folder, members subscribe to it — instead of an ACL check on every path prefix of every file.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Sync unit | Content-addressed blocks | Whole files | 1-byte edit ≠ 4 GB upload; dedup for free |
| Conflict policy | Fork + surface to user | Last-writer-wins | LWW silently destroys someone's work |
| Change detection | Server push (long-lived conn) | Client polling | 100M pollers = self-inflicted DDoS |
| Metadata store | Strongly consistent journal + CAS | Eventual | Version agreement IS the product; blocks can be eventual |

### Checkpoint
1. A user's client is compromised and uploads garbage over 10,000 files. How does version history + journal design bound the damage, and what's recovery?
2. Two users drag the same subfolder to different locations in a shared folder, offline. What does the journal see, and what should users see?
3. Estimate the refcounting burden of content-addressed dedup: what breaks when you delete a block that 40,000 files reference?

## 11. Design Uber

**MOTTO:** Uber is a spatial index with a heartbeat — millions of moving points, and every query is "who's near me *right now*?"

### Requirements
- **Functional:** rider requests ride; nearby drivers found and offered the job; matching; live trip tracking; ETA; pricing (incl. surge); trip lifecycle + payment handoff.
- **Non-functional:** match a rider in < ~15 s; location updates ingested at massive scale but individually disposable; the *trip* state machine must never be lost or duplicated (exactly-once-ish on money-adjacent events); regional isolation (Sydney down ≠ São Paulo down).

### Napkin Math
- 25M trips/day ≈ **~300 ride requests/sec average**, peak ~2K/s. Small! Matching is not a throughput problem.
- Location: 3M concurrent drivers × 1 ping / 4 s = **750K location writes/sec**. THIS is the throughput problem — 2,500× the request rate.
- Ping is ~30 B (driver_id, lat, lng, ts, status) → 750K × 30 B ≈ 22 MB/s in-memory churn; live index for 3M drivers ≈ 3M × ~100 B = **300 MB** — the entire live world fits in RAM. Design accordingly.
- Trip records: 25M/day × ~2 KB (route polyline, states, fare) = **50 GB/day** durable — ordinary.

### High-Level Design
```
driver app ──(ping /4s)──> location gateway ──> geo-sharded in-memory index (H3/geohash cells → drivers)
                                             └──> Kafka ──> trip tracker, ETA models, history (downsampled)
rider ──> ride svc ──> matching svc ──> query index: cells within radius ──> rank (ETA, rating)
                          │──> offer to driver (push, 15 s TTL) ──> accept ──> trip service
trip service ──> trip state machine (requested→matched→enroute→ongoing→done) ──> payment svc
```
- **Location index**: in-memory, sharded by geographic cell (Uber uses H3 hexagons). A driver ping updates one cell entry; a rider query gathers drivers from the ~7 cells covering the search radius (spiral outward if sparse).
- **Location durability: none needed.** A ping is superseded 4 s later; if a shard dies, rebuild from the next round of pings. Kafka gets a copy for analytics/ETA — that's the durable path, off the hot path.
- **Trip service** is the opposite regime: a durable, transactional state machine (relational DB, one row per trip, explicit state transitions).
- **Matching** offers sequentially/batched to top-ranked drivers with expiring offers, handling the "driver ignores it" case by design.

### Deep Dives
- **Geospatial indexing.** Why cells (geohash/H3) and not a DB with lat/lng indexes? Because "range query on two columns" is a poor fit for B-trees, and 750K updates/sec would shred any disk index. Cells turn proximity into "hash lookup on ~7 keys" over in-memory sets. H3's hexagons have near-uniform neighbor distances (squares' diagonal neighbors are √2 farther) — a genuinely good interview flex, one sentence, move on.
- **Double-dispatch prevention.** Two riders, one nearby driver, 300 ms apart: both matchers pick her. The driver's *offer slot* must be a lease — an atomic claim (single-writer per driver, e.g., driver state lives on one shard, or a CAS on the driver's status) so the second matcher sees "busy" and takes driver #2. Money-adjacent invariants get single-writer treatment; location pings don't.
- **Surge pricing.** A streaming job computes demand/supply ratios per cell per minute; a pricing multiplier is looked up at request time. Key design point: surge is *read* at quote time and *frozen into the trip record* — riders are charged what they were quoted, whatever the multiplier does mid-trip.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Location store | In-memory geo-sharded cells | Durable DB w/ spatial index | Pings are disposable; RAM index rebuilds itself in 4 s |
| Cell scheme | H3 hexagons | Geohash rectangles | Uniform neighbor distance → better radius queries |
| Matching claim | Atomic lease per driver | Optimistic, apologize later | Double-dispatch is a user-facing catastrophe |
| Trip state | Transactional state machine | Event-sourced only | Explicit states make refunds/support/debug tractable |

### Checkpoint
1. A city has 50K drivers in one downtown cell at rush hour (hot cell). How do you keep query and update latency flat?
2. Rider's phone dies mid-trip. What does the trip state machine do, and who's the source of truth for trip end + fare?
3. Design "shared ride" (pooling) matching on top of this — what new index and what new latency budget do you need?

## 12. Design Ticketmaster

**MOTTO:** Ticketmaster is an inventory-contention system wearing a website — 100K seats, 1M buyers, and every design choice is about who waits where.

### Requirements
- **Functional:** browse events; view seat map with real-time availability; hold seats during checkout (~10 min); purchase; no double-selling, ever; waiting room for high-demand on-sales.
- **Non-functional:** absolute correctness on inventory (oversell = lawsuits); survive 100× traffic spikes at on-sale second; browse can be stale, checkout cannot; fairness (bots out, queue order honored-ish).

### Napkin Math
- Baseline: ~10K QPS browsing. On-sale spike: 1M users arriving in the first minute ≈ **~20K arrivals/sec** hitting the waiting room, browse traffic 100×.
- Actual purchase throughput ceiling is *inventory-bound*: 100K seats / (say) 30 min sell-out = **~55 purchases/sec**. The write path is tiny; the read/queue path is enormous. Design shape: giant funnel.
- Seat map: 100K seats × ~20 B state ≈ 2 MB per event — the whole map fits in one cache entry; version it and diff-push updates.
- Holds: 10-min TTL × ~55 purchases/sec ≈ up to ~33K concurrent holds worst case — trivial state, tricky semantics.

### High-Level Design
```
1M users ──> waiting room (virtual queue: token + position, admits N users/sec)
                 └──> browse tier (CDN + seat-map cache, seconds-stale is fine)
admitted ──> seat selection ──> hold service (seat lock w/ TTL, atomic claim)
                 └──> checkout ──> payment ──> booking DB (transactional: hold → sold)
                 └──> hold expiry ──> seat released ──> seat-map cache updated
```
- **Waiting room**: users get a queue token; a gate admits a controlled trickle (matched to what checkout can absorb). Everyone else sees a position number, which is honest and calm. This converts a stampede into a steady stream — the single most important component.
- **Browse tier** serves cached seat maps; staleness of a few seconds is acceptable because the *hold* step re-validates.
- **Hold service**: claiming a seat is an atomic conditional write (seat status: available → held(user, expires_at)). Redis with Lua or a DB conditional update — either, but exactly one authority per seat.
- **Booking DB**: the purchase transaction flips held → sold and records the order; payment failure or TTL expiry releases the seat.

### Deep Dives
- **No oversell, no deadlock.** Seat claiming must be: atomic (one winner), TTL'd (abandoned carts self-heal), and single-authority (one shard owns a seat; no distributed lock across replicas). The classic failure: hold in Redis, sale in Postgres, and a crash between them — resolve by making the booking transaction re-check the hold *and* by an expiry reconciler that treats the booking DB as truth.
- **Fairness and bots.** The waiting room token must be unforgeable (signed), rate-limited per account/device/payment fingerprint, and issued *before* the on-sale moment randomizes to blunt refresh-sniping. Perfect fairness is unachievable; say what you're optimizing (bots ejected, humans FIFO-ish) and what you're not.
- **Seat-map liveness.** 500K browsers watching 100K seats flip. Push diffs (seat 14B → held) over SSE/WebSocket from a pub/sub of seat events, coalesced to ~1 update/sec per client; or simply poll the versioned map every 2 s — at these sizes polling a 2 MB cached blob (or its delta) is defensible. Don't let liveness traffic anywhere near the hold service.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Spike handling | Virtual waiting room | Autoscale to the spike | Inventory caps real throughput; scaling browse ≠ scaling seats |
| Seat locks | TTL holds, single authority | Distributed locks | TTL self-heals abandonment; distributed locks add failure modes |
| Browse consistency | Stale-ok cache | Real-time everywhere | Hold step re-validates; staleness costs nothing real |
| Inventory truth | Transactional booking DB | Cache as truth | Money + finite goods = ACID, no debate |

### Checkpoint
1. Payment provider takes 45 s to respond during the spike. Holds are 10 min. What breaks, and what do you tune?
2. Taylor Swift adds a second show. Can your waiting room handle *two* simultaneous on-sales sharing an audience?
3. Design "best available seat" — automatic assignment — without turning contiguous-seat search into a lock-contention nightmare.

## 13. Design a Payment System

**MOTTO:** In payments, you are never the source of truth — the design is a reconciliation loop between your ledger and everyone else's.

### Requirements
- **Functional:** charge a customer (card via PSP like Stripe/Adyen); record every money movement in a ledger; refunds; payouts to merchants; handle PSP webhooks; reconciliation.
- **Non-functional:** never double-charge, never lose a payment (correctness ≫ latency); every state transition durable and auditable; PSP flakiness assumed; ~99.99% availability on the charge path; compliance (PCI — don't touch raw card numbers).

### Napkin Math
- 100M transactions/day ≈ **~1,160 TPS average**, peak ~10K TPS (flash sale). Modest throughput — this system is hard for correctness reasons, not scale reasons.
- Ledger: double-entry → ≥ 2 entries/transaction × ~500 B ≈ 100M × 1 KB = **100 GB/day**, ~36 TB/year, retained ~forever (regulatory 7+ years) → plan ~250 TB. Append-only, partitioned by date: cheap.
- PSP latency: 1–3 s per auth. At 10K TPS peak that's up to ~30K in-flight requests — your charge path must be async-friendly, not thread-per-request-blocking.
- Webhook volume ≈ 2–3 events per transaction ≈ **~3,500/sec average** inbound to ingest idempotently.

### High-Level Design
```
checkout ──> payment service ──> payments DB (state machine: created→pending→succeeded/failed)
   (idempotency key)  │──> PSP client ──> Stripe/Adyen (card details go client→PSP directly; you keep a token)
                      │◄── webhooks ──> webhook ingester (verify, dedupe) ──> Kafka ──> state updater
                      └──> ledger service (double-entry, append-only)
nightly: reconciliation job ──> PSP settlement files vs. ledger ──> discrepancy queue (humans)
```
- **Payment service** owns a per-payment state machine; every transition is a durable write *before* any external call's result is acted on.
- **Idempotency keys** from the client (retry-safe checkout) AND to the PSP (their idempotency header) — belt and suspenders on both hops.
- **Ledger** is append-only double-entry: debits = credits, always, enforced per transaction. Balances are derived (materialized), never hand-edited.
- **Reconciliation** compares your ledger to PSP settlement reports daily; mismatches go to a human queue. This job is not optional plumbing; it's the system's immune system.

### Deep Dives
- **The double-charge problem.** Client retries a timed-out "pay" click. Defense: client sends an idempotency key (UUID per checkout attempt); payment service does create-if-absent on that key and returns the existing payment's state on replay. Then *your* call to the PSP times out — did it charge? Unknown! You must not blindly retry a fresh charge: retry with the *same* PSP idempotency key, or query the PSP for the payment's status before acting. "Timeout ≠ failure" is the sentence to say in the interview.
- **State via webhooks (out-of-order, duplicated).** PSPs deliver webhooks at-least-once and unordered ("succeeded" can arrive before "pending"). Ingester verifies signature, dedupes on event ID, and the state machine only accepts *legal transitions* — a stale "pending" arriving after "succeeded" is a no-op, not a regression. Also poll the PSP as backstop for webhooks that never arrive.
- **Ledger correctness.** Why double-entry? Because a single mutable `balance` column can't tell you *why* it's wrong. Every movement is two immutable entries (debit merchant-receivable, credit customer-payment); invariant checks (per-transaction sum = 0; per-account balance = Σ entries) run continuously. Auditors, refunds, and 3 a.m. incident debugging all read the same append-only truth.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Card handling | PSP tokenization (client→PSP direct) | Store PANs yourself | PCI scope shrinks from "your company" to "one iframe" |
| Ledger | Append-only double-entry | Mutable balances | Auditability; corruption becomes detectable, not silent |
| PSP truth sync | Webhooks + polling + reconciliation | Trust webhooks alone | At-least-once, unordered, and sometimes never |
| Charge path | Persist state before/after each hop | Fire-and-hope | Crash between hops must be recoverable from DB alone |

### Checkpoint
1. The PSP is fully down for 20 minutes during peak. Design the queue-and-retry story: what does the customer see, and what invariants hold?
2. A refund is requested for a payment currently in `pending`. Walk the state machine — every legal path.
3. Reconciliation finds 43 transactions in the PSP report that your ledger has no record of. List the possible causes in order of likelihood, and the repair for each.

## 14. Design a Web Crawler

**MOTTO:** A crawler is a BFS over a hostile, infinite graph — politeness and dedup are the design; the fetching is just HTTP.

### Requirements
- **Functional:** given seed URLs, fetch pages, extract links, keep crawling; store page content for downstream indexing; re-crawl by freshness; respect robots.txt.
- **Non-functional:** politeness (never hammer one host — this is a hard correctness rule, not a nicety); dedup (URL-level and content-level); handle traps (infinite calendars, session-ID URLs); horizontally scalable; resumable after crash.

### Napkin Math
- Target: 1B pages/month ≈ 1e9 / 2.6M s ≈ **~385 pages/sec** sustained.
- Fetch: avg page ~500 KB with assets ignored, HTML-only ~100 KB → bandwidth 385 × 100 KB ≈ **~39 MB/s ≈ 310 Mbps**. A handful of fetcher nodes.
- Concurrency: at ~1 s average fetch latency, 385 pages/sec needs **~400 concurrent connections** minimum; with politeness delays (1 req / host / few sec), you need URLs from **tens of thousands of distinct hosts in flight** to keep the pipe full — this is why the frontier's structure matters more than fetcher count.
- Storage: 1B × 100 KB = **100 TB/month** raw HTML (compressed ~4:1 → 25 TB). Seen-URL set: 10B URLs × ~16 B fingerprint = 160 GB — shard it or Bloom-filter it.

### High-Level Design
```
seeds ──> URL frontier ──┬── front queues (priority: freshness, PageRank-ish)
                         └── back queues (ONE per host + host→queue map, politeness timers)
fetchers (async I/O) ──> DNS cache ──> robots cache ──> GET ──> content store (raw HTML)
     └──> parser workers ──> link extractor ──> URL filter/normalizer ──> dedup (seen-URL set, content hash) ──> frontier
```
- **URL frontier** (the Mercator design — name it): *front* queues implement priority; *back* queues enforce one-queue-per-host so a host is fetched by at most one worker, with a per-host next-allowed-time. This single structure delivers both priority and politeness.
- **Fetchers** are async-I/O machines (thousands of concurrent sockets each), consulting cached DNS and cached robots.txt per host.
- **Parsers** are separate from fetchers (CPU-bound vs I/O-bound scale differently); extracted links are normalized (lowercase host, strip fragments/session params) before dedup.
- **Everything durable** (frontier state checkpointed, seen-set persistent) so a crash resumes instead of restarting the internet.

### Deep Dives
- **Politeness under scale.** One misconfigured crawler = one accidental DDoS + your IP range blacklisted. Per-host back queue + timer guarantees ≥ δ between requests to the same host regardless of fetcher count. Respect robots.txt (cache it ~24 h, honor crawl-delay). Also: per-host adaptive backoff on 429/503s.
- **Dedup two ways.** *URL-seen*: check before enqueueing — a sharded hash set, or a Bloom filter (accepting rare false positives = pages skipped, usually fine at this scale) backed by an exact store for the frontier's integrity. *Content-seen*: mirrors and www/non-www serve identical bytes — hash the content (or SimHash for *near*-duplicates, which are ~30% of the web) and skip re-processing.
- **Traps and the infinite web.** Calendars that paginate forever, faceted search with 10¹² URL combos, session IDs generating unique URLs per visit. Defenses: max depth per site, max URLs per domain budget, URL pattern heuristics (repeating path segments), and per-domain crawl budgets that force breadth over depth. You cannot enumerate the web; you can only spend a budget wisely.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Frontier | Mercator front/back queues | Single priority queue | One structure can't do priority AND per-host politeness |
| URL-seen store | Bloom filter + exact backing | Exact hash set only | 10B URLs in RAM cheaply; FP = harmless skip |
| Fetch model | Async I/O, few big nodes | Thread-per-URL | 400+ concurrent sockets/node; threads waste memory |
| Near-dup detection | SimHash | Exact hash only | ~30% of web is near-duplicate; exact hash misses it |

### Checkpoint
1. How do you crawl JavaScript-rendered pages, and what does headless rendering do to your throughput math (recompute it)?
2. Freshness: nytimes.com/home changes hourly; a 2009 blog post never does. Design the re-crawl scheduler.
3. A site returns 200 OK with an error page for every URL (soft 404s). How does this poison your crawl, and how do you detect it?

## 15. Design Google Docs (Collaborative Editing — OT vs CRDTs)

**MOTTO:** Collaborative editing is a concurrency-control problem where the "database" is a human's sentence — convergence is mandatory, intention-preservation is the art.

### Requirements
- **Functional:** multiple users edit one document simultaneously; everyone converges to the same text; live cursors/presence; offline edits merge on reconnect; version history; comments.
- **Non-functional:** local edits apply instantly (zero perceived latency — never block a keystroke on the network); remote edits visible < ~500 ms; convergence guaranteed (all replicas reach identical state); documents to ~1M characters; sessions of ~100 concurrent editors.

### Napkin Math
- 100M DAU, ~5M concurrently active editors, ~2 ops/sec while typing → **~10M ops/sec globally**, but per-document only ~2–50 ops/sec — each doc is small; the fleet is big. Shard by document; a single doc session fits on one server.
- Op size ~50 B (type, position, char(s), version vector) → a busy 20-editor doc ≈ 40 ops/s × 50 B = 2 KB/s. Bandwidth is nothing; *correctness* is everything.
- History: 10K ops/day on an active doc × 50 B = 500 KB/day of oplog — snapshot every ~1K ops so loading = latest snapshot + tail, not a replay of 3 years of keystrokes.
- Presence: cursors at ~5 updates/sec × 100 editors = 500 msg/s per hot doc — ephemeral, never stored, coalesced.

### High-Level Design
```
editor A ──ws──┐
editor B ──ws──┼──> doc session server (ONE per active doc: sequences ops, transforms, broadcasts)
editor C ──ws──┘         │
                         ├──> oplog (append-only, versioned) ──> snapshot service (periodic materialize)
                         ├──> presence channel (cursors, ephemeral pub/sub)
                         └──> doc registry (doc_id → session server; spins sessions up/down)
```
- **One session server per active doc** (the crucial choice): it's the single sequencer — every op gets a canonical order there. This makes OT tractable; distributed sequencing is where OT implementations go to die.
- **Client**: applies its own ops instantly (optimistic), sends to server, transforms incoming remote ops against its unacknowledged local ops.
- **Oplog + snapshots** give history, undo, and fast loads.
- **Presence** is a separate ephemeral channel — cursor spam must never sit in the oplog.

### Deep Dives
- **OT (what Google Docs uses).** Two concurrent ops: A inserts "x" at position 5, B deletes position 2. Applied naively in different orders → divergence. OT *transforms* ops against concurrent ones: after B's delete, A's insert shifts to position 4. Correctness requires the transformation function to satisfy convergence properties (TP1, and TP2 if you lack a central sequencer) — hence the central server: with one canonical order, clients only transform against the server stream, and the problem stays solvable-by-mortals.
- **CRDTs (what Figma-era systems and Yjs use).** Give every character a unique, totally-orderable ID (e.g., fractional/tree positions + replica ID); inserts reference neighbor IDs; deletes tombstone. Concurrent ops commute — *any* delivery order converges, no transformation, no central sequencer required. Costs: per-character metadata + tombstones (a 100 KB doc can carry MBs of structure — modern encodings like Yjs compress this brutally well), and interleaving anomalies in naive designs. Rule of thumb: OT = smaller payloads + simpler data model but demands a central server and fiendish transform code; CRDT = decentralized, offline-native, at a metadata cost. With a central server anyway, OT is fine; for offline-first or P2P, CRDT wins.
- **Offline reconciliation.** A user returns after 2 h offline with 500 local ops; the doc moved 3,000 ops. OT: replay-transform 500 × against 3,000 — fine but centralized, and the server must retain (or re-derive) that history window. CRDT: just exchange states/deltas — merge is the data structure's native operation. This scenario is precisely why offline-first products pick CRDTs.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Concurrency control | OT + central sequencer | CRDT | Central server exists anyway; smaller ops, lean doc model |
| Session topology | One server per doc | Any-server + shared state | Single sequencer makes ordering trivial; docs are small |
| Local edits | Optimistic immediate apply | Wait for server ack | A laggy keystroke is a broken product |
| History | Oplog + periodic snapshots | Store full versions | Ops are tiny; snapshots bound replay time |

### Checkpoint
1. The session server for a 40-editor doc crashes. What state is lost, and reconstruct the recovery sequence from oplog + client buffers.
2. Two users, offline, both delete the same paragraph and retype it differently. What does OT do? What does a CRDT do? What *should* the user see?
3. How does undo work when the op you're undoing has been transformed against 200 later ops? (Hint: undo is an *inverse op*, itself transformed.)

## 16. Design an Ad-Click Aggregator

**MOTTO:** An ad-click aggregator is a streaming ledger — approximate fast numbers for dashboards, exact slow numbers for invoices, and never confuse the two.

### Requirements
- **Functional:** ingest click events from ad servers; aggregate clicks per ad per time window (minute/hour/day); serve queries ("clicks for ad X, last 5 min") for dashboards and billing; support late events and fraud filtering.
- **Non-functional:** peak 100K+ clicks/sec without loss; dashboard freshness ≤ ~1 min; billing numbers *exact* (money) even where dashboards are approximate; results reproducible from raw events (replayable); handle out-of-order arrival (minutes late).

### Napkin Math
- 1B clicks/day ≈ **11,600/sec average**, peak ~10× = **~120K/sec** (impressions, 100× larger, mercifully out of scope).
- Event ~100 B (ad_id, user fingerprint, ts, ip, metadata) → 1B × 100 B = **100 GB/day raw**; keep 90 days replayable ≈ 9 TB compressed-ish. Cheap. Keep raw events *always* — they are the ground truth.
- Aggregates: 2M active ads × 1,440 min-buckets/day × ~50 B = **~144 GB/day** of minute-level rollups — comparable to raw! Hence: minute-level kept days, hour-level months, day-level forever.
- Kafka: 120K/s × 100 B = 12 MB/s peak — a modest topic; partition by ad_id (see hot-key deep dive).

### High-Level Design
```
ad servers ──> collector fleet ──> Kafka (raw clicks, partitioned by ad_id, retained N days)
                                     ├──> stream job (Flink): dedupe → fraud filter → window agg (1-min, watermark)
                                     │        └──> aggregate store (OLAP: minute/hour/day rollups) ──> query API ──> dashboards
                                     ├──> raw archive (object store, replay source)
                                     └──> (reconciliation) nightly batch over raw ──> corrects/blesses billing aggregates
```
- **Collectors** are dumb, fast, and lossless: validate minimally, stamp arrival time, append to Kafka. All intelligence lives downstream where it can be replayed.
- **Stream job** does event-time windowing with watermarks: a 1-minute window closes when the watermark passes, late events (within allowed lateness) update the window; beyond that, they land in a corrections path.
- **Aggregate store**: an OLAP-ish store (columnar, or pre-aggregated rows keyed ad_id × window) for fast range queries.
- **Nightly batch over raw events recomputes billing-grade aggregates** — the lambda-architecture move, kept because money demands a second, reproducible opinion.

### Deep Dives
- **Exactly-once aggregation.** At-least-once delivery + a counter = overcounting = overbilling. Layers: client/collector attaches a unique click ID; the stream job dedupes within a keyed state window; Flink-style checkpointing gives exactly-once *state* updates; end-to-end, sinks are idempotent (upsert window results by ad_id + window, not increment). Then the batch layer re-derives from raw and wins any argument. Billing reads blessed aggregates only.
- **Late and out-of-order events.** Mobile clients batch and retry; a click can arrive 10 minutes late with an event-time from the past. Watermarks (e.g., "assume ≤ 2 min disorder") balance freshness vs. completeness; allowed-lateness updates already-emitted windows (sinks must upsert); beyond that, corrections flow into the batch recompute. Say the sentence: *event time ≠ processing time*, and every number is "complete as of watermark W."
- **Hot keys.** A Super Bowl ad takes 30% of all clicks; its ad_id partition melts one Kafka partition + one aggregator task. Fix: two-stage aggregation — partition by (ad_id, random salt 0–15), pre-aggregate 16 partial sums, then a second stage merges partials per window. Standard, beautiful, worth drawing.

### Tradeoffs
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Architecture | Stream + batch reconciliation (lambda) | Pure streaming (kappa) | Billing wants a reproducible second opinion from raw |
| Windowing | Event-time + watermarks | Processing-time | Mobile latency would smear clicks into wrong buckets |
| Sink semantics | Idempotent upsert per window | Increments | Upserts make replays and late updates safe |
| Hot ads | Salted two-stage aggregation | Bigger partitions | Skew doesn't shrink by scaling; it must be split |

### Checkpoint
1. An advertiser disputes yesterday's bill. Walk the exact path from their invoice number back to raw events. What makes it reproducible?
2. Fraud rules change retroactively (a botnet identified today clicked all week). How do corrected aggregates propagate, and what happens to already-shown dashboards?
3. Product wants unique-users-per-ad, not just clicks. Exact or HyperLogLog? Defend the choice with memory math at 2M ads.
