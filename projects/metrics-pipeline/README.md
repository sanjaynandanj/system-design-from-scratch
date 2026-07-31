# Project: Metrics Pipeline

> Turn a firehose of raw events into percentiles, windows, and alerts —
> the entire observability industry, minus about 4 million lines of Go.

Every metrics system you've ever paid for (Datadog, Prometheus + friends,
CloudWatch) does the same four things: **collect** events, **aggregate**
them into time windows, **store** the summaries, and **alert** when a
number crosses a line. This project builds that whole chain in one file of
stdlib Python, including the sneakiest part: deciding when a window is
actually *finished*.

## Architecture

```
  ┌─────────┐
  │  app-1  │──┐  Event(metric, value, ts, source)
  └─────────┘  │
  ┌─────────┐  │   ┌───────────┐    ┌──────────────────┐    ┌─────────┐
  │  app-2  │──┼──▶│   QUEUE   │───▶│    AGGREGATOR    │───▶│  STORE  │
  └─────────┘  │   │ (the bus) │    │ tumbling 1s wins │    │ series  │
  ┌─────────┐  │   └───────────┘    │ count/sum/p50/p99│    └────┬────┘
  │  app-3  │──┘                    │ watermark closes │         │
  └─────────┘                       └────────┬─────────┘         ▼
   (has a latency                            │              ┌───────────┐
    incident in                              ▼              │ DASHBOARD │
    windows 2-3)                        ┌─────────┐         │ sparkline │
                                        │ ALERTER │         │  + table  │
                                        │ p99>200 │         └───────────┘
                                        └─────────┘
```

## How it works

**1. Emitters.** Three simulated app servers push `requests` counters and
`latency_ms` samples onto a shared `queue.Queue`. Timestamps are simulated
seconds, so five "seconds" of traffic compresses into ~2 real seconds.
Server `app-3` has a scripted database incident: its latency jumps 10x
during windows 2–3. Somebody has to page the on-call.

**2. Tumbling windows.** The aggregator buckets each event into
`[t, t+1)` by `int(ts)`. Per window it keeps the raw values, and on close
computes count, sum, p50 and p99 (nearest-rank over a sorted list — fine
at this volume; at real volume you'd reservoir-sample or use t-digest).

**3. The watermark (the actually-hard part).** When is window 2 *done*?
You can't just wait for an event with `ts >= 3` — events arrive slightly
late and out of order. The aggregator tracks the max timestamp seen **per
source** and merges them with `min()`: a window closes only when *every*
producer has moved past its end, plus a 0.25s lateness budget. A single
global watermark is the classic streaming bug — one fast producer would
declare windows closed while a slow producer's events were still in
flight, silently dropping them. Events that miss even the lateness budget
are counted and dropped, and the dashboard reports the body count.

**4. Alerting with state.** The alerter isn't `if p99 > 200: print(...)`
— that would page you once per window for the whole incident. It's a tiny
state machine: quiet → FIRING on first breach, FIRING → RESOLVED on first
recovery. One page in, one page out.

**5. The dashboard.** At the end you get a per-window table plus an ASCII
sparkline of the p99 trend, where the incident sticks out like a broken
finger.

## Milestones (build it yourself)

1. **Firehose** — producer threads pushing events on a `Queue`, consumer
   printing them. Feel how fast raw events pile up.
2. **Windows** — bucket by `int(ts)`, close a window when you see any
   event past its end. Compute count/sum/p50/p99.
3. **Watermarks** — add per-source max-ts tracking and `min()`-merge.
   Prove to yourself the global-watermark version drops events (add a
   `time.sleep` to one producer and watch counts go wrong).
4. **Alerting** — threshold + firing/resolved state machine. Then make
   it require 2 consecutive bad windows (hysteresis) and see how much
   flappiness that removes.
5. **Dashboard** — table + sparkline. Squint. That's Grafana.

## How to run

```
python pipeline.py --demo            # ~2s, exits by itself
python pipeline.py --windows 8      # longer simulation
```

You'll see the alert fire mid-run as window 2 closes, resolve at window
4, and a final dashboard with the p99 sparkline spiking in the middle.

## Extension ideas

- **Sliding windows.** Report a 3s window every 1s. Each event now lands
  in 3 windows — watch memory triple, then fix it with pane merging.
- **Reservoir sampling.** Cap per-window storage at 500 samples using
  Algorithm R. Compare the p99 against exact — how wrong is it?
- **Rates, not counts.** Add `requests_per_sec` derived from the counter,
  and a rate-of-change alert ("traffic dropped 50% window-over-window" —
  often the scariest alert of all).
- **High cardinality.** Tag events with `endpoint` and aggregate per tag.
  Add 10,000 endpoints. Congratulations, you've rediscovered why metrics
  vendors bill by cardinality.
- **Backpressure.** Give the queue a max size and decide: block the app
  servers, or drop events? (Real answer: never block the app. Now handle
  the gaps.)
- **Downsampling.** Keep 1s windows for the "last hour", roll them up
  into 10s windows after that. This is exactly what RRDtool did in 1999.

## War story

Averages lie. The canonical cautionary tale is measuring mean latency
while p99 burns: with 40ms typical and a 420ms incident affecting one
server in three, the *average* barely doubles — page-worthy p99 breaches
hide inside a "fine-looking" mean. That's why every serious SLO is
phrased in percentiles, and why this pipeline computes p50/p99 per
window instead of a running average. Gil Tene's "How NOT to Measure
Latency" talk turned this into a whole genre; the coordinated-omission
bug he describes is worth an evening of your life.

## What this is not

No network transport, no persistence, no PromQL. The queue stands in for
Kafka, the dict stands in for a TSDB — deliberately, so the *streaming
semantics* (windows, watermarks, lateness, alert state) are the whole
lesson, with nothing to hide behind.
