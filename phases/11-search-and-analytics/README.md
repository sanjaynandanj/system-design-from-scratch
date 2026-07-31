# Phase 11 — 🔍 Search & Analytics

> Finding needles in exabyte haystacks.

Your database can find a row by ID in microseconds, but ask it "which documents mention 'distributed consensus'?" or "what was revenue by region for the last five years?" and it starts sweating. Search and analytics are the two great specializations of data retrieval — one optimizes for *relevance over text*, the other for *aggregation over history* — and both got there by throwing out the row-store playbook. This phase builds the inverted index, the ranking math, and the columnar engine from scratch, then maps the modern ecosystem: Elasticsearch, vector databases, warehouses, lakes, and the lakehouse peace treaty. It ends with you writing a real search engine in Python, because nothing demystifies BM25 like implementing it.

## 01. Inverted Indexes: How Search Works

**MOTTO:** Don't scan documents for words; keep a list of documents per word.

### The Problem

Naive text search — `SELECT * FROM docs WHERE body LIKE '%consensus%'` — scans every byte of every document per query. At a million documents that's seconds; at web scale it's absurd. A B-tree doesn't save you: it indexes whole values from the *start*, and words live in the middle of documents. You need a structure where lookup cost scales with the *result*, not the corpus.

### The Concept

Flip the mapping. Instead of document → words (the "forward" direction), precompute word → documents. That's exactly the index at the back of a textbook: you don't reread the book to find "entropy"; you look up "entropy" and get page numbers. Each word (**term**) maps to a **postings list** of document IDs — plus, optionally, positions and frequencies for phrase queries and ranking.

```
  Doc1: "the cat sat"        INVERTED INDEX
  Doc2: "the cat ran"        term   -> postings (doc: positions)
  Doc3: "a dog ran"          -----------------------------------
                             cat    -> D1:[1], D2:[1]
  Query: cat AND ran         dog    -> D3:[1]
    postings(cat) = {1,2}    ran    -> D2:[2], D3:[2]
    postings(ran) = {2,3}    sat    -> D1:[2]
    intersect     = {2}  ✓   the    -> D1:[0], D2:[0]
```

Boolean queries become set operations on postings lists: AND = intersect, OR = union, NOT = difference. Phrase queries ("cat ran") intersect postings *and* check adjacent positions.

### Build It

```python
from collections import defaultdict

index = defaultdict(dict)               # term -> {doc_id: [positions]}
def add(doc_id, text):
    for pos, term in enumerate(text.lower().split()):
        index[term].setdefault(doc_id, []).append(pos)

def search_and(*terms):                 # AND query = intersect postings
    postings = [set(index.get(t, {})) for t in terms]
    return set.intersection(*postings) if postings else set()
```

Production concerns the toy skips: postings lists are kept **sorted** so intersection is a linear merge (walk both lists in lockstep, or skip-lists/galloping to leapfrog); doc IDs are **delta-encoded and compressed** (gaps are small numbers — varint or bit-packing shrinks them dramatically); and writes are batched into immutable **segments** that are merged in the background (an LSM-shaped design — updating postings lists in place is brutal).

### Use It

| System | Notes |
|---|---|
| Lucene | The reference implementation; powers Elasticsearch & Solr |
| Tantivy | Lucene's design in Rust |
| PostgreSQL GIN + tsvector | Solid full-text search without new infrastructure |
| SQLite FTS5 | Inverted index in your pocket |

### War Story

The inverted index predates computers (concordances of the Bible were compiled by hand in the 13th century), but its web-scale moment was the 1998 Brin & Page paper "The Anatomy of a Large-Scale Hypertextual Web Search Engine," describing Google's early index: barrels of compressed postings with positional "hits," built by crawling tens of millions of pages on commodity hardware. The core structure in that paper is still recognizably what Lucene builds today.

### Checkpoint

- Why is `LIKE '%term%'` fundamentally unindexable by a standard B-tree?
- How does a phrase query use positional postings? Walk through "cat ran" on the example index.
- Why are postings lists stored sorted by document ID, and what does that enable during intersection?

## 02. Tokenization, TF-IDF, and BM25

**MOTTO:** Matching finds the haystack's needles; ranking decides which needle you actually wanted.

### The Problem

