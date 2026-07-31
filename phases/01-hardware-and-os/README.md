# Phase 01 — ⚙️ Hardware & OS Foundations

> Every distributed system is just computers. Know the computer.

Distributed systems have a dirty secret: they're ordinary boxes running ordinary operating systems, and every exotic behavior at scale — tail latency, throughput cliffs, mysterious stalls — traces back to a CPU cache, a disk head, or a kernel scheduler doing exactly what it was built to do. This phase takes you down the stack until the magic stops. When you come back up, "the service is slow" will decompose into questions you can actually answer.

## 01. The CPU and the memory hierarchy

**MOTTO:** The CPU is a genius chained to a slow mailbox; the hierarchy exists to keep it fed.

### The Problem

A modern CPU can execute an instruction in well under a nanosecond, but fetching data from RAM takes ~100 ns. Naively, your 4 GHz processor spends 99% of its life waiting for the mail. Something has to bridge a 100x speed gap — and that something shapes how fast *your code* runs far more than your algorithm's big-O.

### The Concept

The fix is a pyramid of progressively bigger, slower memories, each caching the one below. Analogy: your desk (registers), the shelf behind you (L1), the office bookcase (L2/L3), the library across town (RAM). You keep what you're using close, and hardware bets — via cache lines and prefetching — that you'll want the neighbors of whatever you just touched.

```
 registers   ~1 KB      <1 ns    on the desk
 L1 cache    ~64 KB    ~0.5 ns   arm's reach
 L2 cache    ~1 MB      ~7 ns    across the room
 L3 cache   ~32 MB     ~30 ns    down the hall
 RAM        ~256 GB   ~100 ns    across town
```

Data moves in **cache lines** (64 bytes). Touch one byte, you paid for 64 — so touching the other 63 next is nearly free. That's *locality*, and it's the whole game.

### Build It

Feel it in Python (the effect survives even the interpreter overhead):

```python
import time, random
N = 10_000_000
data = list(range(N))
idx_seq = list(range(N))
idx_rnd = idx_seq[:]; random.shuffle(idx_rnd)
for name, idx in [("sequential", idx_seq), ("random", idx_rnd)]:
    t = time.perf_counter(); s = 0
    for i in idx: s += data[i]
    print(name, round(time.perf_counter() - t, 2), "s")
```

Same work, same big-O; random loses badly because every access is a cache miss. In C the gap is often 10x+.

### Use It

Cache-consciousness explains real designs: columnar databases (ClickHouse, Parquet) lay values of one column contiguously so scans stream through cache lines; arrays beat linked lists in practice despite identical asymptotics; "mechanical sympathy" is why LMAX's Disruptor queue outran conventional queues by orders of magnitude.

### War Story

Meltdown and Spectre (disclosed January 2018) weaponized this very machinery: CPUs speculatively execute ahead and leave footprints in the cache, and attackers learned to read secrets by timing cache hits. The industry's fixes — kernel page-table isolation among them — made syscalls measurably slower worldwide. The memory hierarchy is so fundamental that its side effects became a global security event.

### Checkpoint

- Why does touching one byte of memory effectively cost you 64 bytes, and how can you exploit that?
- Order these by latency: L1 hit, RAM reference, L3 hit, register access.
- Why can an O(n) array scan beat an O(n) linked-list traversal by 10x in wall-clock time?

## 02. RAM vs disk: the great divide

**MOTTO:** RAM is where data lives; disk is where data survives.

### The Problem

You must constantly choose where state lives, and the two options differ by everything that matters: RAM is ~1,000x faster than even good SSDs for random access, but it evaporates on power loss and costs ~10-50x more per byte. Put hot data on disk and you're slow; put durable data only in RAM and one reboot is an extinction event.

### The Concept

