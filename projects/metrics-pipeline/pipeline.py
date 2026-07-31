"""A miniature metrics pipeline: emitters -> queue -> windows -> store -> alerts.

Teaches: how observability systems turn a firehose of raw events into
1-second tumbling windows with percentiles, why watermarks decide when a
window is "done", and how an alerter with firing/resolved state hangs off
the aggregation stream. Run `python pipeline.py --demo` — finishes in a few
seconds and prints an ASCII dashboard.
"""

import argparse
import queue
import random
import threading
import time

WINDOW_SEC = 1.0
LATENESS_SEC = 0.25       # events may arrive this late and still count
P99_ALERT_THRESHOLD = 200  # ms
SPARK_LEVELS = " .:-=+*#%@"


class Event:
    __slots__ = ("metric", "value", "ts", "source")

    def __init__(self, metric, value, ts, source):
        self.metric = metric
        self.value = value
        self.ts = ts
        self.source = source


def percentile(sorted_vals, q):
    """Nearest-rank percentile; sorted_vals must be non-empty and sorted."""
    idx = max(0, min(len(sorted_vals) - 1, int(q * len(sorted_vals) + 0.5) - 1))
    return sorted_vals[idx]


class AppServer(threading.Thread):
    """Simulated app server emitting request counters + latency samples.

    Timestamps are *simulated* seconds (0..n_windows) so the whole demo
    compresses wall-clock time; the tiny sleeps just interleave producers.
    """

    def __init__(self, name, bus, n_windows, spike_windows=()):
        super().__init__(daemon=True)
        self.name = name
        self.bus = bus
        self.n_windows = n_windows
        self.spike_windows = spike_windows

    def run(self):
        rng = random.Random(self.name)  # str seed -> deterministic demo output
        sim_t = 0.0
        while sim_t < self.n_windows:
            window = int(sim_t)
            if window in self.spike_windows:
                latency = rng.gauss(420, 60)  # database "incident": 10x latency
            else:
                latency = rng.gauss(42, 8)
            # Jitter the timestamp slightly backwards to simulate late arrivals.
            ts = max(0.0, sim_t - (rng.random() * 0.1 if rng.random() < 0.1 else 0.0))
            self.bus.put(Event("requests", 1, ts, self.name))
            self.bus.put(Event("latency_ms", max(1.0, latency), ts, self.name))
            sim_t += rng.uniform(0.015, 0.035)
            if rng.random() < 0.05:
                time.sleep(0.001)
        self.bus.put(("done", self.name))  # sentinel: this producer is finished


class Alerter:
    """Threshold alert with firing/resolved state, so it doesn't spam."""

    def __init__(self, threshold):
        self.threshold = threshold
        self.firing = False
        self.log = []

    def observe(self, window_start, stats):
        p99 = stats["p99"]
        if p99 > self.threshold and not self.firing:
            self.firing = True
            self.log.append((window_start, "FIRING", p99))
            print(f"  !! ALERT FIRING   window t={window_start}s "
                  f"p99(latency_ms)={p99:.0f} > {self.threshold}")
        elif p99 <= self.threshold and self.firing:
            self.firing = False
            self.log.append((window_start, "RESOLVED", p99))
            print(f"  ok ALERT RESOLVED window t={window_start}s "
                  f"p99(latency_ms)={p99:.0f} <= {self.threshold}")