A query for "database replication" might match 50,000 documents. Boolean retrieval treats them all as equal, which is useless — humans read ten results. You need a *score*: which documents are most about these terms? And before any of that, you must decide what a "term" even is — is "Databases" the same as "database"? Is "state-of-the-art" one token or four?

### The Concept

**Tokenization** is the analysis pipeline: split text into tokens, lowercase, maybe strip stopwords ("the", "of"), maybe **stem** ("running" → "run"). Crucially, queries and documents must pass through the *same* pipeline or they'll never meet.

Ranking rests on two intuitions. **TF** (term frequency): a document that says "replication" ten times is more about replication than one that says it once. **IDF** (inverse document frequency): rare terms carry more signal — matching "paxos" means more than matching "system", because everything matches "system". TF-IDF multiplies them. **BM25** (the modern standard) refines TF-IDF with two fixes: term frequency **saturates** (the 50th occurrence adds almost nothing — controlled by k1) and scores are **normalized by document length** (long documents shouldn't win just by being long — controlled by b).

```
                       TF-IDF: score grows forever with TF
  score                     /
    |        ______________/____ BM25: saturates (k1)
    |       /
    |      /
    |_____/________________________ term frequency
         BM25 formula per term t, doc d:
         IDF(t) * TF(t,d)*(k1+1) / (TF(t,d) + k1*(1 - b + b*|d|/avgdl))
```

### Build It

1. Analyze: `tokens = stem(lower(split(text)))` — identically for docs and queries.
2. At index time, store TF per (term, doc), document lengths, and average doc length.
3. IDF per term: `log(1 + (N - df + 0.5) / (df + 0.5))` where N = total docs, df = docs containing the term. (This BM25 variant stays positive.)
4. Score a doc = sum of per-term BM25 contributions for query terms it contains; defaults k1 ≈ 1.2, b ≈ 0.75.
5. Rank with a heap: scan postings for query terms, accumulate scores per doc, return top-k. (Full code in Lesson 10.)

### Use It

| Choice | Tradeoff |
|---|---|
| Stemming (Porter/Snowball) | More recall ("runs"→"run"), occasional weirdness ("universal"→"univers") |
| Stopword removal | Smaller index; breaks phrases like "to be or not to be" |
| BM25 (Lucene default since 6.0) | Robust across corpora; two knobs, rarely needs tuning |
| Learning-to-rank on top | Better relevance; needs click data and ML ops |

### War Story

BM25 comes from the Okapi information-retrieval system at London's City University, developed by Stephen Robertson and Karen Spärck Jones's lineage of probabilistic retrieval work, and battle-tested through the TREC evaluation conferences of the 1990s. Spärck Jones had introduced IDF back in 1972 as "term specificity." Fifty years later, BM25 remains the baseline that embedding models are still measured against — and it still wins on plenty of keyword-heavy workloads.

### Checkpoint

- Why must documents and queries go through the identical analysis pipeline?
- What problem does IDF solve that raw term frequency alone cannot?
- What do BM25's k1 and b parameters each control, and what failure mode of TF-IDF does each address?

## 03. Elasticsearch Architecture

**MOTTO:** Elasticsearch is Lucene with a distributed systems degree and an HTTP habit.

### The Problem

Lucene gives you a world-class inverted index — on one machine, embedded in one JVM. Real corpora exceed one machine; real query loads exceed one machine's CPU; real ops require replication, JSON APIs, and rolling restarts. Someone has to shard the index, route the queries, replicate the segments, and referee cluster membership. That someone is Elasticsearch (and OpenSearch, its fork).

### The Concept

An Elasticsearch **index** is split into **shards**; each shard is a full Lucene index holding a slice of documents (routed by hash of doc ID). Each shard has **replicas** on other nodes for durability and read throughput. Queries **scatter** to one copy of every shard and **gather** top-k results at a coordinating node.

```
  index "logs" (3 primaries, 1 replica each)
     node1         node2         node3
   [ P0 | R2 ]   [ P1 | R0 ]   [ P2 | R1 ]
        ^\            ^             ^
  query  \-- scatter to P0,P1,P2 (or replicas)
          -- each shard returns local top-k
          -- coordinator merges -> global top-k
```

Two more load-bearing facts. **Near-real-time search**: writes land in memory + translog, and become searchable at the next **refresh** (default every 1s) when a new in-memory segment opens — this is why a doc isn't findable the same millisecond you index it. **Segments are immutable**: deletes are tombstones, updates are delete+reinsert, and background merges compact segments (Lucene's LSM-ish heart, straight from Lesson 01).