Think of RAM as your working desk and disk as the filing cabinet in the basement. The desk is instant but small and gets swept clean every night; the cabinet is vast and permanent but every trip costs you. Every storage system ever built is some strategy for shuttling data between these two worlds — caches pull hot data up, write-ahead logs push durability down, and the page cache (the OS's own shuttle) sits invisibly in the middle.

```
            speed      cost/GB     survives power loss?
 RAM       ~100 ns     $$$$        no
 SSD       ~100 µs     $$          yes
 HDD       ~10 ms      $           yes
             ^-- each step: ~1000x slower, ~5-10x cheaper
```

### Build It

The canonical durable-but-fast recipe, used by essentially every database:

1. Keep the working set in RAM (buffer pool / cache).
2. On write: append the change to a sequential **write-ahead log** on disk first (cheap — sequential), *then* update RAM.
3. Acknowledge the client only after the log write is flushed (`fsync`).
4. Periodically checkpoint RAM state to disk in bulk; truncate the log.
5. On crash: reload the checkpoint, replay the log. Nothing acknowledged is lost.

You get RAM-speed reads, disk-grade durability, and the only disk work on the write path is sequential appends.

### Use It

| System | Strategy |
|---|---|
| Redis | RAM-first; optional AOF log / RDB snapshots for durability |
| PostgreSQL/MySQL | Buffer pool in RAM + WAL on disk (the recipe above) |
| Memcached | RAM only, proudly; a cache, not a store |
| Kafka | Disk-first, but sequential + page cache makes it fast anyway |

### War Story

Facebook's NSDI 2013 paper "Scaling Memcache at Facebook" describes running memcached as a RAM-based shield in front of MySQL at the scale of over a billion requests per second — and most of the paper is about the failure modes of that divide: stale data, thundering herds on cache misses, and what happens when the fast layer and the durable layer disagree.

### Checkpoint

- In the WAL recipe, why is it safe to acknowledge a write before updating the on-disk checkpoint?
- Why does the write-ahead log avoid the main cost of disk I/O?
- Your "cache" has data that exists nowhere else. What is it actually, and what just became your problem?

## 03. HDD vs SSD vs NVMe

**MOTTO:** One is a record player, one is a filing wall of flash, and one finally removed the middleman.

### The Problem

"Disk" hides three wildly different animals. Pick wrong and you either pay 10x too much for cold archives or watch your database do 200 random reads per second on spinning rust while your users watch spinners of their own.

### The Concept

An **HDD** is mechanical: platters spin (7,200 RPM), a head seeks (~10 ms per random access) — physics caps it at ~100–200 random IOPS, though sequential streaming hits 100–250 MB/s. An **SSD** is flash: no moving parts, ~100 µs access, tens of thousands of IOPS — but it can only erase in large blocks, so a controller (the FTL) shuffles data behind your back, and cells wear out after finite write cycles. **NVMe** isn't a new medium — it's a new *interface*: flash attached directly to PCIe instead of the SATA protocol designed for record players, unlocking multi-GB/s and up to a million IOPS with deep parallel queues.

```
             random IOPS     latency      sequential      $/TB
 HDD         ~100-200        ~10 ms       ~200 MB/s       $
 SATA SSD    ~50-100K        ~100 µs      ~550 MB/s*      $$     *SATA ceiling
 NVMe SSD    ~100K-1M+       ~20-100 µs   ~3-7 GB/s       $$$
```

### Build It

Choosing, as an algorithm:

1. Random-access working set (databases, indexes)? → SSD/NVMe. HDDs are disqualified by IOPS, not capacity.
2. Sequential, cold, huge (backups, logs, video archives)? → HDD. Streaming is its one trick, and it's cheap.
3. Latency-critical or IOPS-hungry (write-heavy DBs, queues)? → NVMe.
4. Mind SSD write endurance: a cell survives ~1K–100K program/erase cycles; write amplification from the FTL burns them faster. Check the drive's rated TBW against your write volume.

### Use It

Cloud storage tiers mirror the table: AWS gp3/io2 volumes are SSD-class with provisioned IOPS, st1/sc1 are HDD-class for streaming, and S3 Glacier sits on the coldest, cheapest media. Databases now assume SSDs; Kafka and backup systems still happily ride HDDs because they engineered themselves to be sequential (next lesson).

### War Story

Backblaze, the backup company, has published quarterly failure statistics on its fleet — well over 200,000 spinning drives — since 2013, turning drive reliability from vendor marketing into public data: annualized failure rates of roughly 1–2%, with specific models occasionally spiking far higher. At fleet scale, "disks fail" isn't a possibility; it's a Tuesday.

### Checkpoint

- Why are HDDs capped near ~200 random IOPS regardless of how fancy the drive is?
- What does NVMe actually change, given the flash inside can be identical to a SATA SSD's?
- You're storing 2 PB of surveillance video written once and read rarely. Which medium, and why?

## 04. Sequential vs random I/O

**MOTTO:** Storage doesn't reward reading fast; it rewards reading in order.

### The Problem

Two programs read the same 1 GB from the same HDD. One finishes in 5 seconds, the other in 3 hours. Nothing differs but access order. If you don't design your data layout around this, the hardware will design your latency around it.

### The Concept

On an HDD it's obvious: sequential means the head stays put while platters spin data underneath it (~200 MB/s); random means paying a ~10 ms seek per read — 4 KB per seek is a catastrophic ~0.4 MB/s. The napkin math: 1 GB sequential ≈ 5 s; 1 GB in random 4 KB reads ≈ 262,144 seeks × 10 ms ≈ 43 minutes-to-hours. SSDs shrink the gap but don't erase it — sequential still wins by exploiting internal parallelism and being kind to the FTL. So the great trick of storage engineering: **turn random writes into sequential ones**.

```
 Random writes arrive:   w5, w2, w9, w1 ...
 Log-structured answer:  append them all, in arrival order:
   log: [w5][w2][w9][w1][...]        <- sequential! fast!
   + in-RAM index: key -> log offset  <- reads find them
   + background compaction merges/sorts old segments
```

### Build It

That sketch is the **LSM tree** (log-structured merge tree), the storage engine of half the modern data world:

1. Writes go to an in-memory sorted buffer (memtable) + a sequential WAL.
2. When full, flush the memtable as an immutable sorted file (SSTable) — one big sequential write.
3. Reads check memtable, then recent SSTables (Bloom filters skip most).
4. Compaction merges SSTables in the background — sequential reads, sequential writes.

Contrast with B-trees (Postgres, MySQL): update-in-place, better for reads, more random I/O on writes. Neither is "better"; they trade read vs write amplification.

### Use It

| Pattern | Embodiment |
|---|---|
| Append-only log | Kafka, WALs everywhere |
| LSM tree | RocksDB, Cassandra, LevelDB, HBase |
| B-tree | PostgreSQL, MySQL/InnoDB, SQLite |
| Big sequential scans | Analytics engines, backup/restore |

### War Story

Kafka's original LinkedIn-era design documentation makes the counterintuitive case openly: a "disk-based" log that reads and writes sequentially through the OS page cache can outperform designs that try to keep everything in memory, because linear disk access on even modest hardware streams at hundreds of MB/s. Kafka's entire architecture — an append-only partitioned log — is this lesson wearing a trench coat.

### Checkpoint

- Compute the approximate throughput of an HDD doing random 4 KB reads at 10 ms per seek.
- How does an LSM tree convert random writes into sequential I/O, and what's the price paid at read time?
- Why do B-trees generally favor read-heavy workloads and LSM trees write-heavy ones?

## 05. Processes, threads, and context switches

**MOTTO:** Concurrency is the OS lying to every program about having the machine to itself.

### The Problem

One CPU core, ten thousand things to do. Someone must slice time, isolate the slices from each other, and switch between them — and switching isn't free. Servers have died not from work, but from the overhead of juggling it.

### The Concept

A **process** is a program with its own private virtual address space — a house. A **thread** is an execution stream inside that house — a roommate: cheap to add, shares everything, and can therefore burn the house down. The kernel's scheduler preempts and rotates threads across cores; each **context switch** saves one thread's registers, loads another's, and — the hidden tax — trashes warm CPU caches and TLB entries. Direct cost ~1–10 µs; indirect cost, often more.

```
 Process A (address space) | Process B (address space)
   thread 1  thread 2      |   thread 1
      \        /           |      |
       [ kernel scheduler: save regs, switch, restore ]
            cores: [c0] [c1] [c2] [c3]
```

### Build It

Why "one thread per connection" hits a wall — the arithmetic:

1. Each thread needs a stack: often ~1 MB virtual (less resident). 10K connections ≈ gigabytes of address space and real scheduling load.
2. If most threads are blocked on I/O, the scheduler still must inspect, wake, and switch among them; wake-ups cost switches.
3. 10K threads × even 1K switches/sec × ~3 µs = 30% of a core doing pure bookkeeping — before any real work.
4. Escape hatches: thread pools (bound the count), or event loops (Lesson 07), or user-space "green threads" (goroutines, ~KB stacks, scheduled in-process).

### Use It

| Model | Isolation | Cost | Used by |
|---|---|---|---|
| Process per unit | Strong (own memory) | Heavy | Chrome tabs, Postgres backends |
| OS thread per task | Weak (shared memory) | Medium | Classic Java servers |
| Green threads | Weak | Tiny | Go, Erlang, Java virtual threads |

### War Story

Dan Kegel's 1999 "C10K problem" page posed the era-defining question: why should a beefy server struggle to hold ten thousand concurrent connections? The answer — thread-per-connection overhead — drove a decade of redesign toward event-driven servers like nginx, and the document became one of the most influential webpages in systems engineering.

### Checkpoint

- What does a context switch actually save and restore, and what's the *indirect* cost beyond that?
- Why do Chrome and PostgreSQL use processes where a game engine would use threads?
- Roughly why does thread-per-connection break down around 10K connections but goroutine-per-connection doesn't?

## 06. Concurrency primitives: locks, semaphores, atomics

**MOTTO:** Shared mutable state is a loaded gun; primitives are the safety, not the holster.

### The Problem

Two threads both run `count += 1`. That's three machine steps — load, add, store — and if they interleave, one increment vanishes. No error, no log line, just wrong numbers, rarely, under load, never in tests. Race conditions are the closest thing software has to ghosts.

### The Concept

A **mutex** is a bathroom key: one holder, everyone else waits; the code inside is a *critical section*. A **semaphore** is a parking lot with N spaces: it limits concurrency rather than forbidding it. An **atomic** is hardware doing tiny operations (increment, compare-and-swap) indivisibly — no key needed for a single shelf. And a **condition variable** lets a thread sleep until someone announces the thing it's waiting for.

```
 T1: load count(=5) ---- add -> 6 ---- store 6
 T2:      load count(=5) ---- add -> 6 ---- store 6   <- lost update!

 with mutex:  T1 [lock][load 5][store 6][unlock]
              T2 .......waits....... [lock][load 6][store 7][unlock]
```

### Build It

CAS (compare-and-swap) — the atom from which lock-free code is built:

```python
# hardware guarantees this whole check-and-set is indivisible
def cas(ref, expected, new):        # returns True if it won
    if ref.value == expected:
        ref.value = new; return True
    return False

def atomic_increment(ref):
    while True:                      # optimistic retry loop
        old = ref.value
        if cas(ref, old, old + 1): return
```

The two classic ways to die: **deadlock** (T1 holds A wants B; T2 holds B wants A — cure: acquire locks in a global fixed order) and **contention** (everyone queuing on one hot lock — cure: shard the state, shrink critical sections, or go atomic).

### Use It

Every language ships these (Python `threading.Lock`, Java `synchronized`/`j.u.c`, Go `sync.Mutex`, C++ `std::atomic`). The same ideas reappear at distributed scale — Redis `SETNX` locks, ZooKeeper leases — with a cruel twist: there, the "hardware guarantee" is gone and leases can expire while you still think you hold them.

### War Story

In 1997 the Mars Pathfinder lander began rebooting on Mars: a low-priority task held a mutex needed by a high-priority task, while medium-priority work starved it — the textbook **priority inversion**. JPL diagnosed it from 100+ million miles away and hot-patched the fix (priority inheritance) onto the spacecraft. Your on-call rotation could be worse.

### Checkpoint

- Walk through how two concurrent `count += 1` operations lose an update.
- What's the difference in purpose between a mutex and a semaphore?
- State the standard rule that prevents deadlock, and why it works.

## 07. Event loops and async I/O

**MOTTO:** Don't hire a waiter per table; hire one who never stands still.

### The Problem

Network servers spend almost all their time waiting — for packets, for disks, for slow clients. Thread-per-connection assigns a costly OS thread to do that waiting (Lesson 05's wall). We want one thread to *wait on ten thousand things at once* and only spend effort where something actually happened.

### The Concept

The event loop is a single relentless waiter: the kernel keeps a list of sockets you care about, you ask "which are ready?", and you handle exactly those — never blocking on any one of them. The enabling syscalls are `epoll` (Linux), `kqueue` (BSD/macOS), IOCP (Windows): register many fds once, then harvest ready events in O(ready), not O(watched).

```
 loop forever:
   events = epoll_wait(all 10,000 sockets)   # sleeps until something's ready
   for (socket, event) in events:
       run its handler a little (MUST NOT BLOCK)
       if handler needs I/O -> register interest, return to loop
```

The contract has teeth: one handler that blocks (sleeps, spins, calls a sync API) freezes *every* connection. Async is cooperative multitasking — everyone must actually cooperate.

### Build It

`async/await` is compiler sugar over exactly this loop:

```python
import asyncio

async def handle(reader, writer):
    data = await reader.read(1024)     # 'await' = park here, free the loop
    await asyncio.sleep(0.1)           # pretend to work — without blocking
    writer.write(b"echo: " + data)
    await writer.drain(); writer.close()

async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", 9000)
    async with server: await server.serve_forever()

asyncio.run(main())   # one thread; try 10K concurrent clients against it
```

Each `await` is a voluntary yield back to the loop; the "thread of execution" is just a state machine parked in memory — kilobytes, not megabytes.

### Use It

| Runtime | Model |
|---|---|
| nginx, Redis | Event loop in C (epoll/kqueue) |
| Node.js | Event loop (libuv) + worker pool for the blocking stuff |
| Go | Best of both: blocking-*looking* code, event loop underneath the runtime |
| Python asyncio | Explicit async/await, single loop |

Rule of thumb: I/O-bound + many connections → event loop. CPU-bound → threads/processes; an event loop gains you nothing and one hot handler starves the world.

### War Story

Ryan Dahl introduced Node.js at JSConf EU 2009 with a pointed demo: thread-based servers burn memory and switches to wait, while an event loop waits for free — and JavaScript, having no threads, couldn't cheat. nginx, built by Igor Sysoev on the same event-driven principle as a direct answer to C10K, went on to overtake Apache as the web's most deployed server.

### Checkpoint

- What does `epoll_wait` give you that calling `read()` on 10,000 sockets in a loop does not?
- Why does one blocking call inside an async handler damage all connections, not just its own?
- For a service doing heavy image processing per request, why is an event loop the wrong tool?

## 08. File systems: what happens when you save a file

**MOTTO:** "Saved" is a negotiation between your program, the kernel, and a disk that lies.

### The Problem

Your program wrote the file, the call returned success, the process exited cleanly — and after the power flicked, the file is empty. Nobody lied, exactly. There are three layers of buffering between `write()` and magnetized platter, and each returns "done" meaning something different.

### The Concept

A file system maps names to bytes using **inodes** (metadata: size, permissions, pointers to data blocks), **directories** (name → inode tables), and a block allocator. The treachery is in the write path: `write()` usually just copies into the kernel's **page cache** and returns; actual disk I/O happens seconds later, batched, in whatever order the kernel and the disk's own cache prefer. Journaling file systems (ext4, XFS, NTFS) keep a WAL of *metadata* so a crash can't corrupt the file system itself — but your file's *contents* are your problem.

```
 write("a.txt")                     survives crash?
   -> app buffer (fwrite)              no
   -> kernel page cache (write)        no          <- "success" returned here!
   -> disk write cache  (fsync...)     maybe
   -> platter/flash     (...fsync)     yes
```

### Build It

The crash-safe save, as every database and serious editor does it:

1. Write the full new contents to a temp file: `a.txt.tmp`.
2. `fsync(a.txt.tmp)` — force contents to stable storage.
3. `rename("a.txt.tmp", "a.txt")` — POSIX rename is atomic: readers see old or new, never a mangled hybrid.
4. `fsync` the containing directory — the rename itself is metadata that must also survive.

Skip step 2 and a crash can leave `a.txt` pointing at zero-length garbage; skip step 4 and the rename may quietly not have happened.

### Use It

ext4/XFS (Linux), APFS, NTFS all journal metadata by default, not data. Databases therefore bypass hope entirely: Postgres `fsync`s its WAL on commit; SQLite's whole design is atomic-commit machinery. ZFS and btrfs go further with copy-on-write and checksums — they can detect the disk lying.

### War Story

In 2018 the PostgreSQL community discovered "fsyncgate": on Linux, if a background writeback failed, the error could be reported to *one* `fsync` call and then cleared — a subsequent `fsync` returned success while data was silently gone. Postgres had misunderstood this contract for roughly two decades. The fix: treat any fsync failure as grounds to crash and recover from WAL. Even the experts were being lied to.

### Checkpoint

- Name the buffering layers between `write()` returning and data being durable, and which call forces the crossing.
- Why does write-temp / fsync / rename / fsync-dir guarantee readers never see a partial file?
- What does a journaling file system protect by default — and what does it *not* protect?

## 09. Memory management and garbage collection

**MOTTO:** Someone must free the memory; the only question is who suffers, and when.

### The Problem

Programs allocate constantly. Free memory manually and humans ship use-after-frees and leaks; free it automatically and the collector shows up mid-request like a fire drill — and at p99, your users are the ones standing in the parking lot.

### The Concept

The OS hands processes **virtual memory** (per-process fantasy address space, mapped to physical pages on demand). Above that, language runtimes manage a **heap**. Manual management (C) is fast and lethal. **Tracing GC** (Java, Go, C#, JS, Python's cycle collector) starts from roots (stacks, globals), marks everything reachable, and reclaims the rest. **Reference counting** (Python's primary mechanism, Swift) frees at zero refs — prompt, but cycles need a backup tracer. **Ownership** (Rust) proves lifetimes at compile time: no collector, no pauses, stricter compiler arguments.

```
 roots: [stack] [globals]
          |        |
          v        v
         (A) ---> (B)      reachable: A, B  -> keep
                  (C) <-> (D)   unreachable cycle -> tracing GC frees;
                                 pure refcounting leaks it forever
```

### Build It

Why GCs pause, and how they mostly stopped:

1. Naive mark-and-sweep must freeze the world — pointers can't move under the marker. Pause grows with heap size: multi-GB heap, multi-second pause.
2. **Generational** collectors exploit the fact that most objects die young: collect the nursery often and cheaply, the old space rarely.
3. **Concurrent/incremental** collectors (Go's GC, Java's ZGC/Shenandoah) mark while your code runs, using write barriers to catch mutations — pauses drop to sub-millisecond, paid for as ~few-% throughput tax.
4. Practitioner levers regardless: allocate less on hot paths, reuse buffers/pools, keep heaps sized so collection isn't perpetual.

### Use It

| Strategy | Pause profile | Tax | Languages |
|---|---|---|---|
| Manual | none | your sanity | C |
| Refcounting | tiny, constant | per-assignment overhead; cycles | Python, Swift |
| Tracing GC | rare, once large, now ~ms | throughput %, memory headroom | Java, Go, C# |
| Ownership | none | compile-time fight | Rust |

### War Story

In 2020, Discord published why they rewrote their Read States service from Go to Rust: the service was fast except for latency spikes every couple of minutes — the Go garbage collector (of that era) walking a huge long-lived cache. The Rust rewrite, with no collector, flattened the spikes entirely. Not a verdict on Go — a verdict on *knowing where your pauses come from*.

### Checkpoint

- Why does pure reference counting leak cyclic structures, and which collector design does not?
- What empirical fact about object lifetimes makes generational GC effective?
- Your p50 is 5 ms but p99 is 900 ms in a GC'd service. What's your first hypothesis and how would you confirm it?

## 10. Zero-copy and the page cache

**MOTTO:** The fastest way to move bytes is to stop moving them.

### The Problem

A file server "just" sends files. The naive path — `read()` then `write()` — copies each byte four times and crosses the user/kernel boundary four times: disk→page cache, page cache→your buffer, your buffer→socket buffer, socket buffer→NIC. Your CPU is a highly paid bucket brigade.

### The Concept

Two kernel gifts. The **page cache**: the kernel keeps recently used file pages in otherwise-idle RAM, so repeated reads never touch disk — this is why "free" memory on a healthy Linux box is nearly zero and why the *second* run of anything is fast. **Zero-copy**: `sendfile()` tells the kernel "move file → socket yourself," skipping userspace entirely; with DMA scatter-gather, the CPU may only shuffle descriptors while the NIC pulls data straight from the page cache.

```
 naive:      disk ->[DMA]-> page cache ->copy-> user buf ->copy-> socket buf ->[DMA]-> NIC
                                  (2 copies through userspace, 4 mode switches)
 sendfile:   disk ->[DMA]-> page cache ------------------------->[DMA]-> NIC
                                  (0 userspace copies)
```

### Build It

1. Serve static bytes? Use the primitive: `sendfile(sock, file_fd, offset, count)` — Python exposes `socket.sendfile(f)`; nginx has `sendfile on;`.
2. Need the data mapped, not streamed? `mmap()` the file: page cache pages appear in your address space; reads become memory access, no copy.
3. Measure the cache: run a grep over a big file twice — cold vs warm timings differ by ~100x; `free -h` shows the cache column doing it.
4. Caveat: zero-copy helps when you *don't transform* the bytes. TLS encryption historically forced data through userspace — which is why kernel TLS (kTLS) exists: encrypt in-kernel, keep the zero-copy path.

### Use It

Kafka's throughput story is page cache + `sendfile`: brokers barely touch userspace to fan out logs to consumers. nginx serves static content the same way. The flip side: databases like Postgres partially *fight* the page cache (double buffering with their own pool), and `O_DIRECT` exists for engines that want to manage caching themselves.

### War Story

Netflix's Open Connect appliances — the boxes it places inside ISPs — serve video from FreeBSD using an aggressively tuned `sendfile` path, with Netflix engineers contributing async sendfile and in-kernel TLS work upstream to push a *single commodity server* past 100 Gbps, and later toward 400 Gbps, of video delivery. That headroom is almost entirely "stop copying."

### Checkpoint

- Count the copies and user/kernel crossings in the naive read/write file-serving loop.
- Why does encrypting traffic complicate zero-copy, and what's the kernel's answer?
- Why is near-zero "free" RAM on a Linux server usually good news?

## 11. The network path through the kernel

**MOTTO:** Between the wire and your `recv()` lies a small, opinionated bureaucracy.

### The Problem

"The network is slow" is rarely the network. A packet arriving at your NIC passes through interrupts, kernel queues, protocol code, and socket buffers before your app sees byte one — and each stage can drop, delay, or batch. If you can't name the stages, you can't find the loss.

### The Concept

Follow one inbound packet:

```
 wire -> NIC -> [DMA into ring buffer in RAM] -> IRQ ("mail!")
      -> softirq/NAPI: kernel polls ring, builds skbuffs
      -> IP layer (checksums, routing, firewall/netfilter)
      -> TCP layer (reassembly, ACKs, congestion bookkeeping)
      -> socket receive buffer
      -> your recv() copies to userspace  (finally, a copy you asked for)
```

Backpressure lives at every hop: ring buffer full → silent NIC drops; socket buffer full → TCP advertises a smaller window and the *sender* slows; accept queue full → new connections refused. Interrupt-per-packet would melt a CPU at 10 Gbps, so NAPI switches to polling under load; multi-queue NICs (RSS) spread flows across cores.

### Build It

Field kit — observe each stage on a Linux box:

1. NIC-level drops: `ethtool -S eth0 | grep -i drop` (ring buffer overruns live here).
2. Protocol counters: `netstat -s` — retransmits, listen-queue overflows ("SYNs to LISTEN sockets dropped").
3. Per-socket queues: `ss -tmi` — send/receive buffer occupancy, congestion window.
4. Tuning levers: socket buffer sizes (`net.core.rmem_max`), accept backlog (`somaxconn`), NIC ring sizes. Measure before and after; folklore tuning is how configs rot.

### Use It

When the bureaucracy itself becomes the bottleneck (millions of packets/sec: trading, DDoS scrubbing, load balancers), engineers bypass or shortcut it — DPDK (userspace drivers, poll the NIC directly), XDP/eBPF (run filters at the driver, pre-skbuff), or io_uring (batch syscalls). Costs: burned cores, custom stacks, exotic bugs. Most services should tune, not bypass.

### War Story

Cloudflare's engineering blog series ("How to receive a million packets per second," "Kernel bypass") documented exactly this walk: a stock socket path topping out far below line rate, then each fix — multi-queue spreading, receive batching, and ultimately XDP-based DDoS filtering dropping attack packets at the driver before the kernel spends *any* further work on them. The packet path is their product's front line.

### Checkpoint

- List, in order, the stages an inbound packet traverses from wire to `recv()`.
- What happens upstream when a receiver's socket buffer fills, and why is that a feature?
- Why does the kernel switch from interrupts to polling (NAPI) under high packet rates?

## 12. The cost of everything (a benchmark tour)

**MOTTO:** In God we trust; all others must bring benchmarks.

### The Problem

This phase handed you a dozen claims: caches are fast, seeks are slow, syscalls cost, GC pauses. Believing them is not the same as *knowing* them — and hardware, kernels, and runtimes drift every year. An engineer who measures owns their numbers; an engineer who quotes rents them.

### The Concept

A benchmark is an experiment, and experiments have failure modes: measuring the first run (cold caches), measuring the mean (tails hidden), letting the compiler delete your unused work, or benchmarking your laptop's thermal throttling. The discipline is the same as science class — isolate one variable, warm up, repeat, report distributions, and stay suspicious of numbers that flatter you.

```
 the honest benchmark loop:
   warm up  ->  measure N times  ->  report p50 / p99 / max
        ^                                     |
        +---- change ONE thing  <-------------+
```

### Build It

A micro-harness and your lab agenda:

```python
import time, statistics
def bench(fn, n=30, warmup=5):
    for _ in range(warmup): fn()
    t = []
    for _ in range(n):
        s = time.perf_counter(); fn(); t.append(time.perf_counter() - s)
    t.sort()
    return {"p50": t[n//2], "p99": t[int(n*0.99)-1], "max": t[-1]}
```

Measure, on your own machine: (1) sequential vs random list traversal (Lesson 01); (2) `write()` alone vs `write()+fsync` (Lesson 08 — expect ~1000x); (3) thread spawn vs asyncio task spawn (Lessons 05/07); (4) dict lookup vs local SQLite read vs Redis-in-Docker round trip (Phase 0 lab). Write your numbers down. They're your personal latency table now.

### Use It

| Tool | Layer |
|---|---|
| `time`, `hyperfine` | whole programs |
| `fio` | disk I/O patterns |
| `wrk`, `hey` | HTTP services under load |
| `perf`, flame graphs | where CPU time actually goes |
| `iperf3` | raw network throughput |

Cardinal rule for services: benchmark at realistic concurrency and read the *tail*. A system with a great mean and a 2-second p99 is a bad system experienced occasionally by everyone.

### War Story

Brendan Gregg's flame graphs — born from performance work at Joyent and later Netflix — turned profiler output into a single glanceable picture of where CPU time goes, and became the industry's default way to *see* cost. His accompanying "USE method" (Utilization, Saturation, Errors for every resource) is the checklist version of this entire phase: don't guess, enumerate and measure.

### Checkpoint

- Name three classic ways a benchmark lies, and the countermeasure for each.
- Why report p99 and max rather than the mean for a service benchmark?
- Predict, then measure: how much slower is `write()+fsync` than `write()` on your machine — and why (Lesson 08)?