class Aggregator(threading.Thread):
    """Drains the bus into tumbling windows, finalized by watermark.

    The watermark is per-source, merged with min(): a window [t, t+1) closes
    only when EVERY producer has advanced past t+1 (plus a lateness budget).
    A single global watermark would let one fast producer close windows
    before a slow one delivered its events — the classic streaming bug.
    """

    def __init__(self, bus, store, alerter, n_producers):
        super().__init__(daemon=True)
        self.bus = bus
        self.store = store
        self.alerter = alerter
        self.n_producers = n_producers
        self.open_windows = {}  # (metric, window_start) -> list of values
        self.source_max = {}    # source -> max event ts seen from it
        self.watermark = 0.0
        self.late_dropped = 0

    def _finalize(self, metric, wstart):
        values = sorted(self.open_windows.pop((metric, wstart)))
        stats = {
            "count": len(values),
            "sum": sum(values),
            "p50": percentile(values, 0.50),
            "p99": percentile(values, 0.99),
        }
        self.store.setdefault(metric, []).append((wstart, stats))
        if metric == "latency_ms":
            self.alerter.observe(wstart, stats)

    def _advance_watermark(self):
        # No watermark until all producers have checked in, else the first
        # producer to speak would define "late" for everyone.
        if len(self.source_max) < self.n_producers:
            return
        new_mark = min(self.source_max.values()) - LATENESS_SEC
        if new_mark <= self.watermark:
            return
        self.watermark = new_mark
        for (metric, wstart) in sorted(self.open_windows):
            if wstart + WINDOW_SEC <= self.watermark:
                self._finalize(metric, wstart)

    def run(self):
        done = 0
        while done < self.n_producers:
            event = self.bus.get()
            if isinstance(event, tuple):  # ("done", source) sentinel
                self.source_max[event[1]] = float("inf")
                done += 1
                self._advance_watermark()
                continue
            wstart = int(event.ts // WINDOW_SEC)
            if wstart + WINDOW_SEC <= self.watermark:
                self.late_dropped += 1  # too late even for our lateness budget
                continue
            self.open_windows.setdefault((event.metric, wstart), []).append(event.value)
            prev = self.source_max.get(event.source, 0.0)
            self.source_max[event.source] = max(prev, event.ts)
            self._advance_watermark()
        # All producers finished: flush whatever windows remain open.
        for (metric, wstart) in sorted(self.open_windows):
            self._finalize(metric, wstart)


def sparkline(values):
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    idx = [int((v - lo) / span * (len(SPARK_LEVELS) - 1)) for v in values]
    return "".join(SPARK_LEVELS[i] for i in idx)


def dashboard(store, alerter, late_dropped):
    print()
    print("=" * 66)
    print(" DASHBOARD — tumbling 1s windows")
    print("=" * 66)
    for metric in sorted(store):
        series = sorted(store[metric])
        print(f"\n {metric}")
        print(f"   {'window':>7} {'count':>7} {'sum':>10} {'p50':>8} {'p99':>8}")
        for wstart, s in series:
            print(f"   t={wstart:>4}s {s['count']:>7} {s['sum']:>10.0f}"
                  f" {s['p50']:>8.1f} {s['p99']:>8.1f}")
        p99s = [s["p99"] for _, s in series]
        print(f"   p99 trend  [{sparkline(p99s)}]  "
              f"(min {min(p99s):.0f}, max {max(p99s):.0f})")
    print(f"\n alert timeline: " + (" -> ".join(
        f"t={w}s {state}" for w, state, _ in alerter.log) or "(quiet)"))
    print(f" late events dropped past watermark: {late_dropped}")
    print("=" * 66)


def run_demo(n_windows):
    print("=" * 66)
    print(" METRICS PIPELINE — emitters -> queue -> windows -> alerts")
    print("=" * 66)
    print(f"\n[1] 3 app servers emitting counters + latencies over "
          f"{n_windows} simulated seconds")
    print("    app-3 has a latency incident in windows 2-3 ...\n")

    bus = queue.Queue()
    store = {}
    alerter = Alerter(P99_ALERT_THRESHOLD)
    producers = [
        AppServer("app-1", bus, n_windows),
        AppServer("app-2", bus, n_windows),
        AppServer("app-3", bus, n_windows, spike_windows={2, 3}),
    ]
    agg = Aggregator(bus, store, alerter, n_producers=len(producers))

    t0 = time.perf_counter()
    agg.start()
    for p in producers:
        p.start()
    for p in producers:
        p.join()
    agg.join()
    elapsed = time.perf_counter() - t0

    dashboard(store, alerter, agg.late_dropped)
    total = sum(s["count"] for _, s in store.get("requests", []))
    print(f"\n[2] {total} request events aggregated in {elapsed:.2f}s real time.")
    print("    The pipeline never stored raw events — only window summaries.")
    print("    That count-vs-cardinality trade is the entire economics of")
    print("    metrics systems. Demo complete.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="run the automated demo and exit")
    ap.add_argument("--windows", type=int, default=5, help="simulated seconds to run")
    args = ap.parse_args()
    run_demo(args.windows)  # demo is the default and only mode; flag kept for symmetry


if __name__ == "__main__":
    main()
