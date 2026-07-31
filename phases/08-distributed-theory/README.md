# Phase 08 — 🎲 Distributed Systems Theory

> Where clocks lie, networks fail, and consensus is expensive.

A distributed system is what you get when your program's parts can fail independently, can't share a clock, and talk over a network that drops, delays, and duplicates whatever it feels like. Everything in this phase exists because those three facts are non-negotiable. The good news: fifty years of brilliant people have mapped this minefield, and the maps — Lamport clocks, CAP, quorums, Raft, CRDTs — are learnable in an afternoon each. The bad news: after this phase you'll never trust a timestamp again.

## 01. The Eight Fallacies of Distributed Computing

**MOTTO:** Every distributed systems outage is one of these eight assumptions collecting its debt.

### The Problem

Code that works flawlessly on localhost dies in production, because localhost quietly granted you eight miracles: instant, free, reliable, secure delivery on a network that never changes. The moment two machines are involved, all eight miracles are revoked — but your code still assumes them.

### The Concept

The fallacies, compiled at Sun Microsystems (attributed to Peter Deutsch and colleagues, with James Gosling adding to the list):

```
1. The network is reliable        5. Topology doesn't change
2. Latency is zero                6. There is one administrator
3. Bandwidth is infinite          7. Transport cost is zero
4. The network is secure          8. The network is homogeneous
```

Think of the network as postal mail, not a phone call: letters get lost, arrive late, arrive out of order, arrive twice — and you can't tell "lost" from "still in transit."

### Build It

For each fallacy, an antidote — this is your production checklist:

1. *Reliable* → timeouts on every call, retries with jitter, idempotency.
2. *Zero latency* → budget latency per hop; batch; avoid chatty N+1 call patterns.
3. *Infinite bandwidth* → paginate, compress, don't ship the whole object graph.
4. *Secure* → TLS everywhere, authenticate service-to-service (mTLS), zero trust.
5. *Static topology* → service discovery, not hardcoded IPs; handle re-resolution.
6. *One admin* → observability others can use; versioned APIs; graceful deprecation.
7. *Free transport* → measure serialization cost; egress bills are real.
8. *Homogeneous* → wire-level contracts (JSON/proto), never in-memory assumptions.

### Use It

These map directly to tooling: retries/timeouts → resilience libraries and service meshes (Envoy, Istio); discovery → DNS, Consul, Kubernetes services; contracts → protobuf/OpenAPI. Interview tip: when asked "what could go wrong here?", the eight fallacies *are* the answer key.

### War Story

The list crystallized at Sun Microsystems in the 1990s — fitting, since Sun's slogan was "The Network is the Computer." The people selling the networked future were the same ones documenting exactly how it would betray you.

### Checkpoint

- Why can't a sender distinguish a lost request from a lost reply, and which fallacy does that break?
- Which two fallacies do retries-without-idempotency violate simultaneously?
- Your service calls another service 40 times to render one page. Which fallacies is that betting on?

## 02. Time, Clocks, and the Ordering of Events

**MOTTO:** In a distributed system, "what time is it?" is an opinion, not a fact.

### The Problem

Server A logs a write at 10:00:00.100; server B logs one at 10:00:00.050. Did B's happen first? Unknowable from timestamps alone: physical clocks drift, NTP corrects them in jumps (sometimes *backwards*), and typical NTP sync leaves machines milliseconds to tens of milliseconds apart — an eternity when requests take microseconds. Last-write-wins based on wall clocks silently drops data.

### The Concept

Abandon "at the same time" and keep only what's knowable: **causality**. Event A *happened-before* B (written A → B) if: same process and A came first; or A is a send and B is the matching receive; or transitivity. Events with no path between them are **concurrent** — neither happened first, and no clock can tell you otherwise.

```
 P1: ──a──────b───────────▶      a → b (same process)
              │ msg              b → c (send → receive)
 P2: ─────────▼──c───d───▶      a → d (transitivity)
 P3: ────e───────────────▶      e ∥ everything (concurrent)
```

It's mail between pen pals: you can't know what "now" is at your friend's house, but if their letter *replies to yours*, yours definitely came first.

### Build It

1. Monotonic vs wall clocks: use `time.monotonic()` for durations (it never jumps back), wall clocks only for humans.
2. To order events, don't compare timestamps — track causality with logical clocks (next lesson).
3. If you must use physical time, bound the uncertainty: Google's Spanner uses TrueTime (GPS + atomic clocks) to get an error interval ε, and *waits out* the uncertainty before committing — buying external consistency with hardware and latency.

### Use It

| Approach | Gives you | Cost |
|---|---|---|
| Wall clock (NTP) | Human-readable, roughly ordered | Drift, jumps, false ordering |
| Monotonic clock | Correct durations locally | Meaningless across machines |
| Logical clocks | Causal order | No relation to real time |
| TrueTime/HLC | Bounded real-time order | Special hardware / hybrid schemes |

### War Story

