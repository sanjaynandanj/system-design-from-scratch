# Phase 15 — ☁️ Cloud, Containers & Infrastructure

> Someone else's computer, industrialized.

The cloud didn't eliminate servers; it turned them into a utility you rent by the millisecond and configure with code. That shift changed what "infrastructure" means: it's no longer racks you touch, it's APIs you call, declarations you commit, and abstractions stacked from hypervisors up to functions-as-a-service. This phase walks the whole stack — VMs to containers to Kubernetes to serverless — then zooms out to how modern teams ship (CI/CD, canaries), survive (multi-region, cells), and avoid going broke doing it.

## 01. VMs vs Containers

**MOTTO:** A VM virtualizes the hardware; a container virtualizes the operating system — and that one sentence explains every tradeoff.

### The Problem

One app per physical server is absurdly wasteful — most servers idle at 10-15% utilization. But cramming multiple apps onto one OS means dependency hell (app A needs libssl 1.0, app B needs 3.0), noisy neighbors, and "works on my machine." You need isolation *and* density *and* portability, and the two mainstream answers slice the stack at different heights.

### The Concept

A VM is a house: its own foundation, plumbing, and walls (full guest OS on virtual hardware). A container is an apartment: private rooms, but shared foundation and plumbing (shared kernel, isolated userspace).

```
      VMs                                Containers
┌─────────┐ ┌─────────┐            ┌─────────┐ ┌─────────┐
│  App A  │ │  App B  │            │  App A  │ │  App B  │
│ Bins/Libs│ │Bins/Libs│            │Bins/Libs │ │Bins/Libs│
│ Guest OS │ │Guest OS │            └────┬────┘ └────┬────┘
└────┬────┘ └────┬────┘            ┌─────┴───────────┴────┐
┌────┴───────────┴────┐            │   Container runtime   │
│     Hypervisor      │            │      Host OS (one     │
│      Host HW        │            │    shared kernel!)    │
└─────────────────────┘            └──────────────────────┘
Boot: minutes  Size: GBs           Start: ms-secs  Size: MBs
Strong HW-level isolation          Kernel is the shared wall
```

The consequences all follow: containers start in milliseconds and pack densely because there's no OS to boot per instance; VMs isolate more strongly because escaping requires beating the hypervisor, not just the kernel.

### Build It

1. VM mechanics: the hypervisor (KVM, Xen, Hyper-V) traps privileged instructions from the guest and mediates hardware access; modern CPUs assist with VT-x/AMD-V so most guest code runs at native speed.
2. Container mechanics: no virtualization at all — just a normal Linux process wearing kernel-enforced blinders (namespaces) and handcuffs (cgroups). Next lesson dissects them.
3. Decision procedure: untrusted multi-tenant code or a different kernel/OS → VM. Your own microservices, CI jobs, dense packing → containers. Both → containers *inside* VMs, which is exactly what every managed Kubernetes service does.
4. Know the hybrids: Firecracker microVMs (VM isolation, ~125ms boot, runs AWS Lambda) and gVisor (userspace kernel shim) exist precisely because "shared kernel" is the scary phrase in multi-tenant clouds.

### Use It

| Tech | Isolation | Startup | Use when |
|---|---|---|---|
| KVM/EC2 VMs | Hardware-level | Minutes | Untrusted tenants, foreign OS |
| Docker/OCI containers | Kernel-level | ms–secs | Your own services, CI, density |
| Firecracker microVMs | Hardware-level | ~125ms | Serverless multi-tenancy |

### War Story

AWS built Firecracker (open-sourced 2018) because Lambda's original architecture gave each *customer* dedicated EC2 instances — safe but wasteful. Firecracker's stripped-down microVMs (no BIOS, minimal devices, ~125ms boot, ~5MB overhead) let AWS pack thousands of hardware-isolated tenant workloads per server, proving the VM-vs-container dichotomy false: you can have most of both, if you delete enough legacy from the VM.

### Checkpoint

- Why can a container start in milliseconds while a VM takes tens of seconds? What work is each skipping or doing?
- Your platform runs arbitrary code uploaded by strangers. Why are plain containers the wrong isolation boundary?
- What specifically does the hypervisor virtualize that the container runtime doesn't?

## 02. Docker Internals: Namespaces and cgroups

**MOTTO:** A container is just a Linux process that's been lied to about the world and told how much it can eat.

### The Problem

"Container" sounds like a thing — a box, an object the kernel knows about. It isn't. There is no `struct container` in Linux. Treating Docker as magic means you can't debug it: why can the container see that file? why did it get OOM-killed? why does `ps` inside show PID 1? Demystifying the two kernel features underneath answers all of it.

### The Concept

Two independent kernel mechanisms, composed:

- **Namespaces** control what a process can *see* — like giving someone VR goggles showing a private world: their own process list, network stack, filesystem root, hostname.
- **cgroups** control what a process can *use* — a metered allowance for CPU, memory, and I/O.

```
Container = ordinary process
   + PID namespace    → sees itself as PID 1, no other processes
   + NET namespace    → own interfaces, IPs, ports, routing table
   + MNT namespace    → own filesystem tree (pivot_root'ed to image)
   + UTS namespace    → own hostname
   + IPC/USER/... ns  → own IPC, remapped UIDs
   + cgroup           → "≤ 2 CPUs, ≤ 512MB RAM" (exceed memory → OOM kill)
   + layered image    → overlayfs: read-only layers + one writable top
```

Images stack via overlayfs: shared read-only layers (base OS, dependencies) plus a thin copy-on-write layer per container — which is why 50 containers from one image cost almost nothing extra in disk.

