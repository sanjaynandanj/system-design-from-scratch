# Project: URL Shortener Service

> The "hello world" of system design interviews — except this one actually
> runs, rate-limits you, and keeps score.

Everyone can *draw* a URL shortener on a whiteboard. This project makes you
*build* one: a real HTTP service where an ID generator, a base62 codec, an
LRU cache, a SQLite store, and a token-bucket rate limiter all have to
cooperate on every single request. ~280 lines, pure stdlib, no magic.

## Architecture

```
                       ┌──────────────────────── shortener.py ───────────────────────┐
                       │                                                             │
  POST /shorten        │  ┌──────────────┐   deny(429)                               │
  GET  /<code>   ──────┼─▶│ TOKEN BUCKET │──────────▶ ✗                              │
  GET  /stats/<code>   │  │  (per IP)    │                                           │
                       │  └──────┬───────┘                                           │
                       │         │ allow                                             │
                       │         ▼                                                   │
                       │  ┌──────────────┐  miss   ┌───────────────┐                 │
                       │  │  LRU CACHE   │────────▶│ SQLITE STORE  │                 │
                       │  │ code -> url  │◀────────│ id, code, url,│                 │
                       │  └──────┬───────┘  fill   │ hits, created │                 │
                       │         │ hit             └───────┬───────┘                 │
                       │         ▼                         │                         │
                       │   301 Location: <url>       hits += 1 (analytics)           │
                       └─────────────────────────────────────────────────────────────┘
```

## How it works

**1. The codec.** Short codes are not random strings — they're the SQLite
auto-increment row id, base62-encoded. That guarantees uniqueness for free
(the database is the ID generator) and makes decoding trivial. We add an
offset of 62³ so even the very first URL gets a 4-character code and the
service doesn't advertise how empty it is.

**2. The cache.** Redirects are read-heavy and skewed: a few links get most
of the traffic. An `OrderedDict`-backed LRU sits in front of SQLite, and
new codes are written through on creation because "just shortened" is the
best predictor of "about to be clicked." (For the hand-rolled linked-list
version of LRU, see `code/lru_cache.py` in this repo.)

**3. The rate limiter.** A token bucket per client IP: burst capacity 20,
refill 10 tokens/sec. Bursts are fine; sustained hammering gets `429`.
Refill is computed lazily on each request — no background timer thread.

**4. Analytics.** Every redirect bumps a `hits` counter in the same SQLite
row. `GET /stats/<code>` reads it back. Yes, this couples the read path to
a write — that's a deliberate teaching wound (see extension ideas).

**5. Concurrency.** `ThreadingHTTPServer` handles each request on its own
thread, so the store guards its single SQLite connection with a lock, and
the bucket map has one too. Every shared structure earns its mutex.

## Milestones (build it yourself)

1. **Echo server** — `http.server` responding 200 to anything. Bind port 0
   and print the port the OS picked.
2. **Codec + store** — base62 over an auto-increment id; `POST /shorten`
   returns a code, `GET /<code>` returns a 301 with `Location`.
3. **Cache** — LRU in front of the store. Log hits/misses and prove the
   second lookup never touches SQLite.
4. **Rate limiter** — token bucket keyed by `client_address`. Flood
   yourself with `urllib` and watch the 429s roll in.
5. **Analytics** — hit counter + `/stats/<code>`. Then ask yourself what
   this does to your p99 under load. Sit with that feeling.

## How to run

```
python shortener.py --demo     # self-driving walkthrough, exits by itself
python shortener.py            # real server on port 8000 (Ctrl+C to stop)
```

The demo starts the server on an OS-assigned free port in a daemon thread,
shortens 3 URLs, follows a redirect (without auto-follow, so you see the
raw `301 Location:`), demonstrates a cache hit, floods 40 requests to trip
the rate limiter, reads back the hit stats, and shuts down cleanly.

Manual poking (server mode):

```
curl -X POST http://127.0.0.1:8000/shorten -d "{\"url\": \"https://example.com\"}"
curl -i http://127.0.0.1:8000/<code>
curl http://127.0.0.1:8000/stats/<code>
```

## Extension ideas

- **Async analytics.** Move `hits += 1` off the redirect path into a queue
  drained by a background thread. Measure the latency win. This is the
  write-behind pattern, and it's how real shorteners keep redirects fast.
- **Custom aliases.** `POST /shorten` with a `"custom": "my-link"` field.
  Now uniqueness isn't free anymore — handle the conflict.
- **Expiring links.** Add a TTL column and a lazy-deletion check on read.
  Then add a background sweeper and compare the two approaches.
- **Cache stampede.** Kill the cache entry for a hot code, fire 50
  concurrent requests, and watch them all hit SQLite at once. Fix it with
  per-key locking (a.k.a. request coalescing).
- **Two instances.** Run two copies against the same SQLite file behind a
  toy load balancer (see `code/load_balancer.py`). What breaks first —
  and why is the ID generator suddenly the interesting problem?
- **511 checksum.** Add a check digit to codes so typos 404 instead of
  redirecting to someone else's link.

## War story

In 2009, bit.ly was resolving hundreds of millions of clicks a day, and
the lesson from that era still holds: reads outnumber writes by ~100:1,
so the redirect path is the product. When link-shortener outages hit
Twitter clients back then, tweets full of dead short links were the
visible symptom — the URL had become a *dependency*, and a cache miss
storm on a hot link was suddenly everyone's problem. That's why this
project puts the cache, not the database, at the center of the diagram:
in a shortener, the database is the backup plan.

## What this is not

No auth, no HTTPS, no horizontal scale, no Redis. Every one of those
absences is on purpose: this project is the smallest system where the
cache/store/limiter interplay is real. Scale it up in your head first —
then in code.
