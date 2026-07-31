# Phase 13 — 🔭 Observability & Reliability

> Hope is not a strategy. Dashboards are.

You've built the system. Now comes the part that separates engineering from wishful thinking: knowing what it's doing at 3 AM, deciding how reliable it *needs* to be, and having a plan for the day the data center meets a backhoe. This phase covers the instrumentation trinity (logs, metrics, traces), the SRE math that turns "reliability" from a vibe into a budget, and the human systems — alerting, incident response, postmortems — that determine whether an outage is a 10-minute blip or a résumé-generating event. Reliability is a feature; here's how you ship it.

## 01. The Three Pillars: Logs, Metrics, Traces

**MOTTO:** Metrics tell you something is wrong, traces tell you where, logs tell you why.

### The Problem

A user reports "checkout is slow." Your system is 40 services across 300 containers. SSH-ing into boxes and grepping files died as a strategy the day you passed two servers. You need telemetry designed for questions you *didn't anticipate* — because the defining property of production incidents is that they're the failure modes you didn't think to check for. That's the difference between monitoring (watching known unknowns) and observability (being able to interrogate unknown unknowns).

### The Concept

Three complementary data shapes, distinguished by what they trade:

```
  PILLAR    SHAPE                          COST SCALING        BEST QUESTION
  ------    -----                          ------------        -------------
  Metrics   numbers over time,             per-SERIES (cheap,  "is p99 latency up?
            pre-aggregated                 fixed, aggregated)   how much? since when?"
  Traces    tree of timed spans,           per-REQUEST         "where did THIS request
            one per request                (sampled)            spend its 3 seconds?"
  Logs      timestamped event records,     per-EVENT           "what exactly happened
            arbitrary detail               (expensive, rich)    at that moment?"
```

Think of a hospital: metrics are the vital-signs monitor (continuous, cheap, alarm-ready), a trace is one patient's chart through admission → tests → surgery (per-case timeline across departments), and logs are the doctors' detailed notes (rich, searchable, voluminous). No single pillar substitutes for another: metrics aggregate away the individual case; logs lack cross-service structure; traces sample away completeness.

### Build It

The debugging loop that connects them:

1. Instrument everything with shared identifiers: every log line and span carries `trace_id`; metrics carry service/endpoint labels. Correlation is the whole game.
2. Alert on metrics (Lesson 06): p99 checkout latency breaches its SLO.
3. Pivot to traces: filter traces for the slow endpoint; the span waterfall shows 2.7 of 3 seconds inside `payments → fraud-check`.
4. Pivot to logs: query logs where `trace_id = abc123` and `service = fraud-check`; find the retry loop against a timing-out vendor API.
5. Close the loop: add a metric/alert for vendor latency so next time step 2 fires earlier.

If your telemetry can't do steps 3–4's pivots — if logs and traces don't share IDs — you have three data silos, not three pillars.

### Use It

| Pillar | Open source | Managed |
|---|---|---|
| Metrics | Prometheus + Grafana | Datadog, CloudWatch, Grafana Cloud |
| Traces | Jaeger, Tempo, Zipkin | Datadog APM, Honeycomb, X-Ray |
| Logs | Loki, Elasticsearch/OpenSearch | Datadog Logs, Splunk |
| All three, one standard | OpenTelemetry (instrument once, export anywhere) | — |

### War Story

The vocabulary is borrowed from control theory (a system is "observable" if internal state can be inferred from outputs), popularized for software by Twitter's early-2010s observability team blog posts and the Google SRE book (2016). The ecosystem's peace treaty came in 2019 when the competing OpenTracing and OpenCensus projects merged into OpenTelemetry — now one of the CNCF's most active projects, ending a decade of instrument-once-per-vendor lock-in.

### Checkpoint

- Why can't high-cardinality questions ("which user saw errors?") be answered by metrics, and which pillar takes over?
- What single practice makes the metrics → traces → logs pivot possible?
- Your logging bill is exploding but dashboards feel fine. Which pillar's cost model explains this, and what are two levers?

## 02. Structured Logging Done Right

**MOTTO:** Log for the machine that will query it, not the human who wrote it.

### The Problem

`log.info(f"User {user} did {thing} maybe {count} times")` — beautiful prose, unqueryable data. When logs are free-form strings, every investigation starts with writing a regex against whatever sentence a developer improvised two years ago, and "find all failed payments over $100 for user X" is an archaeology project. At scale, logs are a *dataset*. Datasets need schemas.

### The Concept

Structured logging emits events as key-value records (JSON, typically) instead of sentences. The log line stops being a diary entry and becomes a row in a queryable table — the difference between a shoebox of receipts and a spreadsheet.

```
  UNSTRUCTURED (grep and pray):
    "Payment failed for user 42 after 3 retries: timeout"

  STRUCTURED (query like a database):
    {"ts":"2026-07-31T03:12:09Z", "level":"error", "event":"payment_failed",
     "user_id":42, "amount_cents":15000, "retries":3, "reason":"gateway_timeout",
     "trace_id":"abc123", "service":"payments", "version":"2.31.0"}

  Now trivial: rate of payment_failed by reason; all events for trace abc123;
  p95 of amount_cents where reason="gateway_timeout".
```

### Build It

The rules that make it work:

1. One event, one line, machine-first: JSON to stdout; the platform (container runtime → collector) handles shipping. Apps don't manage log files.
2. Standard envelope on every record: timestamp (UTC, ISO 8601), level, `event` name (stable, snake_case — it's an API), service, version, and **trace_id** (Lesson 01's glue).
3. Context propagation beats repetition: bind request-scoped fields once; every log in that request inherits them.

