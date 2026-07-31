# Phase 05 — 🗄️ Databases II — Distributed Data

> One database is a pet. A hundred shards is a farm.

Phase 4 taught you how one database node works. Now we break it — or rather, we outgrow it: more data than one disk, more reads than one CPU, more nines than one machine can promise. The moment your data lives on two machines, physics files a complaint, and you inherit replication lag, split brains, and rebalancing migrations that make grown engineers weep. This phase is your field guide to keeping a herd of databases pointed in roughly the same direction.

## 01. Replication: leader-follower

**MOTTO:** One node decides, everyone else copies — democracy is for later phases.

### The Problem

A single database node is a single point of failure and a single point of throughput. When the disk dies, you're down; when the read traffic triples, you're slow. You need copies of your data on multiple machines — but copies that receive independent writes will diverge into chaos. The simplest fix: only one node accepts writes.

### The Concept

Leader-follower replication is a newsroom: one editor-in-chief (leader) approves every story, and syndicated papers (followers) reprint them in order. Readers can read any paper; corrections flow one way. The wire feed carrying stories is literally the WAL from Phase 4 — replication is "recovery, but on another machine, forever."

```
            writes
   client ─────────> [ LEADER ]
                       │  replication log (WAL / binlog)
              ┌────────┼────────┐
              v        v        v
        [follower] [follower] [follower]
   client ──reads──────^ (any follower, or the leader)
```

### Build It

1. Leader appends every write to its replication log; followers stream the log and apply records in order — identical inputs, identical state.
2. **Sync vs async:** synchronous = leader waits for follower ack before confirming commit (no data loss, higher latency, a dead sync follower blocks writes); asynchronous = confirm immediately (fast, but an un-replicated tail can be lost on leader death). Semi-sync (wait for *one of N*) is the popular compromise.
3. **New follower:** snapshot the leader, restore it, then replay the log from the snapshot's position until caught up. No downtime needed.
4. **Failover:** detect leader death (timeouts — perilous), promote the most-caught-up follower, repoint clients, ensure the old leader — if it returns — demotes itself. Every step hides a razor blade.
5. Deadly failover bug: async replication + promotion = the new leader may lack the old leader's last writes. If the old leader comes back believing it still leads, you have **split brain**: two leaders accepting conflicting writes.

### Use It

| System | Mechanism |
|---|---|
| PostgreSQL | streaming WAL replication + hot standby |
| MySQL | binlog replication (async/semi-sync) |
| MongoDB | replica sets with automated elections |
| Kafka | leader per partition, ISR followers |

Managed offerings (RDS Multi-AZ, Cloud SQL HA) are this exact pattern with the failover runbook automated.

### War Story

On October 21, 2018, a 43-second network partition between GitHub's data centers triggered an automated MySQL leader failover to the West coast — while the East coast leader had writes the new leader never received. The split brain forced GitHub into over 24 hours of degraded service while they carefully reconciled both histories, and their public postmortem became required reading on why automated failover is not a solved problem.

### Checkpoint

- What can be lost in async replication failover that can't be lost in sync — and what do you pay for that safety?
- Why must a recovered old leader be fenced or demoted before rejoining?
- Why do followers apply the log in strict order rather than in parallel willy-nilly?

## 02. Multi-leader and leaderless replication

**MOTTO:** When everyone can write, everyone can disagree.

### The Problem

One leader means every write crosses the planet to reach it — brutal for multi-region apps — and leader failover is a scary, stateful dance. What if multiple nodes accepted writes? You gain locality and availability, but two datacenters can now accept *conflicting* writes for the same key at the same moment. Someone must decide what "the value" even is.

### The Concept

Multi-leader is a document shared by two editors working offline on a plane — both edit paragraph 3, and someone must merge on landing. Leaderless (Dynamo-style) abolishes the editor entirely: you mail your edit to several archivists, and readers poll several archivists and trust the freshest-looking copy.

```
Leaderless write/read with N=3, W=2, R=2:

  write ──> [node A ✓] [node B ✓] [node C ✗ down]   ack after W=2
  read  ──> [node A: v2] [node C: v1(stale!)]        take newest of R=2

  W + R > N  →  read set ∩ write set ≠ ∅  →  you'll see the new value
```

### Build It

1. **Multi-leader:** each region has a leader; leaders asynchronously exchange changes. Conflict resolution options: last-writer-wins (LWW — silently drops data, beware), per-field merge, CRDTs, or "record the conflict and ask the app/human."
2. **Leaderless quorums:** choose N (replicas), W (write acks), R (read fan-out). W+R > N gives overlap; W=R=2, N=3 is the classic.
3. **Read repair:** a read that sees stale replicas writes the newer value back to them.
4. **Anti-entropy:** background process compares replicas (Merkle trees) and syncs differences — catches keys that are never read.
5. **Hinted handoff:** if a home replica is down, another node holds the write with a "hint," delivering it when the node returns. Availability preserved; sloppy quorums weaken guarantees.
6. Even with quorums, concurrent writes conflict — you need **versioning** (vector clocks / dotted versions) to distinguish "newer" from "concurrent." Concurrent siblings must be merged.

### Use It

| Style | Systems | Cost |
|---|---|---|
| Multi-leader | Postgres BDR, MySQL Group Replication (multi-primary), CouchDB | conflict resolution burden |
| Leaderless | Cassandra, Riak, Dynamo, Voldemort | tunable but never "simply consistent" |

