"""Mini-CDN: origin, shield, and edge caches in one file.

Teaches: LRU+TTL edge caching, consistent-hash routing of clients to
edges, origin shielding (many edge misses collapse into one origin
fetch), and purge broadcasts for instant invalidation.

Run: python cdn.py --demo
"""

import argparse
import bisect
import hashlib
from collections import OrderedDict

TTL_SECONDS = 60
EDGE_CAPACITY = 8


class Clock:
    """Fake time so TTL expiry is instant and the demo is deterministic."""

    def __init__(self):
        self.now = 0

    def advance(self, seconds):
        self.now += seconds


class Origin:
    """The one true copy of every asset. Every fetch here is the slow path."""

    def __init__(self, assets):
        self.assets = dict(assets)
        self.fetches = 0

    def fetch(self, path):
        self.fetches += 1
        return self.assets[path]

    def publish(self, path, body):
        self.assets[path] = body


class LruTtlCache:
    """Bounded cache: TTL bounds staleness, LRU bounds memory."""

    def __init__(self, capacity, clock):
        self.capacity = capacity
        self.clock = clock
        self._items = OrderedDict()  # path -> (body, expires_at)

    def get(self, path):
        entry = self._items.get(path)
        if entry is None:
            return None
        body, expires_at = entry
        if self.clock.now >= expires_at:
            del self._items[path]    # expired: pretend it was never here
            return None
        self._items.move_to_end(path)
        return body

    def put(self, path, body):
        self._items[path] = (body, self.clock.now + TTL_SECONDS)
        self._items.move_to_end(path)
        if len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def purge(self, path):
        return self._items.pop(path, None) is not None


class CacheNode:
    """An edge or shield node: check local cache, else ask upstream."""

    def __init__(self, name, upstream, clock, capacity=EDGE_CAPACITY):
        self.name = name
        self.upstream = upstream   # another CacheNode, or the Origin
        self.cache = LruTtlCache(capacity, clock)
        self.hits = 0
        self.misses = 0

    def request(self, path):
        body = self.cache.get(path)
        if body is not None:
            self.hits += 1
            return body
        self.misses += 1
        if isinstance(self.upstream, Origin):
            body = self.upstream.fetch(path)
        else:
            body = self.upstream.request(path)
        self.cache.put(path, body)
        return body

    def hit_ratio(self):
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class CDN:
    """Routes each client to a stable edge via a consistent-hash ring."""

    def __init__(self, origin, edge_names, clock):
        self.clock = clock
        self.origin = origin
        # One shield PoP in front of the origin: edges miss to the shield,
        # the shield misses to the origin. 3 edge misses -> 1 origin fetch.
        self.shield = CacheNode("shield", origin, clock, capacity=32)
        self.edges = {n: CacheNode(n, self.shield, clock) for n in edge_names}
        self._ring = []
        self._owner = {}
        for name in edge_names:
            for i in range(64):
                pos = int(hashlib.md5(f"{name}#v{i}".encode()).hexdigest(), 16)
                bisect.insort(self._ring, pos)
                self._owner[pos] = name

    def edge_for(self, client):
        pos = int(hashlib.md5(client.encode()).hexdigest(), 16)
        idx = bisect.bisect_right(self._ring, pos) % len(self._ring)
        return self.edges[self._owner[self._ring[idx]]]

    def request(self, client, path):
        return self.edge_for(client).request(path)

    def purge(self, path):
        """Invalidation broadcast: every cache in the fleet drops the path."""
        return [n.name for n in [*self.edges.values(), self.shield]
                if n.cache.purge(path)]

    def all_nodes(self):
        return [*self.edges.values(), self.shield]


# --------------------------- demo ---------------------------

def banner(title):
    print(f"\n=== {title} " + "=" * max(0, 58 - len(title)))


def stats_table(cdn, snapshot):
    print(f"  {'node':8} {'hits':>5} {'misses':>7} {'hit ratio':>10}")
    for node in cdn.all_nodes():
        h0, m0 = snapshot.get(node.name, (0, 0))
        h, m = node.hits - h0, node.misses - m0
        ratio = h / (h + m) if h + m else 0.0
        print(f"  {node.name:8} {h:>5} {m:>7} {ratio:>9.0%}")


def snapshot(cdn):
    return {n.name: (n.hits, n.misses) for n in cdn.all_nodes()}


def demo():
    clock = Clock()
    origin = Origin({
        "/index.html": "<html>home</html>",
        "/app.js": "console.log('v1')",
        "/logo.png": "PNG-v1",
        "/style.css": "body{}",
    })
    cdn = CDN(origin, ["edge-1", "edge-2", "edge-3"], clock)
    clients = [f"client-{i}" for i in range(9)]

    banner("1. Routing: consistent hashing pins each client to an edge")
    for client in clients:
        print(f"  {client} -> {cdn.edge_for(client).name}")

    # Same workload every round: each client hits the popular assets.
    workload = [(c, p) for c in clients for p in ("/index.html", "/app.js", "/logo.png")]

    banner("2. Round 1: cold caches — everything is a miss")
    snap = snapshot(cdn)
    for client, path in workload:
        cdn.request(client, path)
    stats_table(cdn, snap)
    print(f"  origin fetches so far: {origin.fetches} "
          f"(shield collapsed {sum(e.misses for e in cdn.edges.values())} edge "
          f"misses into {origin.fetches} — that's origin shielding)")

    banner("3. Rounds 2-3: warm caches — hit ratio climbs")
    for round_no in (2, 3):
        snap = snapshot(cdn)
        for client, path in workload:
            cdn.request(client, path)
        print(f"Round {round_no}:")
        stats_table(cdn, snap)
    print(f"  origin fetches still: {origin.fetches} (the edges absorbed everything)")

    banner("4. TTL expiry: advance the clock past 60s")
    clock.advance(TTL_SECONDS + 1)
    snap = snapshot(cdn)
    for client, path in workload:
        cdn.request(client, path)
    print("Everything expired at once, so this round is cold again:")
    stats_table(cdn, snap)
    print(f"  origin fetches now: {origin.fetches} (refreshed once per asset, via shield)")

    banner("5. Purge: deploy logo v2 and broadcast invalidation")
    origin.publish("/logo.png", "PNG-v2")
    dropped = cdn.purge("/logo.png")
    print(f"  purge('/logo.png') dropped cached copies on: {', '.join(dropped)}")
    body = cdn.request("client-0", "/logo.png")
    print(f"  client-0 GET /logo.png -> {body!r}  (miss -> shield -> origin -> fresh)")
    body = cdn.request("client-0", "/index.html")
    print(f"  client-0 GET /index.html -> {body!r}  (still a hit; purge was surgical)")
    assert cdn.request("client-5", "/logo.png") == "PNG-v2"

    banner("6. Final tally")
    stats_table(cdn, {})
    total_requests = sum(e.hits + e.misses for e in cdn.edges.values())
    print(f"\n{total_requests} client requests, only {origin.fetches} origin fetches.")
    print("That gap is the entire business model of a CDN. Demo complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="run the walkthrough")
    args = parser.parse_args()
    if args.demo:
        demo()
    else:
        parser.print_help()