### Build It

You can hand-roll a crude container with nothing but shell:

```bash
# 1. New namespaces + fresh PID space, running our own root filesystem
sudo unshare --pid --net --mount --uts --fork bash
hostname lied-to-process              # 2. UTS ns: private hostname
mount -t proc proc /proc              # 3. now `ps` shows ~only us, PID 1
# 4. chroot/pivot_root into an extracted image tarball = "the image"
# 5. cgroup: cap memory at 100MB
mkdir /sys/fs/cgroup/demo
echo 100M > /sys/fs/cgroup/demo/memory.max
echo $$   > /sys/fs/cgroup/demo/cgroup.procs
```

That's ~80% of `docker run`. Docker adds the image format and registry protocol (OCI), a veth pair bridging the NET namespace to the host, overlayfs assembly, and a daemon API. Runtime layering: `dockerd → containerd → runc`, where runc is the small binary that actually makes the syscalls above.

### Use It

| Tool | Layer | Note |
|---|---|---|
| runc / crun | OCI runtime — creates the ns/cgroup sandwich | What everything bottoms out in |
| containerd / CRI-O | Image pull, lifecycle management | What Kubernetes actually talks to |
| Podman | Daemonless, rootless containers | Better default security posture |

### War Story

Docker began as an internal tool at dotCloud, a struggling PaaS, and was demoed by Solomon Hykes in a five-minute lightning talk at PyCon 2013. The kernel features were old news — Google had run everything in cgroups (which it contributed to Linux in 2007) for years, and LXC existed — but Docker's packaging insight (the image format + Dockerfile + registry) made the technology usable by everyone, and within two years it had reshaped the industry. Distribution, not virtualization, was the invention.

### Checkpoint

- A process inside a container runs `ps aux` and sees itself as PID 1. Which mechanism produces this, and what is its PID on the host?
- Your container was killed with exit code 137. Which kernel mechanism did that, and what limit did it enforce?
- Why do 50 containers sharing one image consume far less disk and page cache than 50 VM clones? Which filesystem trick is responsible?

## 03. Kubernetes Architecture (Control Plane, kubelet, etcd, Scheduler)

**MOTTO:** Kubernetes is a distributed while-loop: compare desired state to actual state, fix the difference, forever.

### The Problem

Containers on one machine are a solved problem. Now run 500 services across 200 nodes: place each container on a machine with room, restart it when it dies, replace it when its node dies, wire up networking so services find each other, and roll out new versions — continuously, without a human watching. That's a control problem, and Kubernetes is the industry's shared answer.

### The Concept

Kubernetes is a thermostat, not a remote control. You don't command "start container on node 7"; you declare "there shall be 3 replicas" and controllers work relentlessly to make reality match. Everything is this one pattern — the **reconciliation loop** — applied dozens of times.

```
CONTROL PLANE
┌──────────────────────────────────────────────────┐
│  API Server ◀──── the ONLY door to state         │
│      │                                            │
│    etcd  ◀─ desired + observed state (Raft)      │
│      ▲                                            │
│  Scheduler ─ assigns pending pods to nodes        │
│  Controller Manager ─ loops: Deployment,          │
│      ReplicaSet, Node, ... watch & reconcile      │
└──────┬───────────────────────────────────────────┘
       │ (kubelets watch the API server)
┌──────┴──────────┐   ┌─────────────────┐
│ NODE: kubelet   │   │ NODE: kubelet   │  kubelet: "pods assigned to
│  + container    │   │  + container    │   me should be running" —
│    runtime      │   │    runtime      │   another reconcile loop
│  + kube-proxy   │   │  + kube-proxy   │
└─────────────────┘   └─────────────────┘
```

Crucially, components never talk to each other directly — they all watch and write through the API server, with etcd as the single source of truth. That's why the control plane can restart without killing your workloads: the desired state persists; loops resume.

### Build It

Trace one `kubectl apply` of a 3-replica Deployment:

1. API server authenticates, authorizes, validates, writes the Deployment object to etcd. Nothing is running yet.
2. Deployment controller notices (via watch), creates a ReplicaSet; ReplicaSet controller creates 3 Pod objects with `nodeName` unset.
3. Scheduler watches for unbound pods, scores nodes (resource fit, affinity, spreading), and binds each pod by writing `nodeName`.
4. The kubelet on each chosen node sees a pod assigned to it, tells containerd to pull images and start containers, then reports status back.
5. A node dies → node controller marks it gone → its pods are marked failed → ReplicaSet controller sees 2 < 3 → creates a replacement → scheduler places it. Nobody orchestrated the recovery; five independent loops did.

etcd needs Raft quorum (run 3 or 5 members): lose quorum and the cluster becomes read-only-ish — running pods keep running, but nothing can change. Also note the scaling folklore is real: etcd is the bottleneck that cluster size limits are written around.

### Use It

| Offering | You manage | Tradeoff |
|---|---|---|
| EKS / GKE / AKS | Workloads only; control plane is theirs | Some version/feature lag, cost |
| kubeadm / k3s | Everything, incl. etcd backups | Full control, full pain |
| OpenShift / Rancher | Cluster fleet + policy | Heavier platform, opinionated |

### War Story

Kubernetes descends from Borg, the cluster manager Google had run internally since ~2003-2004; the 2015 Borg paper ("Large-scale cluster management at Google with Borg") disclosed the design, and Kubernetes (open-sourced 2014) was built by Borg veterans as a cleaned-up, label-driven, declarative rethink. The reconciliation-loop pattern and the "pods of co-scheduled containers" idea are Borg lessons, industrialized for everyone else.

