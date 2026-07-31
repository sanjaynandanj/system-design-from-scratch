"""Gossip (epidemic) protocol: how rumors and cluster state spread.

Teaches: if every informed node tells k random peers per round, the
number of informed nodes roughly multiplies by (1+k) each round, so
full propagation takes O(log N) rounds — with no coordinator at all.
Key insight: redundancy (nodes hearing the rumor twice) is the price
paid for robustness; the curve is logistic, not linear.
"""

import math
import random


class GossipCluster:
    def __init__(self, num_nodes: int, fanout: int, seed=None):
        self.num_nodes = num_nodes
        self.fanout = fanout
        self.rng = random.Random(seed)
        self.informed = set()

    def start_rumor(self, node: int):
        self.informed.add(node)

    def run_round(self):
        """Every informed node pushes the rumor to `fanout` random peers.

        Returns (newly_infected, wasted_messages).
        """
        new, wasted = set(), 0
        for node in self.informed:
            peers = self.rng.sample(
                [p for p in range(self.num_nodes) if p != node], self.fanout)
            for peer in peers:
                if peer in self.informed or peer in new:
                    wasted += 1  # peer already knew — redundant message
                else:
                    new.add(peer)
        self.informed |= new
        return len(new), wasted


def bar(count, total, width=40):
    filled = round(width * count / total)
    return "#" * filled + "." * (width - filled)


if __name__ == "__main__":
    N, FANOUT = 100, 3
    cluster = GossipCluster(N, FANOUT, seed=42)
    cluster.start_rumor(0)

    print(f"=== Gossip: {N} nodes, fanout={FANOUT}, rumor starts at node 0 ===\n")
    print("round  informed  new  wasted  spread")
    print(f"{0:>5}  {1:>8}  {'-':>3}  {'-':>6}  [{bar(1, N)}]")

    total_msgs = total_wasted = 0
    round_num = 0
    while len(cluster.informed) < N:
        round_num += 1
        sent = len(cluster.informed) * FANOUT
        new, wasted = cluster.run_round()
        total_msgs += sent
        total_wasted += wasted
        print(f"{round_num:>5}  {len(cluster.informed):>8}  {new:>3}  "
              f"{wasted:>6}  [{bar(len(cluster.informed), N)}]")

    print(f"\nAll {N} nodes informed in {round_num} rounds "
          f"(log_{1 + FANOUT}({N}) ~ "
          f"{math.log(N, 1 + FANOUT):.1f} rounds predicted).")
    print(f"Messages sent: {total_msgs}, redundant: {total_wasted} "
          f"({100 * total_wasted / total_msgs:.0f}%).")
    print("\nNote the S-curve: slow start, explosive middle, slow finish —")
    print("the last few uninformed nodes are hard to hit at random, and")
    print("redundant traffic dominates once most nodes already know.")