Rule of thumb: multi-leader across regions only if you can define merges for your data; leaderless when availability trumps freshness.

### War Story

Amazon's 2007 Dynamo paper (Lesson 10 does the full tour) canonized leaderless quorums, hinted handoff, and vector clocks — motivated by shopping carts, where the merge rule is delightfully simple: union the carts, because accidentally re-adding a deleted item beats losing an added one. The paper is admirably honest that this pushed conflict resolution onto application programmers, and a decade of Cassandra LWW data-loss surprises proved how sharp that edge is.

### Checkpoint

- Why does W + R > N guarantee a read overlaps the latest successful write — and name one way that guarantee still leaks (hint: sloppy quorums, or failed partial writes).
- What's wrong with last-writer-wins when clocks are involved?
- Why is a shopping cart an unusually forgiving use case for leaderless replication?

## 03. Replication lag and read-your-writes

**MOTTO:** You posted the comment; the replica hasn't heard the news yet.

### The Problem

Async followers run milliseconds — or, during a spike, minutes — behind the leader. A user updates their profile photo (write hits leader), refreshes the page (read hits a lagging follower), and their change has vanished. They didn't witness "eventual consistency"; they witnessed a bug, and they will file it as one.

### The Concept

Replication lag is watching a "live" broadcast on a 30-second delay: the game has moved on, your feed hasn't. The fix isn't eliminating the delay (physics disagrees) — it's making sure each viewer never sees the *feed jump backward*. That yields a family of session guarantees:

```
Read-your-writes:  after MY write, MY reads include it
Monotonic reads:   MY successive reads never go back in time
Consistent prefix: I never see effect-before-cause
                   ("answer" visible before its "question")
```

### Build It

1. **Read-your-writes, option A:** route a user's reads to the leader for T seconds after their own write (track "last wrote at" per session).
2. **Option B (better):** on write, capture the leader's log position (e.g., Postgres LSN, MySQL GTID). On read, pick any follower but *wait until it has replayed past that position* — or bounce to the leader.
3. **Monotonic reads:** pin each session to one follower (hash user → replica), so time never rewinds between requests.
4. Watch multi-device: read-your-writes per *session* won't cover "posted on phone, refreshed on laptop" unless the token travels (server-side session store).
5. Operationally: expose lag as a metric (`pg_stat_replication`, `Seconds_Behind_Source`), and make the read router lag-aware — evict followers that fall too far behind.

### Use It

| Mechanism | Where |
|---|---|
| GTID/LSN wait | MySQL `WAIT_FOR_EXECUTED_GTID_SET`, Postgres LSN checks |
| Lag-aware routing | ProxySQL, pgpool, app-level read routers |
| Session pinning | sticky routing by user ID |
| Causal tokens | MongoDB causal consistency sessions |

Cheapest correct answer for small apps: send reads-after-writes to the leader and don't be clever until you must be.

### War Story

Doug Terry and colleagues at Xerox PARC defined these session guarantees — read-your-writes, monotonic reads, writes-follow-reads — in a 1994 paper on the Bayou system, decades before "eventual consistency" became a cloud-era buzzword. Nearly every "my update disappeared on refresh" bug ever filed against a read-replica architecture is a rediscovery of exactly the anomalies Bayou catalogued.

### Checkpoint

- A user writes, then reads from a follower 200ms behind. Describe two distinct fixes and their costs.
- How can a user see comments appear and then *disappear* on refresh, and which guarantee prevents it?
- Why does per-session read-your-writes break down across devices?

## 04. Partitioning (sharding) strategies

**MOTTO:** When the data won't fit in one box, the hard part is choosing the knife.

### The Problem

Replication copies *all* data to every node — it scales reads, not data size or write throughput. At some point the dataset or write load exceeds any single machine. You must split (**partition/shard**) the data across nodes. Split badly and one shard gets all the traffic while nine idle: the dreaded **hot spot**.

### The Concept

Sharding is assigning students to exam halls. By surname range (A–F → Hall 1) keeps friends-with-similar-names together — great if you need to visit "all the Singhs" (range scans!) — but Hall S–Z overflows in some countries. By hash of student ID spreads everyone evenly, but now "all the Singhs" are scattered across every hall.

```
Range:  [A──F] [G──M] [N──S] [T──Z]   scans easy, skew likely
Hash:   hash(key) % nodes             even spread, ranges scattered

Hot-spot horror: keys = timestamps, range-partitioned
    → ALL of today's writes land on the last shard. 🔥
```

### Build It

1. **Range partitioning:** keep a sorted key→shard map. Pros: efficient range queries, easy splits at observed boundaries. Cons: sequential keys (timestamps, auto-increment) hammer one shard.
2. **Hash partitioning:** shard = f(hash(key)). Pros: uniform. Cons: range queries become scatter-gather; naive `mod N` reshuffles nearly everything when N changes (Lesson 05 fixes this).
3. **Compound keys:** hash a prefix, range the suffix — Cassandra's `(partition key, clustering key)`: spread users across shards, keep each user's events sorted together.
4. **Celebrity problem:** even perfect hashing can't save you when *one key* is hot (a viral post). Mitigations: split the key (append random suffix, aggregate on read), or cache in front.
5. Choose the shard key by your dominant query: the goal is most queries touching **one** shard. Cross-shard queries and transactions are where sharding stops being fun.

### Use It

| System | Strategy |
|---|---|
| Cassandra/DynamoDB | hash partition key (+ sorted clustering) |
| HBase/Bigtable | range on row key |
| Vitess (MySQL) | configurable vindexes |
| Citus (Postgres) | hash or range distribution column |
| MongoDB | ranged or hashed shard key |

