# Project: Mini-CDN (Edge Caching + Origin Shield)

**Build the reason the internet doesn't melt every time someone goes viral.**

You built an LRU cache in `code/lru_cache.py`. A CDN is that idea,
weaponized: a fleet of caches parked between users and your origin
server, absorbing 95%+ of traffic before it ever touches you. This
project builds the whole pipeline — edges, shield, origin, routing,
and invalidation — in ~230 lines of stdlib Python.

## The Problem

Your origin server is in one region, and physics is undefeated:

- Every request pays full round-trip latency to that one region
- Every request costs origin CPU and bandwidth — viral traffic = outage
- Caching at the edge fixes both, but creates two new monsters:
  **staleness** (users see old content) and **invalidation**
  (the famous second-hardest problem in computer science)

## Architecture

```
 clients            edges (LRU + TTL)        shield          origin
                    ┌──────────┐
 client-0 ─┐   ┌───▶│  edge-1  │──miss──┐
 client-3 ─┼───┘    └──────────┘        │   ┌─────────┐   ┌─────────┐
           │        ┌──────────┐        ├──▶│ SHIELD  │──▶│ ORIGIN  │
 client-1 ─┼───────▶│  edge-2  │──miss──┤   │ (cache) │   │ (truth) │
 client-7 ─┘        └──────────┘        │   └─────────┘   └─────────┘
                    ┌──────────┐        │    3 edge misses
 client-2 ─────────▶│  edge-3  │──miss──┘    = 1 origin fetch
                    └──────────┘
     ▲
     └── consistent-hash ring maps each client to a stable edge
         (real CDNs do this with DNS/anycast; the ring gives the
          same property: sticky, and adding an edge remaps ~1/N)

 PURGE "/logo.png" ──▶ broadcast to every edge + the shield
```

## How It Works

**Edge caches (LRU + TTL).** Each edge holds a bounded `OrderedDict`.
TTL bounds *staleness* (nothing older than 60s is ever served); LRU
bounds *memory* (the least-recently-used asset is evicted first).
Two different problems, two different mechanisms, one cache.

**Consistent-hash routing.** Clients are hashed onto a ring of edge
vnodes, so each client always lands on the same edge — warm caches stay
warm. Adding a fourth edge would remap only ~1/4 of clients, not all
of them. (Compare `code/consistent_hashing.py`.)

**Origin shielding.** Without a shield, N edges missing the same asset
means N origin fetches — a "miss storm." The shield is one extra cache
layer in front of the origin: the first edge miss fills the shield, and
the other N-1 edge misses hit the shield instead of the origin. The
demo prints this collapse explicitly.

**Purge broadcast.** TTL alone means users can see stale content for up
to 60s after a deploy. Purge is the emergency brake: broadcast an
invalidation to every cache node, and the next request pulls the fresh
version through the shield. Surgical, too — purging `/logo.png` leaves
`/index.html` hot.

## Run the Reference

```
python cdn.py --demo
```

Fully automated, uses a fake clock (no sleeps), exits on its own:

1. Prints the client → edge routing table
2. Round 1 on cold caches: ~0% hit ratio, shield collapses 9 edge
   misses into 3 origin fetches
3. Rounds 2-3: hit ratios climb to 100%, origin fetch count freezes
4. Clock jumps 61s: everything TTL-expires, one refresh per asset
5. Logo v2 deploys, `purge('/logo.png')` broadcasts, next request
   pulls the fresh bytes while other assets stay cached
6. Final tally: total client requests vs. total origin fetches

## Build It Yourself: Milestones

1. **LRU + TTL cache** — extend your `lru_cache.py` with an
   `expires_at` per entry, checked on read. Test: expired entries
   behave exactly like missing entries.
2. **Origin + one edge** — a `request()` path that checks the edge and
   falls back to the origin, counting hits/misses. Test: second
   request for the same path never touches the origin.
3. **Three edges + routing** — a consistent-hash ring of edges keyed by
   client id. Test: the same client maps to the same edge 100/100 times.
4. **Shield** — insert a cache between edges and origin. Test: with 3
   edges requesting the same path, origin fetch count is 1, not 3.
5. **Purge** — broadcast invalidation to every node. Test: purged path
   refetches (new version served); unpurged paths still hit.
6. **Stats** — per-node hit ratios per round. Watch them climb; that
   graph is what CDN sales decks are made of.

## Extension Ideas

- **`stale-while-revalidate`** — serve the expired copy instantly,
  refresh in the background (what real CDNs actually do)
- **Request coalescing** — 100 concurrent misses for one path should
  produce 1 upstream fetch, not 100 (needs threads + a lock per key)
- **Negative caching** — cache 404s briefly so a missing asset can't
  DDoS your origin
- **Cache-Control parsing** — let the origin set per-asset TTLs via
  `max-age`, including `no-store`
- **Real HTTP** — put the origin behind `http.server` and make edges
  fetch over localhost sockets (daemon threads, clean shutdown!)
- **Tiered purge** — purge the shield first, then edges; reason about
  what happens if an edge refills from an unpurged shield mid-broadcast

## Checkpoint

- Why does the shield cut origin load by ~(N-1)/N on cold assets but
  do almost nothing once edges are warm?
- TTL = 60s and purge both fight staleness. When is each the right
  tool, and what does purge cost that TTL doesn't?
- A client's edge goes down. With consistent-hash routing, what happens
  to that client's hit ratio, and why is it better than rehashing
  everyone mod N?
