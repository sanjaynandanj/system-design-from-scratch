"""LSM tree: the storage engine behind LevelDB, RocksDB, Cassandra.

Teaches: turn random writes into sequential I/O by buffering in a
sorted memtable, flushing it to immutable SSTable files, and merging
files in the background (compaction).
Key insight: reads check memtable first, then SSTables newest-first —
the newest value always wins, so old files never need in-place updates.
"""

import bisect
import json
import os
import tempfile

TOMBSTONE = "__tombstone__"  # deletes are just writes of a marker


class LSMTree:
    def __init__(self, data_dir: str, memtable_limit: int = 4):
        self.data_dir = data_dir
        self.memtable_limit = memtable_limit
        self.keys = []       # sorted keys (bisect keeps them ordered)
        self.values = {}
        self.sstables = []   # file paths, oldest first
        self._next_id = 0

    # --- write path -----------------------------------------------------
    def put(self, key: str, value):
        if key not in self.values:
            bisect.insort(self.keys, key)
        self.values[key] = value
        if len(self.keys) >= self.memtable_limit:
            self.flush()

    def delete(self, key: str):
        self.put(key, TOMBSTONE)

    def flush(self):
        """Write the sorted memtable out as an immutable SSTable file."""
        path = os.path.join(self.data_dir, f"sstable_{self._next_id:03d}.json")
        self._next_id += 1
        with open(path, "w") as f:
            json.dump({k: self.values[k] for k in self.keys}, f)
        self.sstables.append(path)
        print(f"    [flush] memtable ({len(self.keys)} keys) -> "
              f"{os.path.basename(path)}")
        self.keys, self.values = [], {}

    # --- read path ------------------------------------------------------
    def get(self, key: str):
        if key in self.values:
            value = self.values[key]
            return None if value == TOMBSTONE else value
        for path in reversed(self.sstables):  # newest SSTable wins
            with open(path) as f:
                table = json.load(f)
            if key in table:
                return None if table[key] == TOMBSTONE else table[key]
        return None

    # --- compaction -----------------------------------------------------
    def compact(self):
        """Merge all SSTables into one, dropping shadowed and deleted keys."""
        merged = {}
        for path in self.sstables:  # oldest first, so newer overwrite older
            with open(path) as f:
                merged.update(json.load(f))
        merged = {k: v for k, v in sorted(merged.items()) if v != TOMBSTONE}
        for path in self.sstables:
            os.remove(path)
        path = os.path.join(self.data_dir, f"sstable_{self._next_id:03d}.json")
        self._next_id += 1
        with open(path, "w") as f:
            json.dump(merged, f)
        self.sstables = [path]
        print(f"    [compact] merged into {os.path.basename(path)} "
              f"({len(merged)} live keys)")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        db = LSMTree(tmp, memtable_limit=4)
        print(f"=== LSM tree (memtable flushes at 4 keys) in {tmp} ===\n")

        print("Writing 10 keys (watch flushes fire automatically):")
        for i in range(10):
            db.put(f"key{i:02d}", f"v1-{i}")

        print("\nOverwriting key01 and key02, deleting key03:")
        db.put("key01", "v2-UPDATED")
        db.put("key02", "v2-UPDATED")
        db.delete("key03")

        print(f"\nState: memtable={len(db.keys)} keys, "
              f"sstables={[os.path.basename(p) for p in db.sstables]}")

        print("\nReads BEFORE compaction (newest data wins across files):")
        for key in ["key01", "key03", "key07", "key09"]:
            print(f"  get({key}) = {db.get(key)!r}")

        print("\nRunning compaction:")
        db.flush()  # push remaining memtable down first
        db.compact()

        print("\nReads AFTER compaction (same answers, one file):")
        for key in ["key01", "key03", "key07", "key09"]:
            print(f"  get({key}) = {db.get(key)!r}")

        print("\nTakeaway: writes are always sequential appends; reads pay")
        print("for it by checking multiple files, and compaction pays that")
        print("debt down in the background.")
