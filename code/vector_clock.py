"""Vector clocks: tracking causality in a distributed system.

Teaches: physical timestamps can't order events across machines, but a
vector of per-node counters can — event A happens-before B iff A's
vector is <= B's in every slot (and < in at least one).
Key insight: when neither vector dominates, the events are CONCURRENT,
which is exactly how systems like Dynamo detect write conflicts.
"""


class VectorClock:
    def __init__(self, node_id: str, clock=None):
        self.node_id = node_id
        self.clock = dict(clock or {})

    def increment(self):
        """Tick the local counter — called on every local event or send."""
        self.clock[self.node_id] = self.clock.get(self.node_id, 0) + 1
        return self

    def merge(self, other: "VectorClock"):
        """On receive: take the element-wise max, then tick locally."""
        for node, count in other.clock.items():
            self.clock[node] = max(self.clock.get(node, 0), count)
        return self.increment()

    def snapshot(self) -> "VectorClock":
        return VectorClock(self.node_id, self.clock)

    def compare(self, other: "VectorClock") -> str:
        """Return 'before', 'after', 'equal', or 'concurrent'."""
        nodes = set(self.clock) | set(other.clock)
        less = any(self.clock.get(n, 0) < other.clock.get(n, 0) for n in nodes)
        more = any(self.clock.get(n, 0) > other.clock.get(n, 0) for n in nodes)
        if less and more:
            return "concurrent"
        if less:
            return "before"
        if more:
            return "after"
        return "equal"

    def __repr__(self):
        inner = ", ".join(f"{n}:{c}" for n, c in sorted(self.clock.items()))
        return "{" + inner + "}"


if __name__ == "__main__":
    print("=== Three nodes exchanging messages ===\n")
    A, B, C = VectorClock("A"), VectorClock("B"), VectorClock("C")
    events = {}

    A.increment()
    events["a1"] = A.snapshot()
    print(f"a1: A does local work           A = {A}")

    A.increment()  # sending is an event; the message carries A's clock
    msg_a = A.snapshot()
    print(f"a2: A sends message to B        A = {A}")

    C.increment()
    events["c1"] = C.snapshot()
    print(f"c1: C does local work           C = {C}   (independent of A!)")

    B.merge(msg_a)
    events["b1"] = B.snapshot()
    print(f"b1: B receives A's message      B = {B}")

    B.increment()
    msg_b = B.snapshot()
    print(f"b2: B sends message to C        B = {B}")

    C.merge(msg_b)
    events["c2"] = C.snapshot()
    print(f"c2: C receives B's message      C = {C}\n")

    print("=== Causality queries ===")
    pairs = [("a1", "b1"), ("a1", "c2"), ("c1", "a1"), ("c1", "b1"), ("b1", "c2")]
    for x, y in pairs:
        rel = events[x].compare(events[y])
        print(f"  {x} {events[x]!r:22} vs {y} {events[y]!r:22} -> {rel}")

    print("\nNote: c1 is CONCURRENT with a1 and b1 — no message path links")
    print("them, so no ordering exists. If these were two writes to the")
    print("same key, the store must keep both siblings or ask the client.")