### War Story

Instagram's early engineering posts describe sharding Postgres by embedding a shard identifier into their snowflake-style photo IDs — ID design *was* shard routing. Meanwhile "we chose a timestamp-leading row key" is such a notorious Bigtable/HBase hot-spot trap that Google's own Bigtable schema documentation warns against it explicitly; generations of monitoring pipelines have relearned it the hard way.

### Checkpoint

- Why do range-partitioned timestamp keys create a hot spot, and what compound-key trick fixes it while preserving in-shard ordering?
- What breaks with `shard = hash(key) % N` the day you add a node?
- Your app's top query is "all orders for customer X, newest first." Design the shard key.

## 05. Consistent hashing

**MOTTO:** Add a server, move a sliver — not the whole warehouse.

### The Problem

With `hash(key) % N`, changing N from 10 to 11 remaps roughly 10/11ths of all keys — nearly every key migrates, every cache entry misses at once, and the origin gets trampled. Nodes join and leave constantly at scale. We need a scheme where adding a node moves only ~1/N of the data, touching nothing else.

### The Concept

Picture a circular clock face of hash values. Each server sits at (several) positions on the circle; each key hashes to a point and walks clockwise to the first server it meets. Add a server, and it only claims the arc between itself and its counter-clockwise neighbor — every other arc is untouched.

```
        0/2^32
     ┌────●────┐        ● = node position
   key K ↘     │        K walks clockwise → owned by B
     A ●       ● B
     │           │      add node D between A and B:
     └───● C ────┘      D steals only part of B's arc.
                        A and C never notice.
```

One node per position makes arcs lumpy and failure unfair (the next neighbor inherits *everything*). Fix: **virtual nodes** — each physical server appears at 100–200 points, smoothing load and spreading a dead node's arc across everyone.

### Build It

1. Hash each node ID (with vnode suffixes: `"nodeA#0"`, `"nodeA#1"`, ...) onto a ring of size 2^32 (or 2^64).
2. Keep node positions in a **sorted array**; lookup = hash the key, binary-search for the first position ≥ hash (wrap to index 0 past the end). O(log V).
3. Add node: insert its vnode positions; only keys in the claimed arcs migrate (~K/N of them).
4. Remove node: delete its positions; its arcs fall to clockwise successors — with vnodes, spread across many machines.
5. Replication on the ring: store each key on its owner *plus the next R−1 distinct physical successors* — the "preference list."
6. Alternative for fixed-ish clusters: **jump consistent hash** (Google, 2014) — no ring storage at all, just arithmetic.

### Use It

| System | Use of consistent hashing |
|---|---|
| Cassandra / Dynamo / Riak | data placement via token ring + vnodes |
| Memcached (client libs like ketama) | cache server selection |
| Envoy / load balancers | ring-hash session affinity |
| Discord, Twemproxy | shard routing |

Lesson 14 builds this in real Python — hold that thought.

### War Story

Consistent hashing comes from Karger et al.'s 1997 STOC paper, born from the web-caching problem at MIT that also spawned Akamai — the founding technology of an entire CDN industry. A decade later the Dynamo paper made the ring the load-bearing icon of NoSQL architecture diagrams, vnodes and all.

### Checkpoint

- Exactly which keys move when a node joins the ring, and roughly how many?
- What two distinct problems do virtual nodes solve?
- Why is `% N` fine inside a fixed-size hash table but catastrophic across a fleet of cache servers?

## 06. Rebalancing without downtime

**MOTTO:** Rearrange the furniture while the party is still going.

### The Problem

Shard 7 is at 90% disk. You bought three new machines. Now you must move terabytes between live nodes while reads and writes continue, without dropping a write, serving stale data, or saturating the network so badly that production notices. Rebalancing is where sharding designs go to be judged.

### The Concept

Rebalancing is moving a library to a new building without ever closing: you photocopy a shelf (bulk copy), forward every new borrowing slip for that shelf to both buildings (dual-write/catch-up), verify the copies match, then update the card catalog (routing) and finally clear the old shelf. At no point may a reader be told "we don't know where that book is."

```
Phase 1: bulk copy shelf S  (old node → new node, throttled)
Phase 2: stream changes since copy began (catch-up via log)
Phase 3: brief sync point → flip routing for S
Phase 4: old node forwards stragglers, then drops S
```

### Build It

