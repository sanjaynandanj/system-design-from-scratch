# Project: Message Broker (Mini-Kafka)

**Build the log that outlives every consumer that reads it.**

`code/message_queue.py` gave you a queue in memory. This project builds
what Kafka actually is: not a queue, but a **durable, partitioned,
append-only log** that consumers walk through at their own pace — and
re-walk after they crash. In ~200 lines of stdlib Python, with real
files on disk.

## The Problem

A naive queue deletes a message once it's handed out. Then:

- The consumer crashes mid-processing → the message is gone forever
- Two consumers want the same stream → who gets what?
- You need per-customer ordering at scale → one queue can't parallelize

The fix is to stop deleting. Persist everything to an append-only log,
give each consumer group a bookmark (**offset**), and let crash recovery
be "rewind to the last committed bookmark."

## Architecture

```
 producers                    BROKER                       consumer group
                                                             "billing"
 cust-A ──┐    key hash   ┌──────────────────────┐
 cust-B ──┼──────────────▶│ topic "orders"       │      ┌──────────┐
 cust-C ──┘               │  ├─ partition 0 ─────┼─────▶│ worker-1 │
                          │  │   [0][1][2][3]... │  ┌──▶│          │
                          │  ├─ partition 1 ─────┼──┘   └──────────┘
   append-only files      │  │   [0][1]...       │      ┌──────────┐
   orders-0.log           │  └─ partition 2 ─────┼─────▶│ worker-2 │
   orders-1.log           │      [0][1][2]...    │      └──────────┘
   orders-2.log           └──────────────────────┘
                          committed offsets per group:
                          {p0: 4, p1: 2, p2: 3}   ◀── the bookmarks
```

## How It Works

**Partitions.** A topic is split into P independent logs. A message's
partition is `hash(key) % P`, so all of `cust-A`'s orders land in one
partition, in order. Ordering is guaranteed *per partition*, never
across the topic — that's the trade that buys parallelism.

**The commit log.** Each partition is a JSON-lines file. `append` writes
a line and hands back its offset; `read_from(offset)` scans forward.
Sequential disk I/O is why real Kafka is fast; a sparse index (not
built here) is what makes seeking fast too.

**Consumer groups.** Each partition is owned by exactly one consumer in
the group (round-robin assignment). Add a consumer → **rebalance**
spreads partitions across more workers. Lose one → its partitions are
reassigned to the survivors.

**Offsets and at-least-once.** The broker stores one committed offset
per (group, partition). Consumers poll from the committed offset,
process, *then* commit. Crash between processing and committing? The
next owner polls from the old bookmark and processes the batch again.
Duplicates are possible; loss is not. Deduplication is the consumer's
job (idempotent handlers or a processed-ID set).

## Run the Reference

```
python broker.py --demo
```

Fully automated; creates its logs in a temp directory and deletes them
on exit. The walkthrough:

1. Creates topic `orders` with 3 on-disk partition logs
2. Produces 9 keyed messages — same key, same partition, every time
3. Prints raw commit-log lines so you see it really is just a file
4. Two workers join group `billing`; partitions are rebalanced
5. worker-1 processes and commits; worker-2 processes and **crashes**
   before committing
6. Rebalance hands worker-2's partitions to worker-1, which redelivers
   the crashed batch — asserted: nothing lost, nothing extra

## Build It Yourself: Milestones

1. **One log** — a `Partition` class with `append` and `read_from`
   against a real file. Test: append 5, read from offset 2, get 3 back.
2. **Topic + routing** — P partitions, `hash(key) % P`. Test: the same
   key routes to the same partition 100 times out of 100.
3. **Manual offsets** — a consumer that tracks its own offset dict.
   Feel the pain; that pain justifies broker-side offsets.
4. **Consumer groups** — broker-side offsets + round-robin assignment.
   Test: 3 partitions, 2 consumers → split 2/1.
5. **Crash + rebalance** — remove a member without committing, then
   verify the survivor redelivers exactly the uncommitted records.

## Extension Ideas

- **Sparse index file** — map every Nth offset to a byte position;
  seek instead of scanning
- **Log segments + retention** — roll files at a size limit, delete
  segments older than a retention window
- **Exactly-once-ish** — consumer-side dedup table keyed by
  (partition, offset)
- **Sticky rebalancing** — minimize partition movement when membership
  changes (compare with what Kafka's cooperative rebalancer does)
- **Replication** — follower partitions on a second "broker" object;
  only serve reads from the leader's committed high-water mark
- **Compaction** — keep only the latest record per key (this is how
  Kafka doubles as a database changelog)

## War Story

In 2013, LinkedIn was running Kafka at hundreds of billions of messages
a day, and the most common production incident wasn't the broker — it
was consumers double-processing after rebalances, exactly like step 7
of the demo. Teams that assumed exactly-once delivery corrupted
downstream counts; teams that wrote idempotent consumers didn't notice
rebalances at all. The lesson became folklore: *the broker promises
at-least-once; everything else is your job.*

## Checkpoint

- Why does committing offsets *before* processing turn at-least-once
  into at-most-once?
- Your topic has 4 partitions and 6 consumers in one group. How many
  consumers are idle, and why?
- Ordering is per-partition. What happens to `cust-A`'s ordering if
  you increase the partition count from 3 to 6 on a live topic?
