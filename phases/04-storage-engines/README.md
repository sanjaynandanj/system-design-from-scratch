# Phase 04 — 💾 Databases I — Storage Engines

> Open the hood of a database and find trees, logs, and locks.

You type `INSERT INTO users ...` and hit enter. What happens next is one of the great engineering stories of the last fifty years: bytes get appended to logs, pages get shuffled in trees, locks get taken and released, and somehow your data survives a power cord being yanked out of the wall. This phase strips the mystery out of that story. By the end, you'll have built your own key-value store and you'll never look at `CREATE INDEX` the same way again.

## 01. How a database actually stores your data

**MOTTO:** A database is just a very paranoid program that writes files.

### The Problem

Your app needs to store a million user records and find any one of them in milliseconds. A naive approach — one giant JSON file — means rewriting the whole file on every update and scanning everything on every read. Disks are slow, RAM is small, and crashes happen mid-write. You need a layout on disk that makes reads fast, writes safe, and updates cheap.

### The Concept

Think of a database file like a filing cabinet, not a scroll. A scroll (one big file) must be unrolled to find anything. A filing cabinet is divided into fixed-size drawers — **pages** (typically 4KB–16KB) — and each drawer holds a handful of records plus a little index card telling you what's inside.

```
Database file on disk:
+---------+---------+---------+---------+
| Page 0  | Page 1  | Page 2  | Page 3  |  ... each page = 8KB
| header  | rows    | rows    | rows    |
+---------+---------+---------+---------+
     |
     v  Page internals:
+------------------------------------------+
| page header | slot array -> | free space |
|             | <- row data (tuples)       |
+------------------------------------------+
```

The database reads and writes whole pages at a time, caches hot pages in a **buffer pool** in RAM, and keeps on-disk structures (trees, logs) that map keys to page locations.

### Build It

