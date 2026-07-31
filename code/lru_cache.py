"""O(1) LRU cache built from a dict + hand-rolled doubly-linked list.

Teaches: why LRU needs two structures — a hash map for O(1) lookup and
a linked list for O(1) reordering/eviction.
Key insight: sentinel head/tail nodes eliminate all edge-case branches
when splicing nodes in and out of the list.
"""


class _Node:
    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key=None, value=None):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


class LRUCache:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._map = {}                      # key -> _Node
        # Sentinels: head.next is most-recent, tail.prev is least-recent.
        self._head = _Node()
        self._tail = _Node()
        self._head.next = self._tail
        self._tail.prev = self._head

    def _unlink(self, node: _Node):
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node: _Node):
        node.next = self._head.next
        node.prev = self._head
        self._head.next.prev = node
        self._head.next = node

    def get(self, key):
        node = self._map.get(key)
        if node is None:
            return None
        # A read counts as a "use": move to the most-recent position.
        self._unlink(node)
        self._push_front(node)
        return node.value

    def put(self, key, value):
        node = self._map.get(key)
        if node is not None:
            node.value = value
            self._unlink(node)
            self._push_front(node)
            return None
        if len(self._map) >= self.capacity:
            lru = self._tail.prev
            self._unlink(lru)
            del self._map[lru.key]
            evicted = lru.key
        else:
            evicted = None
        node = _Node(key, value)
        self._map[key] = node
        self._push_front(node)
        return evicted

    def state(self):
        """Keys from most-recent to least-recent (for the demo)."""
        keys, node = [], self._head.next
        while node is not self._tail:
            keys.append(node.key)
            node = node.next
        return keys


if __name__ == "__main__":
    cache = LRUCache(capacity=3)
    print("=== LRU cache, capacity 3 (state shown MRU -> LRU) ===\n")

    for key, value in [("a", 1), ("b", 2), ("c", 3)]:
        cache.put(key, value)
        print(f"put({key}, {value})        state = {cache.state()}")

    print(f"\nget('a') -> {cache.get('a')}     state = {cache.state()}"
          "   ('a' promoted to front)")

    evicted = cache.put("d", 4)
    print(f"\nput('d', 4)        state = {cache.state()}"
          f"   evicted = '{evicted}'  (LRU was 'b')")

    print(f"get('b') -> {cache.get('b')}    ('b' is gone)")

    evicted = cache.put("e", 5)
    print(f"put('e', 5)        state = {cache.state()}"
          f"   evicted = '{evicted}'")

    cache.put("a", 100)
    print(f"put('a', 100)      state = {cache.state()}"
          "   (update, no eviction)")
    print(f"get('a') -> {cache.get('a')}")
