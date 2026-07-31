"""Three classic rate-limiting algorithms: token bucket, leaky bucket,
and sliding-window log.

Teaches: the trade-offs — token bucket allows bursts up to capacity,
leaky bucket smooths output to a fixed drain rate, and a sliding-window
log is exact but stores one timestamp per request.
All three take an injectable clock so the demo can simulate time.
"""

from collections import deque


class TokenBucket:
    """Tokens refill at `rate` per second; a request spends one token.

    Bursts are OK as long as tokens are available.
    """

    def __init__(self, capacity: int, rate: float):
        self.capacity = capacity
        self.rate = rate
        self.tokens = float(capacity)
        self.last = 0.0

    def allow(self, now: float) -> bool:
        # Lazy refill: add tokens for the time elapsed since last check.
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class LeakyBucket:
    """Requests queue in a bucket that leaks at `rate` per second.

    A request is rejected if the bucket (queue) is full — output is
    perfectly smooth regardless of input burstiness.
    """

    def __init__(self, capacity: int, rate: float):
        self.capacity = capacity
        self.rate = rate
        self.water = 0.0
        self.last = 0.0

    def allow(self, now: float) -> bool:
        self.water = max(0.0, self.water - (now - self.last) * self.rate)
        self.last = now
        if self.water + 1 <= self.capacity:
            self.water += 1
            return True
        return False


class SlidingWindowLog:
    """Keep timestamps of accepted requests; allow if fewer than
    `limit` fall inside the trailing `window` seconds. Exact, but
    memory grows with the request rate.
    """

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self.log = deque()

    def allow(self, now: float) -> bool:
        while self.log and self.log[0] <= now - self.window:
            self.log.popleft()
        if len(self.log) < self.limit:
            self.log.append(now)
            return True
        return False


def simulate(name, limiter, arrivals):
    print(f"--- {name} ---")
    allowed = 0
    for i, t in enumerate(arrivals):
        ok = limiter.allow(t)
        allowed += ok
        verdict = "ALLOW" if ok else "deny "
        print(f"  t={t:5.2f}s  req#{i + 1:02d}  {verdict}")
    print(f"  => {allowed}/{len(arrivals)} allowed\n")


if __name__ == "__main__":
    # Traffic pattern: a 10-request burst at t=0..0.09s, then one
    # request every 0.5s. Limiters are all tuned to ~5 req/s steady.
    burst = [i * 0.01 for i in range(10)]
    steady = [1.0 + i * 0.5 for i in range(6)]
    arrivals = burst + steady

    print("=== Same traffic (10-req burst, then 2 req/s) vs 3 limiters ===\n")

    simulate("TokenBucket(capacity=5, rate=5/s) — absorbs a 5-deep burst",
             TokenBucket(capacity=5, rate=5.0), arrivals)

    simulate("LeakyBucket(capacity=3, rate=5/s) — small queue, smooth drain",
             LeakyBucket(capacity=3, rate=5.0), arrivals)

    simulate("SlidingWindowLog(limit=5, window=1s) — exact count per window",
             SlidingWindowLog(limit=5, window=1.0), arrivals)

    print("Takeaway: token bucket tolerates bursts up to its capacity,")
    print("leaky bucket caps queued work, sliding log enforces an exact")
    print("'N per window' rule at the cost of storing timestamps.")
