# Project: Distributed Job Scheduler

> Cron is easy. *Cron that survives the machine dying* is a distributed
> systems problem — and this project kills the machine on purpose.

Run cron on one box and you have a single point of failure. Run it on
three boxes and you have every job running three times (ask anyone who's
triple-sent a billing email). The fix is the same one used by Kubernetes
controllers, Nomad, and every "run exactly one of these" system ever
shipped: **leader election via a lease**. This project builds it, then
assassinates the leader mid-demo to prove the failover works.

## Architecture

```
   ┌────────┐   ┌────────┐   ┌────────┐
   │ node-1 │   │ node-2 │   │ node-3 │      every node runs the SAME loop:
   └───┬────┘   └───┬────┘   └───┬────┘      try lease -> if leader, dispatch
       │  heartbeat │ every 1s   │
       ▼            ▼            ▼
   ┌─────────────────────────────────┐
   │  LEASE  { holder, expires_at }  │ ◀── the entire election protocol
   └───────────────┬─────────────────┘
                   │ only the holder may act
                   ▼
   ┌─────────────────────────────────┐     ┌───────────────────────────┐
   │ JOB TABLE                       │     │ WORK QUEUE  -> worker pool │
   │  send-digest     every 4s       │────▶│  ┌────────┐  ┌────────┐   │
   │  sync-inventory  every 6s       │     │  │ work-1 │  │ work-2 │   │
   │  flaky-etl       every 8s (x2💥)│     │  └────────┘  └────────┘   │
   └─────────────────────────────────┘     │  retries w/ exp backoff   │
                                           └───────────────────────────┘
```

## How it works

**1. The lease IS the election.** No Raft, no Paxos — just one record
`{holder, expires_at}` behind a lock (standing in for a row in etcd,
ZooKeeper, or Postgres). A node becomes leader by writing its name when
the record is empty or expired, and stays leader by re-writing it every
heartbeat. Crash the leader and it simply... stops renewing. TTL later,
the record is up for grabs. This is `SELECT ... FOR UPDATE` leadership,
and it runs half the internet's background jobs.

**2. Everyone runs the same loop.** No special "leader code path" — all
three nodes heartbeat, attempt the lease, and dispatch only if they hold
it. Symmetry is what makes failover free: the new leader was already
running; it just started winning.

**3. Dispatch vs. execute.** The leader never runs jobs — it puts them on
a queue for a worker pool. Separating "deciding what runs" from "running
it" is what lets you scale workers without electing more leaders.

**4. Retries with exponential backoff.** `flaky-etl` is scripted to fail
its first two attempts. Workers retry at 1s, then 2s — doubling per
attempt, so a struggling downstream gets breathing room instead of a
stampede.

**5. Missed-run catch-up.** After the leader dies, jobs come due with
nobody to dispatch them. The new leader finds `next_run` in the past and
applies cron's classic policy: **coalesce** — run once now, skip the
other missed occurrences, schedule the future normally. (Replaying every
missed run is the other policy; for `send-digest`, your users prefer
coalescing.)

**6. The chaos monkey.** At t=13s the current leader is killed without
releasing its lease — the worst case. Watch the gap: no dispatches until
the lease expires (~5s), then a new leader, then catch-up. That TTL is
the fundamental knob: shorter means faster failover but more risk of a
slow-but-alive leader losing its lease mid-dispatch.

## Milestones (build it yourself)

1. **Solo cron** — one loop, a job table with `next_run` timestamps,
   dispatch when due. No election, no workers.
2. **Worker pool** — move execution onto a `Queue` + threads. Add
   scripted failures and exponential backoff.
3. **The lease** — add the `{holder, expires_at}` record and make 3
   nodes race for it. Verify exactly one dispatches.
4. **Kill the leader** — stop the holder's thread without cleanup.
   Measure time-to-failover. Now halve the TTL and measure again.
5. **Catch-up** — make the new leader detect `next_run` in the past and
   coalesce. Log it loudly; silent catch-up is how billing incidents
   start.

## How to run

```
python scheduler.py --demo     # ~2 real seconds of ~30 simulated seconds
```

The clock is accelerated 20x, so the narrative timestamps (`t=13.0s`)
are simulated time. You'll see the election, normal dispatches, the
flaky job failing twice and recovering, the assassination, the eerie
quiet, the failover, and the catch-up — then a post-mortem table with
run/retry/coalesce counts and the leadership timeline.

## Extension ideas

- **Fencing tokens.** Increment an epoch on every election and stamp it
  on dispatched work. Have workers reject stale epochs — then engineer
  the split-brain scenario where that check saves you (old leader
  paused by a long GC, wakes up, still thinks it's boss).
- **Real cron expressions.** Replace intervals with `"*/5 * * * *"`
  parsing. Next-run computation gets spicy around DST transitions.
- **A lease file.** Swap the in-memory lease for a file with
  `os.replace` (atomic on Windows and POSIX) so two *separate processes*
  can compete. Congratulations: actual distributed election.
- **Per-job concurrency policy.** What if a run is still executing when
  the next comes due? Implement `forbid` / `allow` / `replace` — the
  same three options as Kubernetes CronJob, for the same reasons.
- **Jitter.** 500 jobs scheduled at :00 arrive as a thundering herd.
  Add hashed per-job jitter and watch the load flatten.
- **Priority + starvation.** Two queues (high/low) and a worker policy
  that can't starve the low queue forever.

## What this is not

There's no network, so leases can't be *partially* observed — real
systems also need fencing (see extension #1) because two nodes can both
believe they're leader across a partition. The single lock stands in for
the consensus your coordination service provides. For actual consensus,
see `code/raft_lite.py` — this project is what you build *on top* of it.
