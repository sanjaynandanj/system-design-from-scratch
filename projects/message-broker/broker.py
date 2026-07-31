"""Mini-Kafka: a persistent message broker in one file.

Teaches: topics split into key-hashed partitions, an append-only commit
log on real disk, consumer groups with committed offsets, round-robin
rebalancing, and why "at-least-once" means duplicates after a crash.

Run: python broker.py --demo
"""

import argparse
import hashlib
import json
import os
import shutil
import tempfile


class Partition:
    """An append-only commit log: one JSON-lines file, offsets = line numbers."""

    def __init__(self, path):
        self.path = path
        self.next_offset = 0
        open(path, "w", encoding="utf-8").close()

    def append(self, key, value):
        offset = self.next_offset
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"offset": offset, "key": key, "value": value}) + "\n")
        self.next_offset += 1
        return offset

    def read_from(self, offset):
        """Sequential scan — fine for a demo; real brokers keep sparse indexes."""
        with open(self.path, "r", encoding="utf-8") as f:
            return [rec for rec in map(json.loads, f) if rec["offset"] >= offset]


class Topic:
    def __init__(self, name, num_partitions, log_dir):
        self.name = name
        self.partitions = [
            Partition(os.path.join(log_dir, f"{name}-{i}.log"))
            for i in range(num_partitions)
        ]

    def route(self, key):
        # Same key -> same partition -> per-key ordering is preserved.
        return int(hashlib.md5(key.encode()).hexdigest(), 16) % len(self.partitions)


class ConsumerGroup:
    """Tracks who is in the group, who owns which partition, and offsets.

    The committed offset is 'the next offset this group still needs',
    stored broker-side so it survives any single consumer dying.
    """

    def __init__(self, topic):
        self.topic = topic
        self.members = []
        self.assignment = {}   # consumer -> [partition ids]
        self.offsets = {}      # partition id -> committed offset

    def rebalance(self):
        self.assignment = {m: [] for m in self.members}
        for pid in range(len(self.topic.partitions)):
            owner = self.members[pid % len(self.members)]
            self.assignment[owner].append(pid)
        return self.assignment


class Broker:
    def __init__(self):
        self.log_dir = tempfile.mkdtemp(prefix="mini-broker-")
        self.topics = {}
        self.groups = {}

    def create_topic(self, name, num_partitions):
        self.topics[name] = Topic(name, num_partitions, self.log_dir)

    def produce(self, topic_name, key, value):
        topic = self.topics[topic_name]
        pid = topic.route(key)
        offset = topic.partitions[pid].append(key, value)
        return pid, offset

    def join_group(self, group_name, topic_name, consumer):
        group = self.groups.setdefault(group_name, ConsumerGroup(self.topics[topic_name]))
        group.members.append(consumer)
        return group.rebalance()

    def crash_consumer(self, group_name, consumer):
        """Simulate a consumer dying mid-batch: it leaves WITHOUT committing."""
        group = self.groups[group_name]
        group.members.remove(consumer)
        return group.rebalance()

    def poll(self, group_name, consumer):
        """Fetch unread records from every partition this consumer owns."""
        group = self.groups[group_name]
        batch = []
        for pid in group.assignment.get(consumer, []):
            start = group.offsets.get(pid, 0)
            batch.extend((pid, rec) for rec in group.topic.partitions[pid].read_from(start))
        return batch

    def commit(self, group_name, pid, next_offset):
        # Committing AFTER processing is what makes delivery at-least-once:
        # crash between process and commit -> the batch is delivered again.
        self.groups[group_name].offsets[pid] = next_offset

    def close(self):
        shutil.rmtree(self.log_dir, ignore_errors=True)


# --------------------------- demo ---------------------------

def banner(title):
    print(f"\n=== {title} " + "=" * max(0, 58 - len(title)))


def show_assignment(assignment):
    for consumer, pids in sorted(assignment.items()):
        print(f"  {consumer} owns partition(s) {pids}")


def demo():
    broker = Broker()
    try:
        banner("1. Topic 'orders' with 3 partitions (real files on disk)")
        broker.create_topic("orders", num_partitions=3)
        print(f"Commit logs live in: {broker.log_dir}")

        banner("2. Produce: same key always lands on the same partition")
        # Pick 3 customer keys that happen to cover all 3 partitions, so
        # every partition has traffic and the crash story has stakes.
        topic = broker.topics["orders"]
        by_pid = {}
        for i in range(50):
            by_pid.setdefault(topic.route(f"cust-{i}"), f"cust-{i}")
            if len(by_pid) == 3:
                break
        keys = [by_pid[pid] for pid in sorted(by_pid)]
        events = [(keys[i % 3], f"order #{100 + i}") for i in range(9)]
        for key, value in events:
            pid, offset = broker.produce("orders", key, value)
            print(f"  {key} -> partition {pid} @ offset {offset}   ({value})")

        banner("3. The commit log is just an append-only file")
        sample = broker.topics["orders"].partitions[0]
        with open(sample.path, "r", encoding="utf-8") as f:
            for line in list(f)[:2]:
                print(f"  {os.path.basename(sample.path)}: {line.strip()}")

        banner("4. Consumer group 'billing': join + round-robin rebalance")
        broker.join_group("billing", "orders", "worker-1")
        assignment = broker.join_group("billing", "orders", "worker-2")
        show_assignment(assignment)

        banner("5. worker-1 processes its partitions and commits offsets")
        done = set()
        for pid, rec in broker.poll("billing", "worker-1"):
            print(f"  worker-1 processed p{pid}@{rec['offset']}: {rec['value']}")
            done.add(rec["value"])
            broker.commit("billing", pid, rec["offset"] + 1)

        banner("6. worker-2 processes... then CRASHES before committing")
        crashed_batch = broker.poll("billing", "worker-2")
        for pid, rec in crashed_batch:
            print(f"  worker-2 processed p{pid}@{rec['offset']}: {rec['value']}  (uncommitted!)")
        print("  worker-2 died. Its offsets were never committed.")
        assignment = broker.crash_consumer("billing", "worker-2")
        print("Rebalance after crash:")
        show_assignment(assignment)

        banner("7. At-least-once: worker-1 redelivers the crashed batch")
        redelivered = broker.poll("billing", "worker-1")
        for pid, rec in redelivered:
            tag = "REDELIVERED" if rec["value"] not in done else "duplicate?!"
            print(f"  worker-1 got p{pid}@{rec['offset']}: {rec['value']}  [{tag}]")
            broker.commit("billing", pid, rec["offset"] + 1)
        assert {rec["value"] for _, rec in redelivered} == \
               {rec["value"] for _, rec in crashed_batch}
        assert not broker.poll("billing", "worker-1"), "everything should be committed"
        print("\nCrashed batch fully redelivered, nothing lost, nothing left over.")
        print("(Deduplication is the CONSUMER's job — that's at-least-once.)")
    finally:
        broker.close()
        print(f"Cleaned up {broker.log_dir}. Demo complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="run the walkthrough")
    args = parser.parse_args()
    if args.demo:
        demo()
    else:
        parser.print_help()
