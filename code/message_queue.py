"""Kafka-style message queue: partitioned log + consumer groups.

Teaches: a topic is just N append-only lists; a key hashes to one
partition, guaranteeing per-key ordering; consumers in one group split
partitions among themselves, while each GROUP keeps its own offsets.
Key insight: the broker never deletes on read — consumption is only a
per-group cursor moving forward, so many groups replay the same log.
"""

import hashlib


class Topic:
    def __init__(self, name: str, num_partitions: int):
        self.name = name
        self.partitions = [[] for _ in range(num_partitions)]

    def produce(self, key: str, value) -> tuple:
        # Same key -> same partition -> strict ordering for that key.
        p = int(hashlib.md5(key.encode()).hexdigest(), 16) % len(self.partitions)
        self.partitions[p].append((key, value))
        return p, len(self.partitions[p]) - 1  # (partition, offset)


class ConsumerGroup:
    def __init__(self, name: str, topic: Topic):
        self.name = name
        self.topic = topic
        self.members = []
        self.offsets = {p: 0 for p in range(len(topic.partitions))}
        self.assignment = {}

    def join(self, consumer_id: str):
        self.members.append(consumer_id)
        self._rebalance()

    def _rebalance(self):
        """Round-robin partitions across members (real Kafka does this too)."""
        self.assignment = {m: [] for m in self.members}
        for p in range(len(self.topic.partitions)):
            self.assignment[self.members[p % len(self.members)]].append(p)

    def poll(self, consumer_id: str, max_records: int = 10):
        """Fetch new records from this consumer's partitions, advance
        the GROUP's offsets."""
        records = []
        for p in self.assignment.get(consumer_id, []):
            partition = self.topic.partitions[p]
            while self.offsets[p] < len(partition) and len(records) < max_records:
                key, value = partition[self.offsets[p]]
                records.append((p, self.offsets[p], key, value))
                self.offsets[p] += 1
        return records


if __name__ == "__main__":
    topic = Topic("orders", num_partitions=3)
    print("=== Topic 'orders' with 3 partitions ===\n")

    events = [("alice", "cart"), ("bob", "cart"), ("alice", "pay"),
              ("carol", "cart"), ("bob", "pay"), ("carol", "pay"),
              ("alice", "ship"), ("dave", "cart")]
    print("Producing 8 events (key = customer):")
    for key, value in events:
        p, off = topic.produce(key, value)
        print(f"  {key}:{value:<5} -> partition {p}, offset {off}")

    print("\nPartition contents (note: each key stays in ONE partition):")
    for i, part in enumerate(topic.partitions):
        print(f"  P{i}: {[(k, v) for k, v in part]}")

    billing = ConsumerGroup("billing", topic)
    billing.join("billing-1")
    billing.join("billing-2")
    analytics = ConsumerGroup("analytics", topic)
    analytics.join("analytics-1")

    print("\nGroup 'billing' (2 consumers) partition assignment:")
    for member, parts in billing.assignment.items():
        print(f"  {member} owns partitions {parts}")
    print("Group 'analytics' (1 consumer) partition assignment:")
    for member, parts in analytics.assignment.items():
        print(f"  {member} owns partitions {parts}")

    print("\n--- billing-1 polls ---")
    for p, off, key, value in billing.poll("billing-1"):
        print(f"  P{p}@{off}: {key}:{value}")
    print("--- billing-2 polls ---")
    for p, off, key, value in billing.poll("billing-2"):
        print(f"  P{p}@{off}: {key}:{value}")
    print(f"billing group offsets now: {billing.offsets}")

    print("\n--- analytics-1 polls (independent cursor, sees EVERYTHING) ---")
    print(f"  got {len(analytics.poll('analytics-1'))} records; "
          f"offsets: {analytics.offsets}")

    p, off = topic.produce("alice", "refund")
    print(f"\nProduced alice:refund -> P{p}@{off}. Billing group polls again:")
    for member in billing.members:
        for p, off, key, value in billing.poll(member):
            print(f"  {member} got P{p}@{off}: {key}:{value}   "
                  "(only the new record — offsets remembered)")