Leslie Lamport's 1978 paper "Time, Clocks, and the Ordering of Events in a Distributed System" is arguably the founding document of the field — it defined happened-before, introduced logical clocks, and showed how to build a total order without synchronized clocks. It's one of the most cited papers in computer science, and Lamport received the 2013 Turing Award with this work front and center.

### Checkpoint

- Define happened-before using its three rules.
- Why is "concurrent" a statement about information flow rather than about wall-clock simultaneity?
- Why must durations be measured with a monotonic clock rather than a wall clock?

## 03. Lamport Clocks and Vector Clocks

**MOTTO:** Lamport clocks respect causality; vector clocks detect it.

### The Problem

You've accepted that wall clocks can't order events. You still need *some* numbering such that if A caused B, A's number is smaller — and ideally, a way to *detect* when two updates were concurrent so you can flag the conflict instead of silently losing one.

### The Concept

**Lamport clock**: every process keeps one counter. Increment on each local event; stamp messages; on receive, set `counter = max(local, received) + 1`. Guarantee: `A → B ⇒ L(A) < L(B)`. But the converse fails — smaller number does NOT imply causality. Lamport clocks can't spot concurrency.

**Vector clock**: keep a counter *per process*, as a vector. Now comparison is component-wise:

```
 P1: [1,0,0] ──▶ [2,0,0] ──send──┐
 P2: [0,1,0] ────────────receive─▶ [2,2,0]
 P3: ────────── [0,0,1]

 [2,0,0] < [2,2,0]              → causally before
 [2,2,0] vs [0,0,1]: neither ≤  → CONCURRENT (conflict!)
```

`A → B` iff `V(A) ≤ V(B)` element-wise (and not equal). Incomparable vectors = concurrent events. That's the superpower Lamport clocks lack.

### Build It

```python
class VectorClock:
    def __init__(self, node, n):
        self.node, self.v = node, [0] * n
    def tick(self):                       # local event or before send
        self.v[self.node] += 1
    def merge(self, other):               # on receive
        self.v = [max(a, b) for a, b in zip(self.v, other)]
        self.tick()

def compare(a, b):
    le, ge = all(x <= y for x, y in zip(a, b)), all(x >= y for x, y in zip(a, b))
    if le and not ge: return "a -> b"
    if ge and not le: return "b -> a"
    return "equal" if le else "concurrent"
```

Cost: O(processes) per timestamp — painful with many clients. Mitigations: dotted version vectors, pruning, or per-key server-side vectors.

### Use It

Amazon's Dynamo (2007 paper) used vector clocks to detect conflicting shopping-cart writes and hand *both* versions back to the application to merge. Riak followed. DynamoDB (the product) went simpler — last-write-wins — trading correctness for operational simplicity. Lamport timestamps live on inside consensus protocols and as tiebreakers (timestamp, node-id) for total ordering.

### War Story

The Dynamo paper (DeCandia et al., SOSP 2007) reported that in production, 99.94% of reads saw a single version — vector clocks were resolving almost everything automatically, with divergence rare but real. The famous shopping-cart merge rule ("union the items") meant the worst case was a deleted item reappearing — an annoyance deliberately chosen over losing an added item.

### Checkpoint

- Lamport: `L(A) < L(B)`. What exactly can you conclude, and what can't you?
- Show two vector clocks that are incomparable and state what that means physically.
- Why do vector clocks scale poorly with client count, and name one mitigation.

## 04. The CAP Theorem

**MOTTO:** When the network splits, you choose: refuse to answer, or risk being wrong — there is no door number three.

### The Problem

Marketing says the database is "highly available AND strongly consistent." Then a switch dies, your cluster splits into two halves that can't talk, and a client writes to one side while another reads from the other. Something has to give — and CAP says precisely what.

### The Concept

