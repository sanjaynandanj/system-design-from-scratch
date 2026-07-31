# Phase 18 — 🌩️ AWS, GCP & Azure in Practice

> The same ideas, three price tags. Map every concept to a managed service.

Everything you learned in Phases 0–17 — replication, partitioning, queues, caches, consensus — exists as a product with a billing meter attached. This phase is the translation layer: you say "I need an ordered, replayable log," and we tell you what that's called on AWS, GCP, and Azure, what it actually costs you in surprises, and where the sharp edges are. The clouds agree on the concepts and disagree on the defaults, the limits, and the pricing shapes — and those disagreements are exactly where architectures go wrong. By the end, you'll read a whiteboard diagram and see three concrete bills.

## 01. The Cloud Mental Model: Regions, Zones, and the Shared-Responsibility Line

**MOTTO:** A region is a blast radius; an availability zone is a failure domain; everything else is marketing.

### The Problem

You're buying datacenters without buying datacenters. Before you pick a single service, you need to know what physical isolation you're actually getting, what the provider promises to keep alive, and where their responsibility ends and yours begins. Get this wrong and you'll build a "highly available" system where every replica shares one power feed.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Isolation unit | Availability Zone (AZ) — distinct datacenters, independent power/network | Zone — similar promise, zones within a region | Availability Zone — but not every region has them |
| Region model | Regions are hard-isolated; most services are regional | Regions similar, but several services (VPC, load balancing) are natively global | Regions come in "paired region" couples for DR and platform updates |
| Multi-AZ default | You opt in per service (Multi-AZ RDS, cross-AZ ASGs) | You opt in; some managed services default to zonal | You opt in; zone-redundant vs. zonal SKUs of the same service |
| Global backbone | Private inter-region backbone | Famous global fiber network; global VPC rides on it | Global backbone; Front Door as the global edge |
| Responsibility model | Shared Responsibility Model | Shared Fate (their branding, same idea) | Shared Responsibility |

The big philosophical split: AWS treats the region as the unit of everything — global behavior is something you assemble. GCP makes several primitives global by default (one VPC can span the planet), which is convenient right up until a global control plane has a bad day. Azure's twist is that AZ support varies by region and by service SKU, so "we deployed to Azure" doesn't automatically mean "we're zone-redundant" — you must check per service.

### Design With It

This is Phase 8 (failure domains) and Phase 13 (reliability) made purchasable. The standard shape: run stateless compute across ≥3 AZs behind a load balancer, keep state in a service that replicates across AZs for you, and treat cross-region as a separate, deliberate DR project with an RPO/RTO budget.

```
        Region us-east-1 (blast radius)
  ┌─────────────────────────────────────┐
  │  AZ-a        AZ-b        AZ-c       │
  │  [app][db]   [app][db]   [app]      │
  │      └──── replication ────┘        │
  └─────────────────────────────────────┘
        │  async, budgeted RPO
        ▼
        Region us-west-2 (DR)
```

Above the shared-responsibility line, the provider patches hypervisors and replaces disks. Below it, *you* still own data classification, IAM policy, app security, and — crucially — the decision to be multi-AZ at all.

### Gotchas & Cost Traps

