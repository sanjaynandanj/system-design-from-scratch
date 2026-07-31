"""A distributed cron in one process: 3 scheduler nodes, lease-based leader
election with heartbeats, a retrying worker pool with exponential backoff,
missed-run catch-up, and a mid-demo leader kill to show failover.

The clock is accelerated (20 simulated seconds per real second), so
`python scheduler.py --demo` narrates ~30s of cluster life in ~2 real
seconds and exits by itself.
"""

import argparse
import queue
import threading
import time

SPEED = 20.0          # simulated seconds per wall-clock second
LEASE_TTL = 5.0       # sim seconds a leadership lease lasts without renewal
HEARTBEAT = 1.0       # sim seconds between a node's election/renewal attempts
BASE_BACKOFF = 1.0    # sim seconds; doubles per retry attempt
KILL_AT = 13.0        # sim time when the chaos monkey strikes
DEMO_END = 30.0       # sim time when the demo winds down


class Clock:
    """Accelerated clock: all scheduling logic thinks in simulated seconds."""

    def __init__(self, speed):
        self._t0 = time.monotonic()
        self._speed = speed

    def now(self):
        return (time.monotonic() - self._t0) * self._speed

    def sleep(self, sim_secs):
        time.sleep(max(0.0, sim_secs) / self._speed)


class Lease:
    """The whole election protocol: one row of state behind a lock.

    Whoever writes their name here (because it was empty or expired) is
    leader until the expiry — a stand-in for a row in etcd/ZooKeeper/a DB.
    """

    def __init__(self, clock, ttl):
        self.clock = clock
        self.ttl = ttl
        self.holder = None
        self.expires = 0.0
        self.history = []  # (sim_time, node) for each leadership change
        self._lock = threading.Lock()

    def try_acquire(self, node):
        with self._lock:
            now = self.clock.now()
            if self.holder == node or self.holder is None or now >= self.expires:
                newly_elected = self.holder != node
                self.holder = node
                self.expires = now + self.ttl
                if newly_elected:
                    self.history.append((now, node))
                return True, newly_elected
            return False, False


class Job:
    def __init__(self, name, interval, first_run, fail_first=0):
        self.name = name
        self.interval = interval
        self.next_run = first_run
        self.fail_first = fail_first  # simulated failures before success
        self.runs = 0
        self.retries = 0
        self.coalesced = 0