1. **Pre-split into many partitions:** create far more partitions than nodes up front (e.g., 1024 partitions on 8 nodes). Rebalancing = reassigning *whole partitions*, never re-splitting keys. This is the single best trick in this lesson.
2. **Copy + catch-up:** snapshot the partition, then replay its change log from the snapshot point — identical to bootstrapping a replica (Lesson 01). Cutover happens when lag ≈ 0.
3. **Routing update:** somebody authoritative (coordination service, config epoch) flips ownership atomically; in-flight requests to the old owner get "moved, ask node X" redirects (Redis Cluster's `MOVED`/`ASK` do exactly this).
4. **Throttle:** cap migration bandwidth and concurrent moves; a rebalance that causes an outage has negative value.
5. **Never fully automate carelessly:** auto-rebalancers reacting to a slow node can start mass data movement during an incident — exactly when you can least afford it. Human-approved rebalancing is a respectable choice (and Kafka's cruise-control-style tools expose knobs for this reason).

### Use It

| System | Approach |
|---|---|
| Cassandra | vnode token reassignment, streaming |
| Vitess | resharding workflows with VReplication |
| Redis Cluster | 16384 hash slots, slot-by-slot migration |
| Kafka | partition reassignment + throttles |
| CockroachDB/TiKV | automatic range splits + rebalancing |

Fixed hash-slot schemes (Redis's 16384) are pre-splitting taken to its logical, pleasant conclusion.

### War Story

Foursquare's famous 2010 outage — roughly 11 hours down — happened when one MongoDB shard outgrew RAM and the emergency fix (adding a shard) couldn't rebalance fast enough while the overloaded shard thrashed; the postmortem, published openly, became the canonical cautionary tale that you must reshard *before* you're at capacity, because rebalancing consumes the very headroom you've run out of.

### Checkpoint

- Why does pre-splitting into many small partitions make rebalancing dramatically simpler?
- During copy + catch-up, what guarantees no write to the moving partition is lost at cutover?
- Why can fully automatic rebalancing amplify an outage instead of fixing one?

## 07. Secondary indexes in a sharded world

**MOTTO:** Sharded by user, searched by email — pick which query gets to be cheap.

### The Problem

Your users table is sharded by `user_id`. Now someone queries `WHERE email = 'x@y.com'`. The email could live on any shard. Your options: ask every shard (slow, fan-out), or maintain a separate email→shard mapping (a distributed index — with its own consistency problems). There is no free lunch here, only two well-understood lunches with different prices.

### The Concept

**Local indexes**: every branch library keeps a card catalog of *its own* books — finding a title means phoning every branch. **Global indexes**: one central catalog covers all branches — one phone call to find any book, but every new book requires updating a catalog that lives somewhere else (a remote, possibly-failing write).

```
LOCAL (document-partitioned):        GLOBAL (term-partitioned):
shard1: idx{email→row} its rows      email a–m index on shard1
shard2: idx{email→row} its rows      email n–z index on shard2
query email → ASK ALL SHARDS         query email → ask ONE shard
write row  → one shard, done         write row → data shard + index
                                       shard (2 writes, 2 places)
```

### Build It

1. **Local (document-partitioned) index:** each shard indexes only its own rows. Writes stay single-shard (fast, atomic). Reads on the secondary key = **scatter-gather** across all shards; latency is the *slowest* shard's, and tail latency degrades as shard count grows.
2. **Global (term-partitioned) index:** the index itself is sharded by the indexed value. Reads touch one index shard. Writes now span the data shard *and* the index shard — either you pay distributed-transaction costs, or the index is updated async and is briefly stale.
3. Middle path used everywhere: async global index + treating it as a *routing hint* — read the hinted shard, verify against the source of truth.
4. Or step outside: ship changes to a search system (Elasticsearch) via CDC and accept indexing lag explicitly.

### Use It

| System | Model |
|---|---|
| MongoDB | local per-shard indexes (scatter-gather off shard key) |
| Cassandra native 2i | local — infamous for fan-out pain |
| DynamoDB GSI | global, asynchronously maintained (eventually consistent reads) |
| CockroachDB/Spanner | global, transactionally maintained (pay at write time) |

DynamoDB makes the tradeoff beautifully explicit: a GSI is literally a second table with its own provisioned write capacity — and a throttled GSI backpressures writes to the base table.

### War Story

Cassandra's built-in secondary indexes earned a durable community reputation as a "use sparingly" feature precisely because they're node-local: any query not scoped to a partition fans out cluster-wide, and performance degrades as the cluster grows — the opposite of why you adopted Cassandra. The ecosystem's answer (materialized views, SASI, and ultimately storage-attached indexes) is a decade-long tour of every point in this lesson's design space.

### Checkpoint

- Why do local secondary indexes get *worse* for reads as you add shards?
- What atomicity problem do global indexes introduce on the write path, and name two ways real systems handle it?
- A DynamoDB GSI is "eventually consistent." Trace a read-after-write that exposes this.

## 08. Document stores: MongoDB and friends

**MOTTO:** Store the whole aggregate where you'll read the whole aggregate.

### The Problem

Your `order` is one thing to your application — items, addresses, payment status — but a relational schema shatters it across six tables, reassembled by joins on every read. For aggregate-shaped data with evolving fields, the constant shredding and rejoining (and the migration ceremony for every new field) is friction you can feel. What if the database stored the aggregate as the app sees it?

### The Concept

A relational database is a warehouse of standardized parts bins — maximum flexibility to build any report from parts. A document store is a shelf of packed boxes: everything for one order in one box, grab-and-go. Fast when you want whole boxes; awkward when you ask "find every box containing a size-9 shoe" — and risky if the same fact is copied into many boxes (denormalization means *you* own the update fan-out).

```
{ "_id": "order_9127",
  "customer": { "id": 42, "name": "Priya" },
  "items": [ {"sku": "A1", "qty": 2, "price": 499} ],
  "status": "shipped",
  "events": [ {"t": "...", "type": "packed"} ] }
   ← one read, no joins, atomic to update
```

### Build It

1. **Model by access pattern:** embed what you read together (order + items); reference what's shared, unbounded, or independently queried (customer profile). The classic sins: unbounded embedded arrays, and embedding data that many documents duplicate.
2. **Atomicity:** single-document updates are atomic — schema design *is* transaction design. Multi-document ACID exists in MongoDB (4.0+, 2018) but costs more; leaning on it everywhere means you probably wanted Postgres.
3. **Under the hood:** MongoDB's WiredTiger engine is B-trees + WAL + MVCC-style snapshots — Phase 4 all over again; "schemaless" is a storage-format claim, not a data-modeling exemption.
4. **Distribution:** replica sets (Lesson 01 with elections) + sharding by shard key (Lesson 04's rules apply verbatim — bad shard keys are the top MongoDB scaling incident).
5. "Schemaless" really means **schema-on-read**: the reader must tolerate every historical shape of the document. Use validators; your future self is the reader.

### Use It

| Store | Notes |
|---|---|
| MongoDB | richest queries/indexes in class, aggregation pipeline |
| Amazon DocumentDB / Azure Cosmos DB | managed, API-compatible-ish |
| CouchDB | multi-master sync, offline-first replication |
| Postgres JSONB | "document store inside a relational DB" — often the right call |

Honest heuristic: aggregate-shaped reads and evolving schemas → documents shine; many-to-many relationships and ad-hoc cross-entity queries → relations shine. Postgres JSONB covers a shocking amount of the middle.

### War Story

MongoDB's early defaults became a legend of their own: for a period, drivers defaulted to unacknowledged writes (fire-and-forget), producing spectacular benchmark numbers and a genre of "MongoDB lost my data" blog posts, until acknowledged writes became the default in 2012. Jepsen testing over the following decade repeatedly sharpened its consistency claims — a public case study in a database maturing under adversarial scrutiny.

### Checkpoint

- Give one signal that data should be embedded and one that it should be referenced.
- Why is "schemaless" better described as schema-on-read, and who pays the cost?
- Why does single-document atomicity make document design a transactional decision?

## 09. Wide-column stores: Cassandra internals

**MOTTO:** Design the table for the query, because the query won't bend for the table.

### The Problem

You need to absorb hundreds of thousands of writes per second, across regions, surviving node and even datacenter failures — and your access patterns are known upfront (time-series, feeds, device events). A leader-based relational cluster buckles or bottlenecks on the leader. You want a database where *every* node accepts writes and adding nodes adds capacity linearly.

### The Concept

Cassandra is this course's greatest-hits album: Dynamo's ring on the outside (leaderless replication, consistent hashing, gossip), Bigtable's engine on the inside (LSM: memtable, SSTables, compaction). Data modeling flips relational habits: a table is a *precomputed answer to one query*, physically laid out so that answer is a single-partition sequential read.

```
CREATE TABLE events (
  device_id  text,      -- partition key → which node (hash on ring)
  ts         timestamp, -- clustering key → sort order inside partition
  reading    double,
  PRIMARY KEY ((device_id), ts)
) WITH CLUSTERING ORDER BY (ts DESC);

Partition "device42": [ts9|r][ts8|r][ts7|r]...  ← contiguous, sorted
Query "latest N for device42" = one node, one sequential scan. Fast.
```

### Build It

1. **Placement:** partition key hashes to a ring token; the key lives on that node plus the next RF−1 (replication factor) distinct nodes. No leader — any node coordinates any request.
2. **Write path:** coordinator forwards to replicas; each replica appends to commit log (WAL) + memtable → later flushed to SSTables. Writes are blind appends — that's why Cassandra's writes are famously fast.
3. **Read path:** merge memtable + relevant SSTables (Bloom filters prune), newest timestamp wins. Reads cost more than writes — inverted from B-tree engines.
4. **Tunable consistency per query:** `ONE`, `QUORUM`, `LOCAL_QUORUM`, `ALL`. Read QUORUM + write QUORUM > RF gives Lesson-02 overlap.
5. **Deletes are writes:** tombstones mask data until compaction passes `gc_grace_seconds`. Queue-like workloads (write, read, delete, repeat) drown in tombstones — a top Cassandra anti-pattern.
6. **Model by query:** one table per access pattern; duplicate data freely at write time. Joins don't exist; "denormalize" is not a slur here, it's the manual.

### Use It

| Fit | Anti-fit |
|---|---|
| time-series, event feeds, write-heavy telemetry | ad-hoc queries, aggregations |
| multi-region active-active | strong transactions across keys |
| linear scale-out, no single leader | queue patterns (tombstone hell) |

Kin: ScyllaDB (C++ rewrite, same model), HBase (Bigtable-style but *leader-per-region*, CP-flavored — an instructive contrast), Google Bigtable itself.

### War Story

Cassandra was created at Facebook (by engineers including Avinash Lakshman, a Dynamo co-author) for inbox search, open-sourced in 2008 — literally Dynamo's distribution married to Bigtable's storage, the two papers of this phase fused into one system. Apple, Netflix, and Discord ran it at enormous scale; Discord's engineering blog later publicly chronicled migrating their trillions of messages to ScyllaDB in 2023, citing JVM GC pauses and hot-partition pain — hot partitions being, of course, Lesson 04's problem wearing a trench coat.

### Checkpoint

- What different jobs do the partition key and clustering key perform, physically?
- Why are writes cheaper than reads in Cassandra, when B-tree engines are the reverse?
- Explain why using a Cassandra table as a work queue leads to tombstone-driven slow reads.

## 10. Key-value at scale: the Dynamo paper

**MOTTO:** The cart must never say no.

### The Problem

Amazon, mid-2000s: an unavailable shopping cart is directly lost revenue, and their relational infrastructure made unavailability a real risk during failures. The requirement was inverted from classical databases: availability and latency SLAs first (99.9th percentile!), consistency negotiable. No existing system fit. So they wrote one, then told everyone how.

### The Concept

Dynamo (SOSP 2007) is less a database than a *bill of materials* for AP systems — a checklist of techniques this phase has been assembling, snapped together:

```
Problem                    → Dynamo's pick
─────────────────────────────────────────────────────
Placement                  → consistent hashing + vnodes   (L05)
Write availability         → leaderless, sloppy quorum,
                             hinted handoff                (L02)
Conflict detection         → vector clocks → app merges    (L02)
Replica divergence repair  → Merkle-tree anti-entropy      (L02)
Membership & failure       → gossip protocol, no master
Interface                  → get(key) / put(key, ctx, val)
```

The philosophical core: **always writeable**. Conflicts are resolved on *read* (by the application), never refused on write.

### Build It

1. `put()` goes to a coordinator, which writes to the key's N-node preference list, acking at W. If home nodes are down, *any* node accepts the write with a hint (sloppy quorum) — availability over strict overlap.
2. `get()` reads R replicas; the returned `context` carries vector clocks. If versions are concurrent, the client receives **siblings** and must merge (carts: union).
3. Gossip spreads membership and liveness — no central coordinator to lose.
4. Merkle trees let replicas compare key ranges with logarithmic data exchange, syncing quietly in the background.
5. Note what's *absent*: transactions, joins, secondary indexes (v1), strong consistency. Ruthless subtraction in service of one SLA.

### Use It

| Descendant | Relationship |
|---|---|
| Cassandra | Dynamo ring + Bigtable engine |
| Riak | closest open-source implementation |
| Voldemort | LinkedIn's take |
| **DynamoDB** (2012) | *shares the name, not the architecture* — a managed multi-tenant service; later papers describe leader-based replication per partition (Paxos-flavored), plus optional strong consistency and transactions |

That last row is a top-tier interview trap: Dynamo (paper) ≠ DynamoDB (product).

### War Story

The Dynamo paper won the SOSP Hall of Fame award and is arguably the most influential industry systems paper of its decade — it handed the industry a shared vocabulary (quorums, hinted handoff, vector clocks, anti-entropy) and directly seeded Cassandra, Riak, and Voldemort. Werner Vogels, Amazon's CTO, framed its publication as recruiting-and-ecosystem strategy as much as science; it worked on both counts.

### Checkpoint

- What does "always writeable" force onto the read path, and onto the application?
- How does a sloppy quorum differ from a strict one, and what guarantee does it sacrifice?
- Name three concrete mechanisms Cassandra inherited from Dynamo, and the one big thing Cassandra's storage layer took from elsewhere.

## 11. Graph databases

**MOTTO:** When the JOINs are three deep and screaming, the edges were the point all along.

### The Problem

"Friends of my friends who like hiking and live in Vancouver" — in SQL, that's self-JOINs stacked three high, each join re-scanning indexes, with cost exploding as depth grows. Relational engines *store* relationships as foreign keys but *rediscover* them on every query via index lookups. When relationships are the data — social graphs, fraud rings, dependency trees, recommendations — you want traversal to be a pointer-chase, not a join.

### The Concept

A relational join asks the phone book for each friend's address, every single hop. A graph database is walking a city where every house has direct tunnels to its neighbors: each node physically stores references to its edges — **index-free adjacency** — so hop cost is O(edges at this node), independent of total graph size.

```
(Alice) ─FRIENDS→ (Bob) ─FRIENDS→ (Carol) ─LIKES→ (Hiking)
   │
   └─LIVES_IN→ (Vancouver)

Cypher:
  MATCH (me:Person {name:'Alice'})-[:FRIENDS*2]->(fof)
  WHERE (fof)-[:LIKES]->(:Tag {name:'Hiking'})
  RETURN fof
```

Property graph model: nodes and edges both carry labels and key-value properties. The rival model, RDF/SPARQL (subject-predicate-object triples), rules the semantic-web and knowledge-graph world.

### Build It

1. Store nodes and edges as records where a node holds direct pointers (record IDs) into its adjacency list — traversal never consults a global index after the entry point.
2. Query = anchor lookup (one index hit to find Alice), then pure pointer-walking with filters; depth-3 costs ~(avg degree)^3 edge visits whether the graph has thousands or billions of nodes.
3. Contrast the SQL plan: each hop is an index-nested-loop over `friendships(user_id, friend_id)` — log-factor index costs per hop, join machinery throughout, and unbounded-depth queries need recursive CTEs.
4. Beware the supernode: a celebrity with 10M edges wrecks (degree)^k traversals — the hot key of Lesson 04, reborn with edges.
5. Distribution is genuinely hard: graphs resist clean partitioning (edges cross any cut you draw), which is why graph databases scaled up before they scaled out.

### Use It

| System | Model / niche |
|---|---|
| Neo4j | property graph, Cypher — the reference point |
| Amazon Neptune | managed; Gremlin + SPARQL + openCypher |
| ArangoDB | multi-model (docs + graphs) |
| JanusGraph | distributed, over Cassandra/HBase backends |
| Postgres + recursive CTEs | fine for shallow/small graphs — start here |

Killer domains: fraud rings (shared devices/addresses linking "unrelated" accounts), recommendations, network/dependency analysis, knowledge graphs.

### War Story

The 2016 Panama Papers investigation — 2.6TB of leaked offshore-finance documents — was famously analyzed by the ICIJ using Neo4j and its visualization tooling, letting journalists traverse officer→company→address networks to surface hidden ownership chains. Graph queries found in minutes what document review would never have connected; the ICIJ discussed the tooling publicly, and it remains graph databases' best mainstream moment.

### Checkpoint

- What is index-free adjacency, and precisely which cost does it remove compared to a SQL join per hop?
- Why does traversal cost scale with local degree rather than total graph size — and what's the supernode exception?
- Why is partitioning a graph across machines fundamentally harder than partitioning a key-value table?

## 12. NewSQL: Spanner and CockroachDB (TrueTime!)

**MOTTO:** Google bought atomic clocks so your transactions could span continents.

### The Problem

This phase kept offering a bleak menu: SQL-with-transactions on one box, or scale-out with weak consistency and no cross-shard transactions. But some workloads — payments, inventory, anything with invariants spanning shards — need *both*: serializable transactions AND horizontal scale AND survival of datacenter loss. The catch in distribution is always ordering: without a shared clock, nodes can't agree on what happened "before" what.

### The Concept

Spanner's heresy: make the clock a hardware feature. **TrueTime** equips datacenters with GPS receivers and atomic clocks, and its API refuses to lie about precision — it returns an *interval*: `TT.now() = [earliest, latest]`, guaranteed to contain true time (skew typically bounded to a few milliseconds).

```
Commit-wait — buying external consistency with patience:
  txn ready at TT.now() = [t1, t2]
  pick commit timestamp s = t2
  WAIT until TT.now().earliest > s     (~ the uncertainty, few ms)
  then commit & release locks

  ⇒ if txn B starts after txn A finishes — anywhere on Earth —
    B's timestamp > A's. Timestamp order = real-time order.
```

That's **external consistency** (strict serializability): the strongest guarantee in the book, at planet scale, priced at a few milliseconds of deliberate waiting per read-write transaction.

### Build It

1. **Layout:** data in sorted key ranges; each range is a replication group running **Paxos** (Spanner) or **Raft** (CockroachDB) — Phase 4's WAL, replicated by consensus.
2. **Transactions:** 2PL within ranges, two-phase commit *across* ranges, with the coordinator's state itself consensus-replicated — 2PC's classic "coordinator dies, everyone blocks" failure is engineered away.
3. **Reads:** snapshot reads at a timestamp need no locks at all — MVCC (Phase 4, Lesson 08) with globally meaningful timestamps.
4. **No atomic clocks?** CockroachDB uses NTP-synced clocks with a max-offset bound and hybrid logical clocks: instead of commit-wait, a read that encounters a write inside its uncertainty window *restarts at a higher timestamp*. Similar guarantee, different currency (occasional retries vs. hardware).
5. The tradeoff never disappears: cross-region writes pay consensus round-trips — geography is latency; NewSQL makes it *correct*, not free.

### Use It

| System | Clock strategy | Notes |
|---|---|---|
| Google Spanner | TrueTime (GPS + atomic) | powers Google's ad billing (F1) |
| CockroachDB | NTP + HLC, uncertainty restarts | Postgres wire compatible |
| YugabyteDB | HLC, Raft | Postgres-compatible layer |
| TiDB | centralized timestamp oracle (PD) | MySQL compatible; TSO is a design contrast worth knowing |

Reach for NewSQL when you need multi-region + real transactions; skip it when a single-region Postgres with replicas already fits — consensus tax on every write is real.

### War Story

The 2012 Spanner paper (OSDI) landed with the deadpan-audacious claim that the right fix for distributed clock uncertainty was *better clocks* — GPS antennas and atomic references in every datacenter — and that uncertainty could then simply be *waited out*. Google migrated its revenue-critical ads database (F1) onto it, upgrading the paper's claims from research to load-bearing fact, and in 2017 Spanner became a public cloud product.

### Checkpoint

- What does TrueTime return instead of a single timestamp, and why is that honesty the whole trick?
- Explain commit-wait: what is waited for, how long, and what guarantee does it purchase?
- How does CockroachDB approximate Spanner's guarantee without atomic clocks, and what does it cost instead?

## 13. Choosing a database: a decision framework

**MOTTO:** Nobody gets fired for choosing Postgres — and that's not a joke, it's a prior.

### The Problem

You've now met a zoo: B-tree monoliths, LSM rings, document shelves, graphs, Spanner-class exotica. Real projects die from choosing *interestingly* rather than *correctly* — adopting a distributed database for 40GB of data, or discovering at scale that the "webscale" store can't do the one join the business runs on. You need a repeatable interrogation, not a favorite.

### The Concept

Choosing a database is choosing a vehicle: the answer follows from the cargo, the route, and the driver — never from the brochure. The interrogation, in priority order:

```
1. SHAPE     relational? aggregate/doc? key-value? graph? time-series?
2. QUERIES   known access patterns or ad-hoc? joins? ranges? search?
3. SCALE     GB, TB, PB? writes/sec? growth curve? (be honest)
4. CONSISTENCY  invariants that must never break? or feed-like data?
5. LATENCY   p99 target? single-region or global users?
6. OPS       who's on call? managed service budget? team's scar tissue?
```

Most projects that answer honestly discover at step 3 that one well-indexed Postgres (≲ a few TB, ≲ tens of thousands of writes/sec, with read replicas) answers steps 1–6 at once.

### Build It

The decision procedure, as pseudocode:

1. **Default to Postgres.** Deviate only when a specific answer above disqualifies it — write the disqualifying sentence down; it's your design doc.
2. Relationships-as-data, deep traversals → graph DB (or recursive CTEs first).
3. Aggregate documents, evolving schema, dominant whole-object reads → document store — after trying JSONB.
4. Extreme write volume, known queries, multi-region active-active, no cross-key transactions → wide-column / Dynamo-family.
5. Global scale AND real transactions → NewSQL; accept consensus latency.
6. Caching, sessions, counters → Redis *beside*, not instead of, the source of truth. Search → Elasticsearch *beside*, fed by CDC. **Polyglot means derived copies with one system of record** — decide staleness bounds explicitly.
7. Re-run the interrogation at every 10× of load; the right answer changes, and migrations are easiest *before* they're urgent.

### Use It

| Smell | Diagnosis |
|---|---|
| "We chose Cassandra; now we need ad-hoc joins" | step 2 skipped |
| "Kafka + Mongo + Redis, unclear system of record" | step 6's rule violated |
| "Sharded at 50GB for future-proofing" | step 3 dishonesty (premature) |
| "MySQL monolith at 40TB, nightly ALTERs failing" | step 7 skipped (overdue) |

The two failure modes are symmetric: resume-driven over-engineering, and monolith denial. The framework exists to catch both.

### War Story

Both ditches are well-populated. The mid-2010s produced a genre of "we migrated off MongoDB/Cassandra back to Postgres" engineering posts whose root cause was choosing by scale they never reached, forfeiting joins and transactions they used daily. The opposite ditch is real too: teams that stayed on a single relational box past its limits and paid with multi-year emergency sharding projects — Vitess exists because YouTube lived exactly that story with MySQL.

### Checkpoint

- Why is "start with Postgres" a defensible engineering prior rather than mere conservatism?
- In a polyglot stack, what single question determines whether the design is sound?
- Name one honest trigger that should force a re-evaluation of a working database choice.

## 14. Build consistent hashing from scratch

**MOTTO:** Fifty lines of Python, one ring to route them all.

### The Problem

Lesson 05 gave you the theory; theory doesn't page you at 3 a.m. — implementations do. Time to build a hash ring with virtual nodes and *measure* the two claims we made: keys spread evenly, and adding a node moves only ~1/N of them. If the numbers don't come out, the lesson didn't stick.

### The Concept

The whole design compresses to one sentence: keep a **sorted list of (hash, node) points**; to place a key, hash it and **binary-search** for the next point clockwise. Everything else — vnodes, joins, departures — is bookkeeping on that sorted list.

```
ring (sorted hashes):  [h(A#0), h(B#0), h(A#1), h(C#0), h(B#1), ...]
lookup(key): i = bisect(ring, h(key)); wrap if past the end → owner
add(node):   insert its vnode hashes  → steals only adjacent arcs
```

### Build It

```python
import hashlib, bisect

def h(s: str) -> int:
    return int.from_bytes(hashlib.md5(s.encode()).digest()[:8], "big")

class HashRing:
    def __init__(self, vnodes: int = 150):
        self.vnodes, self._ring = vnodes, []   # sorted [(hash, node)]

    def add(self, node: str):
        for i in range(self.vnodes):
            bisect.insort(self._ring, (h(f"{node}#{i}"), node))

    def remove(self, node: str):
        self._ring = [(hv, n) for hv, n in self._ring if n != node]

    def get(self, key: str) -> str:
        i = bisect.bisect(self._ring, (h(key), ""))
        return self._ring[i % len(self._ring)][1]      # wrap = clockwise

    def get_n(self, key: str, n: int) -> list[str]:    # preference list
        i, out = bisect.bisect(self._ring, (h(key), "")), []
        while len(out) < n:
            node = self._ring[i % len(self._ring)][1]
            if node not in out: out.append(node)
            i += 1
        return out

# ---- measure the claims ----
ring = HashRing()
for node in ["A", "B", "C", "D"]: ring.add(node)
keys = [f"user:{i}" for i in range(100_000)]
before = {k: ring.get(k) for k in keys}

from collections import Counter
print(Counter(before.values()))     # claim 1: ~25k each (±few %)

ring.add("E")
moved = sum(before[k] != ring.get(k) for k in keys)
print(f"moved: {moved/len(keys):.1%}")   # claim 2: ~20% (= 1/5), not 80%
```

Experiments to run: set `vnodes=1` and watch balance crumble (rerun a few times — variance is the lesson); sweep vnodes over 1/10/100/500 and plot standard deviation of load; implement `remove("B")` and verify only B's keys moved; use `get_n(key, 3)` to simulate Dynamo-style replica placement.

### Use It

This is, at honest fidelity, the routing core of ketama-style memcached clients, Cassandra's token ring (theirs adds ownership metadata and gossip), and Envoy's ring-hash balancer. Production upgrades from here: replace md5 with a faster non-crypto hash (xxHash/murmur), make ring updates copy-on-write for lock-free concurrent readers, and gossip membership instead of calling `add()` by hand.

### War Story

The ketama library (from Last.fm, 2007) brought exactly this vnode ring to memcached clients, and its name became shorthand for consistent hashing in a dozen languages' client libraries. Amusingly, ketama-compatible quirks — like how many points per server and how they're derived — became de facto standards that later clients reproduce bug-for-bug, because changing them would remap everyone's cache.

### Checkpoint

- Why `bisect` over a linear scan — and what's the lookup complexity in vnodes?
- In the measurement harness, why ~20% moved rather than ~1/5 of *each node's* keys — what exactly does the 1/N claim promise?
- Why must `get_n` deduplicate physical nodes when walking vnode positions?
