# Phase 10 — 🧩 Microservices & Service Architecture

> Distributed monoliths are still monoliths — with extra latency.

Everyone wants microservices until they have microservices. This phase is about the actual engineering discipline behind splitting a system into services: where to cut, how services find each other, what happens when one of them catches fire at 3 AM, and how to keep a hundred deployables from becoming a hundred problems. We'll build the resilience machinery — circuit breakers, discovery, sagas — from first principles, then tour the tools that productionize them. By the end you'll know when microservices are the answer, and (more importantly) when they're an expensive way to turn function calls into network outages.

## 01. Monolith First: When NOT to Use Microservices

**MOTTO:** You don't have a microservices problem; you have a modularity problem wearing a network costume.

### The Problem

A five-person startup ships a "modern" architecture: 14 services, 3 message queues, a service mesh. Now every feature touches four repos, local dev requires 16 GB of Docker, and a rename is a distributed migration. Microservices trade *development* complexity for *operational* complexity — and if you don't yet have the operational muscle (CI/CD, observability, on-call), you've bought the costs before you can afford them.

### The Concept

Think of a restaurant. A food truck (monolith) has one kitchen, one menu, one crew — fast to change, easy to run. A food court (microservices) lets each stall scale, hire, and cook independently — but now you need a landlord, shared plumbing, and health inspections for every stall. You open a food court when the food truck's *line is too long*, not on day one.

```
  Monolith                    Microservices
  +-----------------+         +----+  +----+  +----+
  | UI | API | Jobs |  --->   |Users| |Cart| |Ship|
  |   one deploy    |         +----+  +----+  +----+
  +-----------------+           \      |      /
        1 process                network calls
        1 failure mode           N^2 failure modes
```

### Build It

The honest decision procedure:

1. Count teams, not features. Microservices are an *organizational* scaling tool (Conway's Law). Fewer than ~3 teams? A well-modularized monolith wins.
2. Check for asymmetric scaling: does one component genuinely need 50x the replicas of the rest? That's a real reason to split.
3. Check for independent deploy pressure: are teams blocked waiting on each other's release trains?
4. Verify prerequisites: automated deploys, centralized logging, distributed tracing, on-call rotation. Missing any? Fix that first.
5. If you split, split *one* thing, run it in production for a quarter, and measure before splitting more.

### Use It

| Approach | Good for | Cost |
|---|---|---|
| Monolith (Rails, Django, Spring) | Small teams, fast iteration | Scaling is all-or-nothing |
| Modular monolith | Medium teams, clean boundaries | Requires discipline, not tooling |
| Microservices | Many teams, uneven scaling | Ops burden, distributed failures |

### War Story

Martin Fowler's "Monolith First" essay (2015) observed that almost all successful microservice systems he'd seen started as monoliths that were later carved up — while systems built as microservices from scratch often ended in trouble. Meanwhile, in 2023 an Amazon Prime Video team publicly wrote about consolidating a distributed serverless monitoring pipeline into a monolithic process, cutting infrastructure costs by roughly 90%. Even at hyperscalers, the boring architecture sometimes wins.

### Checkpoint

- What is Conway's Law, and why does it make microservices an organizational tool before a technical one?
- Name three operational prerequisites you should have in place before splitting a monolith.
- Your two-person startup has slow deploys because of flaky tests. Is splitting into services likely to help? Why or why not?

## 02. Service Boundaries and Domain-Driven Design

**MOTTO:** Cut along the seams of the business, not the layers of the code.

### The Problem

The most common microservices failure isn't tooling — it's cutting in the wrong place. Split "frontend service / backend service / database service" and every user action crosses all three: you've built a layered monolith with network cables in the middle. Wrong boundaries mean chatty calls, shared databases, and lockstep deploys — all the costs of distribution, none of the autonomy.

### The Concept

Domain-Driven Design (DDD) says: the business already has natural fault lines. "Billing" people and "Shipping" people barely talk, use different vocabulary, and change for different reasons. Each such area is a **bounded context** — a boundary inside which words have one precise meaning. "Order" means something different to Billing (an invoice) than to Shipping (a box). Services should map to bounded contexts, so that one business change lands in one service.

```
  Bounded contexts (good cuts)        Layer cuts (bad)
  +---------+  +----------+           +-----------------+
  | Billing |  | Shipping |           |   API service   |
  | invoice |  |  parcel  |           +-----------------+
  |  taxes  |  | tracking |           | Logic service   |
  +---------+  +----------+           +-----------------+
   own data      own data             |  Data service   |
   own deploys   own deploys          +-----------------+
                                       every request hits all 3
```

### Build It

1. Run an event-storming session: list the domain events ("OrderPlaced", "PaymentCaptured", "ParcelShipped") on a wall with domain experts.
2. Cluster events by vocabulary and by who cares. Clusters ≈ bounded contexts.
3. For each context, define its **aggregate** — the entity cluster that must be transactionally consistent (e.g., Order + OrderLines). Aggregates never span services.
4. Between contexts, communicate via events or explicit APIs, and *translate* at the border (an anti-corruption layer) so one context's model doesn't leak into another.
5. Litmus test: can this service deploy alone? Does it own its data? Does a typical feature change touch only one service? Three yeses = a real boundary.

### Use It

DDD is a design method, not a product, but tooling reflects it: event storming (Miro/paper), context maps, and per-service databases. The classic references are Eric Evans's *Domain-Driven Design* (2003) and Vaughn Vernon's *Implementing DDD*.

| Signal | Boundary verdict |
|---|---|
| Two services always deploy together | Wrong cut — merge them |
| One service, one team, one database | Healthy |
| Service B reads service A's tables | Shared data — not a boundary at all |

### War Story

Amazon's early-2000s move from its monolithic "Obidos" architecture to service orientation came with an organizational mandate famously attributed to Jeff Bezos: all teams expose functionality only through service interfaces, no shared databases, no backdoors. The boundaries were enforced socially and technically at once — which is exactly why they held. The same decomposition later made AWS possible.

### Checkpoint

- What is a bounded context, and why can "Order" legitimately mean different things in different services?
- Why must an aggregate never span two services?
- Two services share a database table. What problems does this cause, and what does it tell you about the boundary?

## 03. Service Discovery

**MOTTO:** Hardcoded IPs are a promise the cloud will break by Tuesday.

### The Problem

In a monolith, calling another module is a function call. In microservices, you must find the callee first — and in a cloud environment, instances are cattle: they autoscale, crash, get rescheduled, and change IPs constantly. A config file of addresses is stale the moment you write it. You need a live, queryable answer to "where is a healthy instance of `payments` right now?"

### The Concept

Service discovery is a phone book that updates itself. Instances **register** on boot ("I'm payments, at 10.0.3.7:8080"), send **heartbeats** to prove they're alive, and get evicted when they go quiet. Callers **query** the registry and pick an instance.

```
        register/heartbeat        query "payments?"
  payments-1 ----------+      +---------- checkout
  payments-2 -------+  |      |
  payments-3 (dead) |  v      v
                 +--------------------+
                 |  Service Registry  |
                 |  payments:         |
                 |   10.0.3.7  OK     |
                 |   10.0.3.9  OK     |
                 |   10.0.3.4  EVICTED|
                 +--------------------+
```

Two styles: **client-side** discovery (the caller queries the registry and load-balances itself) vs **server-side** (the caller hits a stable virtual IP / load balancer that does the lookup). Client-side saves a hop but pushes logic into every client library; server-side is simpler for callers but adds infrastructure.

### Build It

A toy registry is ~30 lines:

```python
import time
registry = {}  # {service: {addr: last_heartbeat}}
TTL = 10

def register(service, addr):
    registry.setdefault(service, {})[addr] = time.time()

def heartbeat(service, addr):
    registry[service][addr] = time.time()

def lookup(service):
    now = time.time()
    live = [a for a, t in registry.get(service, {}).items() if now - t < TTL]
    return live  # caller picks one (round-robin, random, least-loaded)
```

The hard parts are what this toy skips: the registry itself must be replicated (it's a distributed consensus problem — hello, Raft), and TTLs trade failure-detection speed against heartbeat traffic.

### Use It

| Tool | Style | Notes |
|---|---|---|
| Consul | Both | Raft-backed, health checks, KV store |
| etcd + custom | Client-side | The primitive under Kubernetes |
| Kubernetes Services / DNS | Server-side | `payments.default.svc` just resolves; kube-proxy routes |
| Eureka (Netflix) | Client-side | AP design: prefers stale data over no data |

### War Story

Netflix built Eureka after moving to AWS, and made a deliberate CAP call: during a network partition, a registry that returns *stale* instance lists is better than one that returns errors — clients can still try addresses that were recently healthy. That AP-over-CP stance, documented in Netflix's engineering posts, contrasts with CP registries like ZooKeeper, where losing quorum means losing discovery exactly when the network is at its flakiest.

### Checkpoint

- Why does a shorter heartbeat TTL detect failures faster but cost more? What's the tradeoff curve?
- Contrast client-side and server-side discovery. Where does the load-balancing logic live in each?
- Why might you prefer an AP (eventually consistent) registry over a CP one during a network partition?

## 04. API Gateways in Depth

**MOTTO:** One front door, or every service grows its own bouncer.

### The Problem

Expose 40 services directly to the internet and each one must independently implement TLS, authentication, rate limiting, CORS, request logging, and DDoS protection. Clients must know 40 hostnames. Every cross-cutting change — say, rotating an auth scheme — becomes 40 pull requests. Edge concerns are being duplicated where they should be centralized.

### The Concept

An API gateway is the building's front desk: it checks IDs (auth), stops people from barging in a hundred times a second (rate limiting), and directs visitors to the right office (routing) — so individual offices don't each need a security guard.

```
                    +-------------------------+
  clients --------> |       API GATEWAY       |
   (one hostname)   | TLS | auth | rate limit |
                    | routing | retries | logs|
                    +----+--------+-------+---+
                         |        |       |
                         v        v       v
                      users/   orders/  search/
```

### Build It

A gateway is a reverse proxy with policy hooks. The request pipeline:

1. Terminate TLS.
2. Authenticate: validate the JWT/API key *once*, then pass identity downstream as trusted headers (e.g., `X-User-Id`).
3. Rate limit: token bucket keyed by user/IP (Redis for shared state across gateway replicas).
4. Route: match path/host/header → upstream service; rewrite paths.
5. Resilience: per-upstream timeouts, bounded retries, circuit breaking.
6. Observe: assign a request ID, log, emit latency metrics.

```python
# the essence, minus the production armor
async def handle(req):
    user = verify_jwt(req.headers["authorization"])       # 401 on failure
    if not bucket.take(user.id):                          # 429 on failure
        return Response(429)
    upstream = ROUTES.match(req.path)                     # "/orders/*" -> orders-svc
    return await proxy(upstream, req, headers={"X-User-Id": user.id},
                       timeout=2.0, retries=1)
```

Beware two temptations: putting business logic in the gateway (it becomes a monolith-at-the-edge that every team fights over), and unbounded retries (they amplify outages into retry storms).

### Use It

| Tool | Flavor |
|---|---|
| NGINX / HAProxy | Battle-tested reverse proxies; config-driven |
| Kong, KrakenD, Tyk | Gateways with plugin ecosystems |
| Envoy | Modern proxy core; xDS dynamic config; basis of many meshes |
| AWS API Gateway / Cloudflare | Managed; pay-per-request; less control |

### War Story

Netflix's Zuul gateway — open-sourced in 2013 — fronted their streaming API and became famous for dynamic filters: routing and resilience logic that could be changed at runtime while absorbing traffic spikes and regional failovers. Zuul 2's 2018 rewrite to async non-blocking I/O was publicly documented, including the honest finding that the rewrite's efficiency gains were real but smaller than hoped — a rare, useful data point on event-loop migrations at scale.

### Checkpoint

- Why should JWT validation happen at the gateway instead of in every service? What must downstream services then trust?
- What is a retry storm, and which two gateway settings prevent it?
- Give one example of logic that belongs in the gateway and one that absolutely doesn't.

## 05. Backend-for-Frontend (BFF)

**MOTTO:** One size fits all APIs fit no one — especially not a phone on 3G.

### The Problem

Your mobile app renders a home screen that needs data from five services. With a generic API, the phone makes five round trips over a high-latency radio, downloads fields it never renders, and every screen redesign becomes a negotiation with five backend teams. Web wants big nested payloads; mobile wants tiny tailored ones; your smart-TV app wants something else entirely. One general-purpose API serves all of them badly.

### The Concept

A Backend-for-Frontend is a personal shopper per client type. Instead of every client assembling its own outfit from 40 racks (services), the mobile BFF picks exactly what mobile needs, in one bag, in one trip.

```
  iOS app ----> [ Mobile BFF ]----+---> users-svc
                 1 round trip     +---> orders-svc
                 tailored payload +---> recs-svc
  browser ----> [ Web BFF    ]----+---> (same services,
                 richer payload         different shape)
```

The BFF is owned by the *frontend team* — that's the point. Screen changes stay within one team's blast radius.

### Build It

1. One BFF per client *type* (mobile, web, TV) — not per platform team whim. Two BFFs that serve identical shapes should be one.
2. The BFF aggregates: fan out to services *in parallel*, assemble a view-model shaped like the screen, strip unused fields.
3. Handle partial failure: if recommendations time out, return the screen without them (degrade), don't 500 the whole home page.
4. Keep it thin: composition, translation, and caching only. Business rules live in domain services — a BFF with business logic is a monolith wearing a lanyard.

```python
async def home_screen(user_id):
    user, orders, recs = await gather(
        users.get(user_id), orders.recent(user_id, limit=3),
        recs.top(user_id, limit=5, timeout=0.3, default=[]),  # optional
    )
    return {"name": user.first_name,          # not the whole user object
            "orders": [slim(o) for o in orders],
            "recs": [r.title for r in recs]}
```

### Use It

| Approach | Tradeoff |
|---|---|
| Hand-rolled BFF (Node/Go service) | Full control; another service to run |
| GraphQL as universal BFF | Clients pick fields; adds resolver/caching complexity, N+1 risk |
| BFF per client + shared platform APIs | Common at scale; some duplication across BFFs by design |

GraphQL and BFFs solve overlapping problems; some shops run GraphQL *inside* each BFF.

### War Story

The BFF pattern was named at SoundCloud, described by Phil Calçado in his writeups of their monolith-to-microservices migration (circa 2011–2015): their single API tried to serve web, mobile, and partners, and every client change congested one team. Netflix independently converged on the same idea with its client-adapter API layer, where device teams owned server-side adaptation code — evidence that the pattern is discovered, not invented, wherever many client types meet many services.

### Checkpoint

- Why should a BFF be owned by the frontend team rather than the backend platform team?
- Your mobile BFF and web BFF have drifted to 90% identical code. What does that suggest?
- How should a BFF respond when one of five upstream calls fails, and what determines the answer?

## 06. Circuit Breakers and Bulkheads

**MOTTO:** A slow dependency is more dangerous than a dead one.

### The Problem

Service A calls service B. B doesn't crash — worse, it gets *slow*. A's threads pile up waiting on B, A's own callers start timing out, and the stall propagates upstream until the whole site is down because one recommendation service hiccuped. Dead services fail fast; slow services fail *everyone*.

### The Concept

Two ideas from electrical engineering and shipbuilding. A **circuit breaker** trips when a dependency keeps failing: stop calling it, fail instantly, give it time to recover. A **bulkhead** partitions resources like a ship's watertight compartments: flood one compartment (thread pool), and the others stay dry.

```
  CLOSED ──(failure rate > threshold)──> OPEN
    ^                                      |
    |                              (cooldown timer)
    |                                      v
    +──(probe succeeds)──── HALF-OPEN ──(probe fails)──> OPEN
```

Closed = calls flow, failures counted. Open = calls rejected immediately (fast failure + fallback). Half-open = let a few probes through; success closes the breaker, failure re-opens it.

### Build It

```python
import time

class CircuitBreaker:
    def __init__(self, threshold=5, cooldown=30):
        self.failures, self.threshold = 0, threshold
        self.cooldown, self.opened_at = cooldown, None

    def call(self, fn, fallback):
        if self.opened_at:                                # OPEN
            if time.time() - self.opened_at < self.cooldown:
                return fallback()
            self.opened_at = None                         # HALF-OPEN: try a probe
        try:
            result = fn()
            self.failures = 0                             # success closes it
            return result
        except Exception:
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened_at = time.time()              # trip
            return fallback()
```

Bulkheads: give each dependency its own bounded thread pool / connection pool / semaphore. If B gets slow, only B's pool saturates; calls to C proceed. Always pair breakers with *timeouts* — a breaker can't count failures that never return.

### Use It

| Tool | Notes |
|---|---|
| Resilience4j (Java) | Successor to Netflix Hystrix; breakers, bulkheads, rate limiters |
| Polly (.NET) | Policy composition: retry + breaker + timeout |
| Envoy outlier detection | Mesh-level ejection of bad hosts — breaker without code changes |
| Hystrix (Netflix) | The pattern's popularizer; now in maintenance mode |

### War Story

Netflix built Hystrix after their 2008 database corruption outage era and years of cascading-failure pain, open-sourcing it in 2012 with dashboards showing live breaker states across the fleet. Their engineering blog documented the philosophy: wrap every network call, bound every resource, and make failure a first-class, *fast* outcome. Hystrix was retired in 2018 in favor of Resilience4j and adaptive concurrency limits — but the state machine it popularized is now table stakes in every resilience library.

### Checkpoint

- Why is a slow dependency more dangerous to callers than one that's fully down?
- Walk through the three breaker states and what causes each transition.
- How do bulkheads and circuit breakers differ in what they protect, and why do you usually want both plus timeouts?

## 07. Service Mesh: Sidecar Armies

**MOTTO:** Take the network logic out of the app and put a proxy in its pocket.

### The Problem

You've adopted retries, mTLS, breakers, and tracing — implemented in a Java library. Now the Go team needs it. And the Python team. And the library needs a security patch, which means redeploying 200 services. Cross-cutting network behavior is trapped inside application binaries, duplicated per language, upgraded at the speed of your slowest team.

### The Concept

A service mesh moves that logic into a **sidecar proxy** — a separate process deployed next to every service instance that intercepts all its inbound and outbound traffic. Like giving every employee an interpreter-bodyguard: the employee just talks; the bodyguard handles encryption, credentials, retries, and reports back to headquarters. Headquarters is the **control plane**, which pushes routing rules, certs, and policy to all sidecars (the **data plane**).

```
        CONTROL PLANE (istiod): config, certs, policy
            |            |               |
            v            v               v
  +------------------+  +------------------+
  | app A | sidecar  |--| sidecar | app B  |
  +------------------+  +------------------+
        all A<->B traffic flows proxy-to-proxy
        (mTLS, retries, metrics, traffic split)
```

### Build It

What the sidecar actually does per request:

1. Intercept: iptables/eBPF redirects the pod's traffic through the proxy (the app is unaware).
2. mTLS: sidecars hold workload certificates (e.g., SPIFFE identities) and mutually authenticate — encryption and service identity with zero app code.
3. Policy: "checkout may call payments; nothing else may."
4. Traffic shaping: route 1% of requests to v2 (canary), mirror traffic, inject faults for testing.
5. Resilience & telemetry: timeouts, retries, outlier ejection, plus uniform metrics/traces for every hop.

The costs are real: an extra ~0.5–2 ms and extra memory *per hop per sidecar*, and a control plane you must now operate. Newer designs (Istio ambient mode, eBPF-based Cilium) move work out of per-pod sidecars to cut this overhead.

### Use It

| Mesh | Notes |
|---|---|
| Istio | Envoy-based, most features, most complexity |
| Linkerd | Lightweight Rust micro-proxy; famously simpler |
| Cilium | eBPF; some mesh features without sidecars |
| Consul Connect | Mesh tied to Consul's registry |

Rule of thumb: if you have < ~20 services, a mesh is probably solving problems you don't have yet. A library or gateway may do.

### Use-it corollary — When NOT to mesh

Small fleets, single-language shops (a shared library is fine), or teams without spare ops capacity: the mesh's control plane is itself a distributed system you must keep alive.

### War Story

The mesh lineage runs straight through two companies: Lyft built Envoy (open-sourced 2016) to tame its polyglot microservice network, and Buoyant — founded by ex-Twitter engineers who ran Twitter's Finagle RPC stack — coined the term "service mesh" and shipped Linkerd. Istio (Google/IBM/Lyft, 2017) put Envoy sidecars under a unified control plane. The whole category is Finagle's library-based resilience ideas, re-platformed as infrastructure so every language gets them for free.

### Checkpoint

- What problem does a sidecar solve that a shared resilience library cannot?
- Distinguish the control plane from the data plane. Which one touches your request path?
- Name two concrete costs of running a mesh and one situation where you'd decline to use one.

## 08. Distributed Transactions in Practice

**MOTTO:** In microservices, ACID becomes a story you tell in installments — with apologies.

### The Problem

Checkout must: charge the card (payments service), reserve stock (inventory service), create a shipment (shipping service). Each service owns its own database, so there is no single `BEGIN ... COMMIT` that covers all three. If payment succeeds and inventory fails, you've charged someone for nothing. You need multi-service consistency without a shared database.

### The Concept

Two-phase commit (2PC) — a coordinator asking everyone to "prepare" then "commit" — technically exists, but it holds locks across the network and blocks everyone if the coordinator dies mid-flight. Practitioners mostly avoid it across services. The workhorse is the **saga** (Garcia-Molina & Salem, 1987): a sequence of *local* transactions, where each step that later needs undoing has a **compensating action**. Like booking a trip: reserve flight, then hotel, then car — if the car falls through, you don't "roll back," you *cancel* the hotel and flight, one apology at a time.

```
  SAGA (happy):   charge$ ──> reserve stock ──> create shipment ──> done
  SAGA (failure): charge$ ──> reserve stock ──> shipment FAILS
                     ^              |
                refund$ <── release stock     (compensations, reverse order)
```

### Build It

1. Choose coordination style: **choreography** (each service reacts to events — simple until nobody can tell you the flow) or **orchestration** (a saga orchestrator explicitly drives steps and compensations — visible, testable, one more component).
2. Make every step and compensation **idempotent** (steps will be retried; use idempotency keys).
3. Publish events atomically with local writes via the **transactional outbox**: write the state change AND the event to the same local DB transaction; a relay publishes from the outbox table. No "committed but never announced" ghosts.
4. Accept the semantics: sagas give eventual consistency; intermediate states are visible (the card is charged before the shipment exists). Design UX and invariants for it — "pending" is a real state, not a bug.

```python
SAGA = [(charge, refund), (reserve, release), (ship, cancel_ship)]
done = []
for step, undo in SAGA:
    try:
        step(order); done.append(undo)
    except StepFailed:
        for undo in reversed(done): undo(order)   # compensate backwards
        break
```

### Use It

| Tool | Role |
|---|---|
| Temporal / Cadence | Durable workflow orchestration; retries, timers, and state survive crashes |
| AWS Step Functions | Managed orchestrator |
| Kafka + outbox + Debezium | Choreography backbone; CDC publishes the outbox |
| 2PC / XA | Inside one org's databases maybe; across microservices, rarely |

### War Story

The saga paper predates microservices by two decades — Hector Garcia-Molina and Kenneth Salem published "Sagas" in 1987 for long-lived database transactions. Pat Helland's 2007 paper "Life Beyond Distributed Transactions: An Apostate's Opinion" became the industry's confession: at scale, developers abandon distributed transactions and build workflows over independent, idempotent operations. Nearly every modern checkout flow is that paper wearing a Kafka T-shirt.

### Checkpoint

- Why do practitioners avoid 2PC across microservices even though it guarantees atomicity?
- What is a compensating action, and why is it *not* the same as a rollback?
- Explain the transactional outbox pattern. What failure mode does it eliminate?

## 09. The Strangler Fig Migration

**MOTTO:** Don't rewrite the monolith — surround it, starve it, and let it fall over quietly.

### The Problem

The Big Rewrite is where codebases go to die twice: two years of feature freeze while the new system chases a moving target, followed by a big-bang cutover that fails on undocumented behavior nobody knew the old system had. Meanwhile the business needs the old system running *and changing* every single day. You need migration without a stop-the-world moment.

### The Concept

The strangler fig is a rainforest plant that grows around a host tree, gradually taking over its light and roots until the host dies inside a living lattice. Martin Fowler turned it into an architecture pattern (2004): put a routing facade in front of the monolith, build replacement capabilities alongside it, and shift traffic route by route. At every moment, the system is 100% functional; the monolith just serves a little less each month.

```
          +--------- FACADE / router ---------+
          |                                   |
   /orders/* (migrated)              everything else
          v                                   v
   [ new orders service ]            [ legacy monolith ]
          |                                   |
     new orders DB   <== sync/backfill ==  legacy DB
```

### Build It

1. Interpose a facade (gateway/proxy) in front of the monolith. Day one: it routes 100% to legacy. Nothing changed; now you hold the steering wheel.
2. Pick the first capability — highest change-frequency or clearest boundary, not the hardest one.
3. Build the new service. Deal with data: backfill from legacy, then keep in sync (dual writes with reconciliation, or CDC from the legacy DB).
4. **Dark launch**: route real traffic to both, serve from legacy, *diff the responses*. Fix mismatches until parity holds.
5. Shift reads, then writes: 1% → 10% → 100%, watching error rates, with instant rollback = a routing change.
6. Delete the legacy code path. (Actually delete it. Undeleted legacy paths are how you end up running both forever.)
7. Repeat until the monolith is an empty husk — or until remaining pieces aren't worth migrating, which is also a valid end state.

### Use It

| Tool | Role |
|---|---|
| NGINX / Envoy / API gateway | The facade and traffic splitter |
| Debezium (CDC) | Keep new DB in sync with legacy writes |
| GitHub's Scientist (and ports) | Run old + new code paths and compare results |
| Feature flags (LaunchDarkly etc.) | Percentage rollout and instant rollback |

### War Story

GitHub open-sourced Scientist in 2016 precisely for this: they rewrote critical code paths (like their merge and permissions logic) by running old and new implementations side by side in production, always returning the old result while recording mismatches. Shopify has likewise publicly documented multi-year incremental extractions from its Rails monolith. The common thread: production traffic is the only spec that's actually complete, so migrate under it, never beside it.

### Checkpoint

- Why does the facade go in place *before* any new service is built?
- What is a dark launch, and what question does response-diffing answer that testing cannot?
- What are two ways to keep the new service's database in sync with the legacy database during migration?

## 10. Serverless Architectures

**MOTTO:** No server is easier to manage than no server — until you meet the cold start.

### The Problem

For spiky or low-traffic workloads, provisioned servers are money on fire: you pay for peak capacity 24/7 while it idles at 3%. And every server, container, or VM you run is patching, scaling, and 3 AM paging that isn't your product. What if the unit of deployment were just *the function*, running only while a request exists, billed by the millisecond?

### The Concept

Functions-as-a-Service is a vending machine model of compute: no kitchen, no staff — insert request, receive execution. The platform keeps your code on ice; on an event (HTTP call, queue message, file upload), it thaws an instance, runs your handler, and scales from 0 to thousands of instances by simply thawing more. When traffic stops, so does your bill.

```
  event sources                 platform                  your code
  HTTP ─┐                +---------------------+
  queue ─┼── trigger ──> | spin up | run | die | ──────> handler(event)
  cron ──┘               |  scale 0 <-> N      |          (stateless!)
                         +---------------------+
  cost = invocations x duration x memory   (idle = $0)
```

The catches: **cold starts** (first request after idle pays init latency — tens of ms to seconds, worst for JVM/large deps), **statelessness** (instances vanish; all state goes to external stores), execution time caps, and the fact that your architecture becomes a distributed event graph whose "code" is partly wiring in cloud config.

### Build It

Designing a serverless system honestly:

1. Handlers are stateless and idempotent — most triggers deliver at-least-once, so you *will* see duplicates.
2. Push state out: DynamoDB/S3/Redis for data, queues between functions, Step-Functions-style orchestrators for multi-step flows.
3. Tame cold starts: small bundles, lightweight runtimes, provisioned concurrency for latency-critical paths (which, note, is paying for idle again).
4. Mind the pool math: 1,000 concurrent Lambdas can open 1,000 DB connections — use serverless-friendly databases or connection proxies (e.g., RDS Proxy).
5. Do the break-even math: pay-per-use wins for spiky/low traffic; at sustained high utilization, containers become cheaper. Run the numbers, not the hype.

### Use It

| Platform | Notes |
|---|---|
| AWS Lambda | The category creator (2014); deepest event integrations |
| Cloudflare Workers | V8 isolates, ~ms cold starts, runs at edge; constrained runtime |
| Google Cloud Run / Functions | Container-based serverless; Cloud Run scales containers to zero |
| Knative / OpenFaaS | Self-hosted serverless — you're the platform team now |

### War Story

AWS Lambda's 2014 launch created the category, and the definitive practitioner data came from iRobot and similar all-in adopters at re:Invent talks: thousands of functions, near-zero idle cost, and hard-won lessons about testing event graphs. The counterpoint is the 2023 Amazon Prime Video post (see Lesson 01) where step-function-and-lambda orchestration costs led a team back to a monolithic service — serverless is a pricing model and an ops model, and both have regimes where they lose.

### Checkpoint

- What causes a cold start, and name two mitigations with their costs.
- Why must serverless handlers be idempotent even if your code "only sends each message once"?
- Describe a workload where serverless is clearly cheaper than containers, and one where it's clearly more expensive.

## 11. The Modular Monolith

**MOTTO:** All the boundaries, none of the network — discipline as architecture.

### The Problem

You want what microservices promise — clear ownership, enforced boundaries, independent teams — but you don't want what they cost: network failure modes, distributed transactions, a fleet of deploy pipelines. Most teams' actual problem is that their monolith is a mud ball, not that it's a monolith. Can you get the boundaries without the distribution?

### The Concept

A modular monolith is an apartment building, not a commune: one structure, one entrance (deploy), but real walls between units, and you can't wander into your neighbor's kitchen. Internally, the code is partitioned into modules that mirror bounded contexts (Lesson 02); each module has a small public API, private internals, and *its own tables*. The rules a network would force on you — no reaching into another service's DB, no calling private functions — are enforced by tooling instead.

```
  +----------- one deployable ---------------+
  |  +--------+   +--------+   +---------+   |
  |  | orders |   |billing |   |shipping |   |
  |  | public |-->| public |   | public  |   |   calls cross ONLY
  |  |  api   |   |  api   |   |  api    |   |   via public APIs
  |  |~~~~~~~~|   |~~~~~~~~|   |~~~~~~~~~|   |
  |  |private |   |private |   |private  |   |
  +--+--------+---+--------+---+---------+---+
  |  orders_* | billing_*  | shipping_* |  <- one DB, disjoint schemas
  +------------------------------------------+
```

### Build It

1. One module per bounded context: `orders/`, `billing/`, `shipping/`. Each exposes a narrow interface (a facade class or internal API); everything else is private.
2. Enforce with tools, not vibes: ArchUnit (Java), import-linter (Python), Nx/module boundaries (TS), Go internal packages. CI fails on illegal imports. This step is the whole pattern — unenforced modularity erodes in months.
3. Separate schemas per module in the shared DB; cross-module foreign keys are forbidden. Module A gets B's data by asking B's API.
4. Cross-module communication: synchronous calls through public interfaces, or an in-process event bus for decoupling — same shapes as microservices, minus serialization and packet loss.
5. The payoff: any module already shaped like this can be extracted into a real service later with mostly mechanical work. The modular monolith is both a destination and the best possible launchpad.

### Use It

| Ecosystem | Enforcement tooling |
|---|---|
| Java/Spring | Spring Modulith, ArchUnit |
| Python | import-linter, package conventions |
| TypeScript | Nx enforced module boundaries |
| Elixir | Umbrella apps |

### War Story

Shopify is the canonical public case: engineering posts from 2019–2020 described "componentizing" one of the world's largest Rails monoliths, using an internal tool (Packwerk, open-sourced 2020) to enforce package boundaries and privacy inside a single deployable serving flash-sale traffic at enormous scale. Their stated position: the monolith with enforced components gave them most microservice benefits while keeping one test suite, one deploy, and call stacks that fit in one debugger.

### Checkpoint

- Why is boundary enforcement via CI tooling described as "the whole pattern"? What happens without it?
- How does a modular monolith handle cross-module data access, and what's banned?
- In what sense is a modular monolith a "launchpad" for microservices?

## 12. Microservices Antipatterns Hall of Shame

**MOTTO:** Every microservices failure is a monolith wearing a trench coat made of YAML.

### The Problem

Teams adopt microservices, keep monolith habits, and get a system with the worst properties of both: coupled *and* distributed. These failure shapes are so common they have names. Learning to recognize them in design review — before they ship — is cheaper than any refactor.

### The Concept

Tour the hall. Each exhibit is a coupling that survived the split:

```
  DISTRIBUTED MONOLITH        SHARED DATABASE         CHATTY SERVICES
  A ==deploy together== B     A ──┐    ┌── B          A ->B ->A ->B ->A
  (versions in lockstep)         [ one DB ]           (12 hops per request;
                              (schema = shared ABI)    latency & failure x12)

  NANOSERVICES                THE ESB REBORN          NO INDEPENDENT DEPLOY
  1 function = 1 service      "smart pipes" bus       release train of 30
  (ops cost >> logic)         with business logic     services, quarterly
```

- **Distributed monolith**: services that must deploy together, share libraries with breaking changes, or call each other synchronously in deep chains. Test: "can I deploy this service alone on a Tuesday?" If no, it's an organ, not an organism.
- **Shared database**: two services on one schema means the schema is a public API with no version control. Every migration is a hostage negotiation.
- **Chatty I/O**: cross-service calls in a loop; N+1 across the network. Latencies add; availabilities *multiply* (five 99.9% hops ≈ 99.5%).
- **Nanoservices**: boundaries so fine the operational overhead (deploys, dashboards, on-call) dwarfs the logic. Related: **entity services** ("UserService", "OrderService" as bare CRUD) that force every behavior to orchestrate three anemic services.
- **Smart pipes**: business logic hiding in the message bus / ESB / gateway, owned by nobody, versioned never. The microservices credo is *smart endpoints, dumb pipes*.
- **Breaking the monolith along layers** (Lesson 02's bad cut) and **big-bang decomposition** (Lesson 09's forbidden move) round out the collection.

### Build It

A design-review checklist that catches most exhibits:

1. Can each service deploy independently, today, with zero coordination?
2. Does each service exclusively own its data store?
3. What's the max synchronous call depth for a user request? (>2–3: redesign toward async/events or merge services.)
4. Multiply the availabilities along the critical path. Still meeting your SLO?
5. Who owns each pipe, and can you diff its logic in version control?
6. Count services per team. More services than engineers is a smell, not a flex.

### Use It

| Symptom | Likely exhibit | First aid |
|---|---|---|
| "Release train" coordination meetings | Distributed monolith | Contract tests, backward-compatible APIs |
| Migration requires 3 teams' sign-off | Shared database | Split schema; API or events for access |
| p99 dominated by internal hops | Chatty services | Batch APIs, caching, merge boundaries |
| More dashboards than features | Nanoservices | Consolidate into coarser services |

### War Story

The "distributed monolith" critique is as old as the field's founding documents: the microservices article by Lewis and Fowler (2014) codified "smart endpoints and dumb pipes" precisely because 2000s-era ESBs had accumulated unversioned business logic in the middleware. And the 2023 Prime Video cost-consolidation post plus years of "we went back to a monolith" engineering retrospectives (e.g., Segment's widely read 2018 account of reversing course from ~140 services) made the hall of shame respectable to talk about in public.

### Checkpoint

- Give two concrete tests that reveal a distributed monolith.
- Why does a shared database turn schema migrations into cross-team negotiations?
- Five services in a synchronous chain each offer 99.9% availability. Roughly what availability does the chain offer, and what does that imply for deep call graphs?
