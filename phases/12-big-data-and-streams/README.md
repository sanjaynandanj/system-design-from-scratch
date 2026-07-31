# Phase 12 — 🌊 Big Data & Stream Processing

> When the data is too big to fit anywhere, move the compute.

There's a moment in every data system's life when the dataset stops fitting on one machine — and then keeps growing until it stops fitting in one *building's* worth of machines you'd care to babysit by hand. Big data is the discipline of computing over that: splitting work across thousands of cheap boxes that fail constantly, and pretending to the programmer that none of that happened. Then streams arrive and remove the last comfortable assumption — that the data ever stops coming. This phase walks the whole arc: MapReduce to Spark to Flink, batch to stream, and ends with you building a windowed stream processor in plain Python.

## 01. MapReduce: The Paper That Started It All

**MOTTO:** Make the programmer write two pure functions; make the framework survive a thousand dying machines.

### The Problem

Google circa 2003: index the web on thousands of commodity machines where disks die daily and the network is the bottleneck. Every team was rewriting the same grim scaffolding — split the input, ship the code, retry dead workers, shuffle intermediate data — around what was usually a trivially simple computation like "count words." The insight: the scaffolding is the hard part and it's *always the same*. Factor it out once.

### The Concept

MapReduce is a deal: you express your computation as two pure functions, and the framework owns all distribution. **Map** takes an input record and emits key/value pairs. The framework **shuffles** — groups all values by key across the cluster. **Reduce** takes one key plus all its values and emits results. It's a national census: thousands of local counters each tally their own town (map), the envelopes get sorted by province (shuffle), and one clerk per province adds up its envelopes (reduce).

```
  input splits      MAP             SHUFFLE (group by key)      REDUCE
  "cat sat"   -> (cat,1)(sat,1) \                            cat:[1,1] -> (cat,2)
  "cat ran"   -> (cat,1)(ran,1) --> hash(key) % R buckets -> ran:[1]   -> (ran,1)
  "dog ran"   -> (dog,1)(ran,1) /   sort within bucket       ...
```

Because map and reduce are pure and inputs are immutable files, fault tolerance is just *re-execution*: a worker dies, its tasks rerun elsewhere, and nobody weeps. Stragglers get speculative backup copies; first one done wins.

### Build It

The single-machine essence, faithful to the paper's structure:

```python
from collections import defaultdict

def map_fn(_, line):                      # (key, value) -> [(k2, v2)]
    for word in line.split():
        yield (word, 1)

def reduce_fn(key, values):               # (k2, [v2]) -> [(k2, v3)]
    yield (key, sum(values))

def mapreduce(inputs, map_fn, reduce_fn):
    groups = defaultdict(list)
    for k, v in inputs:
        for k2, v2 in map_fn(k, v):       # MAP
            groups[k2].append(v2)         # SHUFFLE (grouping)
    out = []
    for k2, vs in sorted(groups.items()): # REDUCE
        out.extend(reduce_fn(k2, vs))
    return out
```

Distributed reality adds: (1) input split into 64 MB chunks colocated with GFS/HDFS replicas so map tasks read *locally* — move compute to data; (2) mappers partition output into R files by `hash(key) % R`; reducers pull, merge-sort, and reduce; (3) a master tracks task state and reschedules on failure; (4) **combiners** (mini-reducers on the map side) shrink shuffle traffic for associative ops like counting.

### Use It

| System | Notes |
|---|---|
| Hadoop MapReduce | The open-source clone (2006); historically vital, rarely written by hand today |
| Hive / Pig | SQL / scripting layers that compiled to MapReduce jobs |
| Spark, Flink | The successors — same shuffle heart, better execution (next lessons) |
| BigQuery, Snowflake | The endgame: you write SQL, a shuffle happens somewhere |

### War Story

Dean and Ghemawat's "MapReduce: Simplified Data Processing on Large Clusters" (OSDI 2004) reported that after the library's introduction, engineers across Google — including those with no distributed-systems experience — were spinning up thousand-machine computations, with the index-building system rewritten as MapReduce phases. Doug Cutting and Mike Cafarella cloned the idea (plus GFS) as Hadoop to power the Nutch crawler; Yahoo bet on it in 2006, and an industry was born from one beautifully scoped paper.

### Checkpoint

- Why do map and reduce need to be pure/deterministic for the fault-tolerance story to work?
- What exactly happens during the shuffle, and why is it usually the expensive part?
- What is a combiner, and for which class of reduce functions is it legal?

## 02. HDFS and Object Storage

**MOTTO:** A petabyte doesn't fit on a disk, so the filesystem must become a cluster — or a service.

### The Problem

Big-data compute needs somewhere to put petabytes: readable at aggregate gigabytes per second, survivable when disks die daily (at 10,000 disks, failure is a *rate*, not an event), and cheap. A SAN is a mortgage; a single NFS server is a bottleneck with a blast radius. You need storage that scales horizontally on the same junk hardware the compute runs on — or, in the cloud era, storage that's someone else's fleet entirely.