### Checkpoint

- Why does killing the entire control plane not stop already-running application pods? What *does* stop working?
- Walk the chain of objects and controllers from `kubectl apply -f deployment.yaml` to containers running on a node.
- Why is etcd run with 3 or 5 members rather than 2 or 4, and what degrades when quorum is lost?

## 04. Kubernetes Patterns: Deployments to Operators

**MOTTO:** Kubernetes' real product isn't scheduling — it's a programmable pattern for turning ops knowledge into software.

### The Problem

Raw pods are cattle with no herder: they don't restart on node failure, don't roll out new versions, and can't hold state. Real workloads need patterns layered on top — and eventually you hit workloads (databases, message brokers) whose operational logic ("resize the cluster," "perform failover," "take a backup") no built-in object understands. The question becomes: how does Kubernetes let you teach it new tricks?

### The Concept

Think of Kubernetes primitives as verbs of increasing sophistication, all built from the same reconcile-loop grammar:

```
Pod          ─ run these containers together (atom, no self-healing)
ReplicaSet   ─ keep N identical pods alive
Deployment   ─ ReplicaSets + versioned rollouts/rollbacks   ← stateless apps
StatefulSet  ─ stable identity (pod-0, pod-1) + per-pod storage ← databases
DaemonSet    ─ one pod per node                              ← agents, log shippers
Job/CronJob  ─ run to completion / on schedule
Service      ─ stable virtual IP + load balancing over ephemeral pods
Ingress/GW   ─ HTTP routing from outside
ConfigMap/Secret ─ config injected, not baked into images
─────────────────────────────────────────────────────────────
Operator     ─ YOUR reconcile loop over YOUR custom resource:
               "kind: PostgresCluster, replicas: 3, backup: nightly"
```

An **Operator** is a human operator's runbook compiled into a controller: a Custom Resource Definition (the noun) plus a controller (the verb loop) that knows domain-specific operations Kubernetes doesn't.

### Build It

1. A Deployment rollout under the hood: create a new ReplicaSet at 0, then step new up / old down within `maxSurge`/`maxUnavailable`, gated by readiness probes. Rollback = re-scale the old ReplicaSet, which was kept at 0.
2. Get probes right — this is where most self-inflicted outages live: **liveness** = "restart me if this fails" (keep it dumb: process wedged?), **readiness** = "don't route traffic to me" (dependencies, warm-up). Putting a dependency check in a liveness probe means a flaky database restarts your entire fleet in a loop.
3. Writing an operator's reconcile function — same shape as every Kubernetes loop:

```python
def reconcile(desired: PostgresCluster):
    actual = observe(desired.name)             # pods, PVCs, primary/replica roles
    if actual.replicas < desired.replicas:
        create_replica(clone_from=actual.primary)
    if actual.primary is None:                  # failover: domain knowledge!
        promote(most_caught_up(actual.replicas))
    if backup_overdue(desired.backup_policy, actual.last_backup):
        run_backup(actual)
    # must be IDEMPOTENT: called repeatedly, converges, never assumes prior runs
```

4. Set resource `requests` (scheduler placement) and `limits` (cgroup caps) on everything; unbounded pods are how one memory leak evicts a node.

### Use It

| Pattern/Tool | Job | Watch out |
|---|---|---|
| Deployment + HPA | Stateless services with autoscaling | HPA on CPU alone lags bursty traffic |
| StatefulSet + operator (e.g. CloudNativePG, Strimzi) | Databases, Kafka on k8s | An operator's bugs act with cluster-admin speed |
| Helm / Kustomize | Templating & packaging manifests | Templated YAML sprawl is its own tax |

### War Story

The Operator pattern was coined by CoreOS in a 2016 blog post introducing the etcd operator — explicitly framed as "the ops runbook, encoded." It answered the era's raging debate ("never run stateful things on Kubernetes!") not by winning the argument but by automating away the objection; today mature operators run Postgres, Kafka, and Elasticsearch on k8s at serious scale, and OperatorHub lists hundreds of them.

### Checkpoint

- Why does a database need a StatefulSet rather than a Deployment? Name two concrete guarantees it adds.
- A liveness probe that checks database connectivity took down a whole service fleet during a DB blip. Explain the failure mechanics and the fix.
- What two artifacts make up an Operator, and why must its reconcile function be idempotent?

## 05. Serverless and FaaS (Cold Starts!)

**MOTTO:** Serverless means the server is someone else's problem — until the cold start makes it yours.

### The Problem

Even with Kubernetes you're still capacity-planning, patching nodes, and paying for idle. For spiky or low-volume workloads the math is ugly: a service handling 50 requests/day still occupies replicas 24/7. FaaS inverts the deal — upload a function, the platform runs an instance per burst of requests and bills you per invocation-millisecond, scaling to literal zero between calls. The catch is hiding in "scales to zero."

### The Concept

Provisioned servers are your own car idling in the driveway: instant departure, constant cost. FaaS is ride-hailing: pay per trip — but sometimes no driver is nearby and you wait. That wait is the **cold start**:

```
WARM (instance exists):   invoke ──▶ run handler            ~1-10ms overhead
COLD (scale from zero):   invoke ──▶ provision microVM      \
                                  ──▶ pull + load code       ├─ 100ms – several s
                                  ──▶ init runtime + deps    │  (worst: JVM + VPC
                                  ──▶ run global/init code  /    + huge bundle)
Platform then keeps the instance warm a while, hoping for reuse.
One instance handles ONE request at a time (classic Lambda model)
 → a burst of N concurrent requests can trigger N cold starts.
```

