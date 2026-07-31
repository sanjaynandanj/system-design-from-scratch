# Phase 07 — 📬 Messaging & Async Processing

> Don't call me, I'll queue you.

Synchronous calls are a handshake: both parties must show up at the same moment, and if one is slow, both are slow. Queues break that handshake — the producer drops off work and leaves, and the consumer picks it up whenever it's ready. This one idea powers everything from your food-delivery notifications to LinkedIn's entire data pipeline. In this phase you'll learn why async wins, how the big brokers actually work under the hood, and then you'll build a Kafka-flavored message queue yourself in Python.

## 01. Why Async: Decoupling Time From Work

**MOTTO:** The fastest way to do something during a request is to promise to do it later.

### The Problem

Your signup endpoint creates a user, sends a welcome email, resizes an avatar, notifies analytics, and updates a search index. Done synchronously, the user waits for all five, and if the email provider is down, *signup fails*. You've chained your core flow to your slowest, flakiest dependency.

### The Concept

Async is a restaurant kitchen. The waiter (API) doesn't cook your food — they write the order on a ticket, clip it to the rail, and go serve the next table. Cooks (workers) pull tickets at their own pace. The ticket rail is the queue: it decouples *when work is requested* from *when work is done*.

```
SYNC:   Client ──▶ API ──▶ Email ──▶ Resize ──▶ Analytics ──▶ 200 OK  (2.5s, fragile)

ASYNC:  Client ──▶ API ──▶ [queue] ──▶ 200 OK  (50ms)
                              │
                              ├──▶ email worker
                              ├──▶ resize worker
                              └──▶ analytics worker
```

### Build It

1. Split every operation into **must-happen-now** (write the user row) and **can-happen-soon** (everything else).
2. During the request, do only the must-now work, then enqueue a message describing the rest: `{"event": "user_signed_up", "user_id": 42}`.
3. Return success to the client immediately.
4. Workers consume messages, do the slow work, and retry on failure — invisibly to the user.
5. Accept the new contract: the side effects are *eventually* done, not *already* done. Design UX accordingly ("Your email is on its way").

### Use It

| Approach | Latency | Failure isolation | Complexity |
|---|---|---|---|
| Synchronous calls | Sum of all steps | None — one failure fails all | Low |
| Fire-and-forget threads | Low | Poor — work lost on crash | Low |
| Message queue + workers | Low | Strong — retries, buffering | Medium |

Celery + Redis, Sidekiq + Redis, SQS + Lambda are the classic "background job" stacks.

### War Story

Amazon has long cited internal findings that every 100ms of added latency measurably hurts sales, and Google found similar effects with slower search pages — which is why serious shops ruthlessly evict slow work from the request path. The queue is the eviction mechanism.

### Checkpoint

- Why can a queue make a system *more* reliable, not just faster?
- What new failure mode do you accept when you move email sending to a background worker?
- Name two criteria for deciding whether an operation must stay in the synchronous request path.

## 02. Message Queues: The Fundamentals

**MOTTO:** A queue is a buffer with opinions about delivery.

### The Problem

Producer and consumer run at different speeds and crash at different times. If the producer hands work directly to the consumer, a slow consumer stalls the producer, and a dead consumer loses the work. You need a durable middleman that holds messages until someone confirms they're handled.

### The Concept

A queue is a post office box. The sender drops a letter and leaves; the recipient collects it later, and the box holds it safely in between. The core vocabulary:

```
 producer ──publish──▶ ┌─────────────────────┐ ──deliver──▶ consumer
                       │  queue: [m1 m2 m3]  │ ◀───ack────
                       └─────────────────────┘
```

- **Publish**: producer appends a message.
- **Deliver**: broker hands a message to a consumer.
- **Ack**: consumer says "done, delete it." No ack (crash/timeout)? The broker redelivers.
- **Durability**: messages survive broker restarts if written to disk.

### Build It

The minimal broker is ~5 mechanics:

1. Accept a message; assign it an ID; append it to storage (memory list → WAL file for durability).
2. On consumer poll, hand out the oldest unclaimed message and mark it *in flight* with a deadline (visibility timeout).
3. On ack before the deadline, delete it.
4. On deadline expiry with no ack, return it to the queue for redelivery.
5. Track a delivery count per message so poison messages can be shunted aside (see lesson 08).

That in-flight/ack/timeout loop is exactly how SQS works.

### Use It

| Tool | Model | Sweet spot |
|---|---|---|
| SQS | Managed queue, visibility timeout | Zero-ops AWS default |
| RabbitMQ | Broker with smart routing | Complex routing, task queues |
| Kafka | Replayable log | High throughput, streams, replay |
| Redis lists/streams | In-memory | Simple, fast, weaker durability |

### War Story

Message queuing predates the web: IBM MQSeries shipped in 1993 and still moves money between banks today. The pattern is so durable because the problem — two systems that can't be up, fast, and synchronized at the same time — never went away.

### Checkpoint

- What is a visibility timeout and what failure does it protect against?
- Why does redelivery-on-missing-ack imply your consumers may see a message twice?
- What's the difference between a durable queue and a merely persistent connection?

## 03. Kafka Architecture Deep Dive

**MOTTO:** Kafka isn't a queue — it's a distributed, replicated append-only log that queues are jealous of.

### The Problem

Classic brokers delete messages after ack, serve modest throughput, and can't let a second team replay last week's events. LinkedIn needed a firehose: hundreds of thousands of events per second, consumed by many independent systems, with the ability to rewind.

### The Concept

Kafka's core is embarrassingly simple: an append-only file. A **topic** is split into **partitions**; each partition is an ordered, immutable log. Consumers don't delete anything — they just remember their **offset**, a bookmark in the log.

```
topic "orders"
 partition 0: [0][1][2][3][4][5] ◀── consumer A at offset 3
 partition 1: [0][1][2][3]       ◀── consumer B at offset 4
 partition 2: [0][1][2][3][4]    ◀── consumer C at offset 1

 (each partition replicated to 3 brokers; one replica is leader)
```

- **Consumer groups**: partitions of a topic are divided among the group's members; each partition goes to exactly one consumer in the group. Two different groups each get all the data — that's how one stream feeds both billing and analytics.
- **Replication & ISR**: each partition has a leader and followers. Followers that are caught up form the **In-Sync Replica set**. With `acks=all`, a write is committed only once the ISR has it — so a leader crash loses nothing.

### Build It

1. Producer hashes the message key to pick a partition, sends to that partition's leader broker.
2. Leader appends to its log; followers fetch and append; leader advances the *high watermark* to the minimum ISR offset.
3. Consumers poll `fetch(partition, offset)`, process, then commit offsets back to Kafka (`__consumer_offsets` topic).
4. When a consumer joins or dies, the group coordinator triggers a **rebalance**, reassigning partitions.
5. Old segments are deleted by retention time/size — or compacted, keeping the latest record per key.

### Use It

Kafka shines for event streams, log aggregation, CDC pipelines, and stream processing (Kafka Streams, Flink). Tradeoffs: partitions cap your parallelism (max useful consumers in a group = partition count), rebalances cause pauses, and small-scale setups carry real operational weight — hence managed offerings (Confluent, MSK) and lighter clones (Redpanda).

### War Story

Kafka was built at LinkedIn around 2010 by Jay Kreps, Neha Narkhede, and Jun Rao to unify their tangle of point-to-point data pipelines, then open-sourced to Apache in 2011. Kreps' 2013 essay "The Log: What every software engineer should know about real-time data's unifying abstraction" is the canonical read — the log, not the queue, is the primitive.

### Checkpoint

- Why can two consumer *groups* both receive every message, while two consumers in the *same* group cannot?
- What does `acks=all` guarantee, and what role does the ISR play in that guarantee?
- You have 6 partitions and 8 consumers in one group. What happens to the extra 2?