### The Concept

**HDFS** (from Google's GFS design, 2003): files are split into big **blocks** (128 MB — big to amortize seeks and keep metadata small), each block replicated on 3 datanodes, with a **namenode** holding the entire namespace (file → block list → locations) in RAM. Clients ask the namenode *where*, then stream data directly from datanodes — metadata and data paths are separate, so the namenode isn't a throughput bottleneck. Optimized for huge sequential reads and appends; hostile to small files (each one is namenode RAM) and random writes.

**Object storage** (S3, 2006) rethinks the interface: no directories-as-real-things, no appends, no POSIX — just PUT/GET whole immutable objects by key over HTTP, with the provider handling replication and durability (S3 famously advertises eleven nines of durability). Compute and storage fully separate: scale, pay, and fail independently.

```
  HDFS                                    OBJECT STORE (S3)
  client -> namenode: "where's /f?"       client -> PUT bucket/key (whole object)
         <- [blk1@dn3,dn7,dn9 ...]               -> GET bucket/key [range]
  client <-> datanodes (parallel          flat keyspace; "dirs" are prefixes
             block streams)               no append, no rename-as-move
  compute colocated w/ data               compute elsewhere; cache to compensate
```

### Build It

Reasoning through the designs:

1. Block size math: 1 PB / 128 MB ≈ 8M blocks ≈ fits in namenode RAM; the same PB in 1 MB files ≈ a billion metadata entries ≈ namenode death. Hence "the small files problem" and its fix: compact into big files (Parquet + compaction, Lesson 12.07 of Phase 11).
2. Replica placement: copy 1 local, copy 2 on a *different rack*, copy 3 elsewhere on that rack — survives a full rack/switch loss without tripling cross-rack write traffic.
3. Object-store semantics bite pipelines: no atomic rename or append means "write temp then rename" commit protocols break — table formats (Iceberg/Delta) exist substantially to restore atomic commits on S3. (S3 became strongly consistent read-after-write in Dec 2020, retiring a decade of eventual-consistency workarounds.)
4. The economic verdict: elastic compute + pay-per-GB object storage beat colocated HDFS clusters that must be sized for peak; data locality lost the war to disaggregation, patched by caching and fat network pipes.

### Use It

| System | Notes |
|---|---|
| HDFS | Still runs in large on-prem estates; the design everyone learned from |
| S3 / GCS / Azure Blob | Default substrate of modern data platforms |
| MinIO | S3 API, self-hosted |
| Alluxio / caching layers | Re-adds "locality" atop object stores |

### War Story

The Google File System paper (Ghemawat, Gobioff, Leung — SOSP 2003) opened by declaring component failure "the norm rather than the exception," a sentence that reframed the field's assumptions. Its single-master design was famously pragmatic — and famously a scaling ceiling Google later replaced (Colossus). HDFS inherited both the pragmatism and the ceiling (namenode federation and HA arrived years later), while S3 quietly grew into one of the largest storage systems ever operated, holding hundreds of trillions of objects per AWS's public statements.

### Checkpoint

- Why are HDFS blocks 128 MB when filesystem blocks are 4 KB? Name two pressures the size choice balances.
- Explain the rack-aware replica placement policy and the failure it defends against.
- Why did missing atomic rename/append on object stores push the ecosystem toward table formats like Iceberg?

## 03. Spark: Memory Beats Disk

**MOTTO:** Stop writing every intermediate result to disk; keep the lineage and keep it in RAM.

### The Problem

MapReduce writes intermediate results to disk between *every* stage. A 10-step pipeline pays 10 rounds of disk I/O and job-launch overhead; iterative algorithms (PageRank, ML training — same dataset, many passes) reread from HDFS every single iteration. The fault-tolerance mechanism (materialize everything) taxes exactly the workloads that were becoming most important.

### The Concept

Spark's founding idea (the RDD paper, 2012): fault tolerance doesn't require materializing data — it requires being able to *recompute* it. An RDD is an immutable, partitioned dataset defined by its **lineage**: the recipe of deterministic transformations that produced it from stable input. Cache partitions in RAM for speed; if a machine dies, replay just the lost partitions' recipe. Like a chef who keeps sauces warm on the stove instead of jarring each one — and if a pot spills, re-makes only that pot from the written recipe.

```
  textFile ──map──> words ──map──> pairs ──reduceByKey──> counts
     |__________ narrow deps __________|        ^ wide dep (SHUFFLE)
                 = STAGE 1                       = stage boundary

  lineage: counts = reduceByKey(map(map(textFile)))
  worker dies -> recompute only its lost partitions from lineage
```

The execution model: transformations are **lazy** — nothing runs until an action (`collect`, `save`) triggers it. The scheduler then builds a DAG, fuses **narrow** dependencies (map/filter chains — each output partition needs one input partition) into pipelined stages, and breaks stages at **wide** dependencies (groupBy/join — need data from all partitions), which are shuffles. Shuffles didn't go away; Spark just stopped paying for disk *between the shuffles*.

### Build It

1. Express the job in the high-level API (DataFrames/SQL these days); the Catalyst optimizer rewrites your plan (pushes filters down, prunes columns, picks join strategies) before Tungsten generates tight code — you write intent, not execution.
2. `cache()` datasets reused across actions or iterations — this is the memory-beats-disk moment; forget it and you recompute lineage from scratch each pass.
3. For very long lineages (iterative jobs), `checkpoint()` to truncate the recipe, or recovery replay grows unbounded.
4. Watch the two classic killers: **skew** (one hot key makes one shuffle partition gigantic — one straggler task while 999 idle; fix with salting or adaptive execution) and **memory pressure** (executors spill to disk or OOM; RAM is a cache, not a miracle).

```python
# PySpark word count — MapReduce's hello world, interactive this time
counts = (spark.read.text("s3://corpus/")
          .selectExpr("explode(split(lower(value), '\\\\s+')) AS word")
          .groupBy("word").count())     # lazy: nothing has run yet
counts.cache().show(20)                 # action -> DAG -> stages -> shuffle
```

### Use It

| System | Notes |
|---|---|
| Apache Spark | Default heavy-lift batch engine; SQL, Python, streaming, ML in one |
| Databricks | Spark's creators, managed + proprietary engine (Photon) |
| Trino/Presto | Interactive SQL federation — complements Spark rather than replacing it |
| Dask / Ray | Python-native distributed compute for the Spark-averse |

### War Story

Spark came out of UC Berkeley's AMPLab; Zaharia et al.'s NSDI 2012 RDD paper reported 20x+ speedups over Hadoop on iterative workloads, and in 2014 Spark won the Daytona GraySort benchmark, sorting 100 TB in 23 minutes on 206 machines — beating the previous Hadoop record that had used roughly ten times as many machines, with three times the per-node throughput. The team spun out as Databricks, and "Hadoop job" quietly became "Spark job" across the industry.

### Checkpoint

- How does lineage-based recovery differ from replication-based recovery, and what does each cost?
- What distinguishes a narrow dependency from a wide one, and why do wide dependencies force stage boundaries?
- Your 1000-task Spark stage finishes in 2 minutes except one task that takes an hour. What's the likely cause and two fixes?

## 04. Stream Processing Fundamentals

**MOTTO:** Batch asks "what happened?"; streaming asks "what is happening?" — and never gets to stop.

### The Problem

Batch jobs see a complete, finite input and take minutes-to-hours after the data lands. But fraud detection, live pricing, monitoring, and personalization need answers in seconds — over data that *never stops arriving*. You can't wait for "all the data" because there's no such thing. Processing an unbounded input demands different primitives: what replaces "read the file"? What replaces "the job finished"?

### The Concept

A stream is an unbounded, ordered sequence of timestamped events; a stream processor is a standing query over it — a **dataflow graph** of operators (map, filter, keyBy, window, join) that events flow through continuously. Batch is doing the restaurant's books after closing; streaming is a cashier keeping the running total as each customer pays.

Three load-bearing distinctions:

```
  EVENT TIME vs PROCESSING TIME        STATELESS vs STATEFUL ops
  when it happened | when it arrived   filter/map: no memory
  (phone offline 2h -> events arrive   counts/windows/joins: MUST
   late but timestamped correctly)     remember things -> state

  DELIVERY GUARANTEES
  at-most-once  : may drop      (fast, wrong)
  at-least-once : may duplicate (fine if consumers idempotent)
  exactly-once  : effectively-once results (Lesson 05's whole topic)
```

Because operators hold **state** (running counts, open windows, join buffers) and run forever, the hard problems are: keeping state safe across crashes, handling events that arrive late or out of order (Lesson 06), and scaling by partitioning streams by key — same hash-partitioning instinct as the shuffle, applied to infinity.

### Build It

The minimal mental machine — a keyed, stateful operator:

```python
class RunningCount:                      # "SELECT key, COUNT(*) GROUP BY key"
    def __init__(self):                  # ...but forever
        self.state = {}                  # key -> count  (must survive crashes!)
    def on_event(self, event):
        k = event["key"]
        self.state[k] = self.state.get(k, 0) + 1
        emit(k, self.state[k])           # emits an UPDATE per event
```

Scaling and surviving:

1. Partition the stream by key (`hash(key) % N`); each parallel instance owns its keys' state — no shared state, no locks.
2. Periodically snapshot state + input position (offset) together; on crash, restore snapshot and replay input from the offset. This needs a *replayable* source — which is exactly why Kafka's log-not-queue design and stream processing co-evolved.
3. Notice the output is now a **changelog** (updates, not final answers) — consumers must handle "the count for `cat` is now 7, no wait, 8." Streams and tables are two views of the same thing: a table is a stream compacted; a stream is a table's diff.

### Use It

| System | Notes |
|---|---|
| Kafka + Flink | The canonical pairing (Lesson 05) |
| Kafka Streams | Stream processing as a Java library, no cluster |
| Spark Structured Streaming | Micro-batch model; easy if you're already Spark |
| ksqlDB / RisingWave / Materialize | SQL-on-streams |

### War Story

The field's Rosetta Stone is Tyler Akidau's 2015 essays "Streaming 101/102" and the Google Dataflow paper (VLDB 2015), which unified batch and streaming as one model — bounded data is just a stream that happens to end — and gave the industry its vocabulary of event time, windows, and triggers, distilled from Google's MillWheel and FlumeJava experience. Jay Kreps's 2013 essay "The Log" supplied the other half: a replayable log as the universal source that makes stream state recoverable.

### Checkpoint

- Why does an unbounded input force windowing or continuous emission — what can a streaming `COUNT(*)` never do?
- Distinguish event time from processing time and give a scenario where they diverge by hours.
- Why does stateful streaming's crash recovery require a replayable source like Kafka rather than a classic message queue?

## 05. Flink and Exactly-Once State

**MOTTO:** Exactly-once isn't about delivering messages once; it's about making retries invisible.

### The Problem

Your stream processor crashes mid-flight. Replaying input from the last safe point means some events get processed *twice* — and a fraud counter that double-counts is a fraud counter that lies. Networks duplicate; retries duplicate; crashes force replay. Physical exactly-once *delivery* is impossible (you can't know if the crashed process acted before dying). What's achievable is exactly-once *state semantics*: the final state and outputs are as if each event was processed once.

### The Concept

Flink's answer is **distributed snapshots** — the Chandy-Lamport algorithm (1985) adapted as "asynchronous barrier snapshotting." The trick: inject **checkpoint barriers** into the streams, flowing with the data. When a barrier reaches an operator, the operator snapshots its state *at exactly that point in the stream*; barriers from multiple inputs are aligned first. The result is a globally *consistent* cut: every operator's state reflects exactly the events before barrier N — no tearing. Like a photo finish in a race: one line, everyone's position captured relative to the same instant, without stopping the race.

```
  source ──e5──e4──|BARRIER n|──e3──e2──e1──> [op A] ──> [op B] ──> sink
                                   on barrier arrival:
                                   op snapshots state -> durable store,
                                   forwards barrier downstream
  CRASH? -> restore ALL ops from snapshot n, rewind source to offset n
         -> events after the barrier replay; state is consistent
```

Replay still reprocesses events — so end-to-end exactly-once needs the *sinks* to cooperate: either **idempotent writes** (upsert by key: replays overwrite with same value) or **transactional sinks** (two-phase commit tied to checkpoints: output for checkpoint N commits only when N completes; e.g., Kafka transactions). Kafka's own transactions + idempotent producers (KIP-98) provide the same guarantee for Kafka-in/Kafka-out pipelines.

### Build It

1. Sources record their read positions (Kafka offsets) as part of each checkpoint — state and position snapshot *together* (the atomicity that makes it work).
2. Operators keep state in a local store (RocksDB for big state); checkpoints upload asynchronously — incremental uploads ship only changed SST files.
3. Barrier alignment: an operator with 2 input streams pauses the fast one after its barrier arrives until the slow one's barrier catches up (backpressure risk; Flink's "unaligned checkpoints" trade snapshot size for alignment stalls).
4. On failure: restore every operator's state from the last completed checkpoint, rewind sources, run. Uncommitted transactional output from the doomed epoch is aborted.
5. **Savepoints** = manually triggered, portable checkpoints: the operational superpower — stop, upgrade the job or rescale parallelism, restart from the savepoint with state intact.

### Use It

| System | Exactly-once story |
|---|---|
| Apache Flink | Barrier snapshots + transactional/idempotent sinks |
| Kafka Streams | Kafka transactions (EOS), Kafka-to-Kafka |
| Spark Structured Streaming | Micro-batch + idempotent/transactional sinks |
| Any processor + idempotent sink | The poor man's exactly-once — often all you need |

### War Story

The lineage is unusually clean: Chandy & Lamport's 1985 distributed-snapshots paper (Lamport has a habit of appearing in these phases) → Flink's "Lightweight Asynchronous Snapshots for Distributed Dataflows" (Carbone et al., 2015) → Apache Flink, which grew from the Berlin-based Stratosphere research project into the industry's stateful-streaming default, powering pipelines at Alibaba (which acquired the founding company, Ververica, in 2019), Uber, and Netflix at millions of events per second.

### Checkpoint

- Why is exactly-once *delivery* physically impossible, and what is guaranteed instead?
- What property makes a barrier-aligned snapshot "consistent," and what could go wrong if operators snapshotted at arbitrary independent moments?
- Your Flink job has exactly-once checkpoints but writes to a plain REST API sink. What does the end-to-end guarantee degrade to, and what are your two repair options?

## 06. Windowing and Watermarks

**MOTTO:** You can't count "events per minute" until you decide when a minute is allowed to end.

### The Problem

Aggregating an infinite stream requires chopping it into finite pieces — windows. But events arrive out of order: a phone's 12:00:59 event may arrive at 12:03 (dead zone, retries, GC pauses). When can you close the 12:00–12:01 window and emit its count? Close immediately and you undercount; wait forever and you emit nothing. This — not the windowing arithmetic — is the actual hard problem.

### The Concept

Window shapes first:

```
  TUMBLING (1 min):  |––A––|––B––|––C––|        fixed, non-overlapping
  SLIDING (1m/15s):  |––A––|                    fixed, overlapping —
                        |––B––|                 each event in ~4 windows
  SESSION (gap 30s): |–user1–|   gap   |–u1–|   dynamic: closes after
                                                30s of silence per key
```

Now the clock problem. A **watermark** is the system's flowing declaration: "I believe all events with timestamp ≤ T have now arrived." Watermarks advance through the dataflow like a tide line; when the watermark passes a window's end, the window fires. Watermarks are a *heuristic bet* — typically "max event time seen, minus allowed lateness Δ." Think of a teacher collecting exams: "it's 12:05, I'm confident everyone who took the 12:00 exam has turned it in — grading now." A straggler after that is **late data**: drop it, or reopen and *retract/update* the earlier result, or shunt it to a side output for reconciliation. Small Δ = fast results, more late stragglers; big Δ = accurate but laggy, and windows buffer in state longer. There is no free lunch, only a chosen Δ.

### Build It

1. Assign: each event, by its *event timestamp*, maps to window(s) — tumbling: `start = ts - (ts % size)`; sliding: one window per step it overlaps; session: merge-with-neighbors within gap.
2. Accumulate: per (key, window), fold the event into state — keep an aggregate (count/sum), not the raw events, when the function allows.
3. Advance watermark: `W = max_event_ts_seen - Δ`. With parallel sources, the operator's watermark is the *minimum* across inputs — one silent partition stalls everything (the "idle source" trap; fix with idleness timeouts).
4. Trigger: when `W ≥ window_end`, emit result; schedule state cleanup after an additional allowed-lateness grace period.
5. Handle stragglers per policy: drop / update-with-retraction / side output. (Full code: Lesson 10.)

### Use It

| Concern | Options |
|---|---|
| Window types | Tumbling, sliding, session in Flink / Beam / Kafka Streams |
| Watermark strategy | Bounded out-of-orderness (fixed Δ) is the workhorse |
| Late data | Flink side outputs; Beam triggers with accumulation modes |
| Retractions | Changelog outputs; sinks must upsert |

### War Story

The watermark model was hammered out inside Google's MillWheel (VLDB 2013) and generalized in the Dataflow model paper (Akidau et al., VLDB 2015), which posed the field's defining question as a correctness/latency/cost triangle you *tune* rather than solve — its famous framing: "we can never affordably guarantee correctness of event-time windows, so we offer principled ways to trade." Apache Beam is that paper as an API; Flink is its most faithful open-source executor.

### Checkpoint

- Assign event ts=125s to (a) 60s tumbling windows, (b) 60s windows sliding every 15s — which windows, and how many?
- Why must an operator take the minimum watermark across its parallel inputs, and what pathology does an idle partition cause?
- Your Δ is 10s and an event arrives 45s late. Name the three possible fates for it and one cost of each.

## 07. Lambda vs Kappa Architectures

**MOTTO:** Running two pipelines to hedge one truth means debugging two lies.

### The Problem

Mid-2010s streaming engines were fast but sloppy (weak exactly-once, primitive windowing), while batch was correct but slow. Teams needed both freshness and accuracy — and got an architecture pattern that institutionalized the compromise: run *both*, forever. The question this lesson answers: was that ever a good idea, and what replaced it?

### The Concept

**Lambda architecture** (Nathan Marz, ~2011): every event goes down two paths. The **batch layer** periodically recomputes correct views from the complete raw history; the **speed layer** streams approximate real-time deltas; the **serving layer** merges them — accurate-but-stale plus fresh-but-loose. **Kappa architecture** (Jay Kreps, 2014) counters: if your log retains history and your stream processor is *correct* (exactly-once state, event-time windows — Lessons 05–06), then batch is redundant: one streaming pipeline handles live data, and "recompute" = replay the log through a new version of the same code.

```
  LAMBDA                                KAPPA
          +-> BATCH (nightly, exact) -+        Kafka (long retention)
  events -|                           |-> serve       |
          +-> SPEED (live, approx)  --+          STREAM JOB v1 ──> view v1
                                                 STREAM JOB v2 (replays
  2 codebases, 2 semantics,                       history) ──> view v2
  1 merge headache                               cut over when caught up
```

The Lambda tax is concrete: the same business logic implemented twice (say, Spark *and* Storm), which drift, which double every bug hunt, whose subtle semantic differences surface as "why don't the dashboards agree?"

### Build It

Running a Kappa-style reprocess:

1. Retain the source of truth: Kafka with long/infinite retention, or tiered storage, or the log mirrored to the lakehouse (a common hybrid: stream for serving, lake for ad-hoc — but *one* processing codebase).
2. To change logic or fix a bug: deploy job v2 with a new consumer group and *new output tables*, reading from the beginning (or a savepoint).
3. Let v2 chew through history at full throttle — replay is compute-bound, so it catches up much faster than real time.
4. Diff v1 vs v2 outputs on overlapping windows (your correctness gate), then atomically switch readers to v2's tables and retire v1.
5. Honest caveats: replaying years of events costs real money and time; some logic (calls to external mutable services) isn't replayable; and if you need heavy ad-hoc analytics, you'll have a lake anyway — Kappa is about not duplicating the *pipeline logic*, not banning batch tools from the building.

### Use It

| Pattern | When |
|---|---|
| Kappa (Kafka + Flink, replayable) | Default for event pipelines today |
| Lambda | Legacy estates; or when stream + batch genuinely need different logic |
| Hybrid: stream to serve + lakehouse to explore | Most real companies, in practice |
| Streaming-native stores (Materialize, RisingWave) | Kappa with SQL ergonomics |

### War Story

The debate happened in public and in print: Marz introduced Lambda around 2011 (later the book *Big Data*, 2015), born of his work creating Storm at BackType/Twitter; Kreps — co-creator of Kafka at LinkedIn — published "Questioning the Lambda Architecture" on O'Reilly Radar in 2014, coining "Kappa" and arguing that maintaining two systems' worth of the same logic was an operational tax masquerading as rigor. Engines then made his bet good: Flink's checkpointing and event-time model (2015+) removed the accuracy excuse for most workloads.

### Checkpoint

- What specific weakness of 2013-era stream processors did the Lambda batch layer compensate for?
- Walk through a Kappa reprocess: how do you deploy fixed logic without corrupting live serving?
- Name two situations where a batch path alongside streaming is still the right call.

## 08. Stream Joins and State Stores

**MOTTO:** Joining two infinite tables means deciding how much of each you can afford to remember.

### The Problem

"Join clicks with impressions to attribute ads." In batch, trivial: both tables are complete, hash-join, done. In streaming, neither side is ever complete: when a click arrives, its matching impression may have arrived seconds ago — or may arrive in ten seconds, or never. Someone must *buffer* candidates, and over an infinite stream an unbounded buffer is a slow-motion OOM. Joins force streaming's state problem to its sharpest point.

### The Concept

Three join shapes, by what's remembered:

```
  STREAM-STREAM (windowed):  remember both sides, but only within a
    clicks ⋈ impressions      time bound: |click.ts - imp.ts| < 1h
    [state: 1h of each, per key; expired by watermark]

  STREAM-TABLE (enrichment): remember ALL of one side, as a table
    orders ⋈ user-profiles    (a compacted changelog: latest value per key);
    [each order joins the CURRENT profile — no windowing]

  TEMPORAL/AS-OF: stream-table, but versioned —
    trades ⋈ fx-rates AS OF trade.ts (join the rate that was true THEN)
```

The time bound is the load-bearing decision: it converts "infinite join" into "join within a business-meaningful horizon" — attribution windows, fraud lookback periods. And all of it lives in the **state store**: a local, keyed, persistent store (RocksDB, an embedded LSM tree — Phase 4's storage engines cash their sequel check here) that holds join buffers, window accumulators, and table snapshots, backed up via checkpoints or changelog topics.

### Build It

A windowed stream-stream join, mechanically:

1. Partition both streams by the join key — co-partitioning ensures matching events meet on the same worker (a shuffle wearing streaming clothes).
2. On a left event: probe the right buffer for key matches within the window, emit joined rows; insert self into the left buffer with its timestamp.
3. Symmetrically on right events. (This is a symmetric hash join, streamified.)
4. When the watermark passes `ts + window`, expire buffered entries — for *outer* joins, emit `left ⋈ NULL` for the unmatched at expiry (you can't know "no match" until time closes the door).
5. State store mechanics: RocksDB keyed by `(join_key, ts, seq)` so expiry is a prefix range-delete; recovery restores the store from checkpoint (Flink) or replays a changelog topic (Kafka Streams).

```python
# left-side handler of a symmetric windowed join (right side mirrors it)
def on_left(e):
    for r in right_buf.range(e.key, e.ts - W, e.ts + W):
        emit(join(e, r))
    left_buf.put(e.key, e.ts, e)
def on_watermark(w):
    left_buf.expire_older_than(w - W); right_buf.expire_older_than(w - W)
```

### Use It

| Tool | State store story |
|---|---|
| Flink | RocksDB state backend; interval & temporal joins built in |
| Kafka Streams | RocksDB + changelog topics; KTables for stream-table joins |
| ksqlDB / Flink SQL | `JOIN ... WITHIN 1 HOUR` — the mechanics above, as SQL |
| Feature stores (Feast et al.) | Stream-table enrichment productized for ML |

### War Story

Kafka Streams' "stream-table duality" — a table is a compacted stream, a stream is a table's changelog — was articulated in LinkedIn/Confluent's work (Kreps's "The Log," 2013, and the Samza project, whose local-RocksDB-plus-changelog state design Kafka Streams inherited). Ad-tech attribution was the crucible: joining click and impression streams within a window at millions of events per second is roughly the industry's shared homework problem, and every streaming engine's join docs quietly assume it.

### Checkpoint

- Why must a stream-stream join be windowed, and what business input should size the window?
- In a stream-table join of orders against user profiles, why is there no window — and what determines *which* profile version an order joins?
- Why can a streaming LEFT OUTER join only emit its NULL rows at window expiry, not immediately?

## 09. Schema Registries and Evolution

**MOTTO:** A topic without a schema contract is an API where the breaking change arrives at 2 AM as a deserialization error.

### The Problem

Producer and consumer teams share a Kafka topic but deploy independently. Producer v2 renames a field; every consumer crash-loops at once — or worse, silently misparses money amounts. Events also *persist*: tonight's consumer must read messages written last year, and a replay (Lesson 07!) must read *all* of history. Data in motion needs what APIs have: a versioned, enforced contract — and unlike an API, old versions never stop existing.

### The Concept

A **schema registry** is a small service holding versioned schemas per topic. Producers register/fetch a schema ID and embed it in each message (magic byte + 4-byte ID + compact binary payload); consumers resolve the ID and decode. Crucially, the registry *rejects* registration of schemas that violate the topic's **compatibility policy** — the breaking change fails in CI, not in production at 2 AM.

```
  producer ──register/lookup──> [SCHEMA REGISTRY] <──resolve id── consumer
     |        "orders-value: v3?"    v1,v2,v3 + policy: BACKWARD      |
     +── wire: [0][id=3][binary avro bytes] ─── Kafka ────────────────+

  BACKWARD  : new READER reads old data  (consumers upgrade first)
  FORWARD   : old reader reads NEW data  (producers upgrade first)
  FULL      : both — evolve fields only in mutually-safe ways
```

The compatibility rules fall out of one question per change: *can a reader with schema X make sense of data written with schema Y?* Adding a field **with a default** is safe both ways (old data: reader fills the default; new data: old reader ignores it). Removing a field with a default: same. Renaming, retyping, or adding a defaultless required field: breaking. Avro/Protobuf resolve this mechanically — Avro by comparing writer's and reader's schemas at decode time, Protobuf by field-number discipline (never reuse a number).

### Build It

1. Pick a binary format with evolution semantics: Avro, Protobuf ([field tags]), or JSON Schema (validation without compact encoding). Naked JSON = no contract, no compression, eventual sorrow.
2. Set the policy per topic — BACKWARD (default; supports replaying history with the newest reader) and decide the matching *deploy order* (BACKWARD ⇒ upgrade consumers first).
3. Wire CI: producer builds validate proposed schemas against the registry before merge.
4. Evolve additively: new optional fields with defaults; deprecate-then-remove over quarters; *never* reuse a Protobuf field number or change a field's meaning in place.
5. For genuinely incompatible changes: new topic (`orders.v2`), dual-publish during migration, move consumers, retire — an API version bump, in log form.

### Use It

| Tool | Notes |
|---|---|
| Confluent Schema Registry | The de facto standard; Avro/Protobuf/JSON Schema |
| AWS Glue Schema Registry | The AWS-native flavor |
| Buf (Protobuf) | Breaking-change detection as CI tooling for proto APIs |
| Karapace | Open-source registry-compatible alternative |

### War Story

Avro itself was created by Doug Cutting (yes, again — Lucene, Hadoop, and now this) in 2009, partly because Hadoop needed a compact format whose *reader/writer schema resolution* made stored data evolvable — the writer's schema travels with the data, the reader reconciles. Confluent's Schema Registry (2015) moved that idea onto the wire for Kafka, and "the registry rejected my PR" is now a rite of passage that replaces what used to be a multi-team production incident.

### Checkpoint

- Why does BACKWARD compatibility imply "upgrade consumers before producers"? Reason it through.
- Adding a required field with no default breaks which direction of compatibility, and why?
- Why is "never reuse a Protobuf field number" an iron law even after the field is deleted?

## 10. Build a Stream Processor From Scratch

**MOTTO:** Windows, watermarks, and late data stop being abstract the moment your own code has to drop an event.

### The Problem

Time to cash the checks Lessons 04 and 06 wrote: build a working stream processor — event-time tumbling-window word counts, out-of-order input, watermarks, allowed lateness, late-data policy — in dependency-free Python. If you can build this, Flink's docs read like a description of your own code with better engineering.

### The Concept

The machine: events carrying `(timestamp, payload)` arrive *out of order* → each is assigned to its tumbling window and folded into per-(window, word) state → a watermark (`max_ts_seen - Δ`) advances behind the data → when it passes a window's end, the window **fires** (emit counts) → events arriving for already-fired windows are late: dropped and counted.

```
  events (out of order!) ──> assign window ──> accumulate state
                                                    |
  watermark = max_ts - Δ  ──(passes window end)──> FIRE window, emit
  event for a fired window ─────────────────────> LATE: side-output/drop
```

### Build It

```python
from collections import defaultdict, Counter

class TumblingWordCount:
    def __init__(self, window_size=60, lateness=10):
        self.size, self.lateness = window_size, lateness
        self.state = defaultdict(Counter)   # window_start -> {word: count}
        self.max_ts = float("-inf")         # drives the watermark
        self.fired = set()                  # windows already emitted
        self.late_events = []               # side output

    def window_of(self, ts):
        return ts - (ts % self.size)        # tumbling assignment

    @property
    def watermark(self):                    # "all events <= this have arrived"
        return self.max_ts - self.lateness  # ...probably

    def on_event(self, ts, text):
        win = self.window_of(ts)
        if win in self.fired:               # door already closed
            self.late_events.append((ts, text))
            return
        for word in text.lower().split():
            self.state[win][word] += 1      # accumulate
        self.max_ts = max(self.max_ts, ts)
        self._advance()

    def _advance(self):                     # fire every complete window
        for win in sorted(self.state):
            if win + self.size <= self.watermark and win not in self.fired:
                print(f"WINDOW [{win},{win+self.size}) -> "
                      f"{dict(self.state[win].most_common(3))}")
                self.fired.add(win)
                del self.state[win]         # state cleanup: not optional!

# Drive it with disorder and lateness:
events = [
    (5,  "cat sat"), (12, "cat ran"),      # window [0,60)
    (61, "dog ran"), (58, "cat cat"),      # 58 is out of order but IN TIME
    (75, "dog sat"), (130, "mouse ran"),   # 130 pushes watermark to 120:
                                           #   fires [0,60) and [60,120)
    (55, "too late cat"),                  # [0,60) already fired -> LATE
    (200, "flush"),                        # fires [120,180)
]
p = TumblingWordCount(window_size=60, lateness=10)
for ts, text in events:
    p.on_event(ts, text)
print("late (dropped):", p.late_events)    # [(55, 'too late cat')]
```

Trace it by hand once — watch event 58 land safely (out of order ≠ late) while event 55 gets dropped (its window fired). Then extend: (1) keyed parallelism — hash words across N instances; (2) checkpointing — pickle `(state, max_ts, fired)` plus the input offset, kill the process mid-stream, restore, replay; (3) update-mode late handling — re-fire the window with corrected counts and observe why sinks must then upsert; (4) sliding windows — assign each event to `size/step` windows.

### Use It

Everything here maps 1:1 onto production APIs: Flink's `TumblingEventTimeWindows.of(60s)` + `forBoundedOutOfOrderness(10s)` + side outputs, or Kafka Streams' `TimeWindows.ofSizeAndGrace(...)`. What production adds is exactly your extension list — keyed distribution, durable RocksDB state, barrier checkpoints (Lesson 05) — industrialized.

### War Story

This toy is a faithful miniature of the Dataflow model (Akidau et al., VLDB 2015): its four questions — *what* (word counts), *where* in event time (tumbling windows), *when* to emit (watermark triggers), *how* refinements relate (your drop-vs-update policy) — are literally the paper's organizing framework. Google built MillWheel and Dataflow to answer them at scale; you answered them in 40 lines. The gap between the two is engineering, not concept — which is the most encouraging sentence in this phase.

### Checkpoint

- In the driver, why is event (58, "cat cat") counted but (55, "too late cat") dropped, when 55 < 58?
- What breaks if `_advance` never deletes fired windows' state, and what breaks if it deletes them *without* tracking `fired`?
- What exactly must be included in a checkpoint of this processor for crash recovery to be correct, and why is the input offset part of it?