class JobTable:
    """Cron table, simplified: every job is 'run every N sim-seconds'."""

    def __init__(self, jobs):
        self.jobs = jobs
        self._lock = threading.Lock()

    def claim_due(self, now):
        with self._lock:
            due = []
            for job in self.jobs:
                if job.next_run <= now:
                    # Catch-up policy: coalesce all missed runs into one
                    # execution (like cron after a reboot), never replay each.
                    missed = int((now - job.next_run) // job.interval)
                    job.next_run += (missed + 1) * job.interval
                    job.coalesced += missed
                    due.append((job, missed))
            return due


class SchedulerNode(threading.Thread):
    """Every node runs the same loop; the lease decides who gets to act."""

    def __init__(self, name, clock, lease, table, work_q, log):
        super().__init__(daemon=True)
        self.name = name
        self.clock = clock
        self.lease = lease
        self.table = table
        self.work_q = work_q
        self.log = log
        self.stop_evt = threading.Event()

    def run(self):
        while not self.stop_evt.is_set():
            is_leader, newly = self.lease.try_acquire(self.name)
            if is_leader:
                if newly:
                    self.log(self.name, "elected LEADER (lease acquired)")
                for job, missed in self.table.claim_due(self.clock.now()):
                    if missed:
                        self.log(self.name, f"catch-up: '{job.name}' missed "
                                 f"{missed} run(s) during the gap -> coalescing "
                                 f"into one execution")
                    self.log(self.name, f"dispatch '{job.name}'")
                    self.work_q.put((job, 1))
            self.clock.sleep(HEARTBEAT)


class Worker(threading.Thread):
    def __init__(self, name, clock, work_q, log):
        super().__init__(daemon=True)
        self.name = name
        self.clock = clock
        self.work_q = work_q
        self.log = log
        self.stop_evt = threading.Event()

    def run(self):
        while not self.stop_evt.is_set():
            try:
                job, attempt = self.work_q.get(timeout=0.05)
            except queue.Empty:
                continue
            self.clock.sleep(0.3)  # the "work"
            if job.fail_first > 0:
                job.fail_first -= 1
                job.retries += 1
                backoff = BASE_BACKOFF * (2 ** (attempt - 1))
                self.log(self.name, f"'{job.name}' FAILED (attempt {attempt}) "
                         f"-> retrying in {backoff:.0f}s")
                # Real systems put retries on a delay queue; sleeping in the
                # worker is fine here but note it occupies a pool slot.
                self.clock.sleep(backoff)
                self.work_q.put((job, attempt + 1))
            else:
                job.runs += 1
                self.log(self.name, f"'{job.name}' OK (attempt {attempt})")


def run_demo():
    clock = Clock(SPEED)

    def log(who, msg):
        print(f"  [t={clock.now():5.1f}s] [{who:>7}] {msg}")

    print("=" * 66)
    print(" DISTRIBUTED CRON — 3 nodes, 1 lease, chaos monkey included")
    print("=" * 66)
    print(f"\n[1] Cluster boots: 3 scheduler nodes race for a {LEASE_TTL:.0f}s lease;")
    print(f"    2 workers stand by. Chaos monkey armed for t={KILL_AT:.0f}s.\n")

    lease = Lease(clock, LEASE_TTL)
    table = JobTable([
        Job("send-digest", interval=4.0, first_run=2.0),
        Job("sync-inventory", interval=6.0, first_run=3.0),
        Job("flaky-etl", interval=8.0, first_run=4.0, fail_first=2),
    ])
    work_q = queue.Queue()
    nodes = [SchedulerNode(f"node-{i}", clock, lease, table, work_q, log)
             for i in (1, 2, 3)]
    workers = [Worker(f"work-{i}", clock, work_q, log) for i in (1, 2)]
    for t in nodes + workers:
        t.start()

    while clock.now() < KILL_AT:
        time.sleep(0.02)
    victim = lease.holder
    print(f"\n  [t={clock.now():5.1f}s] [ chaos ] killing leader {victim} "
          f"mid-flight (no goodbye, no lease release)\n")
    for n in nodes:
        if n.name == victim:
            n.stop_evt.set()
    # Nobody can lead until the dead node's lease expires — jobs due in
    # this gap go stale, which is exactly what catch-up exists for.

    while clock.now() < DEMO_END:
        time.sleep(0.02)
    for t in nodes + workers:
        t.stop_evt.set()
    for t in nodes + workers:
        t.join(timeout=1.0)

    print("\n" + "=" * 66)
    print(" POST-MORTEM")
    print("=" * 66)
    print(f"\n {'job':<16} {'every':>6} {'runs':>5} {'retries':>8} {'coalesced':>10}")
    for job in table.jobs:
        print(f" {job.name:<16} {job.interval:>5.0f}s {job.runs:>5} "
              f"{job.retries:>8} {job.coalesced:>10}")
    print("\n leadership timeline:")
    for t, node in lease.history:
        print(f"   t={t:5.1f}s  {node} took the lease")
    print(f"\n[2] Note the gap after t={KILL_AT:.0f}s: no dispatches until the dead")
    print(f"    leader's lease expired (~{LEASE_TTL:.0f}s), then the new leader ran")
    print("    catch-up on everything that came due in the dark. That lease")
    print("    TTL is the knob: shorter = faster failover, more churn risk.")
    print("    Demo complete.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="run the automated demo and exit")
    ap.parse_args()
    run_demo()  # demo is the only mode; the flag is kept for consistency


if __name__ == "__main__":
    main()