## 04. RabbitMQ and AMQP

**MOTTO:** Kafka is a dumb log with smart consumers; RabbitMQ is a smart broker with dumb consumers.

### The Problem

Sometimes you don't want a firehose — you want a switchboard. "Send payment events to the fraud service AND the ledger, route EU orders to the EU worker pool, give this message a TTL and a priority." Encoding routing logic in every consumer is a mess; you want the broker to do it.

### The Concept

AMQP (the protocol RabbitMQ speaks) separates *where you publish* from *where messages land*. Producers publish to an **exchange**; the exchange routes to **queues** based on **bindings**; consumers subscribe to queues.

```
                       bindings
 producer ─▶ exchange ──────────▶ queue A ─▶ consumer 1
             (direct/            ├▶ queue B ─▶ consumer 2
              fanout/            └▶ queue C ─▶ consumer 3
              topic)
```

- **direct** exchange: route on exact key match ("payments.eu").
- **fanout**: copy to every bound queue (broadcast).
- **topic**: wildcard patterns ("payments.*", "#.error").

### Build It

1. Declare exchange `orders` (type: topic).
2. Declare queue `fraud-check`, bind with pattern `order.created.*`.
3. Declare queue `eu-invoicing`, bind with `order.*.eu`.
4. Publish message with routing key `order.created.eu` → lands in *both* queues.
5. Consumers ack per-message; unacked messages are redelivered; `prefetch` limits how many unacked messages a consumer holds (poor man's backpressure).

### Use It

| | RabbitMQ | Kafka |
|---|---|---|
| Routing | Rich (exchanges, bindings) | By partition key only |
| Replay | No (ack = gone)* | Yes (offsets) |
| Throughput | High | Very high |
| Per-message TTL/priority | Yes | No |
| Best for | Task queues, RPC, routing | Streams, pipelines, replay |

*RabbitMQ 3.9+ added "streams" for Kafka-style replay, but the classic model is delete-on-ack.

### War Story

AMQP was born in finance: John O'Hara at JPMorgan Chase initiated it in 2003 to break vendor lock-in on messaging middleware, and RabbitMQ (2007, written in Erlang — a language built for telecom reliability) became its flagship implementation. Erlang's lightweight processes are a big reason a single Rabbit node juggles hundreds of thousands of queues.

### Checkpoint

- A message must reach three different services, each with independent retry. Exchange type and topology?
- Why does delete-on-ack make RabbitMQ a poor fit for "reprocess last month's events"?
- What does consumer `prefetch` control, and what goes wrong if it's unlimited?

## 05. Pub/Sub vs Queues

**MOTTO:** A queue divides work; pub/sub multiplies it.

### The Problem

"Send this message to a worker" and "announce this event to whoever cares" look similar but are opposite semantics. Pick the wrong one and you either process every job N times (oops, N duplicate emails) or exactly one of your N interested services hears the news.

### The Concept

A queue is a taxi rank: one rider per taxi, each job consumed by exactly one worker — *competing consumers*. Pub/sub is a radio station: every tuned-in listener gets the full broadcast.

```
QUEUE (work sharing)              PUB/SUB (event broadcast)
        ┌▶ worker 1 (m1, m4)              ┌▶ billing    (m1, m2, m3)
 [q] ───┼▶ worker 2 (m2)         topic ───┼▶ analytics  (m1, m2, m3)
        └▶ worker 3 (m3)                  └▶ search     (m1, m2, m3)
```

The unifying trick: broadcast to *groups*, compete *within* a group. Kafka consumer groups, SQS+SNS fanout, and RabbitMQ fanout-exchange-into-queues all implement exactly this.

### Build It

1. Model the flow: is the message a **command** ("resize this image" — do once) or an **event** ("image uploaded" — inform all)? Commands → queue. Events → pub/sub.
2. For pub/sub with work sharing: one topic, one subscription/queue *per consuming service*, many workers competing on each subscription.
3. Keep events past-tense and self-contained; keep commands imperative and targeted.
4. Rule of thumb: the *producer* knows who handles a command; the producer of an event should *not* know or care who's listening.

### Use It

| Tool | Queue mode | Pub/sub mode |
|---|---|---|
| Kafka | one consumer group | multiple consumer groups |
| RabbitMQ | one queue | fanout/topic exchange → N queues |
| AWS | SQS | SNS → N SQS queues |
| GCP | Pub/Sub (one subscription) | Pub/Sub (N subscriptions) |

### War Story

The publish–subscribe pattern was formalized in distributed-systems research decades ago (the classic survey is Eugster et al., "The Many Faces of Publish/Subscribe," ACM Computing Surveys 2003), which named its three decouplings: space, time, and synchronization. Every modern event bus is a footnote to that framing.

### Checkpoint

- "Order placed" must trigger email, inventory, and fraud systems. Queue or pub/sub, and why?
- How does a Kafka consumer group give you queue semantics on top of a pub/sub log?
- Why should event producers not know their subscribers, while command senders may know their handler?

## 06. Delivery Semantics: At-Most, At-Least, Exactly-Once

**MOTTO:** Exactly-once delivery is a lie; exactly-once *processing* is an engineering project.

### The Problem

The network eats messages and duplicates them. If a consumer crashes after processing but before acking, the broker redelivers — duplicate. If it acks before processing and then crashes — lost message. You can't have neither; you must pick which poison and design for it.

### The Concept

It's certified mail. At-most-once: drop the letter in the box and walk away — maybe it arrives. At-least-once: demand a signed receipt and resend until you get one — it arrives, possibly twice. "Exactly-once" over an unreliable channel is impossible in general (this is the Two Generals problem); what systems actually offer is at-least-once delivery + deduplication = **effectively-once processing**.

```
at-most-once:   ack BEFORE processing  → crash = message lost
at-least-once:  ack AFTER  processing  → crash = message duplicated
"exactly-once": at-least-once + idempotent/deduplicating consumer
```

### Build It

Making at-least-once safe:

1. Give every message a stable unique ID (or idempotency key).
2. Consumer, in ONE local transaction: check `processed_ids` for the ID → if present, skip; else do the work AND insert the ID.
3. Ack only after the transaction commits.

```python
def handle(msg):
    with db.tx():
        if db.exists("processed", msg.id):
            return  # duplicate, drop it
        apply_business_logic(msg)
        db.insert("processed", msg.id)
    broker.ack(msg)
```

Alternatively, make the operation naturally idempotent: `SET balance = 90` survives replay; `balance -= 10` does not.

### Use It

| Semantics | Cost | Use when |
|---|---|---|
| At-most-once | Cheapest | Metrics, telemetry — losing a few is fine |
| At-least-once | Dedup burden on consumer | Default for almost everything |
| Exactly-once (Kafka txns) | Throughput + complexity | Kafka-to-Kafka stream processing |

Kafka's "exactly-once semantics" (idempotent producer + transactions, KIP-98) genuinely works — *within* the Kafka ecosystem. The moment you call an external API, you're back to idempotency keys.

### War Story

In 2012 Knight Capital deployed broken trading software that fired duplicate/erroneous orders into the market; in about 45 minutes it lost ~$440 million and the firm effectively died. Not a message-broker bug per se — but the canonical reminder that "processed more than once" can be an extinction-level event, and idempotency is not optional where money moves.

### Checkpoint

- Why is exactly-once *delivery* impossible over a lossy network, while exactly-once *processing* is achievable?
- A consumer acks, then crashes mid-processing. Which semantics was it running, and what's the consequence?
- Give one operation that's naturally idempotent and one that isn't, and fix the latter.

## 07. Ordering, Partitions, and Keys

**MOTTO:** Global order is expensive; per-key order is usually all you ever needed.

### The Problem

Events for order #123 arrive as `shipped` then `created` and your state machine faceplants. But enforcing one global order means one single consumer thread for the whole system — throughput dies. How do you scale out *and* keep the sequences that matter?

### The Concept

You don't need every message in order — you need every message *about the same entity* in order. Supermarket checkout: it doesn't matter how customers interleave across lanes, only that each customer's items stay together in one lane. Hash the entity key to pick a lane.

```
 key="order:123" ──hash──▶ partition 1: [created][paid][shipped]   ✓ ordered
 key="order:456" ──hash──▶ partition 2: [created][cancelled]       ✓ ordered
                                        (no order ACROSS partitions — fine!)
```

Kafka's contract: order is guaranteed *within* a partition only. Same key → same partition → per-key order, with parallelism = number of partitions.

### Build It

1. Choose the key = the entity whose history must be sequential (order ID, user ID, account ID).
2. `partition = hash(key) % num_partitions`.
3. Consumer processes each partition single-threaded (or per-key serialized) to preserve order through processing too.
4. Watch for **hot keys**: one furiously active entity pins one partition/consumer. Fix by splitting the entity or accepting the ceiling.
5. Beware: increasing partition count changes `hash % N` mappings — old and new messages for one key can land in different partitions during the transition.
6. Retries can still reorder (msg1 fails and retries after msg2 succeeded). If strict order matters, pause the key on failure instead of skipping ahead.

### Use It

Kafka/Kinesis: partition key. SQS standard: no ordering at all. SQS FIFO: ordering per `MessageGroupId` (same idea, ~different limits). Pulsar: key-shared subscriptions. Rule of thumb: design for per-key order; if someone claims they need global order, make them prove it — they almost never do.

### War Story

Leslie Lamport's 1978 paper "Time, Clocks, and the Ordering of Events in a Distributed System" established that in a distributed system there is no inherent total order of events — only the partial order induced by causality. Partitioned logs are that theory productized: preserve the causal chains you care about (per key), and stop paying for order you don't.

### Checkpoint

- Why does adding partitions to an existing topic threaten per-key ordering?
- What's a hot key, and what's the throughput consequence?
- Your consumer retries failed messages to a retry queue. What did that just do to ordering, and when is it acceptable?

## 08. Dead Letter Queues and Retry Strategies

**MOTTO:** A message that can't be processed shouldn't be allowed to take the whole line hostage.

### The Problem

One malformed message makes your consumer throw. The broker redelivers it. It throws again. Forever. Your queue is now a treadmill powered by a single poison message, real work piles up behind it, and your error tracker is on fire with the same stack trace 40,000 times.

### The Concept

The DLQ is the post office's "undeliverable mail" bin. Try delivery a few times; if it keeps failing, move the letter to the bin for a human, and *keep the trucks moving*.

```
 main queue ─▶ consumer ──ok──▶ ack
                  │fail
                  ▼
            retry (with backoff) ×N
                  │still failing
                  ▼
            ┌───────────┐
            │    DLQ    │──▶ alert → human inspects → fix → replay
            └───────────┘
```

### Build It

1. Track attempt count per message (broker-side delivery count, or a header you increment).
2. On failure, retry with **exponential backoff + jitter**: `delay = min(cap, base * 2^attempt) * random(0.5, 1.5)`. Jitter prevents synchronized retry stampedes.
3. Distinguish error types: *transient* (timeout, 503) → retry; *permanent* (validation error, poison payload) → straight to DLQ, don't waste retries.
4. After N attempts, publish the message + error metadata to the DLQ and ack the original.
5. Alert on DLQ depth > 0. A silent DLQ is just a data-loss queue with extra steps.
6. Build a replay path: after fixing the bug, pump DLQ messages back to the main queue.

Delayed retries in queue-land are commonly done with tiered retry queues (retry-1m, retry-10m, retry-1h) or broker-native delayed delivery.

### Use It

SQS has native DLQs with `maxReceiveCount` redrive policy (and one-click redrive back). RabbitMQ uses dead-letter exchanges (rejected/expired messages reroute automatically). Kafka has no native DLQ — the convention is a `topic.DLT` that your consumer framework (e.g., Spring Kafka) publishes to.

### War Story

AWS's Builders' Library essay "Timeouts, retries, and backoff with jitter" (Marc Brooker) is the industry's standard reference: their simulations show plain exponential backoff still produces clustered retry spikes, and *jitter* — not more backoff — is what flattens the thundering herd. Retries without jitter are a self-inflicted DDoS on your own recovering service.

### Checkpoint

- Why should a schema-validation failure skip retries entirely?
- What specific problem does jitter solve that exponential backoff alone doesn't?
- Your DLQ has 5,000 messages and no alarms fired. What did the team forget, and what are those messages effectively?

## 09. The Transactional Outbox Pattern

**MOTTO:** You can't atomically commit to two systems — so commit to one and let it tell the other.

### The Problem

Your service must save an order to Postgres AND publish `order_created` to Kafka. Write DB then publish? A crash in between means a saved order nobody hears about. Publish then write? A rollback means an announced order that doesn't exist. There is no transaction spanning your database and your broker.

### The Concept

Stop doing two writes. Do ONE atomic write — to the database — that includes both the order and the message, the message going into an `outbox` table *in the same transaction*. A separate relay process then moves outbox rows to the broker. The DB transaction is the single source of truth; publishing becomes an at-least-once follow-up.

```
 ┌── DB TRANSACTION ───────────────┐
 │ INSERT INTO orders (...)        │   relay/CDC        Kafka
 │ INSERT INTO outbox (event json) │ ───────────────▶ [order_created]
 └────────── atomic ✓ ─────────────┘   (polls or tails WAL)
```

### Build It

1. `outbox(id, aggregate_id, event_type, payload, created_at, published_at NULL)`.
2. Business code writes the entity + outbox row in one transaction. Crash before commit → neither exists. Crash after → both exist.
3. Relay options:
   - **Polling publisher**: `SELECT ... WHERE published_at IS NULL ORDER BY id LIMIT 100`, publish, mark published. Simple; adds poll latency.
   - **CDC / log tailing**: Debezium reads the DB's WAL and streams outbox inserts to Kafka. Lower latency, no polling load, more moving parts.
4. The relay can crash after publishing but before marking-published → duplicate publish. That's fine: consumers are idempotent (lesson 06). Outbox gives at-least-once, never zero-or-ghost.
5. Prune published rows on a schedule.

### Use It

Debezium's "outbox event router" is purpose-built for this. Alternatives with different tradeoffs: *listen-to-yourself* (publish first, consume your own event to update state) and using CDC on the business tables directly (couples consumers to your schema — the outbox row is a deliberate, stable contract instead).

### War Story

The pattern was popularized by Chris Richardson's microservices.io pattern catalog and his book *Microservice Patterns* (2018), as the standard answer to the "dual write problem." Debezium — built on Kafka Connect and born at Red Hat — turned it from a cron-job hack into boring, reliable infrastructure, and "just Debezium the outbox" became the default recipe for reliable event publishing from a relational DB.

### Checkpoint

- Walk through the two crash windows of the naive dual-write and what each leaves behind.
- Why is the outbox pattern at-least-once, and what does that require of consumers?
- Polling relay vs CDC relay: name one advantage of each.

## 10. Event Sourcing

**MOTTO:** Don't store what things are; store what happened — the present is just a fold over the past.

### The Problem

A traditional `UPDATE accounts SET balance = 60` destroys information: you know the balance is 60, but not how it got there. Then the auditor asks for the history, the PM asks "what did the cart look like before the bug," and debugging demands the sequence of events. Current-state storage has amnesia.

### The Concept

Your bank already does this. Your "balance" isn't a stored number that gets overwritten — it's the sum of every deposit and withdrawal ever made. Event sourcing makes the append-only ledger the *system of record* and treats current state as a derived, disposable computation.

```
 event store (append-only, immutable):
 [AccountOpened][Deposited $100][Withdrew $40][Deposited $25]
        └──────────── replay / fold ────────────┘
                        ▼
              current state: balance = $85
        (+ snapshot every N events so replay stays fast)
```

### Build It

1. `events(stream_id, version, type, payload, ts)` with a unique constraint on `(stream_id, version)`.
2. **Write path**: load the stream's events → fold into current state → validate the command against that state → append the new event at `version+1`. The unique constraint rejects concurrent writers (optimistic concurrency).
3. **Read path**: replay events (from the latest snapshot) to rebuild state; or maintain **projections** — read models updated by consuming the event stream.
4. Snapshots: every N events, persist the folded state so you replay N events max, not the whole history.

```python
def apply(state, e):
    if e.type == "Deposited": state.balance += e.amount
    if e.type == "Withdrew":  state.balance -= e.amount
    return state

state = reduce(apply, load_events(stream_id), initial_state())
```

### Use It

EventStoreDB is purpose-built; Kafka (with compaction caveats), Postgres, and DynamoDB all serve as event stores in practice. Wins: perfect audit trail, temporal queries ("state as of March 3rd"), replay to fix bugs or build new projections. Costs: schema evolution of *immutable* events (upcasters, versioned event types), GDPR deletion is awkward (crypto-shredding), and it's real complexity — use it for domains where history *is* the business (money, inventory, orders), not for your settings page.

### War Story

Accountants have been event-sourcing since double-entry bookkeeping emerged in medieval Italy (codified by Pacioli, 1494): you never erase a ledger line, you append a correcting entry. Martin Fowler's 2005 essay "Event Sourcing" and Greg Young's decade of talks brought the ledger mindset to software — five centuries of production experience is a decent pilot program.

### Checkpoint

- Why do snapshots not compromise the "events are the source of truth" principle?
- How does the `(stream_id, version)` unique constraint implement optimistic concurrency?
- Name two questions an event-sourced system can answer that a current-state system cannot.

## 11. CQRS

**MOTTO:** The shape that's right for writing is usually wrong for reading — so stop using one shape.

### The Problem

Your beautifully normalized write model needs a 9-table join to render the product page, and your denormalized read-fast schema makes updates a consistency minefield. One model is being asked to serve two masters with opposite needs — and reads outnumber writes 100:1.

### The Concept

CQRS — Command Query Responsibility Segregation — splits the models. **Commands** (writes) go to a model optimized for enforcing business rules; **queries** hit separate read models — denormalized, precomputed, one per screen if you like. A restaurant doesn't cook your order in front of you from raw ingredients per request... actually, it *preps* ahead: the read model is mise en place for queries.

```
          commands                         queries
 client ──────────▶ write model            read model ◀────────── client
                    (normalized,   events  (denormalized views,
                     invariants) ─────────▶ Elastic, Redis, SQL)
                              async projection
                              └── eventual consistency! ──┘
```

### Build It

1. Split the API: `POST /orders` (command, returns ack not data) vs `GET /orders/123/summary` (query, no side effects).
2. Write side commits, then emits an event (via the outbox, lesson 09).
3. **Projectors** consume events and update read models: an Elasticsearch doc for search, a Redis hash for the dashboard, a flat SQL table for reports.
4. Accept the lag: a user may write and then read a stale view. Mitigations: read-your-own-writes from the write side, UI optimism, or returning the new state in the command response.
5. Start small — CQRS can be two tables in one Postgres. The pattern is the *split*, not the tech zoo.

### Use It

| Read model | Serves |
|---|---|
| Elasticsearch | Full-text search |
| Redis | Hot dashboards, counters |
| Denormalized SQL | Reporting, admin screens |
| Materialized views | Poor-man's CQRS, one DB |

Pairs naturally with event sourcing (events are the projection feed) but does not require it. Skip CQRS when a CRUD app is doing fine — it doubles your models and your deploy surface.

### War Story

Greg Young coined CQRS in the late 2000s as an evolution of Bertrand Meyer's Command-Query Separation principle (from *Object-Oriented Software Construction*): Meyer said a *method* should either mutate or return, never both; Young promoted that rule from methods to entire architectures. Young himself spent years warning that CQRS is "not a top-level architecture" — apply it per subsystem, not everywhere.

### Checkpoint

- Why does CQRS almost always imply eventual consistency between write and read sides?
- Give a concrete strategy for "user saves, then immediately sees stale data" complaints.
- What's the relationship between CQRS and event sourcing — which requires which?

## 12. Build a Message Queue From Scratch

**MOTTO:** If you can write `append()` and remember a number, you can build Kafka's soul.

### The Problem

You've talked about partitions, offsets, and consumer groups for eleven lessons. Time to prove they're not magic: build a working partitioned log with durable messages, keyed ordering, and per-group consumer offsets — the actual Kafka mental model — in ~80 lines of Python.

### The Concept

Three ideas, composed: (1) a partition is a file you only append to; (2) consuming is just reading from a remembered position; (3) a consumer group is a dict mapping partition → position. Everything else is optimization.

```
 data/orders/p0.log   ← append-only JSONL, one msg per line
 data/orders/p1.log
 offsets: {"billing": {0: 17, 1: 9}, "analytics": {0: 5, 1: 2}}
```

### Build It

```python
import json, os, hashlib

class MiniKafka:
    def __init__(self, root, topic, partitions=3):
        self.dir = os.path.join(root, topic)
        os.makedirs(self.dir, exist_ok=True)
        self.n = partitions
        self.offsets = {}                      # group -> {partition: next_offset}

    def _path(self, p): return os.path.join(self.dir, f"p{p}.log")

    def produce(self, key, value):
        p = int(hashlib.md5(key.encode()).hexdigest(), 16) % self.n   # same key -> same partition
        with open(self._path(p), "a") as f:
            f.write(json.dumps({"key": key, "value": value}) + "\n")
            f.flush(); os.fsync(f.fileno())    # durability: it's on disk or it didn't happen
        return p

    def consume(self, group, partition, max_msgs=10):
        off = self.offsets.setdefault(group, {}).setdefault(partition, 0)
        if not os.path.exists(self._path(partition)): return []
        with open(self._path(partition)) as f:
            lines = f.readlines()
        batch = [json.loads(l) for l in lines[off : off + max_msgs]]
        return batch                            # NOTE: offset not advanced yet

    def commit(self, group, partition, count):  # at-least-once: commit AFTER processing
        self.offsets[group][partition] += count
```

Exercises, in order of pain:
1. Persist `offsets` to a JSON file — survive restarts (this is `__consumer_offsets`).
2. Track byte positions instead of re-reading all lines — O(1) fetch.
3. Add a `rebalance(group, consumers)` that splits partitions among consumers.
4. Crash a consumer after `consume` but before `commit`; observe the redelivery. You just *demonstrated* at-least-once.

### Use It

Map every toy piece to the real thing: `p0.log` → Kafka segment files; `os.fsync` → broker flush policy; `offsets` dict → `__consumer_offsets` topic; your md5 hash → the producer partitioner (Kafka uses murmur2). What the toy lacks is exactly Kafka's hard 20%: replication/ISR, segment rolling and retention, group coordination, and zero-copy network I/O.

### War Story

Kafka's original design bet — documented in the 2011 NetDB paper "Kafka: a Distributed Messaging System for Log Processing" (Kreps, Narkhede, Rao) — was that sequential disk I/O plus the OS page cache beats clever in-memory structures: sequential writes to spinning disks were measured in hundreds of MB/s while random writes managed ~100 KB/s. The "dumb" append-only file wasn't a simplification of the design. It *was* the design.

### Checkpoint

- Where exactly in the toy's consume/commit cycle does the at-least-once guarantee come from?
- Why does hashing the key give per-key ordering in this implementation?
- Which real-Kafka feature would you add first to make this production-worthy, and why?