1. Fix a page size (say 8KB) and treat the file as an array of pages: page N starts at byte `N * 8192`.
2. Inside each page, store a **slot array** growing from the front and row data growing from the back — they meet in the middle when the page is full.
3. Give every row an address: `(page_id, slot_id)`. That pair is what indexes point to.
4. Cache pages in a buffer pool: a hash map from `page_id` to an in-memory frame, with an eviction policy when RAM runs out.
5. On write, mark the in-memory page "dirty" and flush it to disk later (but see Lesson 04 for why that's terrifying without a log).

### Use It

| System | Page size | Buffer pool |
|---|---|---|
| PostgreSQL | 8KB | shared_buffers |
| MySQL/InnoDB | 16KB | innodb_buffer_pool |
| SQLite | 4KB default | page cache |

Tuning the buffer pool is often the single highest-leverage database config change: a pool that fits your working set turns disk reads into RAM reads.

### War Story

SQLite — a single-file, page-based storage engine — is often described by its developers as among the most widely deployed software components in the world, running in browsers, phones, and airplanes. Its entire architecture is "pages in one file plus a journal," proof that this humble layout scales from wristwatches to warships.

### Checkpoint

- Why do databases read whole pages instead of individual rows from disk?
- What two structures grow toward each other inside a slotted page, and why?
- What problem does the buffer pool solve, and what new problem does it create?

## 02. B-trees: the workhorse of storage

**MOTTO:** Every database you've ever used is secretly a tree with a fear of being tall.

### The Problem

You have millions of rows spread across thousands of pages. To find `user_id = 42`, you can't scan every page — that's seconds of disk I/O. Binary search over a sorted file helps, but inserting into the middle of a sorted file means shifting everything after it. You need a structure that stays sorted, supports fast lookup, *and* handles inserts gracefully.

### The Concept

A B-tree is like a building directory. The lobby sign (root) says "Floors 1–10: names A–M, Floors 11–20: names N–Z." Each floor's sign narrows further, until you reach the actual office (leaf page) holding the data. Crucially, the tree is **short and wide**: with hundreds of keys per page, a 4-level tree can index billions of rows.

```
                [ 100 | 500 ]              <- root (1 page)
               /      |      \
      [10|50]     [200|350]    [700|900]   <- internal pages
      /  |  \      /  |  \      /  |  \
    [leaf pages: sorted rows, linked -> ]  <- leaves (data)
```

In a **B+tree** (what databases actually use), all data lives in the leaves, and leaves are linked left-to-right for fast range scans.

### Build It

1. **Search:** start at root, binary-search the keys to pick a child, descend. Repeat until a leaf. O(log_fanout N) page reads.
2. **Insert:** find the target leaf; if it has room, insert in sorted position. Done.
3. **Split:** if the leaf is full, split it into two half-full pages and push the middle key up to the parent. If the parent overflows, split it too — splits cascade upward, and the tree only grows taller when the *root* splits.
4. **Delete:** remove the key; if a page gets too empty, borrow from or merge with a sibling (many real engines lazily skip this).
5. Fanout is king: an 8KB page holding ~400 keys gives you 400^4 ≈ 25 billion rows in 4 levels.

### Use It

| Engine | Structure | Notes |
|---|---|---|
| PostgreSQL | B+tree indexes, heap tables | index points to heap tuple |
| MySQL/InnoDB | B+tree, clustered on PK | table *is* the PK tree |
| SQLite | B-trees for tables and indexes | one file, many trees |

Tradeoff: B-trees give great read performance and range scans, but every insert may touch multiple pages (write amplification), and random inserts fragment pages.

### War Story

Rudolf Bayer and Edward McCreight published the B-tree in 1970 while at Boeing, and to this day nobody is certain what the "B" stands for — Bayer, Boeing, balanced, or broad. Fifty-plus years later it remains the default answer to "how do I index data on disk," an almost unmatched run for any data structure.

### Checkpoint

- Why does high fanout matter more than tree balance tricks for on-disk trees?
- Walk through what happens when you insert into a full leaf whose parent is also full.
- Why do B+trees link their leaf pages together?

## 03. LSM trees: write-optimized storage

**MOTTO:** Never edit — always append, and clean up when nobody's looking.

### The Problem

B-trees update pages in place: a random write means reading a page, modifying it, and writing it back — possibly splitting along the way. Under a write-heavy workload (metrics, events, messages), that random I/O becomes the bottleneck. Disks and SSDs both *love* sequential writes. What if we never updated in place at all?

### The Concept

An LSM tree (Log-Structured Merge tree) works like a restaurant kitchen's order rail. New orders (writes) go onto the rail in arrival order — fast, no sorting on the spot. Periodically, someone takes a batch off the rail, sorts it, and files it. Old batches get merged into bigger, tidier batches during quiet hours (compaction).

```
Writes -> [ MemTable (sorted, in RAM) ]
               | flush when full
               v
   Level 0:  [SST] [SST]        <- small sorted files
   Level 1:  [ SSTable  ]       <- compaction merges downward
   Level 2:  [   SSTable    ]   <- bigger, older, fewer overlaps

Read(key): check MemTable, then L0, L1, ... (newest wins)
```

### Build It

1. **Write path:** append to a WAL (crash safety), then insert into an in-memory sorted structure (skip list or red-black tree) — the **MemTable**.
2. **Flush:** when the MemTable hits a size limit, write it to disk as an immutable **SSTable** (Sorted String Table) — one big sequential write.
3. **Read path:** check MemTable, then SSTables newest-to-oldest. Use a **Bloom filter** per SSTable to skip files that definitely don't contain the key.
4. **Compaction:** background threads merge overlapping SSTables into larger ones, dropping overwritten values and deleted keys (**tombstones**).
5. Tradeoff triangle: write amplification vs. read amplification vs. space amplification — compaction strategy (leveled vs. size-tiered) picks your poison.

### Use It

| System | Notes |
|---|---|
| RocksDB / LevelDB | embeddable LSM libraries (Google/Meta) |
| Cassandra, ScyllaDB | LSM with size-tiered/leveled compaction |
| HBase | LSM per Bigtable's design |

Rule of thumb: B-tree for read-heavy and transactional; LSM for write-heavy and append-mostly.

### War Story

The 2006 Bigtable paper from Google described the memtable/SSTable/compaction design that popularized LSM storage, and its open-source descendants — LevelDB, then RocksDB — now sit inside systems as different as Kafka Streams, CockroachDB (historically), and Flink state backends. One paper's storage layout quietly became half the industry's write path.

### Checkpoint

- Why are sequential writes so much cheaper than random writes, even on SSDs?
- What is a tombstone, and why can deleted data temporarily *increase* disk usage in an LSM tree?
- What does a Bloom filter's false positive mean for a read, and why is a false negative impossible?

## 04. The write-ahead log (WAL)

**MOTTO:** Tell the diary before you touch the furniture.

### The Problem

Your database buffers dirty pages in RAM for performance. Then the power dies. Half your pages were flushed, half weren't, and one was halfway through being written (a **torn page**). Users were promised their committed transactions were durable. How do you keep that promise without fsyncing every page on every commit — which would be brutally slow?

### The Concept

The WAL is the ship captain's logbook. Before the crew changes course (modifies a page), the captain writes the intention in the log. If the ship's crew all faint (crash), the replacement crew reads the logbook and re-does everything from the last known-good point. The trick: appending one line to a logbook is *fast and sequential*, while rearranging the ship is slow and random.

```
Commit path:
  change page in RAM  ->  append record to WAL  ->  fsync WAL  ->  ACK client
                                                        |
  (dirty pages flushed lazily, later, in any order) <---+
Recovery:
  find last checkpoint -> replay WAL records -> undo uncommitted
```

### Build It

1. Every change is first written as a log record: `(LSN, txn_id, page_id, before_image, after_image)`. LSN = log sequence number, ever-increasing.
2. **The rule:** a dirty page may not be flushed to disk until the log records describing its changes are on disk (that's what "write-ahead" means).
3. **Commit** = append a commit record + fsync the log. The data pages can be flushed whenever.
4. **Checkpoint:** periodically flush dirty pages and note "all changes before LSN X are on disk," so recovery doesn't replay the whole log.
5. **Recovery (ARIES-style):** analysis (what was in flight?), redo (replay history), undo (roll back losers).

### Use It

| System | WAL flavor |
|---|---|
| PostgreSQL | WAL (also powers replication + PITR) |
| MySQL/InnoDB | redo log + undo log |
| SQLite | rollback journal or WAL mode |
| Kafka | *is* basically a distributed WAL as a product |

Bonus: because the WAL is a complete ordered record of changes, it doubles as the replication stream and the change-data-capture feed.

### War Story

The ARIES recovery algorithm, published by C. Mohan and colleagues at IBM in 1992, formalized write-ahead logging with redo-undo recovery and is the direct ancestor of the recovery code in most serious databases today. It's one of the most-cited systems papers ever written, and its core mantra — repeat history, then undo losers — still appears in database course finals everywhere.

### Checkpoint

- State the write-ahead rule precisely: what must happen before a dirty page flush?
- Why is committing via WAL append faster than flushing all modified pages at commit?
- What would break if checkpoints didn't exist? (Hint: think about restart time.)

## 05. Indexes deep dive: covering, composite, partial

**MOTTO:** An index is a bet that you'll read this column more often than you write it.

### The Problem

`SELECT * FROM orders WHERE customer_id = 7 AND status = 'shipped' ORDER BY created_at DESC LIMIT 10` is taking 4 seconds. You have an index on `customer_id` — why is it still slow? Because indexing is not binary; *which* columns, in *what order*, storing *what extra data* determines whether the database does 10 page reads or 100,000.

### The Concept

A composite index is a phone book: sorted by last name, *then* first name. You can find all "Smiths" instantly, and all "Smith, Johns" instantly — but finding everyone named "John" regardless of surname means scanning the whole book. Column order in a composite index works exactly like that: the index is useful for **leftmost prefixes**.

```
Index on (customer_id, status, created_at):

(7, 'pending', Jan-3)
(7, 'shipped', Jan-1)   <- all customer 7 + shipped rows
(7, 'shipped', Jan-5)      are contiguous AND sorted by date!
(8, 'pending', Jan-2)
```

### Build It

1. **Composite:** index `(a, b, c)` supports filters on `a`, `(a,b)`, `(a,b,c)` — and range/sort on the column right after your equality columns. Rule: equality columns first, then the range/sort column.
2. **Covering:** if the index contains every column the query needs, the engine never touches the table — an **index-only scan**. Postgres: `CREATE INDEX ... INCLUDE (col)`.
3. **Partial:** index only the rows you query: `CREATE INDEX ON orders (created_at) WHERE status = 'pending'`. Tiny index, hot subset.
4. Every index taxes writes: each INSERT/UPDATE must update every index on the table. Indexes are read-performance bought with write-performance and disk.

### Use It

| Technique | Best for | Cost |
|---|---|---|
| Composite | multi-column filters + sort | column order is rigid |
| Covering | hot queries, avoid heap fetch | bigger index, slower writes |
| Partial | skewed data (e.g., 1% "active") | only helps matching queries |

Diagnostic workflow: `EXPLAIN ANALYZE`, look for Seq Scan on big tables, check whether sort and limit are satisfied by index order.

### War Story

A common postmortem pattern in the wild: a startup's dashboard grinds to a halt at 10M rows, someone adds a single composite index matching the top query's filter-plus-sort, and p99 latency drops from seconds to single-digit milliseconds — no hardware changed. The inverse also happens: teams "index everything" and discover their write throughput has quietly halved under a dozen indexes per table.

### Checkpoint

- Why does an index on `(status, customer_id)` fail to help `WHERE customer_id = 7` alone?
- What makes a scan "index-only," and what can silently prevent it (in Postgres, think visibility)?
- When is a partial index strictly better than a full one — and when is it a trap?

## 06. ACID transactions

**MOTTO:** All or nothing, alone or not at all, and forever means forever.

### The Problem

Transfer $100 from Alice to Bob: debit Alice, credit Bob. Crash between the two steps and $100 evaporates. Run two transfers concurrently and they interleave into nonsense. Money code without transactions isn't money code — it's a lawsuit generator. You need a way to bundle multiple operations into one indivisible, correct, durable unit.

### The Concept

A transaction is a sealed envelope of changes. The world sees either the whole envelope applied or none of it — never a half-opened envelope. ACID names four separate guarantees:

```
A - Atomicity:   all steps commit, or all roll back
C - Consistency: invariants hold (balances never negative)
I - Isolation:   concurrent txns don't see each other's mess
D - Durability:  once committed, survives crash/power loss
```

They're implemented by different machinery: atomicity by undo logs/rollback, isolation by locks or MVCC, durability by the WAL + fsync. "Consistency" is mostly *your* job — the database enforces your declared constraints, but your invariants are yours.

### Build It

1. `BEGIN` — the engine assigns a transaction ID and a snapshot/lock context.
2. Each write records enough info to undo it (before-images or undo log entries).
3. `COMMIT` — write a commit record to the WAL, fsync. This single append *is* the atomic instant of commit.
4. `ROLLBACK` (or crash) — apply undo records in reverse, releasing locks.
5. Crucial subtlety: atomicity is decided by one bit's durability (the commit record), not by when data pages hit disk.

```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 'alice';
UPDATE accounts SET balance = balance + 100 WHERE id = 'bob';
COMMIT;  -- both or neither, even if the server dies mid-way
```

### Use It

Postgres, MySQL/InnoDB, SQLite, Oracle, SQL Server: full ACID. Early MongoDB offered single-document atomicity only (multi-document transactions arrived in 4.0, 2018). Many "NoSQL" stores trade ACID for scale — the point of the next phase. Know exactly which guarantee you're giving up before you give it up.

### War Story

Jim Gray's work on transactions at IBM and Tandem in the 1970s–80s defined the concepts this lesson teaches — his 1981 paper "The Transaction Concept: Virtues and Limitations" is still a delight to read — and won him the 1998 Turing Award. The acronym ACID itself was coined by Theo Härder and Andreas Reuter in 1983.

### Checkpoint

- Which single physical event marks the exact moment a transaction becomes durable?
- Why is "C" the odd one out among the four ACID letters?
- A crash occurs after Alice's debit page was flushed but before commit. What happens on recovery, and why?

## 07. Isolation levels and their anomalies

**MOTTO:** Serializable is the truth; everything else is a negotiated lie.

### The Problem

Perfect isolation means running transactions as if one-at-a-time — safe but slow. So databases offer weaker levels that permit specific, well-catalogued **anomalies** in exchange for concurrency. Most developers run at their database's default level without knowing which lies it tells. Then a race condition eats an invoice.

### The Concept

Think of isolation levels as noise-cancelling headphone settings. Full cancellation (serializable): you hear nothing from neighbors. Each weaker setting lets a specific category of noise through:

```
Anomaly                | What leaks through
-----------------------+------------------------------------------
Dirty read             | See UNCOMMITTED data from another txn
Non-repeatable read    | Re-read a row, it CHANGED mid-txn
Phantom                | Re-run a query, NEW rows appeared
Write skew             | Two txns each read, both write, and
                       | together break an invariant neither
                       | broke alone

Level            | Dirty | NonRep | Phantom | WriteSkew
READ UNCOMMITTED |  yes  |  yes   |  yes    |  yes
READ COMMITTED   |  no   |  yes   |  yes    |  yes
REPEATABLE READ  |  no   |  no    |  (yes*) |  yes
SERIALIZABLE     |  no   |  no    |  no     |  no
```

(*Postgres's REPEATABLE READ is snapshot isolation: no phantoms, but write skew remains.)

### Build It

Reproduce write skew yourself — the classic on-call doctors example:

1. Invariant: at least one doctor on call. Currently: Alice and Bob.
2. Txn A: `SELECT count(*) WHERE on_call` → 2. "Safe to leave." `UPDATE alice SET on_call = false`.
3. Txn B (concurrently, same snapshot): counts 2, updates *Bob* to false.
4. They touched *different rows* — no write-write conflict — both commit. Doctors on call: zero. Snapshot isolation shrugs; SERIALIZABLE aborts one.
5. Fixes: `SERIALIZABLE`, or explicit locking (`SELECT ... FOR UPDATE`), or materialize the conflict (a row both must update).

### Use It

| Database | Default level |
|---|---|
| PostgreSQL | READ COMMITTED |
| MySQL/InnoDB | REPEATABLE READ |
| SQL Server | READ COMMITTED |
| Oracle | READ COMMITTED (no READ UNCOMMITTED writes-wise; SERIALIZABLE is snapshot) |

Postgres's SERIALIZABLE uses SSI (serializable snapshot isolation, added in 9.1) — optimistic, aborts on dangerous patterns; retry loops are mandatory.

### War Story

The 1995 paper "A Critique of ANSI SQL Isolation Levels" (Berenson, Bernstein, Gray, Melton, O'Neil, O'Neil) demonstrated that the SQL standard's anomaly definitions were ambiguous and missed entire classes of bugs — including write skew under snapshot isolation. Two decades later, Kyle Kingsbury's Jepsen project turned "your isolation level lies to you" into an ongoing public test series that has caught real anomaly bugs in numerous well-known databases.

### Checkpoint

- What distinguishes a phantom from a non-repeatable read?
- Why does write skew survive snapshot isolation when lost updates don't?
- Your payment service runs on Postgres defaults. Which anomalies are you currently accepting?

## 08. MVCC: reading without blocking

**MOTTO:** Don't fight over the document — hand everyone their own photocopy.

### The Problem

Naive isolation via locks means readers block writers and writers block readers. A long-running analytics query would freeze all writes to the table for minutes. That's unacceptable: OLTP systems need reads and writes flowing concurrently *without* seeing each other's half-finished work.

### The Concept

MVCC (Multi-Version Concurrency Control) keeps **multiple versions of each row**, each stamped with the transaction IDs that created and deleted it. A reader picks a **snapshot** — "the world as of transaction 100" — and simply ignores versions from the future or from uncommitted transactions. Nobody waits, because nobody shares a copy.

```
Row versions for account 'alice':
  v1: balance=500  created_by=txn 90   deleted_by=txn 95
  v2: balance=400  created_by=txn 95   deleted_by=txn 102
  v3: balance=300  created_by=txn 102  deleted_by= -

Reader with snapshot@txn 100 sees v2 (400).
Reader with snapshot@txn 105 sees v3 (300).
Neither blocks the writer creating v4.
```

### Build It

1. Tag each row version with `xmin` (creating txn) and `xmax` (deleting/updating txn) — Postgres's actual column names.
2. A snapshot = the set of transactions committed when it was taken. Visibility check: `xmin` committed-and-in-snapshot, `xmax` absent or not-yet-committed for me.
3. UPDATE = insert new version + mark old version's `xmax`. DELETE = set `xmax`. Nothing is overwritten in place.
4. Writers still conflict with *writers* on the same row (locks or first-committer-wins aborts).
5. Garbage: old versions no active snapshot can see must be reclaimed — Postgres calls this **VACUUM**; InnoDB purges undo history.

### Use It

| Engine | MVCC style |
|---|---|
| PostgreSQL | versions live in the heap; VACUUM cleans up |
| MySQL/InnoDB | current row in place; old versions reconstructed from undo log |
| Oracle | undo segments ("snapshot too old" error) |

Tradeoff: Postgres updates write a whole new tuple (bloat, vacuum debt) but rollback is instant; InnoDB updates in place (compact) but rollback replays undo.

### War Story

Long-running transactions are MVCC's kryptonite: they pin old snapshots, blocking version cleanup until tables and indexes bloat. Postgres operators dread the related failure mode of transaction ID wraparound — if aggressive autovacuum can't freeze old tuples in time, the database will eventually refuse writes to protect data, a scenario that has produced multi-hour outages and detailed public postmortems from more than one high-profile engineering team.

### Checkpoint

- Why do MVCC readers never take row locks, and what conflict *still* requires blocking or aborting?
- Trace an UPDATE under MVCC: what happens to the old version and who eventually deletes it?
- Why does an idle-in-transaction connection left open overnight hurt a Postgres database?

## 09. Locking and deadlocks

**MOTTO:** Two transactions, two locks, taken in opposite orders — a tragedy in four rows.

### The Problem

MVCC handles read-write concurrency, but two transactions *writing* the same row must be serialized somehow — and sometimes you need to lock things explicitly (inventory decrements, seat reservations). Locks create a new hazard: transaction A holds lock 1 and wants lock 2; B holds 2 and wants 1. Both wait forever. That's a deadlock, and at scale it's a *when*, not an *if*.

### The Concept

Deadlock is the four-way-stop standoff where everyone politely waves the other driver on, forever. Databases model it as a **waits-for graph**: an edge from A to B means "A waits for a lock B holds." A cycle in the graph = deadlock. The engine periodically hunts for cycles and shoots one participant (the victim), rolling it back so the others proceed.

```
Txn A: LOCK row 1 ✓ ... wants row 2 (held by B) ... waits
Txn B: LOCK row 2 ✓ ... wants row 1 (held by A) ... waits

Waits-for graph:  A ──> B
                  ^      │
                  └──────┘   cycle! kill a victim.
```

### Build It

1. **Lock modes:** shared (S, many readers) vs exclusive (X, one writer); real engines add intention locks (IS/IX) on tables so row and table locks can coexist cheaply.
2. **Two-phase locking (2PL):** acquire locks as you go, release only at commit — this is what makes lock-based isolation actually serializable.
3. **Detection:** build the waits-for graph; on a cycle, abort the cheapest victim (least work done). Postgres checks after `deadlock_timeout` (default 1s).
4. **Prevention beats detection:** always acquire locks in a globally consistent order (e.g., sort account IDs before locking both), keep transactions short, lock late.
5. Application-side: catch deadlock errors (Postgres `40P01`) and retry — a deadlock abort is a normal event, not a bug per se.

### Use It

| Tool | Use |
|---|---|
| `SELECT ... FOR UPDATE` | lock rows you're about to modify |
| `SELECT ... FOR UPDATE SKIP LOCKED` | job queues: grab unclaimed work |
| `NOWAIT` | fail fast instead of queueing |
| Advisory locks (Postgres) | app-defined locks, no table needed |

`SKIP LOCKED` (Postgres 9.5+, MySQL 8.0+) quietly made Postgres a respectable job queue — workers grab rows without convoying behind each other.

### War Story

Lock convoys and deadlocks under Black-Friday-class load are a recurring theme in e-commerce postmortems: a hot inventory row (one bestselling SKU) becomes a single point of serialization, latency balloons, connection pools exhaust, and the whole checkout path falls over — no CPU or disk anywhere near its limit. The fix is rarely "more hardware"; it's shorter transactions, ordered lock acquisition, or redesigning the hot row away.

### Checkpoint

- Why does two-phase locking require holding locks until commit rather than releasing them early?
- Give a concrete coding rule that makes the Alice-and-Bob transfer deadlock impossible.
- What does `SKIP LOCKED` do, and why is it perfect for a job queue but wrong for a bank transfer?

## 10. Query planning and optimization

**MOTTO:** SQL says what you want; the planner gambles on how.

### The Problem

`SELECT` is declarative — you never said whether to use an index, which join algorithm to run, or which table to scan first. For a 5-table join there are thousands of possible execution plans whose costs differ by factors of 100,000×. Someone has to pick, in milliseconds, without running them. That someone is the query planner, and when it guesses wrong, your 20ms query takes 20 minutes.

### The Concept

The planner is a travel agent booking a multi-city trip: it doesn't fly the routes, it estimates costs from timetables (statistics) and picks the cheapest itinerary. Its timetables are **table statistics**: row counts, value histograms, distinct-value estimates. Stale or misleading stats = confidently booking you through a blizzard.

```
SQL ──parse──> AST ──rewrite──> logical plan
        ──optimize (cost model + stats)──> physical plan

           Hash Join  (est. 1,200 rows)
          /         \
   Seq Scan       Index Scan on orders
   on customers   (customer_id = ...)
```

### Build It

1. **Access paths:** sequential scan (cheap per-row, reads everything) vs index scan (targeted, but random I/O per row) — for large fractions of a table, seq scan *wins*, and the planner knows it.
2. **Join algorithms:** nested loop (great when the outer side is tiny + inner is indexed), hash join (build hash table on the smaller side; great for big unsorted inputs), merge join (both sides sorted).
3. **Cost model:** estimated rows × per-row cost constants (`seq_page_cost`, `random_page_cost`...). Cardinality estimation is the hard part — errors compound multiplicatively up the join tree.
4. **Join ordering:** planner searches orders via dynamic programming; beyond ~12 tables Postgres switches to a genetic algorithm (GEQO).
5. **Read plans:** `EXPLAIN ANALYZE` shows estimated vs *actual* rows. A 1000× mismatch is your smoking gun — usually stale stats (`ANALYZE`), correlated columns, or an expression the planner can't estimate.

### Use It

| Symptom | Likely fix |
|---|---|
| Seq scan where index expected | stats stale; or query fetches too much for index to pay off |
| Nested loop on huge inputs | wrong cardinality estimate; ANALYZE or rewrite |
| Plan flips after data growth | plan instability — consider extended statistics or (MySQL/Oracle) hints |

Postgres refuses to support hints on principle; MySQL, Oracle, and SQL Server embrace them. Both camps are certain the other is wrong.

### War Story

The cost-based optimizer descends from IBM's System R project — Patricia Selinger's 1979 paper on access path selection introduced the cost-model-plus-dynamic-programming approach still used today. Meanwhile, "the query was fast yesterday" remains a top-tier DBA complaint: a table crosses a statistics threshold overnight, the planner flips from index scan to seq scan (or nested loop to hash join), and an app that never changed a line of code melts.

### Checkpoint

- Why can a sequential scan legitimately beat an index scan on the same query?
- Where in `EXPLAIN ANALYZE` output do you look to detect a cardinality estimation error?
- Why do cardinality errors get *worse* as the number of joined tables increases?

## 11. Build a key-value store from scratch

**MOTTO:** An append-only file and a dict walk into a bar; by last call they're a database.

### The Problem

Time to stop reading and start building. The challenge: a persistent key-value store with fast writes, fast reads, and crash safety — in under 100 lines. The design we'll steal is **Bitcask** (from Riak, 2010): all writes append to a log file; an in-memory hash map remembers where each key's latest value lives.

### The Concept

It's a receipt spike on a diner counter. Every order gets stabbed onto the spike (append-only, latest on top), and a notepad (hash index) tracks where each table's *most recent* order sits. You never dig through the spike to find things — the notepad tells you exactly how far down to reach.

```
data.log (append-only):
offset 0:   [len]["alice"]["v1"]
offset 21:  [len]["bob"]["hello"]
offset 44:  [len]["alice"]["v2"]     <- newer wins

keydir (RAM): { "alice": 44, "bob": 21 }
GET alice -> seek(44) -> read one record. One disk seek, max.
```

### Build It

```python
import os, struct

TOMBSTONE = b"__DEL__"

class Bitcask:
    def __init__(self, path):
        self.path, self.keydir = path, {}
        if os.path.exists(path):                 # crash recovery = rebuild index
            with open(path, "rb") as f:
                while (hdr := f.read(8)):
                    klen, vlen = struct.unpack(">II", hdr)
                    key = f.read(klen); off = f.tell(); val = f.read(vlen)
                    if val == TOMBSTONE: self.keydir.pop(key, None)
                    else: self.keydir[key] = (off, vlen)
        self.f = open(path, "ab")

    def put(self, key, val):
        self.f.write(struct.pack(">II", len(key), len(val)) + key)
        off = self.f.tell(); self.f.write(val); self.f.flush()
        os.fsync(self.f.fileno())                # durability, the honest way
        self.keydir[key] = (off, len(val))

    def get(self, key):
        off, vlen = self.keydir[key]
        with open(self.path, "rb") as r:
            r.seek(off); return r.read(vlen)

    def delete(self, key):
        self.put(key, TOMBSTONE); del self.keydir[key]
```

Extensions to attempt: **compaction** (rewrite only live records to a new file, swap atomically), CRC checksums per record (detect torn writes), and hint files (persist the keydir so restart doesn't scan the log).

### Use It

This is genuinely how Bitcask (Riak's default engine) works, and the append-log + in-memory-index idea underpins Kafka's log segments and every LSM's WAL. Limits: all keys must fit in RAM, and range scans require a sorted structure — which is exactly the itch LSM trees scratch.

### War Story

Basho's 2010 Bitcask paper is refreshingly short and readable — its stated design goal was "a data structure a single developer can understand in an afternoon" — and it delivered predictable single-seek reads that made Riak's storage latency famously boring. Boring latency is the highest compliment a storage engine can receive.

### Checkpoint

- Why does GET require at most one disk seek, regardless of database size?
- Walk through crash recovery: what's rebuilt, from what, and what's the worst case?
- Why must deletes write a tombstone instead of just removing the key from the dict?

## 12. Postgres vs MySQL internals tour

**MOTTO:** Same SQL on the surface; different animals under the floorboards.

### The Problem

"Postgres or MySQL?" is the tabs-vs-spaces of backend engineering, usually argued with vibes. But the two differ in *architecture* — process model, storage layout, MVCC machinery, replication format — and those differences produce real, predictable consequences for your workload. Choose with the hood open.

### The Concept

Postgres is a research vessel that became a battleship: extensible everywhere (types, indexes, procedural languages, extensions like PostGIS). MySQL is a delivery truck that got very good at one route: fast, simple OLTP, with storage engines swappable behind a common SQL layer (InnoDB won that war).

```
                 PostgreSQL              MySQL/InnoDB
Connections      process per conn        thread per conn
Table storage    heap (unordered)        clustered B+tree on PK
Secondary index  points to heap TID      stores PK, second lookup
MVCC             new tuple per update    in-place + undo log
Old versions     cleaned by VACUUM       purged from undo history
Replication      WAL shipping (physical) binlog (logical row events)
```

### Build It

Reason through the consequences like an engine designer:

1. **Clustered PK (InnoDB):** primary-key range scans are contiguous and fast; but a random PK (UUIDv4) sprays inserts across the tree — page splits everywhere. Hence the classic advice: auto-increment or time-ordered keys (UUIDv7) for InnoDB.
2. **Heap + TID (Postgres):** all indexes point straight at the row — no double lookup — but *every* index must be updated when a row moves... which is why Postgres has **HOT updates** (heap-only tuples) to dodge index churn when unindexed columns change.
3. **Process vs thread:** Postgres backends are heavier — thousands of raw connections hurt; PgBouncer is a rite of passage. MySQL's threads are cheaper per connection.
4. **VACUUM vs undo purge:** Postgres pays cleanup after the fact (bloat, wraparound risk); InnoDB pays on rollback and long-running-read version reconstruction.
5. **Replication:** WAL shipping replicates byte-exact clusters (same major version, whole instance); binlog replicates logical changes (flexible topologies, per-table filters, but replication drift is possible).

### Use It

| Lean Postgres when... | Lean MySQL when... |
|---|---|
| complex queries, CTEs, window functions | massive simple OLTP, PK-centric access |
| rich types (JSONB, arrays, PostGIS) | ecosystem: Vitess-style sharding paths |
| serializable correctness (SSI) | huge connection counts, simple ops story |

Honest answer for most CRUD apps: either, tuned properly, is more database than you need. Uber famously migrated Postgres→MySQL (2016, citing write amplification and replication needs); countless others went the other way. Workload beats fashion.

### War Story

Uber's 2016 engineering post explaining their Postgres-to-MySQL migration — centered on Postgres's index write amplification on updates and their replication topology needs — triggered one of the great public database debates, with detailed rebuttals from Postgres contributors. The healthy takeaway wasn't "MySQL won"; it was that both camps' engineers agreed the *right* answer depends on update patterns, indexes, and replication shape — exactly the internals this lesson covered.

### Checkpoint

- Why do random UUIDv4 primary keys hurt InnoDB more than they hurt Postgres?
- What is a HOT update in Postgres, and what condition must hold for one to occur?
- Explain one workload where InnoDB's secondary-index-to-PK double lookup is a real cost, and one where it's irrelevant.