CAP (Brewer's conjecture 2000; proved by Gilbert & Lynch 2002): a distributed system cannot simultaneously provide all three of —

- **C**onsistency: every read sees the latest write (linearizability),
- **A**vailability: every request to a non-failed node gets a non-error response,
- **P**artition tolerance: the system keeps functioning when messages between nodes are lost.

```
   [N1] ──────╳────── [N2]      client → N2: read(x)
    x=5    partition    x=5     meanwhile N1 accepted write x=7
                                N2 must either:
                                  answer x=5  → gave up C  (AP)
                                  refuse/wait → gave up A  (CP)
```

Common misreadings, debunked:
1. **"Pick 2 of 3."** Wrong framing — partitions aren't optional in a distributed system. The real choice is: *when* a partition happens, C or A?
2. **"CA systems exist."** Only by not being partition-tolerant, i.e., single-node (or pretending).
3. **C ≠ ACID consistency** (that's about integrity constraints), and CAP-A ≠ "five nines" (it's a formal liveness property, not uptime math).
4. CAP says nothing about behavior when the network is healthy — that's PACELC's job (next lesson).

### Build It

1. Decide per *operation*, not per system: your product catalog read can be AP; your payment authorization is CP.
2. CP mechanics: majority quorums — the minority side of a split refuses writes (unavailable, correct).
3. AP mechanics: all sides accept writes, versions diverge, reconcile after healing (vector clocks, CRDTs, LWW).
4. Write down the reconciliation story *before* choosing AP. "We'll figure out conflicts later" is how data disappears.

### Use It

| System | During partition | Flavor |
|---|---|---|
| ZooKeeper, etcd | Minority side stops serving | CP |
| Dynamo-style (Cassandra, Riak) | Everyone keeps answering | AP (tunable) |
| Single-leader RDBMS + async replica | Failover gamble | Configurable pain |

### War Story

Eric Brewer posed the conjecture in his PODC 2000 keynote; Seth Gilbert and Nancy Lynch proved it formally in 2002. Twelve years later Brewer himself wrote "CAP Twelve Years Later: How the 'Rules' Have Changed" (IEEE Computer, 2012), pushing back on the "2 of 3" meme he'd accidentally spawned: partitions are rare, the C/A choice is per-operation, and recovery after partition is where the real engineering lives.

### Checkpoint

- Why is "choosing P" not actually a choice for a multi-node system?
- During a partition, describe exactly what a CP system and an AP system each do with a write to the minority side.
- Name two things CAP does *not* tell you about a system's behavior.

## 05. PACELC: CAP's More Useful Cousin

**MOTTO:** Partitions are rare; the latency-vs-consistency tax is charged on every single request.

### The Problem

CAP only speaks during partitions — which might be minutes per year. It says nothing about the tradeoff you pay 24/7: to make a write "consistent," replicas must coordinate *before* acknowledging, and coordination is latency. Your daily design decisions live in the case CAP ignores.

### The Concept

Abadi's PACELC (2010/2012): **if Partition, choose Availability or Consistency; Else (normal operation), choose Latency or Consistency.**

```
                 ┌── Partition? ──┐
              yes│                │no
                 ▼                ▼
            A  or  C         L  or  C
       (CAP's question)   (the everyday question:
                           wait for replicas = C
                           ack immediately   = L)
```

Analogy: a group chat decision. Wait for everyone to reply before acting (consistent, slow) or act after the first thumbs-up (fast, maybe someone objects later). You make that call on every message, not just when someone's phone dies.

### Build It

1. Classify your system: PA/EL, PA/EC, PC/EL, or PC/EC.
2. The EL/EC knob is usually literal config: Cassandra consistency level (`ONE` = EL, `QUORUM` = leaning EC), Postgres `synchronous_commit` / synchronous replicas, DynamoDB eventually-consistent vs strongly-consistent reads (the latter costs double and has higher latency).
3. Estimate the cost of EC: synchronous replication adds ≥ one round trip to your furthest required replica. Cross-region, that's 50–150ms *per write*. Decide if the read-your-writes guarantee is worth it per use case.

### Use It

| System | PACELC | Meaning |
|---|---|---|
| Dynamo/Cassandra (default) | PA/EL | Available in splits; fast normally |
| Fully replicated 2PC-style | PC/EC | Correct always, slow always |
| MongoDB (majority writes) | PC/EC-leaning | Consistency prioritized |
| Spanner | PC/EC | Pays TrueTime wait for external consistency |

### War Story

Daniel Abadi introduced PACELC in a 2010 blog post and formalized it in "Consistency Tradeoffs in Modern Distributed Database System Design" (IEEE Computer, 2012), largely out of frustration that CAP was being used to explain design decisions it logically couldn't — Dynamo's *normal-case* eventual consistency is a latency choice, not a partition choice.

### Checkpoint

- What question does PACELC answer that CAP structurally cannot?
- Classify a single-leader DB with asynchronous replicas that fails over on partition.
- Why does the EC choice get more expensive as replicas spread across regions?

## 06. Consistency Models: Linearizability to Eventual

**MOTTO:** A consistency model is a contract about which lies the system is allowed to tell you.

### The Problem

"Is it consistent?" is not a yes/no question. Between "every read worldwide sees the latest write instantly" and "reads return whatever, eventually it converges" lies a spectrum — and each step down the spectrum buys latency and availability by permitting specific, well-defined anomalies. You need to know exactly which anomalies you just signed up for.

### The Concept

The ladder, strongest to weakest:

```
 linearizable   "one copy, real-time"— once a write completes, ALL later
      │          reads (by wall clock) see it. The system behaves as if
      │          there's a single copy and ops happen atomically.
 sequential     everyone agrees on ONE order of all ops, consistent with
      │          each process's own program order — but that order may
      │          lag real time. (All spectators see the same replay.)
 causal         only causally-related ops must be seen in order;
      │          concurrent ops may appear in different orders to
      │          different observers. (Reply never appears before post.)
 eventual       stop writing, wait long enough, replicas converge.
                 No promises about the meantime.
```

Analogy: linearizable = everyone watching the match live; sequential = everyone watching the *same* replay, possibly delayed; causal = different edits of the highlights, but the goal always precedes the celebration; eventual = everyone's feed eventually shows the final score.

### Build It

1. Linearizable read of a register: route through a single leader (and confirm leadership!) or read from a quorum and repair — you pay coordination on the critical path.
2. Causal: tag operations with vector clocks / dependency sets; a replica delays applying an op until its causal dependencies are applied.
3. Eventual: apply everything on arrival; use anti-entropy (gossip, read repair, Merkle trees) to converge; resolve conflicts with LWW or CRDTs.
4. Also meet the *client-centric* session guarantees: read-your-writes, monotonic reads — often achieved by pinning a session to a replica or tracking "read at least version X" tokens.

### Use It

| Model | Anomaly you accepted | Typical home |
|---|---|---|
| Linearizable | None (pay latency) | etcd, ZooKeeper, Spanner |
| Sequential | Global lag vs real time | Some replicated state machines |
| Causal | Concurrent ops reorder | COPS-style stores, some CRDT systems |
| Eventual | Stale reads, transient disagreement | Dynamo-style, DNS, caches |

### War Story

Herlihy and Wing defined linearizability in 1990 ("Linearizability: A Correctness Condition for Concurrent Objects"); Lamport had defined sequential consistency back in 1979. In modern practice, Kyle Kingsbury's Jepsen project made the ladder famous by testing real databases against their claimed models — and repeatedly catching marketed "strong consistency" that folded under partition tests.

### Checkpoint

- What real-time guarantee separates linearizability from sequential consistency?
- Give a user-visible anomaly permitted by eventual consistency but forbidden by causal.
- Why does "read your own writes" not require linearizability, and how can a system provide it cheaply?

## 07. Quorums: Majority Rules (W + R > N)

**MOTTO:** If writers and readers must overlap, someone in the room always knows the truth.

### The Problem

You replicate data to N nodes for durability. Wait for all N to ack every write? One slow node stalls everything. Wait for just one? A read hitting a different node returns stale data. You need a middle path with a dial.

### The Concept

Pigeonhole principle as a database feature. With N replicas, require W acks per write and R responses per read. If **W + R > N**, every read set *intersects* every write set — at least one node in your read responses has the latest write. Pick the value with the highest version.

```
 N=5, W=3, R=3:
 write x=7 → {n1, n2, n3}          read → {n3, n4, n5}
                     └── n3 is in both: read sees x=7 ✓
 (any 3 + any 3 out of 5 MUST share a node: 3+3 > 5)
```

- W+R > N: read-sees-latest-write overlap (still not full linearizability without care — see caveats).
- W > N/2: two concurrent writes can't both get quorums — prevents split-brain acceptance.

### Build It

1. Version every value (timestamp or vector clock).
2. Write: send to all N, return success after W acks.
3. Read: query R (or all, take first R), return the highest-versioned value.
4. **Read repair**: push that freshest value back to the stale replicas you just heard from.
5. **Hinted handoff** (sloppy quorum): if a home replica is down, a stand-in holds the write and delivers it later — availability up, strict overlap guarantee gone.
6. Caveats that bite: a failed write that reached < W nodes still *exists* on some replicas; clock-based LWW versions can drop concurrent writes; overlap without ordering discipline isn't linearizability (Cassandra adds no read repair fix for this — lightweight transactions use Paxos instead).

### Use It

| Config (N=3) | Behavior |
|---|---|
| W=3, R=1 | Slow writes, fast reads |
| W=1, R=3 | Fast writes, slow reads |
| W=2, R=2 | Balanced, the common default |
| W=1, R=1 | Fast everything, stale reads possible (W+R ≤ N) |

Cassandra, Riak, and Dynamo-style stores expose these as per-request consistency levels. Majority quorums (W = R = ⌊N/2⌋+1) are also the beating heart of Raft and Paxos.

### War Story

The Dynamo paper (2007) popularized tunable N/W/R along with sloppy quorums and hinted handoff — explicitly trading the strict intersection guarantee for write availability during failures, because for Amazon's cart, rejecting a write was deemed worse than reconciling one later.

### Checkpoint

- Prove (one sentence) why W+R > N guarantees read/write set intersection.
- What does W > N/2 prevent that W+R > N alone doesn't?
- What guarantee do you lose with sloppy quorums + hinted handoff?

## 08. Leader Election

**MOTTO:** Any node can be the leader — as long as everyone agrees it's the same node.

### The Problem

Many tasks need exactly one node in charge: accepting writes, assigning partitions, running the cron. Hardcode it and its crash bricks the system. Let nodes self-appoint and you get two leaders — split brain — which is worse than none: both accept conflicting writes and you get to reconcile the wreckage.

### The Concept

Election with terms, like presidencies: candidates ask for votes; a **majority** wins (two disjoint majorities can't exist, so two leaders in the same term can't either); each election has a monotonically increasing **term/epoch number**, and everyone ignores messages from stale terms — that's how a deposed leader who was merely partitioned gets politely ignored on return.

```
 [n1]───heartbeat───▶[n2]      n1 dies → n2's heartbeat timer expires
   │                            n2: "vote for me, term 5"
   └──heartbeat──▶[n3]          n3: "yes" → 2/3 majority → n2 leads term 5
                                n1 revives, says "I lead term 4" → ignored (4 < 5)
```

### Build It

1. Followers expect heartbeats from the leader; a *randomized* timeout (e.g., 150–300ms) expires → become candidate. (Randomization breaks simultaneous-candidacy ties.)
2. Candidate: increment term, vote for self, request votes. Nodes grant one vote per term, first-come (Raft adds: only to candidates with a sufficiently up-to-date log).
3. Majority of votes → leader; start heartbeating. See a higher term from anyone → step down instantly.
4. **Fencing tokens**: the term number rides along on every leader action, so downstream systems (storage, locks) can reject a zombie ex-leader's writes. Election without fencing is a false sense of safety.

### Use It

| Approach | How | Notes |
|---|---|---|
| Built-in (Raft) | etcd, Consul, Kafka KRaft | Election is part of consensus |
| Lease via coordination service | ZooKeeper ephemeral nodes, etcd leases | The classic "smallest znode leads" recipe |
| DB row + lease expiry | `UPDATE leader SET holder=? WHERE expires < now()` | Fine for cron-style single-runner |

The bully algorithm (highest ID wins) is the textbook classic — simple, but assumes reliable failure detection, which real networks don't provide.

### War Story

Martin Kleppmann's 2016 analysis "How to do distributed locking" dismantled a popular Redis-based lock/leader scheme (Redlock) by showing a paused-then-resumed client (GC pause, VM migration) can act on an expired lease — and argued the fix is fencing tokens checked by the resource, not cleverer timing. The debate with Redis's author is required reading; the moral stands: leases expire, processes pause, the *resource* must enforce the term.

### Checkpoint

- Why does requiring a majority vote make two leaders in the same term impossible?
- What is a fencing token and which failure mode does it neutralize?
- Why are election timeouts randomized?

## 09. Paxos (Gently)

**MOTTO:** Paxos is just two rounds of majority politeness: ask permission, then propose — and never contradict a promise.

### The Problem

Get N unreliable nodes to agree on ONE value (say, "who is leader" or "what is log entry #7") such that once *any* node learns a decision, no different decision can ever emerge — even with crashes, message loss, and reordering. FLP (1985) proved no deterministic protocol can guarantee this *terminates* in a fully asynchronous system; Paxos guarantees safety always, and liveness whenever the network behaves for a while.

### The Concept

A committee that votes by mail. To pass a motion you first poll a majority ("will you consider proposal #n?"). Members promise not to accept anything numbered lower — and crucially, tell you if they already accepted something. If any did, **you must propose *that* value**, abandoning your own. This is Paxos's soul: proposers are forced to become couriers for possibly-decided values.

```
 Phase 1 (prepare/promise)          Phase 2 (accept/accepted)
 P ──prepare(n)──▶ acceptors        P ──accept(n, v)──▶ acceptors
 P ◀─promise(n, prior accepted?)    P ◀─accepted(n)── majority? → CHOSEN
   (majority promised)                (v = highest-numbered prior value seen,
                                       or P's own value if none)
```

Chosen = a majority accepted the same (n, v). Any later proposer's Phase 1 majority must overlap that majority, will hear about v, and is forced to re-propose v. Decisions are permanent by arithmetic, not by memory.

### Build It

1. Acceptor state (persist to disk!): highest promise `np`, highest accepted `(na, va)`.
2. On `prepare(n)`: if n > np → np = n, reply promise with `(na, va)`; else reject.
3. Proposer with majority promises: v = va of the highest na seen, else own value; send `accept(n, v)`.
4. On `accept(n, v)`: if n ≥ np → accept, persist, reply.
5. Learn: majority accepted → chosen. In practice add a distinguished proposer (leader) to avoid duel-of-proposers livelock, and run one instance per log slot = **Multi-Paxos**, where Phase 1 is amortized across many slots.

### Use It

Google Chubby (lock service) runs Paxos and underpins Bigtable/GFS coordination; Spanner uses Paxos groups per data shard; ZooKeeper's ZAB and Raft are siblings in the same family. Nobody hand-rolls Paxos for fun — you use a library or a coordination service — but reading it is how you *understand* every consensus system.

### War Story

Lamport wrote "The Part-Time Parliament" in 1990, framing consensus as archaeology of a Greek island's legislature; reviewers were so baffled it sat unpublished until 1998. He capitulated with "Paxos Made Simple" (2001), whose abstract is a single, slightly wounded sentence: "The Paxos algorithm, when presented in plain English, is very simple." Google's follow-up "Paxos Made Live" (2007) documented how brutal the remaining engineering was anyway — disk corruption, membership changes, and testing ate years.

### Checkpoint

- Why must a proposer adopt the highest-numbered previously-accepted value it hears in Phase 1?
- Which two overlapping majorities make it impossible to choose two different values?
- What does FLP impossibility say, and how does Paxos live with it?

## 10. Raft: Consensus You Can Understand

**MOTTO:** One leader, numbered terms, and a log that flows strictly downhill from leader to followers.

### The Problem

Paxos is correct but famously hard to internalize and harder to implement completely (Multi-Paxos details are folklore). Ongaro and Ousterhout designed Raft (2014) explicitly for *understandability*: same guarantees, but decomposed into three separable pieces — leader election, log replication, safety.

### The Concept

Raft is a newsroom with one editor-in-chief per **term**. All writes go through the editor, who appends to their log and replicates to followers; an entry is **committed** once a majority stores it. If the editor dies, an election picks a new one — but only a candidate whose copy of the paper is at least as up-to-date can win, so nothing committed is ever lost.

```
 term 3   leader log:  [1|a][1|b][3|c][3|d]     ← (term|entry)
                          │ AppendEntries(prevIdx, prevTerm, entries, leaderCommit)
          follower F1: [1|a][1|b][3|c][3|d]  ✓ match
          follower F2: [1|a][2|x]            ✗ conflict → leader decrements
                                               nextIndex, overwrites [2|x]
 commitIndex = 4 once a majority has index 4 → apply to state machines
```

### Build It

1. **Election**: follower's randomized timeout fires → candidate, term++, RequestVote. Voters refuse candidates whose (lastLogTerm, lastLogIndex) is behind their own — this single check is the safety keystone.
2. **Replication**: leader sends AppendEntries with `(prevLogIndex, prevLogTerm)`; follower rejects on mismatch; leader backs up `nextIndex` until logs agree, then follower truncates conflicts and appends. Result: follower logs become prefixes of the leader's.
3. **Commit**: leader advances commitIndex when a majority holds an entry *from its current term* (committing prior-term entries directly is the famous Figure 8 trap). Committed entries are applied, in order, to the state machine.
4. **Safety property**: Leader Completeness — a leader for term T holds all entries committed in terms < T. Follows from vote restriction + majority overlap.

### Use It

etcd (Kubernetes' brain), Consul, CockroachDB (Raft per range), TiKV, Kafka's KRaft mode (retiring ZooKeeper), RabbitMQ quorum queues. If you touched cloud infrastructure today, Raft was involved. Tradeoffs: all writes funnel through one leader (scale by sharding into many Raft groups); majority latency on every commit; typically 3 or 5 voters.

### War Story

The Raft paper — "In Search of an Understandable Consensus Algorithm" (Ongaro & Ousterhout, USENIX ATC 2014) — reported a user study: Stanford/Berkeley students quizzed after learning both algorithms scored significantly higher on Raft than Paxos. It won a best paper award, and within a few years Raft implementations outnumbered production Paxos implementations outside Google — understandability turned out to be a feature with compounding returns.

### Checkpoint

- What does a voter check before granting its vote, and which disaster does that check prevent?
- Walk through how AppendEntries' (prevLogIndex, prevLogTerm) consistency check repairs a divergent follower.
- Why does a Raft leader only directly commit entries from its own term?

## 11. Two-Phase and Three-Phase Commit

**MOTTO:** 2PC gets everyone to say "I do" — and if the officiant faints mid-ceremony, everybody stands frozen at the altar.

### The Problem

One logical transaction spans two databases: debit in ledger-DB, credit in wallet-DB. Commit locally in one and crash before the other, and money vanishes. You need *atomicity across systems*: both commit or neither.

### The Concept

A wedding. Phase 1 — the officiant asks each party "do you?"; saying "I do" (voting YES) is a binding promise: you *can and will* commit if told to, surviving even your own crash (you've written it to your journal). Phase 2 — if all said yes, the officiant pronounces COMMIT to everyone; any NO (or timeout) → ABORT to everyone.

```
 coordinator          participant A        participant B
     ├── PREPARE ────────▶│                    │
     ├── PREPARE ─────────┼───────────────────▶│
     │◀──── YES (locked, ─┤                    │
     │◀──── YES   logged)─┼────────────────────┤
     ├── log COMMIT (the decision point)
     ├── COMMIT ─────────▶│                    │
     └── COMMIT ──────────┼───────────────────▶│
```

The fatal flaw: between voting YES and hearing the verdict, a participant is **in doubt** — holding locks, unable to commit or abort unilaterally. If the coordinator dies there, participants *block* until it returns. 2PC is a blocking protocol.

### Build It

1. Participant on PREPARE: acquire/hold locks, write redo+undo to WAL, force to disk, vote YES. From here you've forfeited the right to unilaterally abort.
2. Coordinator: collect votes, force-write the global decision (this log record IS the commit point), then broadcast.
3. Recovery: rebooted participant finds a prepared-but-undecided transaction → must ask the coordinator (or peers) for the verdict; until answered, locks stay held.
4. **3PC** inserts a pre-commit round so participants can infer the decision without the coordinator and time out safely — non-blocking under crash failures, but *unsafe under network partitions* (two sides can decide differently), which is why essentially nobody runs it. The principled fix is replicating the decision itself with consensus (Paxos/Raft commit), which is what Spanner does.

### Use It

Alive in XA transactions, some JMS/JTA setups, and *inside* distributed SQL (Spanner: 2PC across shard groups, each group Raft/Paxos-replicated so the coordinator can't be "lost"). For cross-*service* workflows, the industry verdict is in: don't hold locks across the network — use sagas (next lesson).

### War Story

Jim Gray formalized the transaction concepts underlying 2PC in the 1970s–80s (Turing Award 1998); Gray and Lamport later co-wrote "Consensus on Transaction Commit" (2006), showing 2PC is a degenerate consensus protocol — one that tolerates zero coordinator faults — and proposing Paxos Commit as the fault-tolerant generalization. The two traditions (transactions and consensus) literally merged into one paper.

### Checkpoint

- Why can't a participant that voted YES unilaterally abort after a coordinator timeout?
- Where exactly is the atomic commit point in 2PC?
- Why did 3PC fail to displace 2PC despite being "non-blocking"?

## 12. Sagas: Transactions Without Transactions

**MOTTO:** Can't lock the world? Then break the journey into steps — and know how to walk each one backwards.

### The Problem

"Book trip" = charge card + reserve flight + reserve hotel, across three services with three databases. 2PC would hold locks across the internet at the mercy of the slowest participant — and most services won't offer you a PREPARE hook anyway. But partial completion (charged, no hotel) is unacceptable.

### The Concept

A saga (Garcia-Molina & Salem, 1987) replaces one big transaction with a sequence of *local* transactions T1..Tn, each with a **compensating action** C1..Cn. If Ti fails, run C(i-1)..C1 in reverse — not undo (history happened; the charge exists) but *counteraction* (refund).

```
  T1 charge ──▶ T2 flight ──▶ T3 hotel ✗ FAILS
                                  │
  C1 refund ◀── C2 cancel flight ◀┘        (compensate in reverse)

 orchestration: [saga orchestrator] ──commands──▶ services (explicit state machine)
 choreography:  each service reacts to the previous one's event (no central brain)
```

Key mind-shift: between T1 and C1, the world *sees* the intermediate state (money charged, then refunded). Sagas trade isolation for availability — you're guaranteed "all done or all compensated," not "nobody saw the middle."

### Build It

1. Decompose into steps; for each, design its compensation. If a step is truly irreversible (email sent), order it last or make it semantically retractable.
2. Choose orchestration (a saga state machine persists progress and issues commands — debuggable, central) or choreography (event chains — decoupled, harder to trace).
3. Every step and compensation must be **idempotent and retryable** — the saga engine will redeliver.
4. Persist saga state transitions (often via the outbox pattern) so a crashed orchestrator resumes, never restarts blindly.
5. Handle dirty reads between steps with countermeasures: *semantic locks* (mark record PENDING), reordering, or commutative updates.
6. Classify failures: business rejection (compensate) vs transient fault (retry forward).

### Use It

Temporal and AWS Step Functions are essentially saga orchestrators with durable state; Axon and Eventuate bake sagas into frameworks; airline/hotel booking flows have run compensation-based flows since before microservices had a name. Rule: use a saga when the workflow spans ownership boundaries; use a plain DB transaction whenever you possibly can — sagas are the fallback, not the goal.

### War Story

Hector Garcia-Molina and Kenneth Salem published "Sagas" at SIGMOD 1987 — aimed at *long-lived transactions* on a single database, where holding locks for hours strangled throughput. The paper predates microservices by ~25 years; the industry rediscovered it wholesale when service boundaries made cross-system locks impossible, and the 1987 mechanics needed almost no modification.

### Checkpoint

- Why is a compensation not the same thing as a rollback?
- Which ACID property do sagas sacrifice, and name one countermeasure for the resulting anomaly.
- When would you pick orchestration over choreography for a 6-step saga?

## 13. CRDTs: Merge Without Conflict

**MOTTO:** Choose data structures where merging is math, and conflicts become impossible rather than resolved.

### The Problem

Offline-capable apps and multi-leader replication mean concurrent writes to the same data with no coordinator to serialize them. Last-write-wins throws away someone's work; asking users to resolve conflicts is misery. What if the data type itself guaranteed that any two divergent replicas merge into the same result?

### The Concept

Conflict-free Replicated Data Types: types whose merge is a **join** in a semilattice — commutative, associative, idempotent. Like two shopping lists merged by union: merge order doesn't matter, merging twice doesn't matter, everyone converges. That's Strong Eventual Consistency: same set of updates ⇒ same state, no consensus required.

```
G-COUNTER (grow-only), 3 nodes — each node owns a slot, increments only its own:
  A: [3,1,0]   B: [2,4,0]   merge = element-wise max = [3,4,2]
  C: [2,1,2]                value = 3+4+2 = 9   (any merge order → same result)
```

### Build It

1. **G-Counter**: vector of per-node counts; `inc()` bumps own slot; `value()` = sum; `merge` = element-wise max. (Max is idempotent — re-delivered states are harmless.)
2. **PN-Counter**: two G-Counters, P and N; value = sum(P) − sum(N). Decrements are just growth in N.
3. **OR-Set** (observed-remove): `add(x)` stores x with a unique tag; `remove(x)` tombstones only the *tags you have observed*. Concurrent add wins over remove — because the remove never saw the new tag. This fixes the naive 2P-set's "can never re-add" flaw.

```python
class ORSet:
    def __init__(self): self.adds, self.removes = set(), set()   # {(elem, tag)}
    def add(self, e): self.adds.add((e, uuid4()))
    def remove(self, e): self.removes |= {(x, t) for x, t in self.adds if x == e}
    def contains(self, e): return any((e, t) not in self.removes for x, t in self.adds if x == e)
    def merge(self, o): self.adds |= o.adds; self.removes |= o.removes
```

4. Two delivery styles: **state-based** (ship full state, merge with join — tolerates any message loss/duplication) vs **operation-based** (ship ops — smaller, but needs reliable causal delivery). Deltas split the difference.

### War Story

Shapiro, Preguiça, Baquero, and Zawirski formalized CRDTs in 2011 ("Conflict-free Replicated Data Types" / the comprehensive INRIA study). Production followed fast: Riak shipped CRDT data types, Redis Enterprise built CRDT-based active-active geo-replication, and collaborative editors (e.g., Yjs, Automerge) made CRDTs the mainstream alternative to operational transformation for real-time text editing.

### Use It

| CRDT | Models | Watch out |
|---|---|---|
| G/PN-Counter | Likes, metrics | Vector grows with node count |
| OR-Set | Carts, tags, presence | Tombstone growth (needs GC) |
| LWW-Register | "Latest value" fields | Back to trusting clocks |
| RGA/sequence CRDTs | Collaborative text | Metadata overhead |

The catch: CRDTs converge, but only to what the math says — not necessarily what the *user* meant. And global invariants ("balance ≥ 0") still need coordination; no data type abolishes that.

### Checkpoint

- Why must a CRDT merge be idempotent, not just commutative and associative — which delivery fault does idempotence absorb?
- In an OR-Set, why does a concurrent add survive a concurrent remove of the same element?
- Name an application invariant CRDTs cannot enforce, and say why.

## 14. Gossip Protocols

**MOTTO:** Tell two friends, who tell two friends — and in O(log N) rounds the whole cluster knows.

### The Problem

A 1,000-node cluster needs every node to know membership, liveness, and light metadata. A central registry is a bottleneck and a single point of failure; naive broadcast is O(N) messages from one node and collapses at scale. You need dissemination that's cheap per node, tolerant of loss, and has no boss.

### The Concept

Epidemics, weaponized for good. Each node periodically picks a few *random* peers and exchanges what it knows; rumors spread exponentially, reaching all N nodes in ~O(log N) rounds with high probability, with each node doing constant work per round. Randomness delivers robustness: no structure to break, no coordinator to lose.

```
 round 0:  ●○○○○○○○         (1 knows)
 round 1:  ●●○○●○○○         each infected node infects ~fanout others
 round 2:  ●●●●●●○○
 round 3:  ●●●●●●●●         ~log₂(N) rounds to full infection

 push: "here's my news"   pull: "what's new?"   push-pull: both (fastest finish)
```

### Build It

1. Every T ms, pick k random peers (fanout, typically 2–3); exchange digests; sync differences. Version every item (per-node heartbeat counters / versions) so newer always overwrites older.
2. **Failure detection**: each node gossips its own heartbeat counter; if node X's counter hasn't advanced past a timeout (or by phi-accrual suspicion), mark X suspect/dead — and gossip *that*.
3. SWIM-style refinement: ping a random node; on silence, ask j others to ping it indirectly (dodges one bad link); spread alive/suspect/dead verdicts piggybacked on normal gossip. Add *incarnation numbers* so a falsely-accused node can publicly refute its own death.
4. Anti-entropy vs rumor-mongering: periodically full-sync digests (slow, thorough) plus hot new updates pushed eagerly for a few rounds (fast, cheap).

### Use It

Cassandra nodes gossip cluster state every second; Consul and HashiCorp's memberlist/Serf implement SWIM (their "Lifeguard" extensions reduce false positives); DynamoDB's ancestors, Redis Cluster, and Akka Cluster all gossip membership. Tradeoffs: eventual (not instant) convergence, probabilistic guarantees, and the classic operational hazard — a partition heals and two halves gossip *stale rumors* about each other's deaths.

### War Story

The founding paper is Demers et al., "Epidemic Algorithms for Replicated Database Maintenance" (PODC 1987) — done at Xerox PARC to keep the Clearinghouse directory service in sync, explicitly borrowing mathematics from epidemiology. The SWIM paper (Das, Gupta, Motivala, 2002) then separated failure detection from dissemination, and its descendants quietly run inside most modern clustering software.

### Checkpoint

- Why does gossip reach all nodes in roughly O(log N) rounds, and what per-node cost does that require?
- How do incarnation numbers let a live node refute a false death rumor?
- What advantage does SWIM's indirect ping give over direct heartbeating?