### Build It

Operating it well means respecting its physics:

1. Shard count is fixed at index creation (resharding = reindex), so plan: aim for shards of ~10–50 GB; avoid thousands of tiny shards (each has fixed overhead in heap and file handles).
2. Time-series data: use time-based indices (`logs-2026.07.31`) with ILM rollover — deleting old data becomes dropping whole indices, which is instant, instead of tombstoning billions of docs.
3. Mappings are schema: decide analyzed `text` vs exact-match `keyword` per field up front; changing analysis means reindexing.
4. Aggregations run distributed too — each shard aggregates locally, the coordinator merges. Some (like distinct counts) are approximate by design (HyperLogLog).
5. Cluster coordination: master-eligible nodes elect a leader via quorum — always run an odd number (typically 3) to survive partitions without split-brain.

### Use It

| System | Notes |
|---|---|
| Elasticsearch | The default; huge ecosystem (Kibana, Beats, Logstash) |
| OpenSearch | AWS-led fork (2021) after Elastic's license change |
| Solr | Same Lucene core, older ecosystem |
| Meilisearch / Typesense | Simpler, instant-search focused, single-purpose |

### War Story

Elasticsearch's early years featured genuinely scary split-brain and data-loss bugs, publicly tracked by the Jepsen distributed-systems tests (Kyle Kingsbury's 2014–2015 analyses found lost writes during partitions). Elastic responded with a multi-year overhaul culminating in a new cluster-coordination layer in Elasticsearch 7 (2019), built on a formally modeled algorithm. It's one of the field's best public case studies of a database growing real consensus underneath an already-huge install base.

### Checkpoint

- Why is a newly indexed document not immediately searchable, and which setting controls the delay?
- Why do time-based indices make retention cheap compared to deleting documents in place?
- What goes wrong with (a) far too few shards and (b) far too many?

## 04. Vector Search and Embeddings

**MOTTO:** Keyword search finds what you said; vector search finds what you meant.

### The Problem

BM25 matches tokens. Query "how do I make my laptop faster" and a document titled "speeding up your notebook computer" scores zero — no shared terms. Synonymy, paraphrase, cross-lingual queries, and image search all break lexical retrieval. You need to match by *meaning*, which means you need a numerical representation where "laptop" and "notebook computer" land near each other.

### The Concept

An **embedding model** (a neural network) maps text/images to dense vectors — say 768 floats — such that semantic similarity becomes geometric proximity (usually cosine similarity). Search becomes **nearest-neighbor lookup**: embed the query, find the closest document vectors. The catch: exact nearest-neighbor over millions of high-dimensional vectors means comparing against everything. So we use **ANN** (approximate nearest neighbor) indexes, trading a sliver of recall for orders-of-magnitude speed. The workhorse is **HNSW**: a multi-layer navigable graph — top layers are sparse "highways" for coarse hops, bottom layers dense "streets" for precision, like zooming from a country map to a city map.

```
  HNSW search for query q:
  L2 (sparse):   A ────────> F              greedy: hop to whichever
  L1:            A ──> C ──> F ──> H        neighbor is closest to q,
  L0 (all pts):  A─B─C─D─E─F─G─H─I         descend a layer, repeat
                              ^ nearest found at L0
```

### Build It

