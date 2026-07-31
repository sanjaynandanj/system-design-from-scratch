"""Consistent hashing with virtual nodes.

Teaches: how to map keys to nodes so that adding/removing a node moves
only ~1/N of the keys, instead of nearly all of them (naive mod-N).
Key insight: place many virtual replicas of each node on a hash ring;
each key belongs to the first node clockwise from its hash position.
"""

import bisect
import hashlib


def _hash(value: str) -> int:
    """Map a string to a point on the ring (0 .. 2^128 - 1)."""
    return int(hashlib.md5(value.encode()).hexdigest(), 16)


class ConsistentHashRing:
    def __init__(self, nodes=None, vnodes=100):
        # More virtual nodes -> smoother key distribution per physical node.
        self.vnodes = vnodes
        self._ring = []          # sorted list of hash positions
        self._owner = {}         # hash position -> physical node name
        for node in nodes or []:
            self.add_node(node)

    def add_node(self, node: str):
        for i in range(self.vnodes):
            pos = _hash(f"{node}#vnode{i}")
            bisect.insort(self._ring, pos)
            self._owner[pos] = node

    def remove_node(self, node: str):
        for i in range(self.vnodes):
            pos = _hash(f"{node}#vnode{i}")
            self._ring.remove(pos)
            del self._owner[pos]

    def get_node(self, key: str) -> str:
        if not self._ring:
            raise RuntimeError("ring is empty")
        pos = _hash(key)
        # First vnode clockwise from the key; wrap around past the end.
        idx = bisect.bisect_right(self._ring, pos) % len(self._ring)
        return self._owner[self._ring[idx]]


def distribution(assignment):
    counts = {}
    for node in assignment.values():
        counts[node] = counts.get(node, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    keys = [f"user:{i}" for i in range(1000)]
    nodes = ["node-A", "node-B", "node-C", "node-D"]

    print("=== Consistent hashing: 1000 keys over 4 nodes ===")
    ring = ConsistentHashRing(nodes, vnodes=100)
    before = {k: ring.get_node(k) for k in keys}
    for node, count in distribution(before).items():
        print(f"  {node}: {count} keys")

    print("\n--- Adding node-E ---")
    ring.add_node("node-E")
    after = {k: ring.get_node(k) for k in keys}
    for node, count in distribution(after).items():
        print(f"  {node}: {count} keys")

    moved_ring = sum(1 for k in keys if before[k] != after[k])
    print(f"\nKeys that moved on the ring: {moved_ring} / 1000 "
          f"({moved_ring / 10:.1f}%)")
    print("Expected ~1/5 = 20% (only keys claimed by the new node move).")

    # Compare with naive mod-N: bucket = hash(key) % num_nodes
    naive_before = {k: nodes[_hash(k) % 4] for k in keys}
    nodes5 = nodes + ["node-E"]
    naive_after = {k: nodes5[_hash(k) % 5] for k in keys}
    moved_naive = sum(1 for k in keys if naive_before[k] != naive_after[k])
    print(f"\nNaive mod-N: {moved_naive} / 1000 keys moved "
          f"({moved_naive / 10:.1f}%) when going from mod 4 to mod 5.")
    print("Nearly every key changes owner -> a cache/shard reshuffle storm.")