- Cross-AZ data transfer is billed per GB on all three clouds. A chatty microservice mesh spread "for HA" across zones can quietly become a top-five line item.
- An AZ name like `us-east-1a` maps to different physical zones in different AWS accounts (zone IDs fix this). Coordinating "same AZ" across accounts by letter doesn't work.
- Azure services have separate zonal vs. zone-redundant SKUs; picking the cheap one silently drops your HA story.
- Many "global" services (AWS IAM, CloudFront config, GCP's global control planes) are homed in one region under the hood — often us-east-1 for AWS. Region-down can still hurt your "unaffected" regions' control plane.
- SLAs pay out service credits, not your lost revenue. An SLA is a refund policy, not an availability guarantee.

### War Story

June 2, 2019: a Google Cloud maintenance config intended for a small group of servers was applied to a much larger set, causing network congestion that degraded GCP, YouTube, Gmail, and Snapchat for about four hours — including some of Google's own tooling for fixing it. A global network is a global blast radius; regional isolation only helps if the control plane is isolated too.

### Checkpoint

- Why can two services deployed "in the same region" still fail independently — and why might two in different AZs fail together?
- Your CTO says "we're on three AZs, we're safe." Name two failure modes that statement doesn't cover.
- Which side of the shared-responsibility line does "an engineer made an S3 bucket public" fall on?

## 02. Compute: EC2 vs Compute Engine vs Azure VMs

**MOTTO:** VMs are the cloud's assembly language — you should be able to read it, and mostly avoid writing it.

### The Problem

You need CPUs and RAM without buying servers. Raw VMs are the most flexible and least managed thing a cloud sells: you get a kernel and a bill, and everything else — patching, scaling, failure recovery — is your problem. The real skill is knowing the instance-family alphabet, the discount mechanics, and when to skip VMs entirely.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Service | EC2 | Compute Engine | Azure Virtual Machines |
| General purpose | M family (m7i, m7g) | N family (n2, n2d), E2 | D series (Dsv5) |
| Compute optimized | C family | C family (c2, c3) | F series |
| Memory optimized | R and X families | M family | E and M series |
| Burstable / cheap | T family (t3, t4g) | E2 shared-core | B series |
| ARM chips | Graviton (any `g` suffix) | Tau T2A, Axion | Ampere Altra / Cobalt (Dps, Eps) |
| Interruptible | Spot Instances (2-minute reclaim notice) | Spot VMs (~30-second notice) | Spot VMs (~30-second eviction) |
| Custom sizing | Fixed sizes only | Custom machine types (dial vCPU/RAM independently) | Fixed sizes only |
| Commitment discounts | Savings Plans, Reserved Instances | Committed use discounts + automatic sustained-use discounts | Reservations, Savings Plans |

Meaningful differences: GCP is the ergonomic outlier — custom machine types let you right-size exactly, and sustained-use discounts apply automatically with zero commitment paperwork. AWS has the deepest catalog (hundreds of instance types) and the most mature ARM story with Graviton, which typically offers meaningfully better price-performance for compatible workloads. Azure's differentiators are enterprise-shaped: Hybrid Benefit lets you bring existing Windows/SQL Server licenses, which can change the math dramatically for Microsoft shops. Spot pricing on all three runs at steep discounts (often well over half off) in exchange for eviction risk.

### Design With It

This is Phase 1 (hardware) plus Phase 9 (scaling) as a product. VMs slot in behind a load balancer in an auto-scaling group (AWS ASG / GCP Managed Instance Group / Azure VM Scale Set), scaling on a metric you learned to pick in Phase 13.

```
  LB ──> [ASG / MIG / VMSS: min=3, max=30]
              │ scale on CPU or queue depth
              ├── on-demand baseline (survives anything)
              └── spot pool (cheap burst, evictable)
```

But default to *not* using VMs: if your workload is a container, use managed containers or Kubernetes (Lesson 11); if it's event-driven, use serverless (Lesson 10). Reach for raw VMs when you need specific kernels, GPUs, licensed software, weird networking, or long-lived stateful daemons.

### Gotchas & Cost Traps

- Forgotten instances are the classic cloud bill killer. A VM bills every hour whether it does work or not — tag everything, and auto-stop dev machines.
- Spot/preemptible eviction notice is short (as little as ~30 seconds on GCP and Azure). If your app can't checkpoint or drain that fast, spot will corrupt your assumptions, not just your pods.
- Egress and cross-AZ traffic bill separately from the instance. The VM is often the *cheap* part of running a VM.
- Burstable (T/B/e2 shared-core) instances run on CPU credits; a sustained load exhausts credits and throttles you — a nasty surprise during your first real traffic spike.
- Vertical scaling requires a stop/start on most types, which means downtime unless you built for it in Phase 9.

### War Story

February 29, 2012: a leap-day bug in Azure's certificate-generation logic (certs dated one year ahead, to a nonexistent Feb 29, 2013) made VM agents fail to start, and the platform's automated recovery interpreted the failures as hardware faults — cascading into a roughly day-long, widespread Azure compute outage. Date math plus well-meaning automation is a classic cascade recipe.

### Checkpoint

- Your batch pipeline runs nightly for 4 hours and can checkpoint every minute. Which purchase model fits, and what must the code tolerate?
- Why might a Graviton/ARM instance be cheaper per unit of work, and what should you verify before migrating?
- Name two workload traits that justify raw VMs over containers or serverless.

## 03. Object Storage: S3 vs Cloud Storage vs Blob Storage

**MOTTO:** Object storage is the cloud's center of gravity — everything else orbits it.

### The Problem

You need to store an effectively unlimited number of blobs — images, backups, data-lake files, static sites — with eleven-nines-style durability, without ever thinking about disks. Object storage is the one service every architecture uses, so its storage classes, consistency model, and access patterns are foundational knowledge.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Service | S3 | Cloud Storage (GCS) | Blob Storage |
| Hot tier | S3 Standard | Standard | Hot |
| Warm/cool tiers | Standard-IA, One Zone-IA | Nearline (30-day min), Coldline (90-day min) | Cool, Cold |
| Archive | Glacier Instant / Flexible / Deep Archive | Archive (365-day min) | Archive (requires rehydration) |
| Auto-tiering | Intelligent-Tiering | Autoclass | Lifecycle management policies |
| Consistency | Strong read-after-write (since Dec 2020) | Strong | Strong |
| Time-limited URLs | Presigned URLs | Signed URLs | SAS tokens |
| Versioning & locks | Versioning, Object Lock (WORM) | Versioning, retention policies | Versioning, immutability policies |

The consistency wars are over — all three are strongly consistent now (S3 was famously eventually consistent until late 2020; old blog posts about "read-after-write except overwrite" are obsolete). The interesting differences: GCS keeps millisecond first-byte latency on *every* class including Archive — you pay retrieval fees but never wait. Azure's Archive tier is genuinely offline: rehydration takes hours. AWS splits the difference with Glacier Instant Retrieval (fast) versus Deep Archive (hours, cheapest). All three charge per GB stored, per request, and per GB retrieved from cold tiers, with minimum storage durations on cold classes.

### Design With It

This implements Phase 4's "write path vs. storage" separation and Phase 9's stateless-service ideal: get large payloads out of your databases and off your app servers. The canonical upload pattern uses time-limited URLs so bytes never touch your backend:

```
  client ──POST /request-upload──> API (authz, returns presigned/signed/SAS URL)
  client ──PUT bytes────────────> object store (direct)
  object store ──event──────────> queue ──> thumbnailer / virus scan / indexer
```

Lifecycle rules then age objects down the tiers automatically: hot for 30 days → cool → archive → delete. Pair with a CDN (Lesson 9) for public reads, and use bucket events as the trigger layer for async pipelines (Phase 7).

### Gotchas & Cost Traps

- Request pricing bites at small-object scale: a billion 4 KB objects costs little to store and a lot to PUT, LIST, and transition. Lifecycle *transitions* themselves are billed per object.
- Cold-tier minimum durations mean deleting or re-tiering early still charges you for the full minimum period. Archiving churny data can cost more than leaving it hot.
- Egress to the internet is the lock-in tax on all three clouds (more in Lesson 14). Data flows in free and pays to leave.
- Public-bucket misconfiguration is a perennial breach headline. Default-deny, block public access at the account level, and treat exceptions as reviewed changes.
- Listing is not free and not fast at scale: paginated LIST calls over hundreds of millions of keys is an anti-pattern — keep an inventory/index (or use the provider's inventory reports) instead.

### War Story

February 28, 2017: an AWS engineer debugging the S3 billing system mistyped a command argument and removed far more capacity than intended, taking down S3 in us-east-1 for about four hours — and with it a large chunk of the internet, including the AWS status dashboard itself, which depended on S3. The postmortem gift to the industry: tools now refuse to remove capacity below safety thresholds.

### Checkpoint

- Why does the presigned-URL upload pattern scale better than proxying uploads through your API servers?
- You store daily database backups, retained 7 years, restored maybe once a year. Which tier on each cloud, and what fee should you budget for the restore?
- What two billing dimensions besides GB-stored routinely surprise object-storage users?

## 04. Relational Databases: RDS & Aurora vs Cloud SQL & AlloyDB vs Azure SQL & Flexible Server

**MOTTO:** Managed Postgres is the boring default; the cloud-native tier is what you graduate to, not start with.

### The Problem

You want Postgres or MySQL with backups, patching, failover, and replicas handled by someone else. Every cloud sells this at two tiers: "your favorite database, hosted" and "our re-architected version with storage/compute separation." Knowing which tier you're buying — and when the fancy one is worth it — is the game.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Hosted classic engines | RDS (Postgres, MySQL, MariaDB, SQL Server, Oracle, Db2) | Cloud SQL (Postgres, MySQL, SQL Server) | Azure Database for PostgreSQL / MySQL Flexible Server; SQL Managed Instance |
| Cloud-native tier | Aurora (MySQL- & Postgres-compatible) | AlloyDB (Postgres-compatible) | Azure SQL Database Hyperscale |
| Storage architecture (native tier) | Log-structured storage, 6 copies across 3 AZs; compute reads pages from shared storage | Disaggregated storage + columnar in-memory engine for analytics | Page servers + log service; scale storage past classic limits |
| Read replicas | RDS: engine-level; Aurora: up to 15 replicas off shared storage | Cloud SQL replicas; AlloyDB read pools | Replicas / Hyperscale named replicas |
| Serverless option | Aurora Serverless v2 (fine-grained capacity scaling) | (Cloud SQL: no; AlloyDB has flexible sizing) | Azure SQL serverless tier (auto-pause) |
| HA model | Multi-AZ standby (RDS) or inherent (Aurora) | Regional HA with automatic failover | Zone-redundant deployment options |

The shared idea in the cloud-native tier is Phase 4's log-structured separation of compute and storage: Aurora ships only redo log records to a distributed storage layer, so replicas are cheap (they read the same storage) and failover is fast. AlloyDB adds a columnar engine that accelerates analytical queries on your operational data. Azure's Hyperscale removes the storage ceiling of classic Azure SQL. Pricing shape: classic tiers bill instance-hours + storage; Aurora adds per-million I/O charges (or a flat I/O-optimized configuration); serverless tiers bill on a capacity unit that scales with load.

### Design With It

This is Phase 5 (replication) purchased as checkboxes. Standard wiring: primary in AZ-a, synchronous standby in AZ-b (HA, invisible to you), async read replicas for read scaling (Phase 9), and — critically — a connection pooler, because serverless app tiers (Lesson 10) will exhaust Postgres connections instantly.

```
  apps ──> pooler (RDS Proxy / built-in poolers / PgBouncer)
              ├──> primary  (writes)
              └──> replicas (reads — accept staleness, Phase 5!)
```

Read replicas are asynchronous: read-your-writes is *not* guaranteed. Route session-critical reads to the primary or use the stickiness patterns from Phase 5.

### Gotchas & Cost Traps

- Aurora's standard configuration bills per I/O operation; a scan-heavy workload can make I/O rival the compute bill. Measure before and after choosing the I/O-optimized flavor.
- Serverless databases that auto-pause save money and then greet your first morning user with a multi-second resume. Know your traffic shape.
- Failover isn't free at the application layer: DNS-based failover leaves stale connections. Your driver needs timeouts and retry logic (Phase 13) or "automatic failover" becomes "automatic 5-minute outage."
- Storage auto-grows but rarely auto-shrinks. Deleting a terabyte doesn't cut the bill until you do surgery.
- Major-version upgrades remain *your* scheduled event on every cloud — managed doesn't mean "never think about Postgres 12 EOL."

### War Story

April 21, 2011: a network change during maintenance in AWS us-east-1 dropped a chunk of the EBS network onto a low-bandwidth backup path; EBS nodes lost their replicas and triggered a "re-mirroring storm" that consumed all spare capacity. Multi-AZ RDS instances stuck in the middle of failover were down for days for some customers — the incident that taught the industry that control planes, too, are a failure domain.

### Checkpoint

- What does Aurora's "ship the log, not the pages" architecture buy you for replicas and failover, in Phase 4/5 terms?
- Why do Lambda-style compute tiers plus vanilla Postgres end in connection exhaustion, and what's the fix?
- Your read replica lags 2 seconds behind. Which user-facing flows break, and how do you route around it?

## 05. NoSQL: DynamoDB vs Bigtable & Firestore vs Cosmos DB

**MOTTO:** Your partition key is the whole design; everything else is configuration.

### The Problem

You need single-digit-millisecond key-based access at any scale, and you're willing to trade SQL's flexible queries for it. Each cloud's answer embodies Phase 5 partitioning with different data models and pricing meters — and all of them will happily let you design a hot partition that melts at your first viral moment.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Service | DynamoDB | Bigtable (wide-column) and Firestore (documents) | Cosmos DB |
| Data model | Key-value / wide items, 400 KB item limit | Bigtable: rows + column families, single row-key index; Firestore: documents/collections | Documents (plus MongoDB, Cassandra, Gremlin, Table APIs) |
| Capacity model | On-demand (per-request) or provisioned RCU/WCU with autoscaling | Bigtable: nodes you size; Firestore: pure per-operation | Provisioned RU/s, autoscale RU/s, or serverless |
| Secondary indexes | GSIs / LSIs | Bigtable: essentially none (design the row key); Firestore: automatic indexing | Automatic indexing (tunable policy) |
| Consistency | Eventually consistent reads by default; strongly consistent option (same region) | Bigtable: eventual across replicated clusters; Firestore: strong | Five tunable levels: strong → bounded staleness → session → consistent prefix → eventual |
| Multi-region writes | Global Tables (active-active, last-writer-wins) | Bigtable multi-cluster routing; Firestore multi-region configs | Multi-region writes with pluggable conflict resolution |

The pricing shapes tell you the intended workloads. DynamoDB and Firestore meter per operation — great for spiky, request-shaped traffic. Bigtable bills for nodes — it wants sustained, heavy throughput (time series, personalization, the workloads HBase was born for) and is overkill below that. Cosmos DB's Request Unit abstraction is the most explicit cost model in the industry: every operation has an RU price, and you provision RU/s like a bandwidth reservation. Cosmos's five-level consistency dial is a working tour of Phase 8 — bounded staleness and session consistency as products you toggle.

### Design With It

This is Phase 5 (consistent hashing, partitioning) with the hash ring hidden. The design act that matters is choosing a partition key with high cardinality and even access — and modeling your access patterns *first*, because you query by key, not by whim (single-table design in DynamoDB land).

```
  PK = user_id      ✔ millions of keys, even traffic
  PK = date         ✘ today's partition takes 100% of writes
  PK = tenant_id    ⚠ fine until one whale tenant = one hot partition
```

Wire change-data-capture streams (DynamoDB Streams / Firestore triggers / Cosmos change feed) into the async patterns from Phase 7: materialized views, search indexing, fan-out.

### Gotchas & Cost Traps

- Hot partitions: throughput is divided across partitions, so one celebrity key gets throttled while the table sits 95% idle. Sharded keys (Phase 5's salt trick) are the fix.
- Every GSI in DynamoDB is a full extra copy with its own write cost — five GSIs roughly means paying write throughput six times.
- Scans are table-sized reads billed accordingly. If your access pattern needs scans, you chose the wrong database (or the wrong key).
- Cosmos DB throttles (429s) the moment you exceed provisioned RU/s; underprovisioning shows up as user-visible errors, not gentle slowdowns.
- Firestore's per-document write-rate guidance and per-operation billing punish "update one hot counter document per event" designs — use sharded counters.

### War Story

September 20, 2015: DynamoDB's internal metadata service in us-east-1 — whose responses had grown heavier with the adoption of Global Secondary Indexes — began timing out storage servers' membership requests; servers took themselves out of service, retried in a storm, and the cascade degraded DynamoDB for hours, dragging down SQS, EC2 Auto Scaling, and console services that depended on it. Metadata planes scale too — until they don't.

### Checkpoint

- Why does adding capacity not fix a hot-partition problem?
- Match the pricing model to the workload: per-request, per-node, and RU/s — which fits a spiky consumer app vs. a sustained time-series firehose?
- Cosmos DB "session consistency" is the default. What guarantee does it give, in Phase 8 vocabulary, and to whom?

## 06. Planet-Scale SQL: Spanner vs Aurora Global vs Cosmos DB Multi-Region

**MOTTO:** You can have global writes, SQL, and low latency — pick two and read the fine print on the third.

### The Problem

You need a database that spans continents and still behaves like a database. This is Phase 8's hardest material — consensus, clocks, and the CAP theorem — sold with an SLA. The three clouds took genuinely different bets, and the differences are architectural, not cosmetic.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Service | Aurora Global Database | Spanner | Cosmos DB (multi-region, plus Cosmos DB for PostgreSQL) |
| Core mechanism | Physical storage-layer replication from a primary region | Synchronous Paxos replication + TrueTime (GPS/atomic clocks) | Per-partition replication with tunable consistency |
| Write topology | Single writer region (write forwarding available); secondaries read-only | Multi-region writes with external consistency (strictest isolation: serializable + real-time order) | True multi-master writes with conflict resolution (LWW default, custom possible) |
| Consistency across regions | Secondaries lag (typically sub-second); reads are stale | Strong everywhere — reads see a globally consistent snapshot | Your choice: strong (single write region) down to eventual |
| Failover | Promote a secondary in minutes; RPO measured in seconds | Automatic; multi-region configs carry a five-nines SLA | Automatic per your priority list |
| Interface | MySQL/Postgres-compatible (it's still Aurora) | SQL (GoogleSQL + a Postgres interface), but its own engine | Multiple APIs; not wire-compatible Postgres in core Cosmos |

Spanner is the famous one from Phase 8: TrueTime bounds clock uncertainty so tightly that Spanner can order transactions globally without cross-region chatter on every read — physics as a service. Aurora Global is honest about being asynchronous: one write region, fast physical replication, and a promotion runbook — a DR and read-locality product, not a global-write product. Cosmos DB says yes to multi-master writes and hands you the Phase 8 bill: conflicts happen, and last-writer-wins silently discards data unless you design otherwise. Pricing shapes: Spanner bills for compute capacity + storage per region; Aurora Global adds replicated-write charges per secondary region; Cosmos multiplies your RU/s by the region count.

### Design With It

Ask the Phase 8 question first: do you need global *writes*, or global *reads* with regional writes? Most systems are the latter, and Aurora Global (or read replicas anywhere) is enough:

```
  Global reads, single write region:        True global writes:
  us-east: primary  ◄─ writes (all)          Spanner: write anywhere,
  eu-west: replica  ◄─ local reads             Paxos commits across regions
  ap-south: replica ◄─ local reads             (writes pay cross-region latency;
                                                reads are local and consistent)
```

If you genuinely need writes on multiple continents with strong consistency, Spanner is nearly alone in that quadrant — and cross-continent commit latency is the honest, physics-mandated price. If you need multi-region writes and can *design* for conflicts (CRDT-ish merges, per-user home regions), Cosmos multi-master works.

### Gotchas & Cost Traps

- Last-writer-wins is data loss with a friendly name. If two regions update the same document, one update evaporates — fine for presence status, catastrophic for balances.
- Spanner's strong consistency doesn't repeal latency: a multi-region write commits across a quorum of regions. Co-locate leaders with your write traffic.
- Aurora Global secondaries are stale by design; serving "your account balance" from one violates read-your-writes. Route by operation, not by geography alone.
- Cost multiplies by region on every platform — a three-region deployment is roughly a 3× storage/throughput bill before you've served a request.
- Failover you've never rehearsed is a hypothesis, not a capability. Game-day the promotion runbook (Phase 13).

### War Story

October 21, 2018: a routine maintenance event caused a 43-second network partition between GitHub's US East and West Coast datacenters. Their MySQL orchestration promoted a West Coast primary while the East Coast had seconds of unreplicated writes — a split-brain that took roughly 24 hours of degraded service to reconcile. Forty-three seconds of partition, a day of cleanup: exactly the trade Phase 8 warned about when async replication meets automated failover.

### Checkpoint

- What does TrueTime actually bound, and why does that let Spanner order transactions without a global lock?
- Your product needs sub-50 ms reads on three continents but all writes come from one region's back office. Which of the three products fits, and why is it the cheapest option here?
- Under last-writer-wins, describe a concrete two-region sequence that silently loses an update.

## 07. Queues & Events: SQS/SNS/EventBridge vs Pub/Sub vs Service Bus/Event Grid

**MOTTO:** At-least-once delivery means your consumers are idempotent or your data is wrong — there is no third option.

### The Problem

You need Phase 7's decoupling — queues, fan-out, and event routing — without running brokers. Each cloud splits the space differently: AWS sells three sharply-scoped services, GCP sells one big one, and Azure sells an enterprise broker plus a lightweight event router. Mapping *your* pattern to *their* split is the exercise.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Work queue (1 consumer group) | SQS | Pub/Sub (pull subscription) or Cloud Tasks | Service Bus queues; Storage Queues (basic) |
| Fan-out pub/sub | SNS (→ many SQS/Lambda/HTTP) | Pub/Sub (many subscriptions per topic) | Service Bus topics |
| Event routing / bus | EventBridge (content-based filtering, schema registry, SaaS sources, cron) | Eventarc | Event Grid |
| Ordering | SQS FIFO (per message group) | Ordering keys | Service Bus sessions |
| Exactly-once-ish | SQS FIFO deduplication window | Optional exactly-once delivery on subscriptions | Duplicate detection window |
| Dead-lettering | DLQ on SQS/SNS/EventBridge | Dead-letter topics | Built-in DLQ, plus transactions and scheduled delivery |
| Delivery semantics (default) | At-least-once | At-least-once | At-least-once |

Meaningful differences: SQS standard is gloriously simple and effectively unlimited in throughput, but FIFO queues cap throughput per message group — order costs parallelism, exactly as Phase 7 predicted. GCP's Pub/Sub is one service wearing every hat (queue, fan-out, even streaming-ish workloads), which simplifies choice but blurs the work-queue/event-bus distinction. Azure's Service Bus is the most featureful classic broker of the three — transactions, sessions, scheduled messages — a natural home for enterprise messaging patterns, while Event Grid handles high-volume reactive event routing. Pricing is per-million requests/operations across the board, with payload-size multipliers.

### Design With It

Straight from Phase 7: queues level load, topics fan out, buses route. The canonical composed pattern:

```
  order-service ──event──> bus/topic (EventBridge / Pub/Sub / Event Grid)
                              ├─ filter: "order.created" ──> queue ──> email worker
                              ├─ filter: "order.created" ──> queue ──> inventory worker
                              └─ filter: "order.*"       ──> archive (audit)
```

Put a queue between the topic and each consumer (topic-queue chaining) so each worker gets its own buffer, retry policy, and DLQ. Set visibility timeout / ack deadline longer than your worst-case processing time, and make every consumer idempotent (Phase 7's dedupe keys) because at-least-once *will* deliver twice.

### Gotchas & Cost Traps

- Retries without a DLQ create poison-message loops: one bad payload cycles forever, burning per-request charges and starving the queue. Always configure max-receive + DLQ, and *alarm* on DLQ depth.
- FIFO ordering is per message group. One group (one hot entity) serializes; thousands of groups parallelize. Choosing "one global group" turns your queue into a single-threaded pipe.
- Empty-polling costs money at scale on per-request pricing; use long polling (SQS) or push/streaming pull (Pub/Sub) instead of tight-loop polling.
- Visibility timeout shorter than processing time = every message processed twice, on purpose, by design, forever. It looks exactly like a duplicate-message bug.
- Max message sizes are small (hundreds of KB). Large payloads go to object storage with a pointer in the message — the claim-check pattern.

### War Story

December 7, 2021: an automated scaling activity in AWS's internal network triggered a surge that overwhelmed networking devices between the internal and main networks in us-east-1. EventBridge event delivery was delayed for hours, API error rates spiked across services, and support cases couldn't even be filed. Systems that treated event delivery as instantaneous discovered they had implicit latency assumptions; systems built on durable queues mostly just... caught up later.

### Checkpoint

- Why must consumers be idempotent even on a queue with "exactly-once" branding?
- You need one event to trigger four independent workflows with separate retry policies. Draw the wiring on any one cloud.
- What symptom tells you your visibility timeout is shorter than your processing time?

## 08. Streaming: Kinesis vs Pub/Sub + Dataflow vs Event Hubs

**MOTTO:** A stream is a replayable log with a clock; a queue is a to-do list — buy the one you actually need.

### The Problem

Phase 12's append-only log — ordered, partitioned, replayable by many independent consumers — as a managed service. This is for clickstreams, CDC, metrics, and anything where "reprocess yesterday from offset zero" is a feature, not a disaster recovery.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Core service | Kinesis Data Streams | Pub/Sub (+ Dataflow for processing) | Event Hubs |
| Capacity model | Shards (fixed per-shard MB/s in and out) or on-demand mode | Fully autoscaling, no capacity units to manage | Throughput/processing units + partitions |
| Ordering | Per shard (by partition key) | Per ordering key | Per partition (by partition key) |
| Replay | Yes — offsets, retention configurable up to long horizons | Seek to timestamp or snapshot within retention | Yes — offsets within retention; Capture to storage for longer |
| Kafka compatibility | Separate service: Amazon MSK | Separate: Managed Service for Apache Kafka | Built-in: Kafka-compatible endpoint on Event Hubs |
| Processing engine | Kinesis Data Analytics / Managed Flink, Lambda consumers | Dataflow (Apache Beam) — batch and streaming, autoscaling | Stream Analytics, or Flink/Spark via Kafka endpoint |
| Delivery-to-storage | Data Firehose (to S3, Redshift, etc.) | Pub/Sub BigQuery/GCS subscriptions | Event Hubs Capture |

The capacity models are the story. Kinesis makes you think in shards: each has fixed ingress/egress, ordering is per shard, and resharding is an operation you plan (on-demand mode softens this at a price premium). Pub/Sub abstracts partitions away entirely — no shard math, global endpoint, autoscaling — at the cost of weaker control over partition-level ordering and a per-data-volume bill. Event Hubs sits in between and plays a trump card: a Kafka-compatible endpoint, so the vast Kafka ecosystem points at it with a config change. All three retain data for replay (retention length is a config/pricing knob) and hand you the Phase 12 consumer-offset model.

### Design With It

The classic streaming backbone — Phase 12's lambda/kappa material, purchasable:

```
  producers ──> [stream: shards/partitions, keyed by entity_id]
                   ├─ consumer A: real-time aggregation (Flink/Dataflow) ──> serving DB
                   ├─ consumer B: raw archival ──> object storage (data lake)
                   └─ consumer C: (added next year) replays from offset 0 ✔
```

Partition by a high-cardinality key that matches your ordering needs (per-user order ⇒ key by user). Consumers track their own offsets, so adding a new one never disturbs the others — the property queues can't give you. Fan-in from streams to warehouses (Lesson 12) goes through the delivery services (Firehose / BigQuery subscriptions / Capture) rather than hand-rolled loaders.

### Gotchas & Cost Traps

- Hot shards: keying a Kinesis stream by something low-cardinality (or one whale customer) throttles a single shard while you pay for twenty idle ones. Same disease as Lesson 5, same cure.
- Per-shard consumer limits mean many consumers on one Kinesis shard contend for read throughput; enhanced fan-out fixes it and adds a separate charge.
- Retention is a pricing knob everywhere. Seven-day replay is cheap insurance; "we'll keep a year in the stream" is a decision to feel in the invoice — long-term replay belongs in object storage.
- Dataflow/Flink autoscaling can happily scale *up* to absorb a poison-pill-induced retry storm — an infinite loop with an infinite budget. Alarm on watermark lag *and* on worker count.
- Kafka-compatible ≠ Kafka-identical: exotic client features (transactions, some admin APIs) may behave differently on compatibility endpoints. Test the ecosystem tools you actually use.

### War Story

November 25, 2020: adding capacity to Kinesis's front-end fleet in us-east-1 pushed the fleet past an OS thread limit — each front-end server maintains a thread per peer, and the fleet had grown too large. Front-end servers failed to build their shard maps, Kinesis went down for many hours, and the blast radius stunned everyone: Cognito logins, CloudWatch metrics, and even AWS's ability to update their own status page were impaired, because they all rode on Kinesis internally. Know your transitive dependencies.

### Checkpoint

- Name two capabilities a stream gives you that a work queue fundamentally cannot.
- You expect 10× traffic spikes for minutes at a time. Compare how shard-based and autoscaling capacity models handle it, and who does the work.
- Why should long-term replayability live in object storage rather than in stream retention?

## 09. Caching & CDN: ElastiCache/CloudFront vs Memorystore/Cloud CDN vs Azure Cache/Front Door

**MOTTO:** The fastest request is the one that never reaches your origin — and the second-fastest never leaves the datacenter.

### The Problem

Phase 6 taught you cache layers; here you buy the two big ones: an in-memory store beside your app (Redis-shaped) and an edge network in front of it (CDN-shaped). Both exist to convert "database query" and "cross-ocean round trip" into "memory read nearby."

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| In-memory cache | ElastiCache (Redis OSS, Valkey, Memcached), Serverless option | Memorystore (Redis, Valkey, Memcached) | Azure Cache for Redis (Enterprise tiers via Redis Inc.) |
| DB-specific cache | DAX (DynamoDB accelerator) | — | — |
| CDN | CloudFront | Cloud CDN, Media CDN | Front Door (Azure CDN classic being absorbed into it) |
| Edge compute | CloudFront Functions (lightweight), Lambda@Edge (heavier) | Service Extensions / (historically limited) | Front Door rules engine |
| Global entry architecture | DNS to distribution, per-distribution config | Anycast global load balancer with CDN as a checkbox | Anycast global entry with WAF, LB, CDN unified |
| Cluster/HA cache | Cluster mode (sharded), multi-AZ replicas | HA tiers, read replicas | Clustering on higher tiers, zone redundancy |

Architectural flavor differences: GCP's CDN is a feature of its global anycast load balancer — one IP worldwide, caching turned on per backend — reflecting the "global by default" philosophy from Lesson 1. CloudFront is its own distribution-based product with the deepest edge-compute story (run code at the edge on every request). Front Door bundles CDN, global load balancing, and WAF into a single front-door product, which is tidy. On caches: all three now offer Valkey (the open-source Redis fork) alongside Redis; Azure's Enterprise tiers are the route to Redis-company modules (search, JSON). Pricing: caches bill per node-hour (or per-GB serverless); CDNs bill per GB egress + per request, with egress-to-internet from the edge typically cheaper than from the origin region.

### Design With It

This is Phase 6's layer cake, deployed:

```
  user ──> CDN edge (static + cacheable API GETs, TLS termination)
              │ miss
              ▼
           app tier ──> Redis/Valkey (sessions, hot objects, rate limits,
              │           cache-aside with TTL + jitter)
              ▼ miss
           database (the thing all of this protects)
```

Cache-aside with TTLs and jitter (Phase 6) for the in-memory layer; `Cache-Control` headers and cache keys (careful with query strings and cookies) for the edge. Signed URLs/cookies gate private content at the edge. Invalidation remains one of the two hard problems: prefer versioned asset URLs (`app.v42.js`, immutable) over purge APIs.

### Gotchas & Cost Traps

- A cache node restart with no replica is a thundering herd aimed at your database (Phase 6 stampede). Multi-AZ replicas plus request coalescing are cheap insurance.
- CDN cache hit ratio is a cost *and* correctness metric: accidentally including a session cookie or random query param in the cache key drops hit rate to ~0 and you pay origin egress on every "cached" request.
- Purge/invalidation calls are billed and rate-limited on some CDNs; a deploy pipeline that purges `/*` on every release is both slow and pricey. Version your URLs.
- Redis is memory-priced: storing unbounded keys with no TTL or eviction policy is a slow-motion OOM. Set `maxmemory` policy deliberately.
- Caching authenticated API responses at the edge without `Vary`/key discipline serves user A's data to user B — a breach, not a bug.

### War Story

June 8, 2021: a Fastly customer pushed a valid configuration change that triggered a latent bug introduced weeks earlier, and roughly 85% of Fastly's global CDN began returning errors — Reddit, Amazon, gov.uk, and major news sites vanished for about an hour. The fix was fast, but the lesson is vendor-neutral: the CDN is a single global dependency in front of *everything*, so know your origin-direct fallback story.

### Checkpoint

- Your CDN hit ratio just fell from 92% to 8% after a deploy. What are the two most likely cache-key culprits?
- Why do versioned asset URLs beat purge-on-deploy for both cost and correctness?
- A Redis node dies and your database latency triples for 10 minutes. Name the Phase 6 phenomenon and two mitigations you should have bought.

## 10. Serverless: Lambda vs Cloud Functions & Cloud Run vs Azure Functions

**MOTTO:** Serverless doesn't remove the servers — it removes your excuses for idle ones.

### The Problem

You want to run code only when there's work, scale to zero when there isn't, and pay per invocation. This is the purest form of Phase 9's stateless-service ideal. The catch: cold starts, concurrency semantics, and execution limits are different enough across clouds to change your architecture.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Function service | Lambda | Cloud Run functions (the artist formerly known as Cloud Functions; gen 2 runs on Cloud Run) | Azure Functions |
| Container serverless | Lambda container images; Fargate; App Runner | Cloud Run (the flagship: any container, HTTP or jobs) | Azure Container Apps (KEDA-based) |
| Concurrency model | One request per execution environment | Cloud Run: up to ~1000 concurrent requests *per instance* | Multiple requests per host, varies by plan/runtime |
| Cold-start mitigation | Provisioned Concurrency; SnapStart (snapshot restore for JVM & friends) | Min instances; CPU always-allocated option | Premium plan pre-warmed workers; Flex Consumption |
| Max duration | Minutes-scale hard cap (15 min) | Cloud Run: up to an hour for requests, longer for jobs | Consumption capped; longer on Premium/Dedicated |
| Orchestration | Step Functions | Workflows | Durable Functions (code-first orchestration) |
| Pricing shape | Per-request + GB-seconds of compute | Per-request + vCPU/memory-seconds (scale-to-zero) | Per-execution + GB-seconds (Consumption) |

The deepest difference is concurrency. Lambda's one-request-per-sandbox model means 1,000 concurrent requests = 1,000 warm environments — beautifully simple isolation, but every new environment is a potential cold start and every environment opens its own database connection (see Lesson 4's pooler). Cloud Run's many-requests-per-instance model amortizes cold starts and connections across concurrent requests — closer to a normal web server that happens to scale to zero. Azure spans both worlds with plan tiers, and Durable Functions is a genuinely distinctive orchestration-in-code offering. Cold starts range from tens of milliseconds (lightweight runtimes) to seconds (heavy JVM/.NET apps, VPC networking in older setups) — mitigations exist on every platform and all of them cost money, which is the point: pre-warmth is a reservation, and reservations aren't serverless pricing anymore.

### Design With It

Event glue and spiky HTTP are the sweet spots — Phase 7's consumers made trivial:

```
  S3/GCS/Blob event ──> function ──> thumbnail, index, notify
  queue (SQS/Pub/Sub/Service Bus) ──> function (batch, DLQ, retries built in)
  HTTP burst ──> API gateway ──> function (0 → thousands, no ASG to tune)
```

Keep functions stateless (state goes to Lessons 3/5), idempotent (at-least-once invocation!), and short. For long-lived, steady, latency-sensitive services, do the math: at high constant utilization, serverless per-invocation pricing usually loses to containers/VMs — serverless buys elasticity, not cheap baseline.

### Gotchas & Cost Traps

- Cold starts compound: a user-facing chain of three cold functions stacks three penalties. Keep hot paths shallow, or pay for pre-warmth on the critical hop.
- Functions + relational DB without a pooler = connection exhaustion at the first traffic spike (Lambda's one-connection-per-environment math). This is the single most repeated serverless outage in the wild.
- Infinite recursion: a function writing to the bucket/queue that triggers it is a self-funding infinite loop. Set concurrency caps and budget alarms before you need them.
- Per-invocation pricing on a high-QPS steady service can cost multiples of an equivalent container. "Serverless everywhere" is an architecture opinion, not a cost optimization.
- Retry semantics differ by trigger (sync vs. async vs. stream) on every platform. Know whether a failure retries, DLQs, or silently drops — per trigger, per cloud.

### War Story

June 13, 2023: AWS us-east-1 suffered a multi-hour incident rooted in a subsystem powering Lambda, driving elevated invocation errors and knock-on failures for API Gateway and other dependent services during peak US hours. Serverless removes your servers, not your dependency on the provider's — regional failover plans apply to functions too.

### Checkpoint

- Explain how Lambda's concurrency model turns 500 concurrent requests into a database problem.
- When does Cloud Run's per-instance concurrency model beat one-request-per-sandbox, and what new failure mode does it introduce inside an instance?
- Your steady service runs at 800 RPS around the clock. Sketch the cost argument for and against serverless.

## 11. Managed Kubernetes: EKS vs GKE vs AKS

**MOTTO:** Managed Kubernetes manages the control plane; the other 80% of the pain is still yours.

### The Problem

You've committed to Kubernetes (Phase 10/15) and want someone else to run etcd, the API server, and the upgrade treadmill for the control plane. All three clouds will — but they differ meaningfully in pricing, in how much of the *node* problem they also take off your hands, and in how terrifying upgrades are.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Service | EKS | GKE | AKS |
| Control plane pricing | Per-cluster hourly fee, always | Per-cluster management fee (with a free-tier allowance) | Free tier: no charge; Standard tier: paid, with uptime SLA |
| Nodeless / hands-off mode | EKS Auto Mode; Fargate for pods | Autopilot: pay per pod's requested resources, Google runs nodes | Node auto-provisioning (Karpenter-based); Virtual Nodes (ACI) |
| Autoscaling story | Cluster Autoscaler or Karpenter (excellent, AWS-born) | Autopilot does it; Standard has NAP + cluster autoscaler | Cluster autoscaler, NAP |
| Upgrade ergonomics | You initiate; extended support for old versions bills extra | Release channels (rapid/regular/stable), auto-upgrade, maintenance windows — the gold standard | Auto-upgrade channels, planned maintenance windows |
| Version support window | ~14 months standard, paid extended support | Rolling channel-based support | Standard window + LTS option |
| Integration gravity | IAM Roles for Service Accounts, ALB controller, VPC CNI | Workload Identity, native logging/monitoring wiring | Entra Workload ID, Azure Monitor |

The consensus take: GKE is the most polished (Google birthed Kubernetes, and it shows — release channels and Autopilot are genuinely lower-toil), AKS is the cheapest to try (free control plane) with solid ergonomics, and EKS is the most assembly-required but sits in the largest ecosystem — and Karpenter, its node-autoscaling project, is best-in-class and now vendor-neutral. The deeper spectrum is *who owns the nodes*: classic node pools (you patch, you size) → auto-provisioning (cloud picks machines) → Autopilot/Auto Mode (you never see a node, you pay per pod's requests).

### Design With It

Phase 10's microservices platform, purchased:

```
  git ──CI──> registry (ECR/Artifact Registry/ACR)
                 │
                 ▼ deploy (GitOps: Argo/Flux)
  [cluster: control plane = cloud's problem]
     ├─ node pool A: on-demand (system, stateful)
     ├─ node pool B: spot (stateless, batch) ◄─ Karpenter/NAP picks sizes
     └─ ingress ──> cloud LB    workload identity ──> cloud IAM (no static keys)
```

Use workload identity federation on every cloud (pods assume cloud IAM roles — no mounted secrets, Phase 14). Requests/limits are your Phase 16 obligation: autoscalers scale on *requests*, so lying about them breaks both packing and billing (on Autopilot, requests literally *are* the bill).

### Gotchas & Cost Traps

- The control plane fee is a rounding error; the nodes are the bill. Overprovisioned requests ("everything gets 2 CPU just in case") silently double a cluster's cost — measure with VPA recommendations.
- Kubernetes versions EOL fast (~three releases a year). Skip upgrades for 18 months and you face a multi-hop forced march — or, on EKS, escalating extended-support fees for procrastination.
- Every LoadBalancer-type Service provisions a real cloud load balancer with a real monthly cost. Use one ingress/gateway, not forty LBs.
- IP exhaustion: VPC-native pod networking (especially AWS VPC CNI) drinks subnet IPs at pod scale. Plan CIDRs before the cluster exists, not after.
- Cross-AZ traffic between chatty pods (Lesson 1's trap) applies double in Kubernetes because the scheduler spreads pods across zones by default. Topology-aware routing exists — turn it on.

### War Story

March 14, 2023: Reddit went down for over five hours during a Kubernetes upgrade — a years-old, undocumented dependency on node labels whose naming had changed between versions broke their Calico network routing, and the team initially couldn't tell whether the cluster was salvageable. Their public postmortem is a masterclass in why upgrade ergonomics (and rehearsal clusters) belong in your platform evaluation.

### Checkpoint

- On GKE Autopilot you pay for pod resource *requests*. What behavior does that billing model incentivize, and what Phase 16 practice does it enforce?
- Why can "free control plane" AKS still cost more than EKS for the same workload?
- Your cluster is three versions behind. Describe the upgrade path and two risks the Reddit incident illustrates.

## 12. Analytics: Redshift vs BigQuery vs Synapse

**MOTTO:** In analytics, the query engine is a commodity — the pricing model is the architecture.

### The Problem

Phase 11's OLAP warehouse — columnar storage, massive scans, star schemas — as a managed service. The three clouds converge on "separate storage from compute" and then diverge hard on how you pay for the compute, which quietly dictates how your team will behave.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Service | Redshift | BigQuery | Synapse Analytics (with Microsoft Fabric as the anointed successor) |
| Provisioned model | RA3 nodes with managed storage (compute/storage separated) | Capacity: slot commitments/editions with autoscaling | Dedicated SQL pools (DWU-based, pausable) |
| Serverless model | Redshift Serverless (RPU-seconds) | On-demand: billed per TB scanned — the native mode | Serverless SQL pools (per TB processed) |
| Query data lake in place | Redshift Spectrum (over S3) | Native external tables (GCS, open formats) | Serverless SQL / Spark over ADLS |
| Scaling behavior | Resize/concurrency scaling; serverless auto | Fully elastic; thousands of slots on demand | Pause/resume/resize DWUs |
| Streaming ingest | Firehose, streaming ingestion | Storage Write API, Pub/Sub subscriptions | Event Hubs + Stream Analytics |
| Ecosystem gravity | AWS-native, S3 data lakes | The serverless benchmark everyone else chases | Power BI + Microsoft data estate |

BigQuery is the philosophical extreme: no clusters, no nodes, on-demand queries billed by bytes scanned — zero to petabyte with nothing provisioned. That model is magical for spiky exploration and dangerous for the undisciplined (one careless `SELECT *` over an unpartitioned petabyte is a memorable invoice), which is why capacity/slot pricing exists for steady workloads. Redshift began as classic provisioned MPP (Phase 11's shared-nothing) and has been retrofitting elasticity — RA3 managed storage and Serverless — ever since. Synapse's dedicated pools are provisioned-and-pausable, its serverless pool mimics the per-TB model, and Microsoft's strategic energy has shifted to Fabric (capacity-based, OneLake-centric) — factor that trajectory into new Azure builds.

### Design With It

Phase 11 and 12's pipeline, assembled from earlier lessons:

```
  OLTP DBs ──CDC──> stream (L08) ──┐
  events ──────────> stream ───────┼──> object storage lake (L03, open formats:
  SaaS/exports ──batch (ELT)───────┘       Parquet/Iceberg, partitioned)
                                              │
                              external tables │ + curated loads
                                              ▼
                                    warehouse (this lesson)
                                              ▼
                                    BI, dashboards, ML features
```

The modern default is lake-first: land raw data in object storage in open columnar formats, let the warehouse query it externally, and load only curated, hot marts into native storage. Partition and cluster tables by your dominant filter columns — on scan-priced engines this is a *cost* control, not just a performance one. Keep the warehouse out of your serving path: user-facing reads come from Lessons 4/5/9 stores fed *by* the warehouse, never from it directly.

### Gotchas & Cost Traps

- On-demand BigQuery bills bytes *scanned*, and `LIMIT 10` does not reduce the scan. Partition filters and clustering do. Set per-user/per-project custom quotas before your first intern arrives.
- A dashboard auto-refreshing an expensive query every 30 seconds is a money printer in reverse on any pricing model. Cache BI results; schedule refreshes.
- Paused ≠ free: dedicated/provisioned tiers still bill storage while paused, and someone must actually remember to pause. Automate it.
- Small frequent inserts antagonize columnar engines (Phase 11): micro-batch or use the streaming ingest APIs, and beware per-row streaming-insert pricing.
- Warehouse-as-app-backend is an anti-pattern: seconds-scale latency and concurrency limits masquerading as an outage. Serve users from a serving store.

### War Story

September 4, 2018: a lightning strike near Azure's South Central US region caused a cooling failure and emergency shutdown of storage hardware; because Azure DevOps (then VSTS) hosted critical data solely in that region, customers worldwide lost access for the better part of a week's working days. Analytics estates concentrate an entire company's data in one region by default — the postmortems that followed pushed Microsoft toward zone- and geo-redundancy by design. Ask where *your* warehouse's second copy lives.

### Checkpoint

- Why does `SELECT * ... LIMIT 10` cost the same as the full query on scan-priced engines, and what schema features actually cut the bill?
- Match workload to pricing model: nightly ELT + steady dashboards vs. sporadic ad-hoc exploration. Which gets slots/provisioned and which gets on-demand, and why?
- What breaks when a product team points a mobile app's home screen at the warehouse?

## 13. IAM & Networking: VPCs, Peering, Private Endpoints, and Identity

**MOTTO:** In the cloud, identity is the perimeter and the network is a billing surface.

### The Problem

Every service in this phase sits inside two invisible systems: a virtual network deciding what can *reach* what, and an identity system deciding what can *do* what. Phase 14 taught the principles; here you buy them — and the three clouds' models differ more here than anywhere else in this phase.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Network scope | VPC is regional; subnets are zonal | VPC is **global**; subnets are regional | VNet is regional; subnets span zones |
| Peering | VPC peering (non-transitive) | VPC peering (non-transitive) | VNet peering (non-transitive) |
| Hub-and-spoke at scale | Transit Gateway | Network Connectivity Center | Virtual WAN / hub-spoke VNets |
| Private access to PaaS | PrivateLink + VPC endpoints (gateway endpoints for S3/DynamoDB are free) | Private Service Connect, Private Google Access | Private Endpoint, Service Endpoints |
| NAT for egress | NAT Gateway (hourly + per-GB processed) | Cloud NAT | NAT Gateway |
| Identity system | IAM: identity- and resource-based JSON policies; roles assumed via STS | IAM on a resource hierarchy: org → folders → projects; roles bound at any level; service accounts | Entra ID (née Azure AD) tenant; management groups → subscriptions → resource groups; RBAC; managed identities |
| Workload identity (no static keys) | IAM roles (instance profiles, IRSA) | Service accounts + Workload Identity | Managed identities |

Three genuinely different identity philosophies. AWS is policy-document-centric: fine-grained JSON evaluated per request, immensely expressive, famously easy to get subtly wrong. GCP is hierarchy-centric: bind a role at the org/folder/project level and it inherits downward — clean, but inheritance means a folder-level grant is a wide grant. Azure is directory-centric: Entra ID is a full enterprise identity platform (users, groups, conditional access) with resource RBAC layered on — the natural fit if your company already lives in Microsoft's directory. On networking, GCP's global VPC is the standout: one network across regions with no peering gymnastics, the same "global by default" bet from Lesson 1. Peering is non-transitive on all three, which is why hub products (Transit Gateway et al.) exist and bill per attachment and per GB.

### Design With It

Phase 14's zero-trust and least-privilege, wired:

```
  internet ──> edge (LB/WAF, L09) ──> public subnets: load balancers only
                                          │
                                     private subnets: apps
                                          │  workload identity (no keys!)
                                          ├──> private endpoint ──> DB / storage
                                          └──> NAT gateway ──> internet egress
```

Nothing but load balancers gets a public IP. Apps reach cloud services over private endpoints so data-plane traffic never crosses the internet. Humans get short-lived SSO credentials, not IAM users with access keys; workloads get roles/service accounts/managed identities, never `.env` secrets. Guardrails live at the top of each hierarchy: AWS Organizations SCPs, GCP org policies, Azure Policy at management-group scope.

### Gotchas & Cost Traps

- The NAT gateway is the most infamous cost trap in cloud networking: you pay per GB *processed*, so a private-subnet fleet pulling images or writing to regional storage through NAT rings the register on every byte. Free/cheap gateway endpoints and private access paths exist precisely to bypass it — use them.
- Peering is non-transitive: A↔B and B↔C does not give A↔C. Ten VPCs full-meshed is 45 peerings; that's the hub product's sales pitch and its per-GB fee.
- Overlapping CIDR blocks make networks unpeerable forever-ish. Allocate IP space like it's 1993 and you're the IANA.
- Wildcard IAM (`Action: *` on `Resource: *`, Owner/Editor roles, org-level bindings) is how "least privilege" dies in practice. Access analyzers and policy linters exist on all three clouds — run them in CI.
- Security groups/firewall rules are necessary but not sufficient: identity-based controls must hold even if the network fails, because misconfigured peering or a leaked credential bypasses your subnet diagram (Phase 14's zero-trust argument).

### War Story

Azure AD had a rough stretch: on September 28, 2020, an update to the authentication service caused a multi-hour global outage of Azure AD sign-ins, locking users out of Microsoft 365, Teams, and the Azure portal itself; on March 15, 2021, an error in a key-rotation process (a key marked "retain" was rotated anyway) broke token validation for around 14 hours of staggered impact. When identity is the perimeter, the identity provider is the biggest single point of failure you own — cache tokens gracefully and know what your apps do when the IdP blinks.

### Checkpoint

- Why does traffic to object storage from a private subnet sometimes cost per-GB NAT processing fees, and what's the free-path fix on AWS?
- Contrast how a "grant read access to all of team X's projects/accounts" is expressed in GCP's hierarchy model vs. AWS's policy model.
- Your app holds a database password in an env var. Name the replacement mechanism on each cloud and why it's categorically better.

## 14. Choosing a Cloud (and Surviving Multi-Cloud)

**MOTTO:** Pick one cloud, use it boringly, and keep your exits at the design layer — not the runtime layer.

### The Problem

After thirteen lessons of "all three clouds sell this," the obvious question: which one? And should you hedge with several? This is an engineering-economics decision dressed up as a technology one — the honest inputs are your team, your data's gravity, your existing contracts, and one number the brochures whisper: egress.

### The Landscape

| Capability | AWS | GCP | Azure |
|---|---|---|---|
| Strongest pitch | Broadest catalog, deepest ecosystem, most hiring liquidity | Data/analytics crown jewels (BigQuery, Spanner), best K8s, network | Enterprise/Microsoft estate integration, hybrid (Arc), license benefits |
| Typical adopter | Default choice; startups through enterprises | Data-heavy products, K8s-native teams | Microsoft shops, regulated enterprises |
| Lock-in gravity wells | DynamoDB, IAM sprawl, org-wide tooling | BigQuery, Spanner (few true substitutes) | Entra ID everywhere, Fabric/Power BI |
| Egress pricing | Per-GB out to internet; free-egress-on-exit programs exist (regulator-driven) | Same shape; similar exit programs | Same shape; similar exit programs |
| Portability aids | EKS, Postgres-compatible services, S3 API as de facto standard | GKE, open formats (Iceberg/Parquet), Postgres interfaces | AKS, Postgres/MySQL flexible servers |

The differences that *should* drive the choice are mostly non-technical: where your team has muscle memory (a mediocre cloud you know beats a great one you don't), where your data already lives (data gravity: moving petabytes costs real money and real quarters), what credits/contracts you hold, and whether one cloud has a genuinely unmatched service you need (BigQuery and Spanner are the usual honest answers; most other services have close substitutes). Egress fees are the structural lock-in: data enters free and leaves at per-GB rates, so architectures that straddle clouds pay a permanent tax on every cross-cloud byte — which is precisely why "split the stack across two clouds" fails as a default strategy.

### Design With It

A decision framework, in order:

```
  1. Hard constraint? (regulator, parent company, sovereign region) ──> obey it
  2. One irreplaceable service? (e.g., BigQuery-shaped analytics)  ──> weight it
  3. Team expertise + existing contracts/credits                    ──> heavy weight
  4. Otherwise ──> any of the three; pick one, go deep, stay boring
```

Multi-cloud is *justified* when: a regulator or customer mandates it; an acquisition hands it to you (the most common cause — plan the integration, don't pretend); one workload genuinely belongs elsewhere (run *that workload* there, whole, with its data — don't stripe one system across clouds); or at contract scale, credible portability is negotiating leverage. Multi-cloud is *not* justified for availability by default: you'll double your IAM/networking/observability surface, dilute your team across two learning curves, and Phase 13 says complexity is where outages come from — a well-drilled multi-*region* story on one cloud beats a shallow multi-cloud one for almost everyone. Keep exits cheap at the design layer: containers, Postgres-compatible databases, S3-compatible object APIs, open table formats (Parquet/Iceberg), Terraform/OpenTofu, and OpenTelemetry — so that leaving is expensive-but-possible rather than unthinkable.

### Gotchas & Cost Traps

- Lowest-common-denominator multi-cloud ("only use what all three offer") forfeits exactly the managed services you came to the cloud for — you rebuild Phase 4–12 yourself on VMs, badly, twice.
- Cross-cloud data pipelines pay egress *continuously*: a "best of breed" design streaming events from cloud A into cloud B's warehouse has a per-GB toll booth in the middle, forever.
- Abstraction layers that promise cloud portability often deliver the union of nobody's features and the intersection of everybody's bugs; portability lives in standards (SQL, S3 API, K8s, OTel), not in wrapper SDKs.
- Free-egress-on-exit programs cover the final move, not ongoing hybrid operation — don't design a permanent architecture around a one-time door.
- The real switching cost is rarely the data transfer: it's re-encoding years of IAM policies, network topology, CI/CD, and team knowledge. Budget the org, not just the bytes.

### War Story

Snap's 2017 IPO filing disclosed commitments to spend two billion dollars with Google Cloud and one billion with AWS over five years — multi-cloud as public, contractual negotiating posture from a company whose infrastructure ran overwhelmingly on one of them. That's the honest version of multi-cloud for most companies: leverage and optionality at the contract layer, one primary cloud at the architecture layer.

### Checkpoint

- Your startup's five engineers all know AWS; GCP offers larger credits and you admire BigQuery. Walk the framework — what wins, and what design-layer hedges do you keep?
- Why does multi-region-on-one-cloud usually beat multi-cloud for availability, in Phase 13 terms?
- Name four design-layer choices that keep your exit cheap without running anything on a second cloud.