```python
import structlog
log = structlog.get_logger()

def handle_request(req):
    slog = log.bind(trace_id=req.trace_id, user_id=req.user_id)  # bind once
    slog.info("payment_attempt", amount_cents=req.amount)
    try:
        charge(req)
    except GatewayTimeout as e:
        slog.error("payment_failed", reason="gateway_timeout", retries=e.retries)
```

4. Levels mean something: `error` = a human may need to act; `warn` = degraded but handled; `info` = business events; `debug` = off in prod, toggleable. An error level that fires routinely trains everyone to ignore it.
5. Discipline: never log secrets/PII (tokens, passwords, card numbers — enforce with scrubbing middleware); keep `event` names stable so saved queries don't rot; sample or drop high-volume debug noise *at the edge* — per-GB ingestion pricing is how logging becomes your second-biggest cloud bill.

### Use It

| Tool | Role |
|---|---|
| structlog (Python), zerolog/zap (Go), Serilog (.NET) | In-process structured emitters |
| Fluent Bit / Vector / OpenTelemetry Collector | Collect, transform, scrub, route |
| Loki | Indexes labels only — cheap, grep-like queries |
| Elasticsearch/OpenSearch | Full-text index on everything — powerful, pricier |

### War Story

The 12-Factor App manifesto (Heroku, 2011) codified "logs as event streams" — apps write to stdout, the platform does the rest — which quietly killed the in-app log-rotation ceremony. The cost lesson arrived a decade later: practitioner postmortems of six-and-seven-figure observability bills (a staple of engineering blogs and conference talks by the early 2020s) mostly trace to unbounded debug logging and high-cardinality labels nobody queried. Structure isn't just for querying; it's how you *meter* what you keep.

### Checkpoint

- Why is a stable `event` name field described as "an API"? Who are its consumers?
- What does context binding (attaching trace_id/user_id once per request) buy over passing fields at each call site?
- Name two practices that keep log costs sane without losing incident-debugging power.

## 03. Metrics and Prometheus

**MOTTO:** Aggregate at the edge, scrape from the center, and never put a user ID in a label.

### The Problem

You need "requests per second, error rate, p99 latency, per service, per endpoint, right now and for the last month" — continuously, cheaply, for thousands of instances. Shipping a log line per request to compute these is a firehose solving a garden-hose problem. Metrics pre-aggregate at the source: each process keeps a handful of counters in RAM, and the monitoring system collects compact snapshots.

### The Concept

Prometheus's model: a metric is a named time series with key-value **labels** — `http_requests_total{service="checkout", path="/pay", status="500"}`. Three core instrument types:

```
  COUNTER    only goes up (requests, errors, bytes)
             -> query with rate(): rate(http_requests_total[5m])
  GAUGE      goes up and down (queue depth, memory, in-flight requests)
  HISTOGRAM  observations in buckets (latency) ->
             http_request_seconds_bucket{le="0.1"} 9432   <- cumulative
             http_request_seconds_bucket{le="0.5"} 9921      counts per
             http_request_seconds_bucket{le="+Inf"} 9967     bound
             -> p99 estimated via histogram_quantile()
```

And the contrarian architecture choice — **pull**: your process exposes `/metrics` as plain text; Prometheus *scrapes* it every 15s. Like a building inspector on rounds versus every apartment mailing letters: the inspector controls the schedule, notices silent apartments immediately (`up == 0` — a dead target is itself a signal, versus push where silence is ambiguous), and any human can `curl /metrics` to see exactly what a process reports. Push still has its place (short-lived batch jobs → Pushgateway).

### Build It

1. Instrument the RED trio per endpoint — Rate, Errors, Duration:

```python
from prometheus_client import Counter, Histogram, start_http_server

REQS = Counter("http_requests_total", "requests", ["path", "status"])
LAT  = Histogram("http_request_seconds", "latency", ["path"],
                 buckets=[.01, .05, .1, .25, .5, 1, 2.5, 5])

def handle(req):
    with LAT.labels(req.path).time():
        resp = route(req)
    REQS.labels(req.path, str(resp.status)).inc()
```

