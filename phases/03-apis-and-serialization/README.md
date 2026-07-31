# Phase 03 — 🔌 APIs & Serialization

> Contracts between machines — and the humans who break them.

An API is a promise made in public: other people's code will depend on your exact field names, your exact error codes, and your exact behavior at 2 a.m. under retry storms. This phase is about making promises you can keep — designing interfaces, encoding data efficiently, evolving contracts without breaking strangers, and surviving the network's failure modes with idempotency, timeouts, and backoff. It's the least glamorous phase and the one that most decides whether people enjoy building on your systems.

## 01. REST API design that doesn't hurt

**MOTTO:** Good REST is boring on purpose — surprise is the only real API design crime.

### The Problem

Every team invents its own API dialect: `/getUserData?uid=5`, `POST /deleteUser`, errors as `200 OK {"error": true}`. Each snowflake API forces every consumer to learn, wrap, and work around it. The cost isn't aesthetics — it's every integration bug caused by a violated expectation.

### The Concept

REST's usable core: model your domain as **nouns (resources)** addressed by URLs, manipulated with HTTP's standard **verbs**, returning HTTP's standard **status codes**. The payoff is predictability — a developer who's seen one good REST API can guess yours. (Purist REST — Roy Fielding's architectural style — includes hypermedia; the industry mostly ships this pragmatic subset.)

```
 GET    /users            list      (safe: no side effects)
 POST   /users            create    (returns 201 + Location: /users/42)
 GET    /users/42         read
 PATCH  /users/42         partial update   (PUT = full replace)
 DELETE /users/42         delete
 GET    /users/42/orders  nested resource

 statuses: 200 ok · 201 created · 204 no content · 400 your fault ·
 401 who are you · 403 not allowed · 404 no such thing · 409 conflict ·
 422 understood-but-invalid · 429 slow down · 500 our fault · 503 try later
```

### Build It

Design checklist, in order of how often it's violated:

1. Nouns, not verbs, in paths (`POST /orders`, never `/createOrder`). Actions that resist nouning become sub-resources: `POST /orders/42/cancellation`.
2. Status codes carry the truth. Never tunnel errors inside `200`.
3. `GET` must be safe and cacheable; anything state-changing goes in POST/PUT/PATCH/DELETE — intermediaries and browsers *will* assume this.
4. Plural nouns, consistent casing, consistent envelope (pick `{"data": ..., "error": ...}` or bare — once).
5. Design the *error body* as carefully as the success body: machine-readable code, human message, correlation ID.
6. Write the OpenAPI spec first; generated docs, clients, and mock servers all fall out of it.

### Use It

| Style | Sweet spot | Weakness |
|---|---|---|
| REST/JSON | public APIs, CRUD-ish domains | verbs-that-aren't-CRUD get awkward |
| gRPC (Lesson 02) | internal service-to-service | browser/human hostility |
| GraphQL (Lesson 03) | many heterogeneous clients | server complexity, caching |

Stripe's and GitHub's public APIs are the de facto style guides — read them like literature.

### War Story

REST comes from Roy Fielding's 2000 PhD dissertation, which *reverse-engineered* why the web had scaled — statelessness, uniform interface, cacheability — rather than proposing something new. Fielding co-authored HTTP/1.1 itself, and has spent years since politely noting that most "REST" APIs ignore half his constraints; the pragmatic subset won anyway, because predictability was the part everyone actually needed.

### Checkpoint

- Why must `GET` never mutate state — name two pieces of infrastructure that assume this.
- Design the routes and status codes for "user 42 cancels order 7, but it already shipped."
- What belongs in a well-designed error response body, and why an error *code* separate from the HTTP status?

## 02. gRPC and Protocol Buffers

**MOTTO:** Write the contract once; generate the client, the server, and the arguments about types.

### The Problem

Internal microservices calling each other over REST/JSON pay a triple tax: JSON bytes are bloated and slow to parse, every service hand-writes client wrappers, and nothing machine-checks that caller and callee agree on the shape of anything. At hundreds of services, "we'll keep the docs updated" is comedy.

### The Concept

Flip the workflow: define the API in a `.proto` **schema file**, and generate everything from it. **Protocol Buffers** encode messages as compact binary — field *numbers* (not names) tagged with wire types, varint-encoded integers, missing fields omitted — typically several times smaller and much faster to parse than JSON. **gRPC** carries those messages as RPC calls over HTTP/2 (Phase 2, Lesson 07), inheriting multiplexing and gaining four call shapes: unary, server-streaming, client-streaming, bidirectional.

```
 // orders.proto
 service Orders {
   rpc GetOrder (GetOrderRequest) returns (Order);
   rpc WatchOrders (WatchRequest) returns (stream Order);  // server push
 }
 message Order {
   int64 id = 1;              // <- field numbers are the wire contract,
   string status = 2;         //    names are just for humans
   repeated LineItem items = 3;
 }

 protoc ──> generated client (10+ languages) + server stubs + types
```

### Build It

1. Write the `.proto`; run `protoc` (or `buf`) to generate Python/Go/Java stubs.
2. Server: implement the generated service interface — the only code you write is the logic.
3. Client: `stub.GetOrder(GetOrderRequest(id=42))` — a typed function call; serialization, HTTP/2, deadlines all hidden beneath.
4. Evolution rules that make protobuf famous: **never reuse or renumber a field**; add new fields with new numbers (old readers skip unknown fields; new readers treat missing as default); `reserved 4;` retired numbers so no one reuses them. Follow these and decade-old binaries still parse today's messages.
5. Note what you lose: `curl`ability. Debugging binary needs tooling (`grpcurl`, reflection).

### Use It

| Dimension | gRPC/protobuf | REST/JSON |
|---|---|---|
| Payload size / parse cost | small, fast | 3–10x larger, slower |
| Type safety | generated, compile-time | discipline + validators |
| Browser support | poor (needs grpc-web proxy) | native |
| Human debuggability | tooling required | curl and eyeballs |
| Streaming | first-class, 4 shapes | bolt-on (SSE/WS) |

Standard posture: gRPC inside the datacenter, REST/JSON at the public edge.

### War Story

Protocol Buffers date to the early 2000s inside Google, and gRPC (open-sourced 2015) is the public descendant of **Stubby**, the internal RPC framework carrying on the order of 10¹⁰ RPCs per second across Google's services. The design wasn't speculative: the schema-evolution rules exist because Google learned, at scale, exactly how contracts rot when thousands of binaries upgrade at different times.

### Checkpoint

- Why are protobuf field *numbers* sacred while field *names* are freely renameable?
- A new required-in-spirit field must be added to a message consumed by 40 services. What's the safe sequence?
- Why does gRPC specifically require HTTP/2 — which two features does it lean on?

## 03. GraphQL: queries, mutations, and the N+1 trap

**MOTTO:** GraphQL lets clients order à la carte — and makes the kitchen's life correspondingly interesting.

### The Problem

A REST backend serving mobile, web, and TV clients faces death by round trips: the mobile app needs a user, their last 5 orders, and each order's first item's thumbnail — that's 1 + 5 + 5 REST calls (underfetching), or one bloated bespoke endpoint per screen (overfetching, endpoint sprawl). Multiply by every screen on every platform.

### The Concept

GraphQL exposes one endpoint and a typed **schema graph**; the *client* sends a query describing exactly the shape it wants, and gets exactly that shape back. **Queries** read, **mutations** write, **subscriptions** stream. The server implements a **resolver** per field — and therein hides the famous trap.

```
 query {                          # one round trip
   user(id: 42) {
     name
     orders(last: 5) {
       total
       items(first: 1) { thumbnailUrl }
     }
   }
 }

 N+1 trap:  resolve user (1 query)
            -> resolve orders (1 query)
            -> resolve items for order#1 (1 query)  ┐
               ... order#2 ... order#3 ...          ├ N more queries
               naive resolvers = death by a thousand SELECTs ┘
```

### Build It

1. Define schema types (`type User { name: String!, orders(last: Int): [Order!]! }`).
2. Write resolvers: functions receiving `(parent, args, context)` returning each field.
3. **Slay N+1 with DataLoader:** within one request tick, collect all pending `Order.items` lookups, issue *one* batched `WHERE order_id IN (...)` query, fan results back out. Batching + per-request caching is the pattern; every serious GraphQL server uses it.
4. Defend the kitchen — clients can now compose pathological orders: enforce query depth limits, complexity budgets (cost points per field), pagination limits, and timeouts. A public GraphQL API without these is a DoS invitation with documentation.

### Use It

| Reality check | Verdict |
|---|---|
| Many client types, fast-moving UIs | GraphQL's home turf |
| Simple CRUD, one client | REST is less machinery |
| HTTP caching (CDNs) | harder — POSTed queries bypass URL caching |
| File uploads, webhooks | awkward; usually stays REST |

Ecosystem: Apollo, GraphQL Yoga, Relay; schema federation for splitting the graph across teams.

### War Story

GraphQL was built at Facebook starting in 2012, when rebuilding its mobile apps as native clients collided with REST endpoint sprawl and mobile networks' round-trip costs; it was open-sourced in 2015 and later spun into the GraphQL Foundation. GitHub's public API v4 adopted it — citing exactly the flexibility-vs-many-clients math — while keeping v3 REST alongside, which is itself a lesson: GraphQL tends to *join* REST, not replace it.

### Checkpoint

- Explain over- and underfetching, and how one GraphQL query addresses both.
- Walk through how DataLoader converts an N+1 resolver cascade into two queries.
- Name three guardrails a public GraphQL endpoint needs that a fixed REST endpoint gets implicitly.

## 04. JSON vs binary formats: the serialization showdown

**MOTTO:** Every message pays a tax in bytes and CPU — choose your tax bracket deliberately.

### The Problem

Serialization is invisible until it isn't: at 10K messages/sec, JSON's repeated field names, quoted numbers, and parse cost become real machines and real milliseconds. But the tempting fix — binary everything — costs you `curl`, greppable logs, and effortless interop. This is a genuine tradeoff, not a performance morality play.

### The Concept

Formats differ on three axes: **text vs binary**, **schema-on-read vs schema-required**, and **self-describing vs positional**. JSON ships field names in every message (self-describing, human-readable, redundant); protobuf ships field numbers and relies on the schema to interpret them (compact, opaque); Avro goes further — barely any per-message metadata, with the schema stored *alongside the data* (superb for millions of records per file).

```
 {"id": 123456, "active": true, "name": "ada"}      JSON: 46 bytes
 protobuf: 08 c0 c4 07 10 01 1a 03 61 64 61          11 bytes
           └field 1 varint┘ └f2┘ └f3: len 3 "ada"┘
 same information, ~4x smaller, no names on the wire
```

### Build It

Run the showdown yourself:

```python
import json, pickle, timeit
record = {"id": 123456, "active": True, "name": "ada", "scores": list(range(50))}
for name, enc, dec in [
    ("json",   lambda o: json.dumps(o).encode(), lambda b: json.loads(b)),
    ("pickle", pickle.dumps,                     pickle.loads),
]:
    blob = enc(record)
    t = timeit.timeit(lambda: dec(enc(record)), number=20_000)
    print(f"{name:7} {len(blob):4} bytes  {t:.2f}s / 20k round trips")
# then: pip install protobuf / msgpack and extend the table
```

Also measure *with compression* — gzipped JSON closes much of the size gap (those repeated names compress well), so the remaining argument is parse CPU and type fidelity (JSON has no integers-vs-floats distinction, no binary type, no 64-bit-int safety in JavaScript).

### Use It

| Format | Schema | Superpower | Watch out |
|---|---|---|---|
| JSON | none | universal, debuggable | size, parse cost, number types |
| Protobuf | required | compact, evolvable, codegen | tooling needed to inspect |
| Avro | required (stored with data) | big-data files, schema registry | JVM-centric ecosystem |
| MessagePack/CBOR | none | "binary JSON," drop-in | still ships field names |
| Parquet | required | columnar analytics scans | not a message format |

Default: JSON at the edge, protobuf between services, Avro/Parquet at rest in the data platform.

### War Story

The simdjson project (Daniel Lemire et al., paper 2019) showed JSON parsing could hit gigabytes per second using SIMD instructions — an implicit indictment of how much CPU the world was burning on naive parsers. It's a rare double lesson: text formats cost more than people think, *and* clever engineering can claw back an order of magnitude before you abandon readability.

### Checkpoint

- Why does protobuf's schema-required design make messages smaller than self-describing formats?
- Why does gzip narrow the JSON-vs-binary *size* gap but not the *CPU* gap?
- Your analytics team scans billions of rows but reads 3 of 40 columns. Which format family and why?

## 05. API versioning without tears

**MOTTO:** You can change an API or you can have users — with versioning discipline, both.

### The Problem

Your API has a thousand integrations you've never met. Rename a field and somewhere a warehouse stops shipping. But never changing anything means the API fossilizes around every early mistake. Versioning is how you buy the right to improve without breaking strangers.

### The Concept

First, know the line. **Non-breaking** (just ship it): adding response fields, adding optional parameters, adding endpoints. **Breaking** (needs a version): removing/renaming anything, changing types or semantics, tightening validation, restructuring errors. The golden default that makes most versioning unnecessary is the *robustness expectation on clients*: consumers must ignore unknown fields — then additive change is free forever.

```
 URL path:    GET /v2/users/42          loud, cacheable, simple
 Header:      GET /users/42
              Accept: application/vnd.api+json; version=2
 Date-pinned: GET /users/42
              Stripe-Version: 2024-06-20   <- account pinned to a date;
                                             upgrade when YOU choose
```

### Build It

A survivable versioning policy, end to end:

1. Publish the compatibility contract: "we add fields without notice; clients MUST tolerate unknown fields." Enforce with contract tests.
2. Breaking changes ride a new version; old versions get a **deprecation window** with dates, not vibes.
3. Instrument per-version, per-consumer usage — you cannot retire what you cannot measure; emails to "whoever still calls v1" require knowing who that is.
4. Warn in-band: `Deprecation`/`Sunset` headers, changelog, and direct outreach to the top-N callers.
5. Internally, translate: implement the *latest* logic once, with thin adapters mapping old request/response shapes onto it (Stripe has described this "version-change modules" architecture) — never maintain N parallel codebases.

### Use It

| Scheme | Pro | Con |
|---|---|---|
| Path (`/v2/`) | obvious, easy routing/caching | "big bang" migrations; v1 lingers a decade |
| Header | clean URLs | invisible in logs/browsers; easy to forget |
| Date-pinned per account | continuous evolution, per-consumer pace | serious internal machinery |
| Additive-only + no versions | zero migration cost | mistakes become permanent residents |

For gRPC, the field-number rules (Lesson 02) *are* the versioning story; for GraphQL, `@deprecated` fields plus usage metrics play the same role.

### War Story

Stripe's date-based versioning — each account pinned to the API behavior as of a chosen date (e.g., `2024-06-20`), with old versions supported for years and upgrades opt-in — became the industry's most admired scheme after their engineering write-ups explained the adapter-chain implementation. The moral is the sticker price: world-class compatibility isn't a URL convention, it's an architecture you commit to maintaining.

### Checkpoint

- Classify: adding a response field; renaming `user_name` to `username`; rejecting a formerly accepted malformed date. Which need a version bump?
- Why does "clients must ignore unknown fields" eliminate most versioning needs?
- What operational capability must exist before you can ever *retire* an old version?

## 06. Idempotency: the art of safe retries

**MOTTO:** The network will make you ask twice; idempotency makes asking twice safe.

### The Problem

You POST a $500 payment. The connection times out. Did it go through? You literally cannot know — the timeout may have hit before the request arrived, or *after the server succeeded* but before the response returned. Retry and you risk double-charging; don't retry and you risk the order silently not existing. This ambiguity is fundamental to networks — it cannot be eliminated, only defused.

### The Concept

An operation is **idempotent** if doing it N times equals doing it once — an elevator button, not a "one coffee please" shout. Then retries become free. Some operations are naturally idempotent (`SET x = 5`, `DELETE /users/42`, full PUTs); the dangerous ones are the *increments and creates* (`x += 5`, `POST /payments`). The universal fix: the client names the operation with a unique **idempotency key**, and the server remembers keys it has already processed.

```
 client:  POST /payments  Idempotency-Key: 7f3a-...-91  {amount: 500}
 server:  seen 7f3a before?
            no  -> process, store {key -> response}, reply
            yes -> return the STORED response; do not re-execute
 timeout? client retries with the SAME key -> at-most-once execution
                                            + retries = effectively-once
```

### Build It

The server-side mechanism, honestly:

1. On request: `INSERT INTO idempotency_keys (key, status='running')` — the **unique constraint** is the actual concurrency guard (two racing retries: one insert wins, the loser waits or gets 409).
2. Execute the operation; store the response (status + body) against the key; mark `done`.
3. On replay: return the stored response verbatim.
4. Sharp edges you must decide: keys scoped per endpoint+consumer; TTL (Stripe: ~24 h); a replay with the same key but *different body* is a client bug — reject it (422/409); and the operation+key-write should share a transaction, or a crash between them resurrects the ambiguity you were killing.

Client side: generate a UUID *when the user intends the action* (button press), reuse it across all retries of that intent.

### Use It

HTTP semantics already promise idempotency for GET/PUT/DELETE (which is why infrastructure auto-retries them but never bare POSTs). Stripe's `Idempotency-Key` header popularized the pattern for payments; message consumers reinvent it as deduplication (exactly-once processing = at-least-once delivery + idempotent handling); SQL speaks it as `INSERT ... ON CONFLICT DO NOTHING` and Terraform/Kubernetes as "declare desired state, apply repeatedly."

### War Story

The pattern's fame owes much to Stripe's engineering posts on idempotency keys, which walked through exactly the timeout-ambiguity scenario above for real money. And the cost of the *general* class of unsafe repetition has a grim benchmark: Knight Capital (2012) lost ~$440 million in 45 minutes when re-activated legacy code re-processed orders it should never have repeated — repetition without safety, at market speed.

### Checkpoint

- Why can a client that times out on a POST *never* determine the operation's outcome without help?
- What database feature makes concurrent retries with one idempotency key safe, and what should the second request receive?
- Same key, different request body — what should the server do and why?

## 07. Pagination, filtering, and sorting at scale

**MOTTO:** Nobody gets the whole table — the only question is how gracefully you slice it.

### The Problem

`GET /orders` against ten million rows will OOM your server, saturate the network, and time out the client — so every list API must slice. But the obvious slice, `OFFSET 100000 LIMIT 20`, makes the database *walk and discard* 100,000 rows to serve page 5,001, and shifts items between pages whenever a row is inserted mid-browse. Deep pagination is where naive APIs go to die.

### The Concept

**Offset pagination** is "skip N rows" — simple, jumpable-to-page-7, and O(offset) per request with anomalies under writes. **Cursor (keyset) pagination** is "give me rows *after this bookmark*": the cursor encodes the last-seen sort key, and the database seeks straight to it via index — O(page) forever, stable under inserts.

```
 offset:  SELECT ... ORDER BY created_at DESC OFFSET 100000 LIMIT 20
          └ reads 100,020 rows, returns 20; page drift under inserts

 cursor:  SELECT ... WHERE (created_at, id) < ($cur_ts, $cur_id)
          ORDER BY created_at DESC, id DESC LIMIT 20
          └ index seek; response carries next_cursor = last row's (ts, id)
```

Note the `(created_at, id)` pair: sort keys must be **unique and stable**, so you break timestamp ties with the primary key — otherwise rows sharing a timestamp straddle page boundaries and get skipped or duplicated.

### Build It

1. Response contract: `{"data": [...], "next_cursor": "eyJ0cyI6...", "has_more": true}` — cursor is opaque (base64 of the key tuple); clients must not parse it, which frees you to change its contents.
2. Match the composite index to the sort: `(created_at DESC, id DESC)`. Every offered sort order needs index support, which is precisely why mature APIs offer *few* sort orders.
3. Filtering: whitelist filterable fields (each is an index commitment), reject unknown params loudly, and cap `limit` (e.g., max 100) server-side — never trust `?limit=1000000`.
4. Know the cursor's limits: no "jump to page 47" (offer search/date-range instead), and totals (`COUNT(*)` over millions) deserve an estimate or a separate endpoint, not a tax on every page.

### Use It

| Scheme | Use when | Cost |
|---|---|---|
| Offset | admin UIs, small/static data, page numbers required | deep pages, drift |
| Cursor | feeds, infinite scroll, APIs at scale | no random access |
| Search engine (ES) | arbitrary filter/sort combos | second system to run |

GitHub's REST API (`Link` headers), Slack's (`next_cursor`), and Twitter's (`max_id`/`since_id` — cursor-by-tweet-ID) all converged on cursors for exactly these reasons; GraphQL codified them as the Relay connection spec (`edges`, `pageInfo`, `endCursor`).

### War Story

Twitter's developer documentation has long taught cursoring through its timeline via `max_id` — an early, public admission that offset pagination cannot survive a write-heavy feed: with thousands of tweets arriving between two page fetches, "page 2" by offset would re-serve or skip content unpredictably, while "everything older than tweet 123456" stays exact forever. The bookmark, not the page number, is the scalable primitive.

### Checkpoint

- Why is `OFFSET 1000000 LIMIT 20` slow even with a perfect index on the sort column?
- Why must a cursor's sort key be unique, and how does `(created_at, id)` achieve that?
- Name two client capabilities you give up moving from offset to cursor pagination, and your mitigation for each.

## 08. Errors, retries, timeouts, and deadlines

**MOTTO:** Untuned retries are how a hiccup becomes an outage — with your own clients as the botnet.

### The Problem

A dependency slows down. Callers time out and retry. Now the struggling service receives 2x, then 4x, the load — each retry layer multiplying the last — and a 30-second blip becomes a self-sustaining **retry storm** that outlives the original fault. The failure-handling code becomes the failure.

### The Concept

Four disciplines, layered:

```
 timeout:   never wait forever (every call, no exceptions)
 retry:     only on retryable errors, budgeted, with...
 backoff:   exponential (1s, 2s, 4s...) — give the victim air
 jitter:    randomize the backoff — or all clients return in synchronized
            waves, a thundering herd with a metronome

 deadline propagation:
 user (2s budget) -> A (spent 0.3s, passes 1.7s) -> B (passes 1.2s) -> C
 C sees 1.2s left; if it can't answer in time, fail NOW — a result after
 the user gave up is pure wasted load
```

Classify before retrying: `429`/`503`/timeouts → retry with backoff; `400`/`403`/`422` → *never* retry, it will fail identically forever; `500` → maybe once, if the operation is idempotent (Lesson 06 — non-idempotent retries need keys).

### Build It

```python
import random, time

def call_with_retries(fn, deadline_s, max_attempts=4, base=0.5, cap=8.0):
    for attempt in range(max_attempts):
        remaining = deadline_s - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("deadline exhausted")
        try:
            return fn(timeout=min(remaining, cap))
        except RetryableError:
            sleep = random.uniform(0, min(cap, base * 2 ** attempt))  # full jitter
            if time.monotonic() + sleep > deadline_s: raise
            time.sleep(sleep)
    raise MaxRetriesExceeded
```

System-level guards beyond one client: **retry budgets** (retries ≤ ~10–20% of request volume — Finagle/Envoy style), retry at *one* layer only (edge retries + mesh retries + client retries = combinatorial amplification), and **circuit breakers** (past a failure threshold, fail fast without calling — periodically probe for recovery).

### Use It

| Mechanism | Where you'll meet it |
|---|---|
| Timeout + deadline propagation | gRPC deadlines (first-class, propagated), `context` in Go |
| Backoff + jitter | every AWS SDK default |
| Circuit breaker | Envoy/Istio, Resilience4j, Polly |
| Retry budget | Finagle, Envoy retry policies |

### War Story

AWS's 2015 "Exponential Backoff and Jitter" post (Marc Brooker) simulated competing clients and showed *full jitter* dramatically reducing total work and time-to-recovery versus plain exponential backoff — turning a folk practice into measured doctrine. The companion cautionary tale is the September 2015 DynamoDB disruption, whose public postmortem describes storage servers timing out against an overloaded metadata service and re-requesting in unison — retry pressure sustaining the brownout until AWS throttled it to let the system breathe.

### Checkpoint

- Why does jitter matter even when everyone already uses exponential backoff?
- A downstream call returns 422. Retry or not — and what about a timeout on a non-idempotent POST?
- Explain deadline propagation and the specific waste it prevents in a 4-service call chain.

## 09. Webhooks: APIs in reverse

**MOTTO:** Don't call us, we'll call you — signed, retried, and occasionally twice.

### The Problem

Your app needs to know when a payment settles or a repo gets pushed. Polling the provider's API every few seconds wastes both sides' resources and still averages seconds of staleness (Phase 2, Lesson 10's math). The provider knows *instantly* — the efficient design inverts the arrow: they call you.

### The Concept

A webhook is you registering a URL; the provider POSTs event payloads to it as things happen. Congratulations: you are now a *server* receiving traffic from the internet, and you've inherited server problems — authenticity (is this really Stripe, or an attacker POSTing `payment.succeeded`?), reliability (your endpoint was down for the deploy — where did the event go?), and ordering/duplication (delivery is at-least-once and networks reorder).

```
 [provider] --POST /hooks/payments  {event, id, timestamp}--> [you]
                 |  signature: HMAC-SHA256(secret, timestamp + body)
                 |  you verify BEFORE trusting a byte
                 └─ no 2xx? retry with backoff: 1m, 5m, 30m, ... (hours-days)
                    -> your handler WILL see duplicates -> dedupe by event id
```

### Build It

The consumer-side checklist (where all webhook bugs live):

1. **Verify the signature** — recompute the HMAC over timestamp+raw-body with your shared secret; compare in constant time; reject stale timestamps (replay defense). Raw body, *before* any JSON re-serialization mangles it.
2. **Ack fast, work later** — return `200` immediately after persisting the event to a queue/table; do the real processing async. A 30-second handler gets timed out and re-delivered forever.
3. **Dedupe** — store processed event IDs (Lesson 06's idempotency, arriving from the other direction) since retries guarantee duplicates.
4. **Don't trust order** — use the event's timestamp/sequence, or better, treat the webhook as a *hint* and re-fetch authoritative state from the API ("trust but verify").
5. Local dev: tunnels (`ngrok` and kin) expose your laptop; providers offer test-event senders and delivery logs — read them during incidents.

Provider side, the same list mirrored: sign everything, per-endpoint retry queues with backoff, a dead-letter view customers can replay from, and event types the consumer opts into.

### Use It

Stripe (payments), GitHub (pushes/PRs), Twilio, Slack, and essentially every SaaS platform ship webhooks with this exact shape — HMAC signature headers, documented retry schedules, delivery dashboards, and replay buttons. Newer alternatives layer on it rather than replace it: event streams you pull (Kafka-style "fan-in"), or standardized envelopes (CloudEvents).

### War Story

Webhook retry queues have a failure mode providers learned publicly: when a large consumer's endpoint goes down for hours and then recovers, the accumulated backlog delivers as a flood — at-least-once semantics mean the recovering service is greeted by its own missed history at full speed. It's why mature providers document retry schedules and offer replay-on-demand, and why mature consumers ack-fast-and-queue: a webhook endpoint must be engineered for the day it comes back from the dead.

### Checkpoint

- Why must webhook signatures be verified over the raw request body, and what does the timestamp in the signature prevent?
- Why is "return 200 immediately, process async" the rule, and what happens to slow handlers?
- Given at-least-once delivery with retries, what two consumer-side mechanisms make processing correct anyway?

## 10. The API gateway pattern

**MOTTO:** One front door — so every service doesn't have to be its own bouncer, translator, and accountant.

### The Problem

Twenty microservices each need auth, rate limiting, TLS, request logging, and CORS. Implement that twenty times and you get twenty subtly different security postures, and clients must learn twenty hostnames. Every cross-cutting concern duplicated per service is a bug farm with a deployment schedule.

### The Concept

Put one **gateway** — a reverse proxy with opinions (Phase 2, Lesson 12) — at the edge. Clients see one host; the gateway authenticates, throttles, terminates TLS, then routes each request to the right internal service. Cross-cutting concerns move from N implementations to one policy point.

```
                        ┌─> /users/*     -> users service
 clients ─> [ GATEWAY ] ┼─> /orders/*    -> orders service
             │          └─> /search/*    -> search service
             ├ authn/authz (validate JWT once; pass claims inward)
             ├ rate limits & quotas (per key/user/IP)
             ├ TLS termination · routing · retries/timeouts
             ├ logging/metrics/tracing headers · CORS · caching
             └ protocol translation (REST outside -> gRPC inside)
```

Kin worth distinguishing: **BFF** (backend-for-frontend — a gateway variant per client type, so the TV app and the phone get tailored aggregation) and **service mesh** (Envoy sidecars doing gateway-ish work for *internal* east-west traffic, while the gateway guards north-south).

### Build It

A functioning gateway in nginx, to demystify the category:

```nginx
server {
  listen 443 ssl;                       # TLS terminates here
  location /users/  { proxy_pass http://users:8000/;  }
  location /orders/ { proxy_pass http://orders:8000/; }
  limit_req zone=perip burst=20;        # rate limiting
  proxy_set_header X-Request-Id $request_id;   # tracing correlation
  proxy_connect_timeout 2s; proxy_read_timeout 5s;   # Lesson 08 lives here too
}
```

1. Wire two lab services behind it (Phase 0 playground) and confirm one hostname fronts both.
2. Add an `auth_request` subrequest so the gateway rejects bad tokens before services see them.
3. Now feel the tradeoffs: the gateway is a single point of failure (run replicas), a latency hop (~ms), and — the classic disease — a *temptation*: business logic accretes in gateway config until it's an unversioned, untested service that everyone fears. Policy at the gateway, logic in services.

### Use It

| Option | Flavor |
|---|---|
| nginx / HAProxy | DIY, maximal control |
| Kong, Envoy Gateway, Traefik | gateway products, plugin ecosystems |
| AWS API Gateway / cloud equivalents | managed, per-request pricing, deep cloud hooks |
| Apigee, Zuplo, etc. | full API-management (keys, portals, monetization) |

### War Story

Netflix's Zuul (open-sourced 2013) became the reference implementation of the pattern: the front door for all Netflix API traffic, handling routing, resiliency, and insight for the device fleet. Its sequel is the instructive part — Zuul 2 (2016–2018 writeups) rewrote the core from blocking thread-per-request to async/non-blocking, and Netflix's posts frankly tallied the price of that migration: at gateway scale, Phase 1's threading lessons stop being theory and start being roadmap.

### Checkpoint

- Name five cross-cutting concerns that belong in a gateway rather than in each service.
- What distinguishes a BFF from a generic gateway, and a service mesh from both?
- What is the classic failure mode of gateway *governance* (not uptime), and what rule prevents it?