Cold starts don't hurt your *average* — they hurt your **tail**, and bursts synchronize them right when traffic (and attention) spikes.

### Build It

1. Write handlers to exploit the lifecycle: heavy things (DB clients, SDK init, config fetch) in global scope — paid once per instance, reused across warm invocations. Never per-request.
2. Cut cold-start cost mechanically: small bundles (tree-shake, no fat frameworks), fast-init runtimes (Rust/Go/Node beat cold JVMs by an order of magnitude), lazy-load rarely used deps.
3. Statelessness is compulsory: instances are born and killed freely, and in-memory state is a cache at best. Externalize to a store — and mind connection storms: 1,000 concurrent instances opening 1,000 DB connections melts Postgres. Use a proxy/pool (e.g. RDS Proxy) or HTTP-native data APIs.
4. For latency-critical paths, pay to pre-warm (provisioned concurrency) — which is quietly admitting you want a server again; price that honestly.
5. Design event-driven: queues, streams, and triggers between functions; keep per-function scope small and timeouts explicit.

### Use It

| Platform | Model | Cold-start posture |
|---|---|---|
| AWS Lambda | Function-per-event, Firecracker microVMs | ms–seconds; SnapStart (resume from snapshot) for JVM |
| Cloudflare Workers | V8 isolates, not VMs | ~ms cold starts; restricted runtime in exchange |
| Google Cloud Run | Serverless *containers*, concurrent reqs per instance | Fewer cold starts by design; min-instances option |

### War Story

AWS Lambda's 2014 launch created the category, but the definitive cold-start artifact is Firecracker (see Lesson 01): AWS rebuilt its virtualization layer largely to shrink the cold path to ~125ms of microVM boot. Cloudflare Workers then attacked the same problem from the other side — using V8 isolates instead of VMs so "cold start" nearly ceased to exist, at the cost of a restricted runtime. The whole sub-industry is one long negotiation with the cold start.

### Checkpoint

- Enumerate the stages of a cold start and rank which typically dominate for a large JVM function inside a VPC.
- Why do cold starts show up at p99 rather than p50, and why do traffic bursts make it worse in the one-request-per-instance model?
- Your Lambda fleet is exhausting Postgres connections at 1,000 concurrent executions. Explain the mechanics and two standard fixes.

## 06. Infrastructure as Code

**MOTTO:** If it isn't in version control, it doesn't exist — it's just a rumor about your infrastructure.

### The Problem

Click-built infrastructure rots: the staging and prod environments drift apart in undocumented ways, the one engineer who knows why that security group rule exists leaves, and disaster recovery means "rebuild from memory." Console changes have no diff, no review, no rollback, and no second copy. You'd never run application code this way; infrastructure stopped being an excuse the moment it became API calls.

### The Concept

IaC treats infrastructure like sheet music instead of a live improvisation: the score (declarative config) is the artifact — reviewable, versioned, replayable note-for-note in any concert hall (region/account). The engine that makes it work is **declarative reconciliation** — the same thermostat idea as Kubernetes:

```
   desired state          current state
  (your .tf/.yaml)   vs   (real cloud +
        │                  state file)
        └──────┬───────────────┘
               ▼
             DIFF  ──▶  PLAN: "+ create 2   ~ modify 1   - destroy 1"
               │              (a human or CI reviews THIS)
               ▼
             APPLY ──▶ ordered API calls following the dependency graph
```

You say *what* should exist; the tool computes *how* — including ordering (subnet before VM) from the resource dependency graph. The state file is the tool's memory of what it manages; lose or corrupt it and the tool is amnesiac about your world.

### Build It

