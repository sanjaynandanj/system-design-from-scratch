"""Raft leader election and log replication, radically simplified.

Teaches: how a cluster picks exactly one leader per term (randomized
timeouts break ties), and why an entry is 'committed' only once a
majority of nodes store it.
Key insight: time is simulated in discrete ticks and messages are
plain function calls — the ALGORITHM, not the networking, is the point.
"""

import random

FOLLOWER, CANDIDATE, LEADER = "follower", "candidate", "leader"
rng = random.Random(7)


class Node:
    def __init__(self, node_id: int, cluster):
        self.id = node_id
        self.cluster = cluster
        self.state = FOLLOWER
        self.term = 0
        self.voted_for = None      # one vote per term — the core safety rule
        self.log = []              # list of (term, command)
        self.commit_index = 0
        self.alive = True
        self.reset_timeout()

    def reset_timeout(self):
        # Randomization is what prevents endless split votes.
        self.timeout = rng.randint(5, 10)

    def tick(self):
        if not self.alive or self.state == LEADER:
            return
        self.timeout -= 1
        if self.timeout <= 0:
            self.start_election()

    def start_election(self):
        self.state = CANDIDATE
        self.term += 1
        self.voted_for = self.id
        self.reset_timeout()
        votes = 1
        print(f"    node {self.id} times out -> candidate for term {self.term}")
        for peer in self.cluster.others(self.id):
            if peer.request_vote(self.term, self.id):
                votes += 1
        if votes > len(self.cluster.nodes) // 2:
            self.state = LEADER
            print(f"    node {self.id} wins with {votes}/"
                  f"{len(self.cluster.nodes)} votes -> LEADER (term {self.term})")
        else:
            print(f"    node {self.id} only got {votes} votes -> stays candidate")

    def request_vote(self, term, candidate_id) -> bool:
        if not self.alive or term < self.term:
            return False
        if term > self.term:
            self.term, self.voted_for, self.state = term, None, FOLLOWER
        if self.voted_for in (None, candidate_id):
            self.voted_for = candidate_id
            self.reset_timeout()
            return True
        return False

    def append_entries(self, term, entries) -> bool:
        """Heartbeat / replication RPC from the leader."""
        if not self.alive or term < self.term:
            return False
        self.term, self.state = term, FOLLOWER
        self.reset_timeout()
        self.log.extend(entries)
        return True


class Cluster:
    def __init__(self, size=5):
        self.nodes = [Node(i, self) for i in range(size)]

    def others(self, node_id):
        return [n for n in self.nodes if n.id != node_id]

    def leader(self):
        return next((n for n in self.nodes if n.alive and n.state == LEADER), None)

    def run_until_leader(self, label):
        print(f"  [{label}]")
        for t in range(1, 100):
            for node in self.nodes:
                node.tick()
            if self.leader():
                print(f"  leader elected after {t} ticks\n")
                return self.leader()
        raise RuntimeError("no leader elected")

    def replicate(self, command):
        leader = self.leader()
        entry = (leader.term, command)
        leader.log.append(entry)
        acks = 1  # leader stores it itself
        for peer in self.others(leader.id):
            acks += peer.append_entries(leader.term, [entry])
        majority = len(self.nodes) // 2 + 1
        if acks >= majority:
            leader.commit_index = len(leader.log)
            print(f"  '{command}': {acks}/{len(self.nodes)} acks >= "
                  f"majority({majority}) -> COMMITTED")
        else:
            print(f"  '{command}': only {acks} acks -> NOT committed")


if __name__ == "__main__":
    cluster = Cluster(5)
    print("=== Raft-lite: 5 nodes, randomized election timeouts ===\n")
    leader = cluster.run_until_leader("initial election")

    print(f"Killing leader (node {leader.id})...")
    leader.alive = False
    leader = cluster.run_until_leader("re-election after leader crash")
    print(f"New leader: node {leader.id}, term {leader.term} "
          "(term increased — stale ex-leaders can be detected)\n")

    print("Replicating 3 entries through the leader:")
    for cmd in ["set x=1", "set y=2", "set x=3"]:
        cluster.replicate(cmd)

    print("\nFinal logs (dead node 0 missed everything, as expected):")
    for node in cluster.nodes:
        status = "DEAD  " if not node.alive else f"{node.state:<6}"
        print(f"  node {node.id} [{status} term={node.term}] "
              f"log={[c for _, c in node.log]}")
    print("\nA 4/5 majority stored each entry, so all 3 are safely")
    print("committed even with one node down.")
