"""Mini-Dynamo: a distributed key-value store in one file.

Teaches: consistent-hash placement, replication (N=2), sloppy quorum
writes (W=2) with hinted handoff, quorum reads (R=1), and recovery
when a dead node rejoins the cluster.

Run: python kv_store.py --demo
"""

import argparse
import bisect
import hashlib

N_REPLICAS = 2   # each key lives on 2 distinct physical nodes
W_QUORUM = 2     # a write must land on 2 nodes (real replica or hint holder)
R_QUORUM = 1     # a read succeeds after 1 replica answers


def _hash(value: str) -> int:
    return int(hashlib.md5(value.encode()).hexdigest(), 16)


class ConsistentHashRing:
    """Maps keys to an ordered walk of physical nodes (the preference list)."""

    def __init__(self, node_names, vnodes=64):
        self._ring = []       # sorted vnode positions
        self._owner = {}      # position -> physical node name
        for name in node_names:
            for i in range(vnodes):
                pos = _hash(f"{name}#vnode{i}")
                bisect.insort(self._ring, pos)
                self._owner[pos] = name

    def walk(self, key: str):
        """Yield distinct physical nodes clockwise from the key's position."""
        start = bisect.bisect_right(self._ring, _hash(key))
        seen = set()
        for i in range(len(self._ring)):
            node = self._owner[self._ring[(start + i) % len(self._ring)]]
            if node not in seen:
                seen.add(node)
                yield node


class StorageNode:
    """One storage server: a local dict plus a mailbox of hints for others."""

    def __init__(self, name):
        self.name = name
        self.alive = True
        self.data = {}    # key -> (version, value)
        self.hints = {}   # intended_node -> {key: (version, value)}

    def store(self, key, version, value):
        # Last-write-wins: only overwrite if the incoming version is newer.
        current = self.data.get(key)
        if current is None or version > current[0]:
            self.data[key] = (version, value)

    def store_hint(self, intended_node, key, version, value):
        self.hints.setdefault(intended_node, {})[key] = (version, value)


class Cluster:
    """The coordinator: routes client requests to the right storage nodes."""

    def __init__(self, node_names, vnodes=64):
        self.ring = ConsistentHashRing(node_names, vnodes)
        self.nodes = {name: StorageNode(name) for name in node_names}
        self._version = 0  # monotonic write version (a toy Lamport clock)

    def preference_list(self, key):
        """The first N_REPLICAS distinct nodes clockwise from the key."""
        walk = self.ring.walk(key)
        return [next(walk) for _ in range(N_REPLICAS)]

    def put(self, key, value, verbose=True):
        self._version += 1
        version = self._version
        preferred = self.preference_list(key)
        acked = []
        # Sloppy quorum: if a preferred replica is dead, keep walking the
        # ring and park a *hint* on the next healthy node instead.
        fallback = (n for n in self.ring.walk(key) if n not in preferred)
        for target in preferred:
            node = self.nodes[target]
            if node.alive:
                node.store(key, version, value)
                acked.append(target)
            else:
                helper = next(n for n in fallback if self.nodes[n].alive)
                self.nodes[helper].store_hint(target, key, version, value)
                acked.append(f"{helper}(hint for {target})")
        if len(acked) < W_QUORUM:
            raise RuntimeError(f"write quorum failed for {key!r}")
        if verbose:
            print(f"  PUT {key!r:14} = {value!r:22} -> {', '.join(acked)}")
        return acked

    def get(self, key):
        answers = []
        for target in self.preference_list(key):
            node = self.nodes[target]
            if node.alive and key in node.data:
                answers.append((target, node.data[key]))
                if len(answers) >= R_QUORUM:
                    break
        if not answers:
            raise KeyError(key)
        served_by, (version, value) = answers[0]
        return value, served_by

    def kill(self, name):
        self.nodes[name].alive = False

    def revive(self, name):
        """Node rejoins: every peer delivers the hints it held for it."""
        self.nodes[name].alive = True
        delivered = 0
        for peer in self.nodes.values():
            for key, (version, value) in peer.hints.pop(name, {}).items():
                self.nodes[name].store(key, version, value)
                delivered += 1
        return delivered


# --------------------------- demo ---------------------------

def banner(title):
    print(f"\n=== {title} " + "=" * max(0, 58 - len(title)))


def demo():
    names = ["node-A", "node-B", "node-C", "node-D"]
    cluster = Cluster(names)

    banner("1. Placement: consistent hashing picks 2 replicas per key")
    print(f"Cluster: {', '.join(names)}   N={N_REPLICAS} W={W_QUORUM} R={R_QUORUM}")
    fixtures = {
        "user:alice": "alice@example.com",
        "user:bob": "bob@example.com",
        "cart:alice": "3 items",
        "cart:bob": "1 item",
        "session:9f2": "logged-in",
        "feature:dark": "enabled",
    }
    for key, value in fixtures.items():
        cluster.put(key, value)

    banner("2. Failure: kill a replica, reads still succeed (R=1)")
    victim = cluster.preference_list("user:alice")[0]
    print(f"Killing {victim} (primary replica for 'user:alice')...")
    cluster.kill(victim)
    value, served_by = cluster.get("user:alice")
    print(f"  GET 'user:alice' = {value!r}  (served by surviving replica {served_by})")

    banner("3. Sloppy quorum: writes during the outage use hinted handoff")
    print(f"{victim} is still down; writing keys it should own...")
    for key, value in fixtures.items():
        cluster.put(key, value + " (v2)", verbose=victim in cluster.preference_list(key))
    parked = sum(len(node.hints.get(victim, {})) for node in cluster.nodes.values())
    print(f"  -> {parked} hint(s) parked on healthy nodes, addressed to {victim}")

    banner("4. Recovery: node rejoins, peers deliver its hints")
    delivered = cluster.revive(victim)
    print(f"{victim} is back. Peers delivered {delivered} hinted write(s) to it.")
    for key in fixtures:
        if victim in cluster.preference_list(key):
            stored = cluster.nodes[victim].data.get(key)
            print(f"  {victim} now holds {key!r} = {stored[1]!r}")

    banner("5. Sanity check: every key readable, every value is the newest")
    for key, expected in fixtures.items():
        value, served_by = cluster.get(key)
        assert value == expected + " (v2)", (key, value)
        print(f"  GET {key!r:14} = {value!r:28} via {served_by}")
    print("\nAll reads returned the latest version. Demo complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="run the walkthrough")
    args = parser.parse_args()
    if args.demo:
        demo()
    else:
        parser.print_help()
