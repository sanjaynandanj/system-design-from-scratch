# Project: Distributed Key-Value Store (Mini-Dynamo)

**Build the database that survives a node catching fire mid-write.**

You've implemented consistent hashing in `code/consistent_hashing.py`.
Now put it to work: a replicated key-value store where any node can die
and clients never notice. This is the core idea behind Amazon Dynamo,
Cassandra, and Riak — squeezed into ~180 lines of stdlib Python.

## The Problem

One server holding your data is a single point of failure. Two servers
holding *copies* of your data raises new questions:

- Which servers hold which keys? (**placement**)
- How many copies, and how many must confirm a write? (**quorum**)
- What happens when a replica is down during a write? (**hinted handoff**)
- How does a dead node catch up when it comes back? (**recovery**)

This project answers all four, concretely.

## Architecture

```
                        ┌─────────────────┐
        client ────────▶│   COORDINATOR   │  put/get, quorum logic
                        └────────┬────────┘
                                 │ consistent-hash ring (64 vnodes/node)
          ┌──────────┬───────────┼───────────┬──────────┐
          ▼          ▼           ▼           ▼          │
     ┌────────┐ ┌────────┐  ┌────────┐  ┌────────┐     │
     │ node-A │ │ node-B │  │ node-C │  │ node-D │     │
     │ data{} │ │ data{} │  │ data{} │  │ data{} │     │
     │ hints{}│ │ hints{}│  │ hints{}│  │ hints{}│     │
     └────────┘ └────────┘  └────────┘  └────────┘     │
                                                        │
   key "user:alice" hashes onto the ring ───────────────┘
   → first 2 distinct nodes clockwise = its replicas (N=2)
```

## How It Works

**Placement.** Every node contributes 64 virtual nodes to a hash ring.
A key's *preference list* is the first N=2 distinct physical nodes
clockwise from the key's hash. Adding a node moves only ~1/N of keys.

**Writes (W=2, sloppy quorum).** The coordinator writes to both
preferred replicas. If one is dead, it keeps walking the ring and hands
the write to the next *healthy* node as a **hint** — a sticky note
saying "give this to node-C when it wakes up." The write still counts
toward the quorum, so availability survives the outage. That's the
"sloppy" in sloppy quorum: the quorum is met, just not by the ideal nodes.

**Reads (R=1).** The coordinator asks replicas in preference order and
returns the first answer. With one node dead, the surviving replica
answers. R=1 + W=2 with N=2 means a read always hits at least one node
that saw the latest write — as long as failures are transient.

**Recovery.** When a node rejoins, every peer delivers the hints it was
holding for it. A version number per write (a toy Lamport clock) makes
delivery idempotent: last write wins, stale hints are ignored.

## Run the Reference

```
python kv_store.py --demo
```

The demo is fully automated and exits on its own. It walks through:

1. Six keys placed on a 4-node ring, replicas printed per key
2. The primary replica for `user:alice` is killed — reads still succeed
3. Writes during the outage park hints on healthy nodes
4. The node rejoins and receives its hinted writes
5. A final sweep asserts every key returns the newest version

## Build It Yourself: Milestones

1. **Ring** — reuse `code/consistent_hashing.py`; add a `walk(key)` that
   yields distinct physical nodes clockwise. Test: walking past all
   nodes never repeats one.
2. **StorageNode** — a dict of `key -> (version, value)` plus an
   `alive` flag. No networking needed; in-process objects teach the
   same lessons.
3. **Replicated writes** — coordinator writes to the first N=2 nodes on
   the walk. Test: kill neither, read from either replica directly.
4. **Failure + R=1 reads** — add `kill()`. Reads skip dead replicas.
   Test: kill one replica, `get` still returns the value.
5. **Hinted handoff** — on write, replace each dead replica with the
   next healthy ring node holding a hint. Test: write during outage,
   inspect the helper's `hints` mailbox.
6. **Recovery** — `revive()` delivers hints with version checks.
   Test: rejoin, then read the key *from the revived node directly*.

## Extension Ideas

- **Vector clocks** instead of a global counter — detect true
  concurrent writes and surface siblings (see `code/vector_clock.py`)
- **Read repair** — on R>1 reads, push the newest version to stale replicas
- **Merkle-tree anti-entropy** — background sync instead of hints
- **Real networking** — put each node behind `http.server` on its own
  port and make the coordinator use `urllib`
- **Tunable consistency** — expose N/W/R as constructor args; explore
  what W=1, R=1 does to your durability guarantees
- **Gossip membership** — replace the coordinator's god-view of
  liveness with `code/gossip.py`

## War Story

Amazon's 2007 Dynamo paper exists because of the 2004 holiday season:
Oracle-backed shopping carts buckled under peak load, and a lost cart is
lost revenue. The team's insight was that a cart *must* accept writes
even during failures — so they chose sloppy quorums and hinted handoff,
accepting eventual consistency to buy always-on writes. The exact
mechanism you just built is the one that keeps "Add to Cart" working
while a datacenter rack is on fire.

## Checkpoint

- Why does W + R > N matter, and why is our N=2/W=2/R=1 setup only safe
  for *transient* failures?
- A hint is stored on a node that doesn't own the key. What breaks if
  that helper node dies before the owner returns?
- Why virtual nodes? What would placement look like with 4 physical
  nodes hashed once each?