2. Why histograms, not averages: latency is long-tailed; the mean hides the suffering. Bucketed histograms also **aggregate across instances** (sum the buckets, then take the quantile) — you cannot average per-instance p99s and get anything meaningful.
3. Respect cardinality physics: cost = number of *distinct label combinations*. `path × status` = dozens of series; add `user_id` and you've minted millions of series and killed the TSDB. Labels are for dimensions you'd GROUP BY, never for identifiers (that's what logs/traces are for).
4. For infra, the USE method (Utilization, Saturation, Errors) per resource complements RED per service.
5. Long-term/global storage: Prometheus is per-cluster and local-disk by design; Thanos/Mimir/Cortex federate and retain.

### Use It

| Tool | Notes |
|---|---|
| Prometheus + Grafana | The default stack; PromQL is the lingua franca |
| Thanos / Mimir / VictoriaMetrics | Scale-out, long retention |
| OpenTelemetry metrics | Vendor-neutral instrumentation, Prometheus-compatible |
| StatsD/Datadog agent | The push lineage — still common |

### War Story

Prometheus was built at SoundCloud starting in 2012 by ex-Google engineers (Matt Proud, Julius Volz) explicitly modeled on Google's internal Borgmon — bringing the "white-box metrics + label-based query language + pull" religion outside. Open-sourced, it became the second project ever accepted into the CNCF (2016, right after Kubernetes) and the de facto metrics standard of the cloud-native era; the Google SRE book's Borgmon chapter reads as its origin story.

### Checkpoint

- Why must a counter only ever increase, and what does `rate()` compute from it that raw values can't give?
- Why can't you average per-instance p99 latencies, and how do histogram buckets solve cross-instance quantiles?
- Explain the cardinality explosion: what happens to Prometheus if you add a `user_id` label, and where should that data live instead?

## 04. Distributed Tracing

**MOTTO:** One request, forty services, one ID to bind them all.

### The Problem

A request enters the front door and fans out through a dozen services before returning. It takes 3 seconds. *Where* did the time go? Each service's own logs and metrics see only their fragment; nobody sees the request's whole journey. Worse, without a shared identifier you can't even collect the fragments. Debugging latency in microservices without tracing is assembling a crime timeline from forty witnesses who don't know they saw the same crime.

### The Concept

A **trace** is the tree of work done for one request. Each unit of work is a **span**: name, start time, duration, attributes, plus three IDs — `trace_id` (shared by the whole journey), `span_id` (this hop), `parent_span_id` (who called me). Services propagate the context in request headers (the W3C `traceparent` standard), so every hop knows which story it's part of. Render spans on a timeline and you get the waterfall:

```
  trace abc123 (3.01s total)
  gateway        |=============================================| 3.01s
   checkout        |=========================================|  2.90s
    inventory        |====|                                     0.31s
    payments              |==================================|  2.51s
     fraud-check            |================================|  2.43s  <-- there.
    (inventory and payments in parallel; fraud-check is the long pole)
```

The waterfall answers by inspection what no dashboard can: serial vs parallel calls, the long pole, gaps (time between spans = queueing or missing instrumentation).

### Build It

1. Propagate: on inbound requests, extract `traceparent`; on outbound, inject it. Instrumentation libraries hook HTTP/gRPC clients so this is mostly automatic — the discipline is ensuring *every* hop (including queues: stash context in message headers) participates. One non-propagating service cuts the tree.
2. Emit: each service records spans with timing and attributes (`http.status_code`, `db.statement`), exporting asynchronously to a collector — never block the request path on telemetry.

```python
from opentelemetry import trace
tracer = trace.get_tracer("checkout")

def handle_order(order, ctx):                       # ctx from traceparent header
    with tracer.start_as_current_span("checkout", context=ctx) as span:
        span.set_attribute("order.id", order.id)
        reserve_inventory(order)   # instrumented client auto-creates child
        charge_payment(order)      # spans and injects headers downstream
```

3. Sample: tracing every request at volume is unaffordable. **Head sampling** decides at the trace's birth (e.g., 1%) — cheap, but blind to outcomes; **tail sampling** buffers and decides at the end ("keep all errors and everything > 1s") — keeps exactly the interesting traces, costs buffering infrastructure.
4. Connect the pillars: stamp `trace_id` on logs (Lesson 02) and exemplars on metrics, completing Lesson 01's pivot loop.

### Use It

| Tool | Notes |
|---|---|
| OpenTelemetry | The instrumentation standard — SDKs, auto-instrumentation, collector |
| Jaeger / Tempo / Zipkin | Open-source backends |
| Honeycomb / Lightstep / Datadog APM | Managed; strong high-cardinality analysis |
| W3C Trace Context | The `traceparent` header spec making vendors interoperate |

### War Story

Google's Dapper paper (2010, Sigelman et al.) described tracing production at Google scale with two findings that shaped everything since: propagation must live in shared infrastructure libraries (so application developers get it for free — where instrumentation is optional, coverage is partial), and aggressive sampling (they cite rates as low as 1 in 1024) still catches systemic patterns. Twitter's Zipkin (open-sourced 2012) was Dapper's public reimplementation; Dapper's authors later founded Lightstep and helped drive OpenTelemetry.

### Checkpoint

- What do the three IDs on a span each identify, and how does a backend reconstruct the tree from a bag of spans?
- In the waterfall above, what tells you inventory and payments ran in parallel, and why does that matter for optimization?
- Contrast head and tail sampling: which can guarantee "keep every trace containing an error," and what does that guarantee cost?

## 05. SLIs, SLOs, and Error Budgets

**MOTTO:** 100% is the wrong reliability target for everything; the right question is how much failure you can afford.

### The Problem

"The site should be reliable" is not an engineering requirement — it's a mood. Without a number, every debate between shipping features and hardening infrastructure is decided by whoever argues loudest, ops teams block releases out of generalized fear, and nobody can say whether last month was actually *bad*. Meanwhile, each extra nine costs roughly 10x more, and past a point users can't tell the difference — their WiFi is less reliable than your service.

### The Concept

Three definitions, one lever:

- **SLI** (indicator): a measured ratio of good events to total events. *"Proportion of requests served successfully in < 300ms."*
- **SLO** (objective): the target for that SLI over a window. *"99.9% over 30 days."*
- **Error budget**: 1 − SLO — the failure you're *allowed*. At 99.9% of ~43,200 minutes/month, that's **43 minutes of badness you may spend**.

```
  SLO 99.9%/30d  ->  budget = 0.1% ≈ 43 min

  budget healthy               budget exhausted
  ┌────────────────┐          ┌────────────────┐
  │ ship fast,     │          │ freeze risky   │
  │ take risks,    │   ...    │ launches; work │
  │ run chaos exps │          │ on reliability │
  └────────────────┘          └────────────────┘
```

The genius is what the budget *is*: a pre-negotiated peace treaty between velocity and reliability. Budget left? Ship aggressively — reliability work beyond the SLO is over-engineering by agreement. Budget spent? Feature launches pause, reliability work takes priority — by agreement, not by argument. (SLAs are the external, contractual cousins with refunds attached; set them looser than your SLOs.)

### Build It

1. Choose SLIs from the user's chair: availability (`good requests / total`), latency (`requests under threshold / total`), freshness/correctness for pipelines. Measure as close to the user as possible (load balancer, not the app's opinion of itself).
2. Express as PromQL-able ratios: `sum(rate(requests{code!~"5..", le="0.3"}[w])) / sum(rate(requests[w]))`.
3. Set the SLO from reality, not aspiration: look at achieved performance, pick a defensible target, tighten later. Different endpoints deserve different SLOs (checkout ≠ avatar upload).
4. Alert on **burn rate** — how fast you're eating budget: burn 14x (budget gone in ~2 days) sustained 1h → page; burn 2x sustained 6h → ticket. Multi-window burn alerts (Lesson 06) beat threshold alerts on both speed and noise.
5. Enforce the policy: budget exhaustion triggers the agreed consequence. An error budget nobody acts on is a dashboard, not a contract.

