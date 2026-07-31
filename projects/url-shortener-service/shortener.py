"""A tiny-but-real URL shortener: HTTP API + LRU cache + SQLite + rate limiter.

Teaches: how the classic interview system actually fits together — a base62
codec over an auto-increment ID, a write-through cache in front of durable
storage, and a token-bucket keeping abusive clients out. Run with --demo for
a self-driving walkthrough that exercises every component and exits.
"""

import argparse
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Offsetting the row id means even id=1 produces a 4-char code, so codes
# don't leak how few URLs the service has stored.
CODE_OFFSET = 62 ** 3


def base62(n: int) -> str:
    digits = []
    while n:
        n, rem = divmod(n, 62)
        digits.append(ALPHABET[rem])
    return "".join(reversed(digits)) or "0"


class LRUCache:
    """Bounded cache; OrderedDict gives us O(1) recency reordering."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._data = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if key in self._data:
            self._data.move_to_end(key)
            self.hits += 1
            return self._data[key]
        self.misses += 1
        return None

    def put(self, key, value):
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)


class TokenBucket:
    """Per-client-IP token bucket: burst up to `capacity`, refill at `rate`/s."""

    def __init__(self, capacity: float, rate: float):
        self.capacity = capacity
        self.rate = rate
        self._buckets = {}  # ip -> (tokens, last_refill)
        self._lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        with self._lock:
            now = time.monotonic()
            tokens, last = self._buckets.get(ip, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self._buckets[ip] = (tokens - 1.0, now)
                return True
            self._buckets[ip] = (tokens, now)
            return False


class Store:
    """SQLite behind a lock: one connection shared by all handler threads."""

    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS urls ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " code TEXT UNIQUE, url TEXT NOT NULL,"
            " hits INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)"
        )

    def insert(self, url: str) -> str:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO urls (url, created) VALUES (?, ?)", (url, time.time())
            )
            code = base62(cur.lastrowid + CODE_OFFSET)
            self._db.execute("UPDATE urls SET code = ? WHERE id = ?", (code, cur.lastrowid))
            self._db.commit()
            return code

    def lookup(self, code: str):
        with self._lock:
            row = self._db.execute("SELECT url FROM urls WHERE code = ?", (code,)).fetchone()
            return row[0] if row else None

    def bump_hits(self, code: str):
        with self._lock:
            self._db.execute("UPDATE urls SET hits = hits + 1 WHERE code = ?", (code,))
            self._db.commit()

    def stats(self, code: str):
        with self._lock:
            row = self._db.execute(
                "SELECT url, hits, created FROM urls WHERE code = ?", (code,)
            ).fetchone()
        if row is None:
            return None
        return {"code": code, "url": row[0], "hits": row[1], "created": row[2]}


def make_handler(store: Store, cache: LRUCache, limiter: TokenBucket, quiet: bool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if not quiet:
                super().log_message(fmt, *args)

        def _send(self, status, payload, headers=None):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _rate_limited(self) -> bool:
            if limiter.allow(self.client_address[0]):
                return False
            self._send(429, {"error": "rate limited, slow down"})
            return True

        def do_POST(self):
            if self._rate_limited():
                return
            if self.path != "/shorten":
                return self._send(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                url = json.loads(self.rfile.read(length))["url"]
            except (ValueError, KeyError):
                return self._send(400, {"error": "body must be JSON with a 'url' key"})
            if not url.startswith(("http://", "https://")):
                return self._send(400, {"error": "url must start with http:// or https://"})
            code = store.insert(url)
            cache.put(code, url)  # write-through: new codes are likely hot
            self._send(201, {"code": code, "short_url": "/" + code})

        def do_GET(self):
            if self._rate_limited():
                return
            if self.path.startswith("/stats/"):
                info = store.stats(self.path[len("/stats/"):])
                return self._send(200, info) if info else self._send(404, {"error": "unknown code"})
            code = self.path.lstrip("/")
            url = cache.get(code)
            if url is None:
                url = store.lookup(code)
                if url is None:
                    return self._send(404, {"error": "unknown code"})
                cache.put(code, url)
            store.bump_hits(code)
            self._send(301, {"redirect": url}, headers={"Location": url})

    return Handler


def serve(port: int, db_path: str, quiet: bool = False):
    store = Store(db_path)
    cache = LRUCache(capacity=1024)
    limiter = TokenBucket(capacity=20, rate=10.0)
    # Port 0 lets the OS pick a free port — no conflicts, ever.
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, cache, limiter, quiet))
    server.daemon_threads = True
    return server, cache


def run_demo():
    say = print
    say("=" * 62)
    say(" URL SHORTENER — end-to-end demo")
    say("=" * 62)
    server, cache = serve(port=0, db_path=":memory:", quiet=True)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    say(f"\n[1] Server up on {base} (OS-assigned port, daemon thread)")

    # An opener that does NOT follow redirects, so we can see the raw 301.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)

    def post(path, payload):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    say("\n[2] Shortening 3 URLs via POST /shorten ...")
    codes = []
    for url in ("https://example.com/very/long/path?utm=stuff",
                "https://en.wikipedia.org/wiki/Base62",
                "https://news.ycombinator.com/"):
        result = post("/shorten", {"url": url})
        codes.append(result["code"])
        say(f"      {url[:48]:<50} -> {result['code']}")

    say(f"\n[3] GET /{codes[0]} (redirect, no auto-follow so we see the 301) ...")
    try:
        opener.open(base + "/" + codes[0])
    except urllib.error.HTTPError as e:
        say(f"      HTTP {e.code} -> Location: {e.headers['Location']}")
    try:
        opener.open(base + "/" + codes[0])
    except urllib.error.HTTPError:
        pass
    say(f"      second lookup served from LRU cache "
        f"(hits={cache.hits}, misses={cache.misses})")

    say("\n[4] Flooding 40 rapid requests to trip the token bucket ...")
    ok = limited = 0
    for _ in range(40):
        try:
            opener.open(base + "/" + codes[0])
            ok += 1
        except urllib.error.HTTPError as e:
            if e.code == 429:
                limited += 1
            else:
                ok += 1  # 301s raise too, since we refuse to follow them
    say(f"      {ok} passed, {limited} rejected with 429 (bucket: cap 20, refill 10/s)")

    say(f"\n[5] GET /stats/{codes[0]} — analytics survived the flood ...")
    time.sleep(0.15)  # let the bucket refill a token so stats isn't 429'd
    stats = {"error": "still rate limited"}
    for _ in range(20):
        try:
            with urllib.request.urlopen(base + "/stats/" + codes[0]) as resp:
                stats = json.loads(resp.read())
            break
        except urllib.error.HTTPError:
            time.sleep(0.15)
    say(f"      {json.dumps(stats)}")

    server.shutdown()
    server.server_close()
    say("\n[6] Server shut down cleanly. The moral: a shortener is just an")
    say("    ID generator + a codec + a cache + a rate limiter, holding hands.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="run the automated walkthrough and exit")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default="shortener.db")
    args = ap.parse_args()
    if args.demo:
        run_demo()
        return
    server, _ = serve(args.port, args.db)
    print(f"Serving on http://127.0.0.1:{server.server_address[1]} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