1. Brute force first (and honestly — it's fine to ~1M vectors with numpy/BLAS):

```python
import numpy as np
def top_k(query, doc_matrix, k=10):        # rows are L2-normalized
    sims = doc_matrix @ query              # cosine == dot product
    return np.argsort(-sims)[:k]
```

2. To scale: build an ANN index — HNSW (graph, great recall/latency, RAM-hungry) or IVF (cluster vectors, search only the nearest few clusters), optionally with **product quantization** to compress vectors 10–30x at some recall cost.
3. Recall@k vs latency is *the* tuning axis (HNSW's `efSearch`, IVF's `nprobe`).
4. In practice, run **hybrid search**: BM25 + vector retrieval, fused (e.g., reciprocal rank fusion) — lexical still wins on IDs, names, and rare exact terms; vectors win on paraphrase. Then optionally **rerank** the top ~100 with a heavier cross-encoder model.

### Use It

| System | Notes |
|---|---|
| FAISS / hnswlib | Libraries; you bring the serving layer |
| pgvector | Vectors inside Postgres; one less system |
| Qdrant / Weaviate / Milvus | Dedicated vector DBs: filters + vectors |
| Elasticsearch / OpenSearch kNN | HNSW bolted onto the lexical champion — easy hybrid |

### War Story

The 2019 wave started when embedding models became broadly usable and Facebook AI Research's FAISS library (open-sourced 2017, with the 2017 Johnson, Douze, Jégou "Billion-scale similarity search with GPUs" paper) proved billion-vector search practical. HNSW itself comes from Malkov & Yashunin's 2016 paper. By the LLM/RAG boom of 2023, "vector database" was a funded product category — and practitioners promptly rediscovered why hybrid lexical+vector beats either alone, with BM25 the fifty-year-old comeback kid.

### Checkpoint

- Why does BM25 fail on the query "make my laptop faster" against "speeding up your notebook computer"?
- What does "approximate" mean in ANN search, and which knob trades recall for latency in HNSW?
- Why do production systems run hybrid lexical + vector retrieval instead of vectors alone?

## 05. OLTP vs OLAP

**MOTTO:** One database serves the checkout line; the other serves the boardroom. Don't seat them together.

### The Problem

Your Postgres happily handles orders — until an analyst runs "total revenue by region by month, last 3 years." That query scans a hundred million rows, evicts the hot working set from cache, and checkout latency spikes during it. Transactions want tiny, indexed, concurrent reads/writes of *current* data; analytics wants giant scans and aggregations over *historical* data. One engine, two irreconcilable access patterns.

### The Concept

**OLTP** (online transaction processing): many small operations — "insert this order," "read this user" — needing millisecond latency, high concurrency, and strong consistency. **OLAP** (online analytical processing): few huge queries — "aggregate a year of orders" — needing throughput over columns, not point lookups. The metaphor: OLTP is a bank teller handling one customer's transaction precisely and fast; OLAP is an auditor reading the entire ledger to draw charts. Same ledger, opposite motions.

```
                 OLTP                    OLAP
  op shape   read/write 1-10 rows    scan 10^8 rows, few cols
  latency    ~1 ms                   seconds-minutes OK
  users      thousands concurrent    a handful of analysts/dashboards
  data       current state           full history
  layout     row store + B-trees     column store + compression
  schema     normalized (3NF)        denormalized (star schema)
```

The classic bridge: replicate OLTP data into a dedicated analytical store, modeled as a **star schema** — a central fact table (order line items: amounts, foreign keys) surrounded by dimension tables (customer, product, date) — denormalized for scan-friendly joins and readable BI queries.

### Build It

Separating them, step by step:

1. Keep the OLTP schema normalized and indexed for the app's access paths. No analyst logins on the primary.
2. Ship changes out: nightly batch extracts (simple, stale) or change-data-capture streaming (fresh, more moving parts) into the analytical store.
3. Remodel on arrival: facts + dimensions. An OLTP `orders`/`order_items`/`addresses` web becomes one wide fact table plus a handful of dimensions.
4. Point dashboards and analysts exclusively at the OLAP side; the checkout line never waits for the boardroom again.
5. Know the counter-trend: "HTAP" systems (SingleStore, TiDB, AlloyDB) run both workloads by keeping a row store and a column replica in one system — genuinely useful, still governed by the same physics.

### Use It

| Side | Systems |
|---|---|
| OLTP | PostgreSQL, MySQL, DynamoDB, Spanner |
| OLAP | Snowflake, BigQuery, Redshift, ClickHouse, DuckDB |
| Bridge | Debezium/CDC, Fivetran, Airbyte |
| HTAP | TiDB (TiFlash), SingleStore, AlloyDB columnar engine |

### War Story

The terms crystallized in the early 1990s: Edgar Codd (of relational-model fame) coined "OLAP" in a 1993 paper, and Ralph Kimball's *The Data Warehouse Toolkit* (1996) canonized the star schema, opposite Bill Inmon's top-down normalized-warehouse school — a Kimball-vs-Inmon debate that data teams reenact to this day. The one-liner that survives every fashion cycle: analysts and transactions sharing a database is how you page the on-call with a BI query.

### Checkpoint

- List three dimensions along which OLTP and OLAP workloads differ.
- What is a star schema, and why is denormalization acceptable there when it's a sin in OLTP?
- Why does one big analytical scan degrade OLTP latency even if it's read-only?

## 06. Columnar Storage: Why Analytics Is Sideways

**MOTTO:** If you only ever read two columns, why are you paying to read all forty?

### The Problem

`SELECT region, SUM(amount) FROM orders GROUP BY region` touches two columns. In a row store, those two columns are interleaved with 38 others on every page, so the engine reads ~all of the table's bytes to use ~5% of them. At a billion rows, you're paying 20x in I/O for data you instantly discard. Row layout is optimized for "give me this whole record" — exactly what analytics never asks.

### The Concept

Store the table sideways: all values of `region` contiguously, then all values of `amount`, and so on. A query reads *only the columns it names*. The bonus is compression: a column is a run of same-typed, similar values — `region` might be ten distinct strings repeated a billion times — which compresses savagely (dictionary + run-length encoding), often 10x+. Less data on disk, less I/O, better cache behavior, and same-typed arrays unlock **vectorized execution** (SIMD: sum eight values per CPU instruction).

```
  Row store (pages of whole rows):        Column store:
  [id,region,amount,date,...38 more]      id:     [1,2,3,4, ...]
  [id,region,amount,date,...38 more]      region: [W,W,W,E, ...] -> dict+RLE: tiny
  [id,region,amount,date,...38 more]      amount: [9.5,3.2, ...] -> delta-packed
     read EVERYTHING for 2 columns        date:   [...]
                                             read ONLY region + amount
```

The price: reassembling one full row means one fetch *per column* (terrible point reads), and single-row inserts/updates touch every column file (terrible OLTP writes). Hence columnar systems ingest in large batches and pair with a row-store OLTP side (Lesson 05).

### Build It

Anatomy of a Parquet-style columnar file:

1. Partition rows into **row groups** (e.g., 128 MB); within each, store one compressed **column chunk** per column.
2. Encode per column: dictionary encoding for low-cardinality strings, run-length for repeats, delta + bit-packing for sorted ints; then general compression (ZSTD) on top.
3. Keep **zone maps**: min/max (and null counts) per chunk in the footer. `WHERE date >= '2026-07-01'` skips every chunk whose max date is June — predicate pushdown means most of the file is never read.
4. Execute vectorized: operators process batches of ~1000 values in tight loops over arrays, not row-at-a-time function calls.
5. Sort order matters: sorting the table by a common filter column (say, date) makes zone maps surgical. Choosing the sort key is the columnar analog of choosing an index.

### Use It

| Thing | Role |
|---|---|
| Parquet / ORC | Columnar *file formats* — the lingua franca of data lakes |
| ClickHouse | Columnar engine famous for raw speed |
| DuckDB | In-process columnar OLAP — "SQLite for analytics" |
| Arrow | Columnar *in-memory* format for zero-copy interchange |
| Snowflake/BigQuery/Redshift | Warehouses; columnar inside |

### War Story

The academic shot was the C-Store paper (Stonebraker et al., VLDB 2005), which argued row stores were "one size fits all" relics for analytics and demonstrated order-of-magnitude wins; it commercialized as Vertica. Google's Dremel paper (2010) showed columnar storage over nested data at web scale, later surfacing publicly as BigQuery — and Dremel's record-shredding format directly inspired Parquet (Twitter + Cloudera, 2013), now the default answer to "what format is the data lake in?"

### Checkpoint

- Why does columnar layout compress so much better than row layout?
- What is a zone map, and how does it let a query skip most of a file?
- Why are single-row updates painful in a columnar store, and how do real systems cope?

## 07. Warehouses, Lakes, and Lakehouses

**MOTTO:** The warehouse is a curated library; the lake is a garage full of boxes; the lakehouse is the garage after you installed shelves and a card catalog.

### The Problem

The classic warehouse wants structured, modeled, schema-on-write data — but half your data is JSON logs, clickstreams, and images that don't fit neatly, and warehouse storage used to be expensive enough that teams threw raw data away. The lake said "dump everything cheap in object storage, decide later" — and without transactions or enforcement, many lakes rotted into swamps: undocumented files, partial writes, no idea what's current. You want warehouse *reliability* on lake *economics*.

### The Concept

Three generations:

```
  WAREHOUSE                 LAKE                      LAKEHOUSE
  schema-on-write           schema-on-read            lake + table format layer
  SQL, ACID, BI-ready       any format, any tool      Parquet + txn log =
  $$$/TB (historically)     $/TB (S3/GCS)             ACID tables on S3
  structured only           structure optional        SQL + ML on one copy
  Snowflake/BigQuery        S3 + Parquet + Spark      Delta Lake/Iceberg/Hudi
```

The lakehouse's trick is a **table format**: a transaction log (a sequence of JSON/Avro manifest files in the object store) that records exactly which Parquet files constitute the table at each version. Writers commit atomically by adding a new log entry; readers see consistent snapshots; old versions remain queryable (time travel). It's MVCC, rebuilt on top of a dumb file store.

### Build It

How a lakehouse commit works (Iceberg/Delta style):

1. Table state = the latest committed metadata: a manifest listing data files, schema, and partition info.
2. A writer writes *new* Parquet files (never mutating old ones), then attempts to commit metadata version N+1 via an atomic operation (conditional put / metastore swap).
3. Two concurrent writers: one wins the atomic commit; the loser sees the new version and retries — optimistic concurrency, with conflict checks (did the winner touch my files?).
4. Readers pin a snapshot version for the whole query: consistent reads with zero locks.
5. Housekeeping is real work: compact small files (streaming writers produce confetti), expire old snapshots, and cluster/sort data for zone-map pruning.

Organizationally, lakes/lakehouses are commonly layered bronze → silver → gold (raw → cleaned → business-ready) so consumers know what they're drinking.

### Use It

| System | Notes |
|---|---|
| Snowflake / BigQuery | Warehouses (both now also read table formats — lines are blurring) |
| Delta Lake | Databricks' table format; tightest Spark integration |
| Apache Iceberg | Vendor-neutral table format; broad engine support — current momentum leader |
| Apache Hudi | Table format with strong upsert/incremental focus |
| Trino / Spark / DuckDB | Engines that query lakehouse tables directly |

### War Story

The pendulum swung in public: Hadoop-era lakes (2010s) earned the "data swamp" epithet in countless retrospectives; Snowflake's 2020 IPO — among the largest software IPOs ever — proved the cloud warehouse thesis; and Databricks answered with the "lakehouse" term and the CIDR 2021 lakehouse paper (Armbrust et al.), having open-sourced Delta Lake in 2019. Netflix, meanwhile, built Iceberg to fix Hive-table correctness at petabyte scale and donated it to Apache in 2018 — and by the mid-2020s even Snowflake and BigQuery were racing to speak Iceberg.

### Checkpoint

- What's the difference between schema-on-write and schema-on-read, and what failure mode does each risk?
- How does a table format achieve ACID commits on an object store that only offers atomic single-object operations?
- Why do streaming writers create a "small files problem" for lakehouses, and what's the remedy?

## 08. ETL vs ELT

**MOTTO:** ETL cooks in a cramped kitchen before the party; ELT brings groceries and cooks in the warehouse's industrial kitchen.

### The Problem

Data must travel from source systems (OLTP DBs, SaaS APIs, event streams) into analytical stores — and it never arrives analysis-ready. The old constraint: warehouses were expensive and weak, so you transformed data *before* loading, in external processing servers. That put business logic in opaque pipeline code, forced you to decide what to keep upfront, and meant every new question required replumbing. Cloud warehouses removed the constraint; the workflow needed to notice.

### The Concept

**ETL**: Extract → Transform (in a middle tier: Informatica, custom Spark) → Load only the polished result. **ELT**: Extract → Load *raw* into cheap warehouse/lake storage → Transform inside the warehouse with SQL, as many times as you like. The pivot is economics: when storage is cheap and the warehouse's engine is the most powerful compute you own, transforming *after* loading means you keep raw history forever and can re-derive any table when logic changes — instead of discovering that the data you now need was filtered out in 2023 by a Perl script nobody can read.

```
  ETL:  sources -> [transform server] -> warehouse (curated only)
                        ^ logic hidden here; raw data discarded

  ELT:  sources -> warehouse RAW layer -> SQL models -> STAGING -> MARTS
                     keep forever         (dbt: versioned,   BI-ready
                                           tested, rerunnable)
```

### Build It

The modern ELT workflow:

1. Extract & load with dumb-on-purpose connectors (Fivetran/Airbyte or CDC): land source tables raw, append-only, into a `raw` schema.
2. Transform as layered SQL models: staging (rename/cast/dedupe) → intermediate (joins, business logic) → marts (facts & dimensions for BI). Each model is a `SELECT` materialized as a table/view.
3. Everything in git: transformations are code-reviewed, tested (uniqueness, non-null, referential integrity checks), and documented with lineage — this is dbt's whole pitch.
4. Rebuild is cheap: logic change? Rerun the DAG from raw. Incremental models process only new partitions when full rebuilds get pricey.
5. Watch the two failure modes: warehouse compute bills (transformation isn't free, it's just elsewhere) and the temptation to let "load raw" mean "govern nothing" — PII must still be handled at ingestion.

### Use It

| Stage | Tools |
|---|---|
| Extract/Load | Fivetran, Airbyte, Debezium, Kafka Connect |
| Transform-in-warehouse | dbt, Dataform, plain SQL + orchestration |
| Orchestration | Airflow, Dagster, Prefect |
| Classic ETL | Informatica, Talend, SSIS, custom Spark jobs (still fine for heavy non-SQL transforms) |

### War Story

dbt began in 2016 as an open-source tool from Fishtown Analytics (later dbt Labs) and became the center of the self-described "modern data stack," turning warehouse transformation into a software-engineering discipline — version control, tests, CI — and coining "analytics engineer" as a job title. The broader lesson echoes MapReduce's (see Phase 12): when compute moves next to the data, whole toolchains and job descriptions reorganize around it.

### Checkpoint

- What economic shift made ELT rational when it would have been wasteful in 2005?
- Why does keeping raw data loaded (not just transformed outputs) make logic changes cheap?
- Name a workload where classic ETL / external transformation still beats in-warehouse SQL.

## 09. Real-Time Analytics

**MOTTO:** Yesterday's dashboard is a history lesson; some decisions need the last ten seconds.

### The Problem

The warehouse answers "how did we do last quarter?" superbly — via batch loads, hours after the fact. But fraud scoring, ops dashboards during an incident, live A/B monitoring, and "is the checkout broken *right now*?" need query results over data that's seconds old, at sub-second query latency, often for many concurrent users. Batch warehouses fail the freshness bar; OLTP databases fail the aggregation-scan bar. This is a third workload.

### The Concept

Real-time analytics systems sit at the awkward intersection: **streaming ingest** (from Kafka, visible in ~seconds) + **columnar/OLAP query shapes** (aggregations over millions of rows) + **interactive latency** (sub-second, high QPS). The trick is an LSM-flavored columnar design: events land in a write-optimized in-memory segment that is immediately queryable, then get flushed and compacted into immutable columnar segments — queries transparently merge "the hot last few minutes" with "the cold compressed past."

```
  Kafka ──> [ in-memory segment ]  <── queries see BOTH, merged
                   | flush (seconds-minutes)
                   v
            [ immutable columnar segments ] ── background compaction
  freshness: seconds        query latency: <1s        history: months
```

Complementary trick: **streaming materialized views** — precompute the aggregation continuously (e.g., orders-per-minute per region) as events arrive, so the dashboard reads a tiny, always-current result instead of re-scanning (the stream-processing world of Phase 12 meets the serving world here).

### Build It

Designing a real-time metrics pipeline:

1. Events flow through Kafka; the analytics store ingests continuously (per-second visibility).
2. Pre-aggregate what you can: if dashboards only ever show per-minute rollups, ingest or materialize minute buckets — 100x less data to scan.
3. Partition segments by time; retention drops old segments wholesale (rhymes with Lesson 03's time-based indices).
4. Handle late/duplicate events: at-least-once ingest plus idempotent upserts or dedup keys, or accept small error on counters.
5. Serve dashboards with denormalized, purpose-shaped tables — real-time stores hate big joins at query time; join upstream (in the stream or at ingest).

### Use It

| System | Notes |
|---|---|
| Apache Druid | The pattern's pioneer; time-partitioned segments |
| ClickHouse | General columnar speed demon; increasingly the default |
| Apache Pinot | Built at LinkedIn for user-facing, high-QPS analytics |
| Materialize / RisingWave | Streaming materialized views as the product |
| Tinybird | Managed ClickHouse-based APIs over streams |

### War Story

Apache Pinot was built at LinkedIn to power the member-facing "Who Viewed Your Profile" analytics — OLAP queries served to *every user* interactively, not just internal analysts, a use case documented in LinkedIn engineering posts and Pinot's papers. Druid, born at Metamarkets around 2011 for ad-tech dashboards, published its design in a 2014 paper. Both prove the category's founding claim: with the right segment design, "analytics" can be a product feature with p99s in milliseconds.

### Checkpoint

- Why does real-time analytics need a different engine than both the OLTP database and the batch warehouse?
- How does the hot-segment/cold-segment design deliver both second-level freshness and fast scans?
- When would a streaming materialized view beat scan-on-query, and what flexibility do you give up?

## 10. Build a Search Engine From Scratch

**MOTTO:** You don't understand BM25 until your own code ranks the right document first.

### The Problem

You've now met tokenization, inverted indexes, and BM25 as separate ideas. Time to make them one artifact: a working search engine — index a corpus, run ranked queries, return top-k — in ~80 lines of dependency-free Python. Everything Lucene does is an optimization of what you're about to write.

### The Concept

Three stages, one pipeline: **analyze** text into terms → build the **inverted index** with term frequencies (plus doc lengths for normalization) → **score** query terms against postings with BM25 and heap out the top-k.

```
  "The cat sat..." ──analyze──> [cat, sat] ──index──> postings + doc lengths
                                                          |
  "cat"           ──analyze──> [cat] ──────score──> BM25 ──> ranked doc IDs
```

### Build It

```python
import math, re, heapq
from collections import defaultdict, Counter

TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it"}

def analyze(text):
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]

class SearchEngine:
    def __init__(self, k1=1.2, b=0.75):
        self.k1, self.b = k1, b
        self.postings = defaultdict(dict)   # term -> {doc_id: tf}
        self.doc_len = {}                   # doc_id -> token count

    def index(self, doc_id, text):
        terms = analyze(text)
        self.doc_len[doc_id] = len(terms)
        for term, tf in Counter(terms).items():
            self.postings[term][doc_id] = tf

    def _idf(self, term):
        n, df = len(self.doc_len), len(self.postings.get(term, {}))
        return math.log(1 + (n - df + 0.5) / (df + 0.5))   # always positive

    def search(self, query, k=5):
        avgdl = sum(self.doc_len.values()) / len(self.doc_len)
        scores = defaultdict(float)
        for term in analyze(query):
            idf = self._idf(term)
            for doc_id, tf in self.postings.get(term, {}).items():
                norm = 1 - self.b + self.b * self.doc_len[doc_id] / avgdl
                scores[doc_id] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return heapq.nlargest(k, scores.items(), key=lambda kv: kv[1])

# Drive it:
docs = {
    1: "The cat sat on the mat. The cat was happy.",
    2: "Dogs and cats are common household pets.",
    3: "Distributed systems require consensus protocols like Raft.",
    4: "The mat was red. A very red mat indeed, a mat of mats.",
}
se = SearchEngine()
for doc_id, text in docs.items():
    se.index(doc_id, text)
print(se.search("cat on a mat"))   # doc 1 first: has both terms, sane length
print(se.search("consensus"))      # doc 3: rare term, huge IDF
```

Extensions worth attempting: positional postings for phrase queries; snippet highlighting; incremental indexing with segment merges; then swap `postings` for sorted on-disk runs and feel Lucene's design pressures firsthand.

### Use It

This toy is honestly comparable, in structure, to SQLite FTS5 and Tantivy's core loop. What production adds: compressed on-disk postings, segments and merging, faceting/aggregations, distribution (Lesson 03), and analysis chains for real languages (CJK tokenization, stemming, synonyms).

### War Story

Doug Cutting wrote Lucene in 1999 as a side project in Java — then a contrarian language choice for performance software — and gave it to Apache in 2001. The same Cutting later co-created Nutch and Hadoop; a remarkable share of this phase and the next traces to one engineer's open-source side projects. Lucene's core is still recognizably the loop you just wrote, twenty-five years of optimization deep.

### Checkpoint

- In the demo corpus, why does doc 4's mat-spam not let it crush doc 1 on the query "cat on a mat"? (Name both BM25 mechanisms involved.)
- What breaks in this implementation at 100M documents, and which production techniques (from Lessons 01–03) fix each break?
- Add-a-feature thought experiment: what must change in the index structure to support the phrase query "cat sat"?