### Use It

| Tool | Notes |
|---|---|
| Prometheus + recording rules | Hand-rolled SLOs; Sloth/Pyrra generate the rules |
| Datadog/Grafana SLO products | SLO tracking as a feature |
| OpenSLO | Spec for declaring SLOs as code |
| Spreadsheet + honesty | Genuinely fine at small scale |

### War Story

Error budgets are Google SRE's signature export, canonized in the 2016 SRE book: the founding insight (per Ben Treynor Sloss, who named SRE) was making product and reliability teams *share one currency*, ending the classic dev-wants-to-ship vs ops-wants-to-freeze standoff by pre-agreeing what happens when the budget runs dry. The book's blunt framing — users can't distinguish 99.999% from 99.9999%, but the cost difference is enormous — gave engineers permission to stop worshiping nines.

### Checkpoint

- Define SLI, SLO, and error budget, and compute the monthly budget in minutes for a 99.95% SLO.
- Why does the error-budget mechanism reduce *organizational* conflict, not just measure reliability?
- What is burn rate, and why does alerting on it beat alerting on "SLI dipped below target right now"?

## 06. Alerting Without Fatigue

**MOTTO:** Every page must be urgent, actionable, and real — or it's training your team to ignore the one that matters.

### The Problem

The on-call phone buzzes 40 times a night: CPU crossed 80%, a pod restarted, disk hit a threshold on a box nobody remembers. All self-resolved. Three weeks of this and humans do what humans do — swipe away alerts on reflex. Then the real outage pages, gets swiped, and burns for four hours. Alert fatigue isn't an annoyance; it's the mechanism by which monitoring systems cause outages to last longer.

### The Concept

The core distinction: **symptom-based** alerts fire on what users experience (error rate up, latency up, SLO burning); **cause-based** alerts fire on internal conditions that *might* matter (CPU high, replica down). Page on symptoms; record causes as context. A high-CPU box serving every request within SLO is not an emergency — and a fleet at 30% CPU failing every request is. The fire alarm should ring for smoke, not for the oven being warm.

```
  severity ladder:
  PAGE    users hurting NOW or budget burning fast -> wake a human
  TICKET  needs a human this week, not this minute  -> queue it
  RECORD  context for debugging                     -> dashboard/log only

  and the fatigue equation:
  every non-actionable page ──> +cynicism ──> slower response to real pages
```

The refinement that makes SLO alerting practical is **multi-window, multi-burn-rate** (from the SRE Workbook): page only when budget burns fast over both a long and short window (fast burn *still happening*); ticket on slow sustained burn. Two alerts total per SLO, high precision *and* high recall.

### Build It

The alert design review, applied to every rule:

1. Ask the five questions: Does it indicate user pain (or imminent, certain pain)? Is it urgent — does responding at 3 AM beat responding at 9 AM? Is it actionable — is there something a human *does*? Is it novel — or a duplicate of another alert that fires with it? Does it need intelligence — or could automation handle it (restart, failover) and log instead?  Fail any → demote below page.
2. Implement burn-rate pairs per SLO: e.g., page when `burn(1h) > 14 AND burn(5m) > 14`; ticket when `burn(6h) > 2 AND burn(30m) > 2` (fast-window clause stops paging for already-recovered blips).
3. Reduce blast: group related alerts (Alertmanager grouping), inhibit downstream alerts when an upstream cause fires ("datacenter down" silences 500 per-service alerts), and silence during known maintenance.
4. Attach a runbook link to every page: symptom, dashboards, first diagnostic steps, escalation path. A page without a runbook outsources design work to a sleepy brain.
5. Run the feedback loop: review pages weekly — count them, mark each actionable/not, delete or demote repeat offenders. Track pages-per-shift; more than a handful per week means the system is broken, whatever the uptime says.

### Use It

| Tool | Role |
|---|---|
| Prometheus Alertmanager | Grouping, inhibition, silencing, routing |
| PagerDuty / Opsgenie | Escalation policies, schedules, ack tracking |
| Grafana OnCall / IRM | Open-source-friendly paging |
| SRE Workbook ch. 5 | The multi-window burn-rate recipes, worked out |

### War Story

Rob Ewaschuk's "My Philosophy on Alerting" — written from his Google SRE experience and absorbed into the SRE book (2016) — is the field's founding text: pages must be urgent, actionable, and user-visible, and "every page should require intelligence to deal with; if it has an algorithmic response, that response should be automated." The SRE Workbook (2018) then published the multi-window burn-rate design as the practical endpoint of a chapter-length journey through five inferior alerting schemes — a rare case of a vendor-neutral, fully worked answer.