1. Structure: modules for reusable components (a "service" = ALB + service + alarms), thin per-environment compositions passing different variables. Dev/prod parity becomes a variable file, not a hope.
2. Remote state with locking (e.g. S3 + lock) — two engineers applying concurrently against local state is how resources get orphaned or double-created.
3. Pipeline: PR → `plan` posted as a comment → human review of the *diff, not the code* → merge → `apply` from CI only. Nobody applies from a laptop; laptop applies are console-clicking with extra steps.
4. Treat **drift** (manual console changes behind the tool's back) as an incident: scheduled `plan` in CI to detect it; the fix is either codify or revert.
5. Never store secrets in state or code; reference a secrets manager (Phase 14, Lesson 06). State files famously contain more secrets than people expect — encrypt and access-control them like credentials.
6. `destroy` is one command away from résumé-generating. Protect stateful resources (`prevent_destroy`, deletion protection) and separate blast domains into separate state files.

### Use It

| Tool | Model | Tradeoff |
|---|---|---|
| Terraform / OpenTofu | Declarative HCL, multi-cloud, explicit state | State management is your problem |
| Pulumi / CDK | Real languages compiled to declarations | Power + the temptation to be too clever |
| CloudFormation | AWS-native, managed state | AWS-only, slower feedback loops |
| Ansible | Procedural config management | Better for machine config than cloud topology |

### War Story

Terraform (HashiCorp, 2014) won the multi-cloud era, then in 2023 HashiCorp switched it from open source to the BSL license — and the community forked it as **OpenTofu** under the Linux Foundation within weeks. Beyond the licensing drama, the episode proved how load-bearing IaC had become: companies discovered their entire infrastructure's definition had a software supply chain, with all the governance questions that implies.

### Checkpoint

- What is the state file for, and what failure modes appear when it's lost, stale, or edited concurrently?
- Why should humans review the `plan` output rather than (only) the config diff? Give a case where the config change looks tiny but the plan is scary.
- Someone "quickly fixed" a security group in the console during an incident. What happens on the next apply, and what's the disciplined follow-up?

## 07. CI/CD Pipelines

**MOTTO:** The pipeline is the only path to production — every shortcut around it is a future incident with a timestamp TBD.

### The Problem

Manual releases concentrate risk: giant infrequent deploys, a wiki page of steps executed slightly differently each time, and one person who "does releases." Integration pain compounds too — branches diverging for weeks merge like continental plates. The fix is old wisdom: if it hurts, do it more often, and make a machine do it. Continuous integration merges and verifies constantly; continuous delivery keeps every green build shippable.

### The Concept

A pipeline is a factory line with quality gates: raw commit in one end, verified deployable artifact out the other, with the line stopping the instant any station rejects the work.

```
commit ─▶ build ─▶ unit ─▶ package ─▶ integration ─▶ deploy ─▶ deploy
          &lint    tests    ARTIFACT    tests (svcs    staging   prod
                            (image,     in containers)  + smoke  (gated or
                            digest-      │              tests     automatic)
                            pinned)      ▼
  ◀──── fail fast: cheapest checks first, minutes not hours ────
```

Two iron rules. **Build once, promote everywhere**: the *same* immutable artifact (image digest) moves through every stage — rebuilding for prod means testing one thing and shipping another. And **the artifact's journey is the audit trail**: what's in prod is answerable by digest, not by folklore.

### Build It

1. Order stages by cost: lint and unit tests (seconds–minutes) before integration tests (minutes) before deploys. A 40-minute wait for feedback trains people to batch changes, which raises risk — the opposite of the goal.
2. Keep main releasable: small PRs, trunk-based or short-lived branches, and **feature flags** to decouple *deploy* (moving code) from *release* (exposing behavior). Half-done features ship dark.
3. Make everything reproducible and hermetic: pinned dependencies, containerized build steps, no snowflake build agents.
4. Gate deploys on automated verification (smoke tests, error-rate checks post-deploy), not just test suites — next lesson makes this progressive.
5. Secure the pipeline as production infrastructure, because it *is*: it holds deploy credentials for everything. Short-lived OIDC-federated cloud credentials instead of static secrets in CI config; least-privilege per pipeline; sign artifacts and verify provenance at deploy time.
6. Measure yourself with the DORA four: deploy frequency, lead time, change-failure rate, time-to-restore.

### Use It

| Tool | Style | Tradeoff |
|---|---|---|
| GitHub Actions / GitLab CI | YAML workflows in-repo | Ubiquitous; YAML sprawl at scale |
| Jenkins | Self-hosted, infinitely pluggable | You become a Jenkins administrator |
| Argo CD / Flux | GitOps CD — cluster pulls desired state from git | Reconciliation model; another controller to run |

### War Story

The 2020 SolarWinds compromise weaponized a build pipeline: attackers implanted malware *inside the build system* so that officially signed Orion updates shipped a backdoor to ~18,000 customers, including US government agencies. Nothing in the source repo was wrong — the pipeline itself was the vulnerability. It reframed CI/CD security from afterthought to supply-chain frontline (SLSA, artifact signing, provenance attestation all trace lineage to it).

### Checkpoint

- Why must the exact artifact tested be the artifact deployed? Describe a failure that rebuild-per-stage permits.
- How do feature flags separate "deploy" from "release," and what new hygiene problem do they introduce?
- Your CI holds static admin cloud keys. Rank the blast radius and name the modern replacement pattern.

## 08. Blue-Green and Canary Deployments

**MOTTO:** Never send new code to 100% of users when 1% will tell you everything you need to know.

### The Problem

Even a perfectly tested build meets production — real traffic, real data, real dependency weirdness — for the first time at deploy. In-place deploys make that first contact a cliff: everything cuts over at once, and "rollback" means a panicked redeploy of the old version measured in tens of minutes of full-blast impact. Deployment strategy is blast-radius engineering: how few users see a bad build, for how short a time?

### The Concept

- **Blue-green** is a theater with two identical stages: the audience watches Blue while you fully set up Green, then you rotate the whole seating section at once — and can rotate right back.
- **Canary** is named for the coal-mine bird: expose a small slice of real traffic to the new version, watch vital signs, widen only while healthy.

```
BLUE-GREEN                             CANARY
 LB ──100%──▶ Blue v1                   LB ──95%──▶ v1
      0%───▶ Green v2 (idle,               └─5%──▶ v2  ← compare error rate,
              smoke-tested)                            p99, business metrics
 flip: 0/100 → instant, all-or-        healthy? → 25% → 50% → 100%
 nothing; rollback = flip back         unhealthy? → auto-rollback to 0%
 cost: 2× fleet during deploy          gradual, metric-gated, cheaper
```

### Build It

1. Prerequisite for both — **N and N+1 must coexist**: backward-compatible APIs and, critically, databases. Use expand/migrate/contract: add the new column (both versions fine) → ship code using it → remove the old one releases later. Never a breaking migration in the same deploy as the code that needs it.
2. Canary analysis must be automated and pre-declared:

```python
def canary_gate(canary, baseline):     # baseline = SAME-SIZE slice of v1,
    for m in [error_rate, p99_latency, # not the whole fleet — else statistics lie
              checkout_conversion]:     # business metrics catch what 200s hide
        if degraded(m(canary), m(baseline), significance=0.95):
            return ROLLBACK
    return PROMOTE
```

3. Route the slice deliberately: internal users → 1% random → sticky-by-user percentage ramp (a user flapping between versions mid-session is its own bug).
4. Watch for the canary's blind spots: slow-burn issues (memory leaks, cache poisoning) outlive the analysis window — keep watching after 100%; and low-traffic slices need longer bakes to reach statistical significance.
5. Blue-green's sharp edge is state: long-lived connections, in-flight jobs, and queues must drain from Blue before you recycle it.

### Use It

| Tool | Strategy | Note |
|---|---|---|
| Argo Rollouts / Flagger | Automated canary + analysis on k8s | Metric queries define the gate — write them well |
| AWS CodeDeploy | Blue-green & canary for EC2/ECS/Lambda | Linear/canary traffic shifting built in |
| LaunchDarkly-style flags | Percentage rollout at app layer | Finest targeting; not an infra rollback |

### War Story

Knight Capital, August 1, 2012: a manual deploy to 8 servers left old code on the 8th, and a reused feature flag activated a dormant test routine on it — the mismatched fleet fired ~4 million errant orders into the market in 45 minutes, losing about $440 million and ending the company. It is *the* canonical argument for automated, verified, all-or-nothing-consistent deployments: the disaster wasn't the bug, it was the partial rollout nobody could see.

### Checkpoint

- Why must database migrations be backward-compatible for either strategy to work? Sketch expand/migrate/contract for renaming a column.
- Why compare the canary against a same-sized baseline slice rather than against the whole remaining fleet?
- Name two failure classes a 30-minute canary at 5% traffic will systematically miss, and the mitigation for each.

## 09. Multi-Region Architectures (Active-Passive, Active-Active)

**MOTTO:** A region is a blast radius; multi-region is deciding what you'll pay so one blast isn't everything.

### The Problem

Cloud regions fail — rarely whole, but often enough in part (a control-plane outage, a networking event) to take dependent services down for hours. If your business can't tolerate that, you need presence in a second region. Immediately you meet the two costs: latency physics (~70-80ms round trip across the continental US; you cannot patch the speed of light) and the CAP-flavored question of what your data does when regions can't agree.

### The Concept

Two restaurant strategies. **Active-passive**: one open restaurant plus a fully equipped dark kitchen — staffed, stocked (replicated), lights off — that opens only if the main one burns. **Active-active**: two open restaurants sharing one reservations book, which forces the hard question: what happens when both accept the last table at the same instant?

```
ACTIVE-PASSIVE                       ACTIVE-ACTIVE
 users ─▶ Region A (all traffic)      users ─▶ nearest region (geo-DNS/anycast)
             │ async replication       Region A ◀═ bidirectional ═▶ Region B
             ▼                                    replication
          Region B (warm standby)      + lower latency, no failover event
 failover: promote B, shift DNS        − write conflicts OR cross-region
 RTO: minutes+  RPO: replication lag     write latency: choose your poison
```

Vocabulary that anchors every DR conversation: **RPO** (how much data you may lose — replication lag) and **RTO** (how long until you're serving — failover time). Multi-region is buying those numbers down with money and complexity.

### Build It

1. Active-passive mechanics: async-replicate data to the standby; health-check-driven promotion; traffic shift via DNS/anycast. The catch nobody tests: failover promotes a replica that is *behind* — you must decide in advance whether to lose those writes or wait.
2. **Drill failovers regularly.** An untested standby is a rumor: config drift, missing capacity, expired credentials, and IAM surprises all hide until the real event. Schedule game days.
3. Active-active data — pick one per dataset:
   - **Partition writes by home region** (EU users' data lives in EU): no conflicts, and each user's failover is really active-passive. The workhorse pattern.
   - **CRDTs / last-writer-wins**: accept concurrent writes, merge deterministically; fine for carts and counters, unacceptable for money.
   - **Consensus across regions** (Spanner-style): real consistency, and every write pays cross-region latency. Reserve for the data that truly needs it.
4. Anti-pattern to hunt down: hidden single-region dependencies — the "global" auth service, config store, or scheduler quietly pinned to one region turns your multi-region design into theater.
5. Mind the bill: cross-region data transfer is one of the most underestimated line items in cloud budgets.

### Use It

| Tool | Role | Note |
|---|---|---|
| Route 53 / Traffic Manager | Health-checked geo/failover routing | DNS TTLs bound your real RTO |
| Aurora Global Database / Cloud Spanner | Managed cross-region data | Spanner: consistency for write latency |
| DynamoDB Global Tables | Multi-master, last-writer-wins | You must be ok with LWW semantics |

### War Story

The February 28, 2017 S3 outage in us-east-1 began with a routine debugging command that took out more subsystem capacity than intended; S3 was down for ~4 hours and dragged much of the internet with it — including, famously, the AWS status dashboard's own health icons, which were hosted on S3. The December 7, 2021 us-east-1 outage repeated the theme at the network layer. Both are the standing argument for regional independence — and for keeping your incident tooling out of your own blast radius.

### Checkpoint

- Define RPO and RTO, and identify which one asynchronous replication lag directly determines.
- Why does "partition writes by home region" sidestep the conflict problem, and what request pattern still pays cross-region latency?
- Your standby region hasn't served production traffic in 14 months. List four distinct ways the failover plausibly fails.

## 10. Cell-Based Architecture

**MOTTO:** Don't build one big ship with watertight doors — build a fleet, and let a ship sink.

### The Problem

Horizontal scaling as usually practiced shares fate: all 500 instances behind one load balancer, one connection-pool config, one deployment wave. A poison-pill request, a bad config push, or a cascading overload doesn't take down one instance — it sweeps the whole fleet, because the fleet is one failure domain wearing a thousand hats. Blast radius grows with scale unless you deliberately partition it.

### The Concept

A cell is a complete, self-contained copy of your service stack — app tier, cache, database, queues — serving a fixed slice of customers, with **no runtime dependencies on other cells**. The system becomes a fleet of small ships instead of one Titanic with internal doors:

```
            THIN ROUTING LAYER (dumbest possible: customer → cell map)
                 │              │              │
        ┌────────┴───┐  ┌───────┴────┐  ┌──────┴─────┐
        │  CELL 1    │  │  CELL 2    │  │  CELL 3    │
        │ app+cache+ │  │ app+cache+ │  │ app+cache+ │
        │ db+queues  │  │ db+queues  │  │ db+queues  │
        │ cust A-H   │  │ cust I-P   │  │ cust Q-Z   │
        └────────────┘  └────────────┘  └────────────┘
Cell 2 dies → only customers I-P affected. Poison request lands
in ONE cell. Scale = add cells, not grow cells. Deploy = one
cell at a time (a cell is the ultimate canary unit).
```

It's sharding elevated from the database to the *entire stack*, chosen explicitly for blast-radius control: with N cells, the worst single-cell event hurts ~1/N of customers.

### Build It

1. Pick the partition key — almost always customer/tenant ID, because a tenant's whole experience should live (and fail) in one place.
2. Make the router boring and bulletproof: a static-ish `tenant → cell` lookup, aggressively cached, with no business logic. The router is the one shared component, so its simplicity *is* your availability story.
3. Cap cell size deliberately. A full cell is your tested, known-good scale unit — you know exactly how it behaves at capacity, because every cell is a copy. Growth = stamp out another cell from the same IaC template (Lesson 06 pays off here).
4. Handle the hard parts honestly:
   - **Migration**: moving a tenant between cells (growth, rebalancing) needs a real data-move procedure — build it early, it's the hardest part.
   - **Whales**: a tenant bigger than a cell breaks the model; give whales dedicated cells.
   - **Cross-cell features** (global search, analytics): route around, aggregate asynchronously, or accept the seam. Never let cells call each other synchronously — that quietly rebuilds the shared-fate monolith.
5. Deploy cell-by-cell, always. Config changes too — config is code with a faster trigger.

### Use It

| Adopter/Tool | Form | Note |
|---|---|---|
| AWS internally | Cells + shuffle sharding across many services | Documented in the Amazon Builders' Library |
| Slack, DoorDash (public eng posts) | Cellular production architectures | Motivated by gray failures & AZ isolation |
| Shuffle sharding | Each customer → random small subset of nodes | Poison-pill blast radius shrinks combinatorially |

### War Story

AWS is the loudest proponent: the Amazon Builders' Library and re:Invent talks describe cell-based design and **shuffle sharding** as core to services like Route 53 — where each customer domain is served by a small pseudo-random subset of name-server capacity, so a DDoS against one customer's domain leaves nearly all other customers' subsets untouched. The punchline is combinatorial: with modest node counts, the odds that two customers share their entire shard drop to nearly zero.

### Checkpoint

- How does cell-based architecture differ from ordinary horizontal scaling behind one load balancer, in terms of failure domains?
- Why must the routing layer be as thin and logic-free as possible?
- Name the three classic hard problems of cellular designs (think: moving, oversized, and cross-cutting) and one mitigation for each.

## 11. Edge Computing

**MOTTO:** You can't negotiate with the speed of light, but you can move the conversation closer.

### The Problem

Light in fiber crosses the Atlantic and back in ~65ms minimum — before a single byte of your application logic runs. A user in Singapore hitting your Virginia origin eats 200ms+ of pure physics per round trip, multiplied by TLS handshakes and API calls. Some workloads (interactive apps, personalization, auth checks, IoT) can't tolerate it, and no amount of server tuning helps: the problem is *where*, not *how fast*.

### The Concept

Classic CDNs put warehouses near customers (cached static goods). Edge computing puts *workshops* near customers: hundreds of small points of presence that can execute your logic, not just serve your files.

```
user ── 5-20ms ──▶ EDGE PoP (100s worldwide)          ── 50-200ms ──▶ ORIGIN
                   │ static cache (classic CDN)                        │ core DB
                   │ + compute: auth/JWT verify, redirects,            │ heavy logic
                   │   A/B assignment, personalization,                │ source of
                   │   full request handling                           │ truth
                   │ + edge KV/queues (eventually consistent)
                   └── goal: answer here; go to origin only when you must
```

The mental model: the edge is a *distributed reflex layer* — fast, local, slightly stale — in front of a centralized brain. The engineering discipline is deciding which decisions tolerate staleness (auth token verification: yes, it's signature math; account balance: no).

### Build It

1. Sort every request path into: static (cache at edge), computable-at-edge (needs only the request + replicated read-mostly data), origin-required (needs strongly consistent core state).
2. Edge runtimes are constrained on purpose — V8 isolates or WASM with millisecond cold starts, small memory, short CPU budgets (Lesson 05's cold-start lesson, solved by shrinking the unit). Design edge logic as small, pure, stateless functions.
3. State at the edge is the hard part. Use it honestly:
   - **Replicated read-mostly KV** (feature flags, geo rules, session-validation keys): fine, embrace eventual consistency measured in seconds.
   - **Writes**: queue at the edge, apply at origin — or use per-object placement (e.g. Durable-Object-style "this chat room lives in one location") to regain consistency by *pinning*, not replicating.
4. Standard wins to implement first, in order of ROI: TLS termination at edge (saves handshake round trips), cached API responses with short TTLs + stale-while-revalidate, JWT verification at edge (reject bad traffic before it crosses an ocean), geo-routing and redirects.
5. Observability caveat: your logic now runs in 300 places — centralized log/metric aggregation from the edge is non-optional.

### Use It

| Platform | Model | Tradeoff |
|---|---|---|
| Cloudflare Workers (+KV, Durable Objects) | V8 isolates at every PoP | Restricted runtime; DO pins state to one place |
| AWS Lambda@Edge / CloudFront Functions | Functions at CloudFront PoPs | Two tiers with different limits; slower deploys |
| Fastly Compute | WASM at edge | Language-flexible; smaller ecosystem |

### War Story

The June 8, 2021 Fastly outage is the edge's cautionary tale: a latent bug in an edge configuration system, triggered by one customer's valid config change, took down roughly 85% of Fastly's network in seconds — vanishing Reddit, Amazon, gov.uk, and major news sites globally for about an hour. Moving compute to 300 PoPs also means a bad config propagates to 300 PoPs at line speed; the edge inherits every lesson from Lessons 08 and 10 about staged rollout and blast radius.

### Checkpoint

- Why is JWT signature verification a perfect edge workload while "check the user's current account balance" is not?
- What consistency model does replicated edge KV give you, and name two data types that fit it comfortably?
- Your edge provider deploys config globally in seconds. Which deployment discipline from earlier lessons does this violate, and what would you demand from the provider?

## 12. Cloud Cost Optimization

**MOTTO:** The cloud bill is an architecture diagram with dollar signs — every line item is a design decision you made.

### The Problem

The cloud's superpower — anyone can provision anything instantly — is also the failure mode: spend is decentralized, invisible at decision time, and billed 30 days later in a 40,000-line CSV. Idle dev clusters at 3am, unattached volumes, over-provisioned instances "to be safe," and cross-AZ chatter quietly compound into bills that grow faster than traffic. Cost is a first-class non-functional requirement, exactly like latency — and like latency, it's mostly determined at design time.

### The Concept

Think of cloud pricing as an electricity market with three tariffs, plus a toll system nobody reads:

```
On-demand   ─ full price, walk away anytime        (default = most expensive)
Committed   ─ 1-3yr reserved/savings plans: ~30-60% off for baseline load
Spot        ─ ~60-90% off surplus capacity that can vanish with 2min notice

           capacity
              ▲        ......... provisioned (you pay this)
              │   ▄▄▄▄▄▄
              │▄▄█ actual load █▄▄▄
              └────────────────────▶ time
              the gap IS the waste — cost opt = shrinking the gap
              (rightsizing, autoscaling, scale-to-zero)

+ the toll roads: egress to internet ($$), cross-region ($$),
  cross-AZ ($) — data transfer is the line item that ambushes everyone
```

Strategy: cover the predictable base with commitments, ride autoscaling on-demand for the swell, throw interruptible work at spot, and architect data flows like the tolls are real — because they are.

### Build It

1. **See it first**: enforce tagging/labels (team, service, env) via IaC policy so every dollar has an owner; blocked-untagged is the only tagging policy that works. Show teams their own dashboards — visibility alone changes behavior.
2. **Rightsize with data**: compare provisioned vs. actual P95 utilization over weeks; shrink the chronic over-provisioners. In Kubernetes, this is the requests-vs-usage gap — most clusters run under 30% utilization, i.e., most of the bill is reservation, not work.
3. **Eliminate idle**: scale-to-zero for dev/staging off-hours (a 12×5 dev environment costs ~35% of a 24×7 one), TTLs and cleanup jobs for orphaned volumes, snapshots, and IPs.
4. **Buy correctly**: commitments sized to the *observed floor* (never the peak); spot for stateless, checkpointable, retry-tolerant work (CI, batch, big data) with graceful-interruption handling.
5. **Architect the big levers**: storage lifecycle tiering (hot → infrequent → archive); cache and compress before data crosses AZ/region/internet boundaries; question every cross-region chatty dependency (Lesson 09's bill arrives here).
6. **Institutionalize**: unit economics (cost per request / per tenant / per GB) on the same dashboards as latency; cost review in design docs; anomaly alerts on spend like you alert on error rates. That's FinOps, minus the buzzword.

### Use It

| Tool | Job | Note |
|---|---|---|
| AWS Cost Explorer / CUR + Athena | Visibility, allocation | Raw truth; needs tagging discipline to be useful |
| Karpenter / cluster autoscaler | Bin-pack k8s nodes, ride spot | Biggest single k8s cost lever |
| Infracost | Cost diff on IaC pull requests | Moves the cost conversation to design time |
| OpenCost / Kubecost | Per-namespace/pod cost allocation | Makes k8s spend attributable |

### War Story

Dropbox ran one of the most famous repatriations: between 2015-2016 it moved user file storage off S3 onto its own custom hardware ("Magic Pocket"), and its IPO filing disclosed ~$75M in infrastructure cost savings over the following two years — workable because storage was its core competency and utterly predictable at exabyte scale. Counterpoint in the same breath: 37signals publicized its 2022-2024 cloud exit claiming multi-million-dollar annual savings for its steady-state workloads. The shared lesson isn't "leave the cloud" — it's that elasticity is what you're paying premium for, and paying it for perfectly flat, predictable load is renting a ballroom to store furniture.

### Checkpoint

- Why is the gap between provisioned and actual utilization the central object of cost optimization, and name three distinct mechanisms that shrink it.
- Which workload properties make something spot-safe? Give one workload that is and one that never will be.
- Your bill shows massive inter-AZ transfer charges from a chatty microservice pair. What are your architectural options, and what does each trade away?
