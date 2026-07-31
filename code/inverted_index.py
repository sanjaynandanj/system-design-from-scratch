"""Inverted index + BM25 ranking — the core of every search engine.

Teaches: instead of scanning documents for a word, map each word to the
documents containing it; then rank matches with BM25.
Key insight: BM25 = TF (saturating, so 100 repeats isn't 100x better)
x IDF (rare words matter more), normalized by document length.
"""

import math
import re
from collections import Counter, defaultdict

K1 = 1.5  # TF saturation: higher = term frequency matters more
B = 0.75  # length normalization: 1 = full penalty for long docs


def tokenize(text: str):
    return re.findall(r"[a-z0-9]+", text.lower())


class InvertedIndex:
    def __init__(self):
        self.postings = defaultdict(dict)  # term -> {doc_id: term_freq}
        self.doc_len = {}
        self.docs = {}

    def add(self, doc_id: str, text: str):
        tokens = tokenize(text)
        self.docs[doc_id] = text
        self.doc_len[doc_id] = len(tokens)
        for term, freq in Counter(tokens).items():
            self.postings[term][doc_id] = freq

    def _idf(self, term: str) -> float:
        n, df = len(self.docs), len(self.postings.get(term, {}))
        # BM25's IDF; the +0.5s keep it finite and positive-ish.
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, top_k: int = 5):
        avg_len = sum(self.doc_len.values()) / len(self.doc_len)
        scores = defaultdict(float)
        for term in tokenize(query):
            idf = self._idf(term)
            for doc_id, tf in self.postings.get(term, {}).items():
                norm = 1 - B + B * self.doc_len[doc_id] / avg_len
                scores[doc_id] += idf * (tf * (K1 + 1)) / (tf + K1 * norm)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        return ranked[:top_k]


DOCS = {
    "d01": "Consistent hashing spreads cache keys across nodes evenly",
    "d02": "A cache stores hot data in memory for fast reads",
    "d03": "Raft elects a leader and replicates a log to followers",
    "d04": "The leader sends heartbeats so followers do not start elections",
    "d05": "Kafka partitions a log by key for ordered message delivery",
    "d06": "A bloom filter answers set membership with false positives",
    "d07": "LSM trees buffer writes in memory then flush sorted files to disk",
    "d08": "Load balancers route requests to healthy backend nodes",
    "d09": "Vector clocks detect concurrent writes in distributed stores",
    "d10": "Gossip protocols spread cluster membership info between nodes",
}

if __name__ == "__main__":
    index = InvertedIndex()
    for doc_id, text in DOCS.items():
        index.add(doc_id, text)

    print(f"=== Indexed {len(DOCS)} mini-documents, "
          f"{len(index.postings)} unique terms ===\n")

    sample = "leader"
    print(f"Posting list for '{sample}': {dict(index.postings[sample])}")
    print(f"  IDF('{sample}') = {index._idf(sample):.3f}  (appears in 2 docs)")
    common = "a"
    print(f"  IDF('{common}') = {index._idf(common):.3f}  "
          f"(appears in {len(index.postings[common])} docs -> "
          "low discriminating power)\n")

    for query in ["leader election log", "cache nodes"]:
        print(f'Query: "{query}"')
        for rank, (doc_id, score) in enumerate(index.search(query), 1):
            print(f"  {rank}. [{score:5.2f}] {doc_id}: {DOCS[doc_id]}")
        print()

    print("Note how d03/d04 top the first query (they match the rare terms")
    print("'leader'/'election'), while docs matching only common words rank")
    print("low — IDF does the heavy lifting, TF saturation stops keyword")
    print("stuffing, and shorter docs get a mild boost.")
