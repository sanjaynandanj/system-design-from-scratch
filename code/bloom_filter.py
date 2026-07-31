"""Bloom filter: a probabilistic set with no false negatives.

Teaches: how m bits + k hash functions answer "definitely not present"
or "probably present" using a fraction of the memory of a real set.
Key insight: for n items and target false-positive rate p, the optimal
size is m = -n*ln(p)/ln(2)^2 bits and k = (m/n)*ln(2) hash functions.
"""

import hashlib
import math


class BloomFilter:
    def __init__(self, expected_items: int, fp_rate: float):
        n, p = expected_items, fp_rate
        self.m = max(1, math.ceil(-n * math.log(p) / (math.log(2) ** 2)))
        self.k = max(1, round((self.m / n) * math.log(2)))
        self.bits = bytearray((self.m + 7) // 8)
        self.count = 0

    def _positions(self, item: str):
        # k independent-ish hashes by salting md5/sha1 with the index.
        for i in range(self.k):
            digest = hashlib.md5(f"{i}:{item}".encode()).digest() if i % 2 == 0 \
                else hashlib.sha1(f"{i}:{item}".encode()).digest()
            yield int.from_bytes(digest[:8], "big") % self.m

    def add(self, item: str):
        for pos in self._positions(item):
            self.bits[pos // 8] |= 1 << (pos % 8)
        self.count += 1

    def __contains__(self, item: str) -> bool:
        return all(self.bits[p // 8] >> (p % 8) & 1 for p in self._positions(item))

    def theoretical_fp_rate(self) -> float:
        # Probability a bit is still 0 after n inserts: (1 - 1/m)^(kn)
        return (1 - math.exp(-self.k * self.count / self.m)) ** self.k


if __name__ == "__main__":
    n, target_p = 500, 0.02
    bf = BloomFilter(expected_items=n, fp_rate=target_p)

    print("=== Bloom filter sized for 500 items at 2% false positives ===")
    print(f"  m = {bf.m} bits ({len(bf.bits)} bytes), k = {bf.k} hash functions")
    print(f"  (a plain hash set of 500 words needs kilobytes; "
          f"we use {len(bf.bits)} bytes)\n")

    inserted = [f"word{i:04d}" for i in range(n)]
    for w in inserted:
        bf.add(w)

    ones = sum(bin(b).count("1") for b in bf.bits)
    print(f"After inserting {n} words: {ones}/{bf.m} bits set "
          f"({100 * ones / bf.m:.1f}% full)\n")

    print("Membership checks (items we DID insert — never a false negative):")
    for w in inserted[:3]:
        print(f"  '{w}' in filter -> {w in bf}")

    print("\nMembership checks (items we did NOT insert):")
    for w in ["hello", "world", "absent0001"]:
        print(f"  '{w}' in filter -> {w in bf}")

    # Measure the actual false-positive rate on 10,000 unseen items.
    trials = 10_000
    false_pos = sum(1 for i in range(trials) if f"unseen{i:05d}" in bf)
    print(f"\nFalse-positive measurement over {trials} unseen items:")
    print(f"  actual      = {false_pos / trials:.4f} ({false_pos} hits)")
    print(f"  theoretical = {bf.theoretical_fp_rate():.4f}")
    print(f"  target      = {target_p:.4f}")
    print("\nTakeaway: 'no' is always correct; 'yes' is right ~98% of the")
    print("time here — perfect for cheap pre-checks before hitting disk/DB.")