### Checkpoint

- Distinguish symptom-based from cause-based alerts and give an example where a cause-based page would be wrong both ways (false positive and false negative).
- In a multi-window burn alert, what is the short window's job?
- A page fires weekly and the fix is always "restart the worker." What do the five questions say to do?

## 07. Health Checks and Probes

**MOTTO:** "Are you alive?" and "can you take traffic?" are different questions with different wrong answers.

### The Problem

The orchestrator needs to know two things about your process: should I *restart* it, and should I *route requests* to it? Conflate them and you get the classic self-inflicted outage: the database blips, every instance's health check fails because it checks the DB, the orchestrator restarts *all of them simultaneously*, and a 10-second dependency blip becomes a 10-minute full outage with cold caches. The check meant to protect the system killed it.

### The Concept

Split the questions:

- **Liveness**: "is this process irrecoverably broken (deadlocked, wedged)?" Failure ⇒ **restart me**. Must test only *internal* state.
- **Readiness**: "can I usefully serve right now?" Failure ⇒ **stop sending me traffic** (stay in the pool's penalty box; no restart). May consider dependencies and warm-up.
- **Startup** (Kubernetes's third probe): "still booting?" — holds off liveness checks so slow starters aren't killed mid-initialization.

```
  event                liveness   readiness   orchestrator action
  -----                --------   ---------   -------------------
  process deadlocked   FAIL       (moot)      restart container
  cache warming up     OK         FAIL        no traffic yet; no restart
  DB dependency down   OK         FAIL(maybe) drain traffic; DON'T restart
  healthy              OK         OK          route traffic

  THE CARDINAL SIN: dependency check inside liveness
  DB blip -> all liveness fail -> mass restart -> cold caches -> real outage
```

Doctor's-office version: liveness is "does the patient have a pulse?"; readiness is "is the doctor ready for the next patient?" You don't declare a doctor dead because the lab downstairs is backed up.

### Build It

1. Liveness: trivially cheap, internal-only — "event loop responsive, not deadlocked." Return 200 unless the process itself is wedged. When in doubt, *less* in liveness.
2. Readiness: server warmed up, config loaded, and (judiciously) hard dependencies reachable — but think it through: if *every* instance fails readiness on a shared-dependency blip, the whole pool drains and you've built the outage anyway. For shared dependencies, often better to stay ready and fail requests fast (circuit breakers, Phase 10) than to vanish from the pool.
3. Wire graceful shutdown through readiness: on SIGTERM, fail readiness first, keep serving in-flight requests, wait for the LB to stop sending (`preStop` sleep covers propagation delay), then exit. This is the difference between zero-downtime deploys and a 502 spike on every rollout.
4. Tune probe math: `period × failureThreshold` = detection delay; too twitchy restarts healthy-but-busy pods (GC pause ≠ death), too lax leaves zombies serving errors.
5. Deep health (full dependency battery) belongs on a *diagnostic* endpoint for humans and dashboards — not wired to any automated trigger.

### Use It

| Context | Mechanism |
|---|---|
| Kubernetes | liveness/readiness/startup probes (HTTP, TCP, exec, gRPC) |
| Load balancers (ALB, NGINX, Envoy) | HTTP health checks gate the pool; Envoy adds outlier ejection |
| Service registries (Consul) | TTL/heartbeat checks (Phase 10, Lesson 03) |
| systemd | watchdog timers — same idea, one machine |

### War Story

"Liveness probes can be dangerous" is practically a genre of Kubernetes postmortem: the pattern — dependency checks in liveness probes turning partial failures into mass-restart cascades — is warned against in Kubernetes documentation and countless SRE writeups, and echoes the older LB lesson that health checks with shared failure modes cause correlated ejection (the whole pool "fails" at once, and some LBs sensibly enter a fail-open panic mode rather than eject everyone — Envoy ships this behavior). The recurring moral: a health check is an automated trigger, and automated triggers deserve failure-mode analysis like any other code.

### Checkpoint

- Why must liveness checks never include dependency checks? Walk the cascade.
- Describe the graceful-shutdown sequence and readiness's role in a zero-downtime deploy.
- Every instance's readiness fails when a shared cache blips, draining the pool. What design alternatives keep partial capacity?

## 08. Graceful Degradation and Feature Flags

**MOTTO:** A system that can only be perfectly up or completely down has chosen its own worst failure mode.

### The Problem

Binary thinking — the site is "up" or "down" — leaves enormous value on the table. When the recommendation engine dies, should the store stop selling? When load exceeds capacity, should everyone get errors, or should search get slower while checkout stays crisp? And separately: why does turning *anything* off require a deploy — the slowest, riskiest lever you own — in the middle of an incident?

### The Concept

**Graceful degradation** means designing explicit *reduced* service levels: a restaurant that 86's the specials when the kitchen is slammed, rather than locking the front door. Rank your features by criticality; when resources tighten or dependencies fail, shed from the bottom.

**Feature flags** are the control surface: runtime switches, changeable in seconds without deploying. Born for decoupling deploy from release (dark launches, canary percentages, A/B tests), they double as operational kill switches — the incident commander's panel of circuit breakers for *features*.

```
  DEGRADATION LADDER (e-commerce under duress):
  L0 full service:  recs, reviews, search, checkout, live inventory
  L1 shed frills :  recs -> cached bestsellers; reviews hidden
  L2 shed weight :  search -> simpler ranking; inventory counts cached
  L3 core only   :  browse (CDN-cached) + checkout. Nothing else.
                    checkout dies last. always.

  flags: {recs: on, reviews: on, rich_search: on, ...}  <- flip in seconds
```

Related machinery: **load shedding** (reject excess/low-priority work early, at the edge, before it eats resources — a fast 503 to some beats slow failure for all) and **brownout** (auto-disable optional content under latency pressure).

### Build It

1. Rank features by criticality with the business — during an incident is the wrong time to debate whether reviews outrank recommendations. Write the ladder down.
2. Give every non-core dependency a fallback: cached last-known-good, static default, or clean absence (a missing recs panel, not a spinner, not a 500). Timeouts + circuit breakers (Phase 10) trigger fallbacks *automatically*; flags let humans force them.
3. Implement flags with fast local evaluation (in-process cache of rules, background sync) — flag evaluation on the request path must never be a network call that can itself fail. Decide fail-open vs fail-closed per flag for when the flag service is unreachable.
4. Load-shed by priority at admission: classify requests (checkout > browse > bot), shed lowest first when queues/latency breach limits.
5. Pay the hygiene tax: stale flags are technical debt with a blast radius — name owners, set expiry dates, test both branches in CI, and *delete* launched flags. Flag count only grows unless someone's job is making it shrink.

### Use It

| Tool | Notes |
|---|---|
| LaunchDarkly / Unleash / Flagsmith / OpenFeature | Flag platforms; OpenFeature is the vendor-neutral API |
| Envoy admission control / adaptive concurrency | Load shedding at the proxy |
| Netflix Hystrix lineage | Fallbacks as first-class code paths |
| CDN stale-while-revalidate / stale-if-error | Degradation for content, free with HTTP |

### War Story

The cautionary tale is Knight Capital (August 1, 2012): a deploy left old code reachable on one server via a *repurposed feature flag*, and 45 minutes of runaway orders cost ~$440 million and the company's independence — the canonical citation for "flags are code with a blast radius; manage their lifecycle." On the success side, Netflix's resilience engineering popularized fallbacks-by-default: their public architecture talks describe personalized rows degrading to non-personalized popular titles rather than an error — most users never notice the difference, which is the entire point.

### Checkpoint

- What's the difference between automatic degradation (circuit breaker + fallback) and operator-driven degradation (kill switch), and why do you want both?
- Why must feature-flag evaluation be a local, in-process operation, and what decision must you still make for flag-service outages?
- What made Knight Capital a *flag lifecycle* failure rather than just a bad deploy?

## 09. Chaos Engineering

**MOTTO:** Break it on purpose on Tuesday afternoon, or it breaks by surprise on Saturday night.

### The Problem

Your architecture diagram says "if a replica dies, traffic fails over." Does it? The failover path runs approximately never, which means it rots: a config drift here, an expired credential there, a timeout that was always too long. Untested recovery code is Schrödinger's reliability — assumed alive, probably dead. The only way to know a system survives failure is to *have the failure*, and you'd rather schedule it than await it.

### The Concept

Chaos engineering is the experimental method applied to resilience: form a hypothesis about steady state, inject a real fault in a controlled way, and compare. It's a vaccine — a small, controlled dose of the pathogen to build systemic immunity — or a fire drill where the fire is real but the building is instrumented and the extinguishers are pre-positioned.

```
  THE EXPERIMENT LOOP
  1. steady state:  "checkout success rate = 99.95%"
  2. hypothesis:    "killing 1 of 6 payment pods won't move it"
  3. minimize blast: 1% of traffic, business hours, all hands on
  4. inject:        kill the pod (or add 300ms latency, or block a dep)
  5. observe:       SLIs hold?  -> confidence, next larger experiment
                    SLIs dip?   -> ABORT (auto), you found a real bug
                                   at 2 PM with everyone watching
                                   instead of 2 AM with no one
```

Fault menu, in rough order of ambition: kill a process → add latency/packet loss to a dependency (often more revealing than death — Phase 10's slow-is-worse-than-down) → exhaust a resource → block a whole dependency → drop an AZ → fail a region.

### Build It

1. Prerequisites, non-negotiable: observability good enough to see the blast (Lessons 01–04), an abort switch, and an SLO to define "acceptable" (Lesson 05). Chaos without observability is just vandalism.
2. Start in staging; graduate to production deliberately — production is the point (staging never has real traffic patterns, data volumes, or config drift), but you earn it with small blast radii.
3. Automate the guardrails: experiments auto-halt on SLO breach; scope by tenant/percentage/region.
4. Run game days: announced, cross-team exercises injecting a scenario ("payments DB primary is gone") that test the *humans* — detection time, runbooks, escalation — not just the software. Half of what game days find is wrong dashboards and missing permissions.
5. Treat findings as incidents-that-didn't-happen: file them, fix them, re-run the experiment to verify. An experiment that always passes gets promoted to a bigger one; that's the ratchet.

### Use It

| Tool | Notes |
|---|---|
| Chaos Monkey / Simian Army | Netflix's originals — random instance termination |
| Gremlin | Managed chaos platform, safety-first design |
| Chaos Mesh / LitmusChaos | Kubernetes-native, CNCF projects |
| AWS Fault Injection Service | Faults as a managed cloud primitive |

### War Story

Chaos Monkey was born from Netflix's 2008–2010 migration to AWS: they reasoned that since instances *would* die randomly, the only winning move was to kill them constantly during business hours so every team built for it — then open-sourced the tool (2012) and the discipline ("Principles of Chaos Engineering," 2015). The graduation exercise: Netflix's regional evacuation drills, in which they shift live traffic out of an entire AWS region — documented in their engineering blog — turning "can we survive a region failure?" from a prayer into a rehearsed procedure with a measured completion time.

### Checkpoint

- Why is injecting *latency* into a dependency often more revealing than killing it outright?
- What three prerequisites must exist before running chaos experiments in production?
- What do game days test that automated chaos tooling cannot?

## 10. Incident Response

**MOTTO:** An incident is a project with a deadline of now — so it needs a manager, not a mob.

### The Problem

The outage starts. Fifteen engineers pile into a channel; three try conflicting fixes simultaneously; someone restarts a service mid-diagnosis and destroys the evidence; nobody tells support; an executive demands updates from the one person actually debugging. The technical problem was 20 minutes of work — the coordination failure made it three hours. Severe incidents fail on *organization* more often than on engineering.

### The Concept

Incident response imports the fire department's playbook (literally — it descends from FEMA's Incident Command System): explicit roles, one commander, structured communication.

```
  ROLES (severe incident):
  INCIDENT COMMANDER (IC)  owns coordination & decisions.
                           DOES NOT TOUCH KEYBOARDS. Delegates everything.
  OPS/SUBJECT EXPERTS      hands on the system; investigate & execute
  COMMS LEAD               updates stakeholders/status page on a cadence
  SCRIBE                   timeline: observations, actions, times

  LIFECYCLE:
  detect -> declare (page, sev level, channel, roles)
         -> MITIGATE FIRST (rollback? failover? flag off? shed load?)
         -> then diagnose root cause
         -> resolve -> handoff or stand down -> postmortem (Lesson 11)
```

Two doctrinal points. **Mitigation before diagnosis**: the top deploy-shaped suspect gets rolled back *before* you understand the mechanism — stop the bleeding, autopsy later. And **the IC paradox**: the best debugger makes the worst IC, because command is a full-time job; an IC who dives into a shell has left the incident leaderless.

### Build It

1. Define severity levels before you need them (SEV1: users down, all hands; SEV3: degraded, business hours) — with *pre-agreed* response for each. Declaring "too early" is free; declaring late is expensive. When in doubt, declare.
2. Build the declare button: one command/workflow that opens the channel, pages the roles, starts the doc, posts the status page holding message. Friction at declaration time is paid in outage minutes.
3. Train the mitigation reflex — maintain a short menu of generic mitigations (rollback last deploy, fail out of a region, flip kill switches from Lesson 08, shed load) that responders reach for *before* understanding root cause.
4. Communicate on a cadence: comms lead posts updates every N minutes even if the update is "still investigating" — silence generates executive drive-bys into the ops channel.
5. Manage the humans: hand off IC and ops roles every few hours in long incidents (tired responders make the second incident), and log everything — the scribe's timeline is Lesson 11's raw material.

### Use It

| Tool | Role |
|---|---|
| PagerDuty / Opsgenie / Grafana IRM | Paging, escalation, on-call schedules |
| incident.io / FireHydrant / Rootly | Declare-button automation, roles, timelines |
| Statuspage etc. | External comms |
| PagerDuty's open-source Incident Response docs | A complete, battle-tested process to steal |

### War Story

The role structure descends from the Incident Command System developed after devastating 1970s California wildfires exposed multi-agency coordination chaos — Google (SRE book, "Managing Incidents") and PagerDuty (whose open-sourced incident response documentation became an industry reference) explicitly adapted it for software. The SRE book's framing survives every retelling: the unmanaged incident's failure modes are exactly a mob's — no one in charge, freelancing responders, and communication by osmosis.

### Checkpoint

- Why must the incident commander stay hands-off-keyboard, and what happens to the incident when they don't?
- Justify "mitigate before diagnose" — what's the argument, and name three generic mitigations that work without root-cause knowledge?
- Why should declaring an incident be nearly frictionless, and what does hesitation to declare actually cost?

## 11. Blameless Postmortems

**MOTTO:** If your postmortem's conclusion is "someone screwed up," you stopped digging one layer too early.

### The Problem

An incident ends. If the review's output is "Dave ran the wrong command; Dave will be more careful," three things follow: the system that *let* one command destroy production remains armed and waiting for the next Dave; everyone learns to hide near-misses and shade timelines to avoid being next; and the organization's most expensive lessons — bought with real outage minutes — evaporate. Blame doesn't just feel bad. It destroys the information supply chain that reliability runs on.

### The Concept

The blameless postmortem borrows from aviation safety: assume everyone acted reasonably given what they knew, saw, and were incentivized to do at the time — then interrogate the *system* that made a reasonable action catastrophic. The pilot isn't the root cause; the confusable switches are.

```
  BLAMEFUL (stops at the human)      BLAMELESS (keeps asking why)
  "Dave ran cleanup on prod"        Why did prod & staging creds both
   -> "be careful, Dave"             work in the same terminal?
                                    Why did the script have no dry-run,
                                     no confirmation, no environment guard?
                                    Why did nothing alert for 40 minutes?
                                    Why did restore take 3 hours?
                                     -> four systemic fixes; "next Dave"
                                        is now harmless
```

Watch for **hindsight bias** — after the outcome, the path looks obvious; the honest question is "why did it make sense *at the time*?" — and treat counterfactuals ("they should have checked X") as clues about missing affordances, not verdicts. Blameless ≠ consequence-free: recklessness and malice remain accountability matters; honest error inside a fragile system is the system's bug report.

### Build It

The document and the process:

1. Trigger criteria decided in advance (any SEV1/2, any data loss, any SLO-budget-blowing event) — not a per-incident debate.
2. The scribe's timeline (Lesson 10) becomes the factual backbone: what was observed, decided, and done, with timestamps. Facts first, interpretation second.
3. Analyze contributing causes — plural. Real incidents are conjunctions ("the bug AND the alert gap AND the slow rollback"); techniques like "five whys" help but resist collapsing to one tidy root cause.
4. Extract action items that would each have prevented, shortened, or shrunk the incident — each with an owner and a due date, tracked like real work. A postmortem whose action items die in backlog is theater; unclosed items from *previous* postmortems appearing in *new* postmortems is the metric of theater.
5. Publish wide. The Sev-1 you paid for is only amortized if every team can read it. Mature orgs review postmortems in a recurring forum and celebrate the best ones.

### Use It

| Resource | Notes |
|---|---|
| Google SRE book ch. 15 + published template | The canonical starting kit |
| Etsy's Debriefing Facilitation Guide | The deep end: how to *run* the meeting |
| incident.io / FireHydrant / Jeli | Timeline capture and tracking tooling |
| Public postmortems (Cloudflare, GitLab, AWS...) | Free masterclasses in the genre |

### War Story

The style's public exemplar is GitLab's 2017 database incident: an engineer, fatigued and fighting replication lag, removed a data directory on the *primary*; five separate backup mechanisms then turned out to be broken or misconfigured. GitLab live-streamed the recovery, published a full blameless postmortem, and explicitly declined to fire anyone — the analysis targeted the unverified backups and the confusable environments. The intellectual lineage runs through aviation's confidential reporting systems and Etsy's "blameless postmortem" writing (John Allspaw, 2012), which argued that punishing honest error simply buys you silence plus the same error later.

### Checkpoint

- Why does blame reduce the *information* available to an organization, not just morale?
- What is hindsight bias, and how should a facilitator handle "they obviously should have checked X"?
- What distinguishes a postmortem process that works from postmortem theater? Name two observable signals.

## 12. Disaster Recovery: RTO and RPO

**MOTTO:** A backup you haven't restored is a rumor, and a DR plan you haven't rehearsed is a bedtime story.

### The Problem

Region-scale events happen: floods, fires, fat-fingered infrastructure automation, ransomware, the fabled backhoe. When they do, two questions decide your company's fate: how long until we're serving again, and how much data did we lose forever? If your first attempt to answer them is *during* the disaster — restoring a backup you've never tested onto infrastructure you've never rebuilt — the answers will be "much longer than the business survives" and "more than the press release admits."

### The Concept

Two numbers govern everything:

- **RPO** (Recovery Point Objective): maximum acceptable *data loss*, measured backward in time. Set by how you copy data (backup cadence, replication lag).
- **RTO** (Recovery Time Objective): maximum acceptable *downtime*. Set by how much standby infrastructure you keep warm.

```
                 last good copy   DISASTER      service restored
  ────────────────────●──────────────X──────────────●─────────────> time
                      |<--- RPO ---->|<---- RTO --->|
                        (data lost)     (downtime)

  DR TIER          RPO        RTO         COST
  backup+restore   hours-day  hours-days  $        (backups + a plan)
  pilot light      minutes    ~1 hour     $$       (data replicated; infra cold)
  warm standby     seconds+   minutes     $$$      (scaled-down copy running)
  hot / multi-site ~zero      ~zero       $$$$$    (active-active, both live)
```

Both dials cost money on a steep curve — the business, not the engineers, should choose the price point per system: payments may warrant warm standby while the internal wiki rides backups. Beware correlated failure: backups in the same region (or same account/credentials — think ransomware) as the primary aren't disaster recovery, they're disaster *participation*. Hence 3-2-1: three copies, two media, one off-site — modernized with immutable/offline copies.

### Build It

1. Classify systems and negotiate RPO/RTO per tier with the business, in writing.
2. Build the data leg (RPO): automated backups + WAL/log shipping for point-in-time recovery, replicated cross-region, at least one copy immutable (object-lock) against ransomware and credential compromise.
3. Build the infra leg (RTO): everything as code (Terraform + images + config), because RTO is dominated by "rebuild the environment" unless the environment is a `git clone` away. DNS/traffic failover procedure written and rehearsed.
4. Mind the dependency graph: restoring services in the wrong order (app before database before secrets manager) burns RTO; know what bootstraps what — including "where do we log in if SSO is down?"
5. **Test restores routinely** — an untested backup is a rumor. Automate a periodic restore-and-verify job; run DR game days (Lesson 09) that fail over a real (scoped) workload; measure *achieved* RTO/RPO against the objectives, because the gap is the truth.

### Use It

| Tool | Role |
|---|---|
| pgBackRest / WAL-G, Velero | Database PITR; Kubernetes backup |
| Cross-region replication (S3 CRR, Aurora Global, Spanner) | The RPO workhorses |
| Object lock / immutable vaults | The ransomware answer |
| Terraform + image pipelines | Infrastructure as restorable code |
| AWS Elastic Disaster Recovery / Azure Site Recovery | Managed replication and failover |

### War Story

Two bookends. GitLab 2017 (Lesson 11's incident): five backup mechanisms, effectively none restorable when needed — the outage cost ~6 hours of production data and made "test your restores" a punchline with a body count. And OVHcloud's March 2021 Strasbourg datacenter fire destroyed SBG2 entirely; customers whose "backups" lived in the same facility as their servers lost both at once — the industry's starkest recent lesson that RPO is defined by your *most distant* copy, not your most convenient one.

### Checkpoint

- Define RPO and RTO, and identify which engineering mechanisms move each dial.
- Why do same-region (or same-credential) backups fail the definition of disaster recovery? Give two threat scenarios.
- Your last DR test restored the database in 40 minutes — but the *service* took 9 hours to return. What consumed the difference, and which practices attack it?
