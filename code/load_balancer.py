"""Four load-balancing strategies over simulated backends.

Teaches: round-robin is fair but blind; weights encode capacity;
least-connections adapts to slow servers; consistent hashing gives
sticky sessions (same client -> same backend, even as backends change).
Key insight: 'balanced' means different things — equal counts, equal
load, or stable mapping — and each strategy optimizes a different one.
"""

import hashlib
from collections import Counter


class Backend:
    def __init__(self, name: str, weight: int = 1, speed: int = 1):
        self.name = name
        self.weight = weight
        self.speed = speed        # requests finished per tick (simulated)
        self.active = 0           # currently open connections

    def __repr__(self):
        return self.name


class RoundRobin:
    def __init__(self, backends):
        self.backends = backends
        self.i = 0

    def pick(self, request):
        backend = self.backends[self.i % len(self.backends)]
        self.i += 1
        return backend


class WeightedRoundRobin:
    """Smooth WRR (nginx algorithm): avoids sending all of a heavy
    backend's share consecutively."""

    def __init__(self, backends):
        self.backends = backends
        self.current = {b.name: 0 for b in backends}

    def pick(self, request):
        total = sum(b.weight for b in self.backends)
        for b in self.backends:
            self.current[b.name] += b.weight
        best = max(self.backends, key=lambda b: self.current[b.name])
        self.current[best.name] -= total
        return best


class LeastConnections:
    def pick_from(self, backends):
        return min(backends, key=lambda b: b.active)

    def __init__(self, backends):
        self.backends = backends

    def pick(self, request):
        return self.pick_from(self.backends)


class ConsistentHashLB:
    """Hash the client id onto a ring of virtual nodes — sticky routing."""

    def __init__(self, backends, vnodes=50):
        self.ring = sorted(
            (int(hashlib.md5(f"{b.name}#{i}".encode()).hexdigest(), 16), b)
            for b in backends for i in range(vnodes))

    def pick(self, request):
        h = int(hashlib.md5(request["client"].encode()).hexdigest(), 16)
        for pos, backend in self.ring:
            if pos >= h:
                return backend
        return self.ring[0][1]  # wrap around


def run(name, lb, backends, requests, note):
    counts = Counter()
    in_flight = []  # (finish_tick, backend) — only used by LeastConnections
    for tick, req in enumerate(requests):
        # Release connections that finished before this request arrives.
        for finish, backend in in_flight[:]:
            if finish <= tick:
                backend.active -= 1
                in_flight.remove((finish, backend))
        backend = lb.pick(req)
        counts[backend.name] += 1
        if isinstance(lb, LeastConnections):
            backend.active += 1
            # Fast backends finish requests sooner, so they free up first.
            in_flight.append((tick + 6 // backend.speed, backend))
    dist = "  ".join(f"{n}:{counts[n]:>2}" for n in sorted(counts))
    print(f"{name:<22} {dist}")
    print(f"{'':<22} ^ {note}\n")


if __name__ == "__main__":
    requests = [{"id": i, "client": f"client-{i % 5}"} for i in range(20)]
    print("=== 20 requests (from 5 clients) through each strategy ===\n")

    b = lambda: [Backend("s1", weight=5, speed=3),
                 Backend("s2", weight=3, speed=2),
                 Backend("s3", weight=1, speed=1)]

    run("RoundRobin", RoundRobin(b()), None, requests,
        "even split, ignores capacity")
    run("WeightedRoundRobin", WeightedRoundRobin(b()), None, requests,
        "split ~5:3:1 to match backend weights")
    backends = b()
    run("LeastConnections", LeastConnections(backends), backends, requests,
        "fast servers (higher drain speed) absorb more load")
    run("ConsistentHashLB", ConsistentHashLB(b()), None, requests,
        "each client always lands on the same backend (sticky)")

    print("Sticky check: client-0's 4 requests all hit one backend; the")
    print("distribution is lumpy because there are only 5 distinct clients.")
