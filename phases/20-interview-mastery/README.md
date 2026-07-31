# Phase 20 — 🎤 Interview Mastery

> 45 minutes, one whiteboard, zero panic.

You now know more system design than most working engineers. Irrelevant — the interview doesn't measure what you know, it measures what you can *demonstrate* in 45 minutes under mild social stress. That's a performance skill, and like all performance skills it's trainable: structure, phrases, timing, recovery moves. This phase turns Phase 17's knowledge into something an interviewer can actually see.

## 01. The 4-Step Interview Framework (Requirements → Estimation → High-Level → Deep-Dive)

Every strong system design interview has the same skeleton, and interviewers are literally grading against it. Memorize the time budget for a 45-minute slot:

1. **Requirements (5–8 min).** Turn "design Twitter" into a scoped, agreed problem. Functional (what it does) and non-functional (how well). End with a spoken summary: *"So we're building the home timeline and posting, for 200M DAU, read-heavy, eventual consistency is fine — search and DMs are out of scope. Agreed?"* That last word matters — get the nod before touching the marker.
2. **Estimation (3–5 min).** QPS, storage, bandwidth — just enough to know what kind of system this is. *"5,800 tweets/sec but 46K timeline reads/sec — so this design lives or dies on the read path."* Estimation isn't a ritual; it's how you justify every later decision.
3. **High-level design (10–15 min).** Boxes and arrows covering every functional requirement, end to end. Resist the urge to perfect any one box. Narrate as you draw: *"Client hits the LB, API tier is stateless, writes land in the post service..."* By the end, the happy path works on paper.
4. **Deep dives (15–20 min).** Pick the 2–3 hardest problems *for this system* and go deep — fan-out for Twitter, seat locking for Ticketmaster, ordering for chat. Say the transition out loud: *"The design works at a high level; the hardest part is X. Let me dig into that."* Senior candidates drive this phase; junior candidates wait to be dragged into it.

The most common failure isn't lack of knowledge — it's spending 25 minutes on steps 1–2, or diving into ID generation before there's an end-to-end picture. The framework is a clock. Respect the clock.

Two more habits that hold the skeleton together: **checkpoint aloud** between steps ("before I move on — anything you want me to adjust?"), and **write decisions down** in a corner of the board (a running list like "eventual consistency ok / 5-yr retention / hybrid fanout") so neither of you re-litigates settled ground.

### Checkpoint
1. Without notes, recite the four steps with their time budgets for a 45-minute interview.
2. Take "Design Dropbox" and write only the *transition sentences* you'd say between the four steps.
3. You realize at minute 30 that you're still on high-level design. What exactly do you say and cut?

## 02. Requirements Clarification: Questions That Impress

Weak candidates ask questions to stall. Strong candidates ask questions that visibly *shrink the problem* and *reveal judgment*. The difference is that every good question carries an implied design consequence.

Ask about scale, because scale picks the architecture: *"Are we building for a startup's 10K users or 100M DAU? — because those are different designs, and I'd rather build the one you want."* Ask about the read/write ratio: *"Is this read-heavy like a feed or write-heavy like a metrics pipeline?"* Ask what's allowed to break: *"When the network partitions, would you rather show stale data or an error?"* — that single question scopes your consistency story for the whole interview.

Then scope ruthlessly, out loud, as offers the interviewer can veto: *"I'll treat auth, and abuse prevention as solved and focus on the core flow — okay?"* Interviewers almost always accept, and you've just bought 10 minutes. The questions that impress most are the ones that show you've operated systems: *"Do we need to handle the celebrity case — a user with 100M followers — or is the follow graph capped?"* Nobody asks that without knowing why it matters.

A concrete drill list — for any prompt, you should be able to generate these five in under a minute:
- **Users & scale:** DAU? Growth? Geographic spread (one region or global)?
- **Core flows:** "Of everything X does, which 2–3 flows do you want designed?"
- **Read/write shape:** ratio, burstiness, payload sizes.
- **Guarantees:** consistency needs, durability needs, latency targets ("is 200 ms fine or is this a game?").
- **Non-goals:** "What are you explicitly *not* asking me to design?"

And write the answers on the board as you get them. A visible, agreed requirements list is armor: when you make a tradeoff at minute 35, you point at it.

### Checkpoint
1. For "Design a parking garage system," write 8 clarifying questions, and for each, the design decision it unlocks.
2. Practice the scoping offer: write three "I'll assume X is out of scope — okay?" sentences for "Design Netflix."
3. Which single question would most change your design of a rate limiter? Defend it.

## 03. Capacity Estimation Drills (With Worked Answers)

Napkin math has one job: telling you what kind of system you're building. Interviewers don't care about your arithmetic; they care that your numbers *drive decisions*. The core toolkit: **86,400 sec/day (round to 100K for mental math)**, ~2.6M sec/month, powers of two for storage (1 GB ≈ 10⁹ B), and the habit of stating every assumption before using it. Round aggressively — 11,574 is 12K, and saying "roughly" is professional, not sloppy.

Say your setup out loud before computing: *"Let me assume 100M DAU and 10 events per user per day — tell me if you'd like different numbers."* This turns estimation into a collaboration and protects you if the assumption is off.

**Drill 1 — QPS for a photo app.** 200M DAU, each views 50 photos and uploads 0.5/day. Views: 200M × 50 = 10B/day ÷ 100K sec ≈ **100K QPS** average; peak ≈ 2–3× → ~250K. Uploads: 200M × 0.5 = 100M/day ≈ **1K QPS**. Conclusion to say: "100:1 read-heavy — CDN and caching dominate this design."

**Drill 2 — storage for a messaging app.** 500M users × 40 messages/day × 100 bytes = 500M × 40 = 20B messages/day × 100 B = **2 TB/day** → ~730 TB/year → ~3.7 PB over 5 years. Conclusion: "Text is cheap — one order of magnitude below media; if we add photos at 5% of messages × 200 KB, that's 20B × 0.05 × 200 KB = **200 TB/day**, which is 100× the text. Media dominates; design the blob path first."

**Drill 3 — memory for a cache.** We want to cache 20% of a 10B-object catalog, objects ~2 KB. 10B × 0.2 = 2B objects × 2 KB = **4 TB**. At 64 GB usable per cache node → 4 TB / 64 GB ≈ **63 nodes**, call it 80 with replication headroom. Conclusion: "Feasible but a real cluster — worth checking whether the 80/20 rule means 2% of objects would capture most hits and 8 nodes suffice." (That last sentence — interrogating your own estimate — is the senior move.)

The pattern in all three: assumption → arithmetic → **"therefore."** An estimate without a "therefore" is decoration. End every estimation block by naming the bottleneck: reads, writes, storage, or fan-out.

### Checkpoint
1. Estimate QPS, storage/day, and 5-year storage for a Strava-like fitness app (state your assumptions first, then compute, then say the "therefore").
2. Your interviewer says "assume 10× the users you just used." Redo Drill 3's cache sizing in under 60 seconds.
3. Estimate the bandwidth of a service serving 50M podcast streams/day at 128 kbps × 40 min average. Which number in your answer would change the design most if it doubled?

## 04. High-Level Design, Then Deep Dives

The high-level phase has one deliverable: a diagram where **every functional requirement has a traceable path through the boxes**. Draw client → entry point (LB/gateway) → stateless services → data stores, then walk each requirement through it aloud: *"Requirement one, post a photo: client → API → upload service → object store, metadata → posts DB. Requirement two, view feed: ..."* That walk is your proof of completeness, and interviewers audibly relax when they hear it.

Keep the first pass deliberately boring. Boxes named for responsibilities ("media service", not "Kafka"), arrows labeled with what flows, and technology choices deferred with a phrase: *"I'll put a queue here — whether it's Kafka or SQS is a decision I'll come back to if it matters."* Premature vendor-picking burns time and invites tangents. Also: don't erase — annotate. A messy board that evolved beats a clean board you spent minutes redrawing.

Then comes the pivot most candidates fumble. Don't wait to be told. Look at your own diagram and name the danger: *"This works until someone with 50M followers posts — the fan-out box is the hard part. I'd like to deep-dive there."* Choosing the *right* deep dive is itself the skill being graded: it should be (a) genuinely hard, (b) specific to this system, and (c) something your estimation flagged. Fan-out for feeds, locking for inventory, ordering for chat, dedup + idempotency for payments, hot partitions for anything sharded.

In a deep dive, run a tight loop: state the problem crisply → give 2–3 candidate approaches → compare against *this system's* requirements → commit. *"For feed delivery: push, pull, or hybrid. Push breaks on celebrities, pull breaks on read latency; our 200 ms read budget plus the celebrity case says hybrid with a follower threshold. Committing to that."* Two deep dives done this way beat five done shallowly. If the interviewer redirects you to a different component — follow immediately and cheerfully; their redirect *is* the rubric.

### Checkpoint
1. Draw a high-level design for a URL shortener in under 5 minutes, then perform the requirement-walk out loud, timed.
2. For each of: Ticketmaster, WhatsApp, an ad aggregator — name the single deep dive you'd volunteer, and the sentence you'd use to pivot into it.
3. Practice the commit: pick push vs. pull vs. hybrid for a news feed in ≤ 4 spoken sentences, ending with "committing to that."

## 05. The Tradeoff Vocabulary

Interviewers grade tradeoff reasoning above almost everything, and it has a grammar: **claim, cost, justification by requirement.** The template — *"I'd choose X over Y because we need A, and I'm accepting cost B, which is fine here because C."* Never present a choice as free; a stated cost is what separates judgment from recitation.

The phrasebook. Steal these whole:
- **Consistency vs. availability:** "This is a CP-vs-AP question. For the seat inventory I need CP — an oversold seat is worse than a 500 error. For the seat *map view*, AP — stale-by-2-seconds costs nothing because the hold step re-validates."
- **Latency vs. throughput:** "Batching writes raises throughput but adds up to 50 ms of latency; on the analytics path nobody's waiting, so batch. On the checkout path, never."
- **Latency vs. consistency:** "Replicating synchronously to a second region costs ~60 ms per write. Users won't pay that for a like; they will for a bank transfer."
- **Precompute vs. compute-on-read:** "Fan-out-on-write buys 10 ms reads at the price of write amplification — right for feeds because reads outnumber writes 50 to 1."
- **Simplicity vs. scalability:** "One Postgres handles this for the first 10M users, and I'd genuinely start there — the sharded design is what I'd migrate to, and here's the seam I'd leave for it."
- **Accuracy vs. cost:** "HyperLogLog gives unique counts within ~2% in 12 KB per key; exact sets would cost gigabytes. Dashboards get HLL; billing gets exact."
- **Buy vs. build:** "I'd take managed Kafka — our differentiation isn't in operating brokers."

Two power moves. First, **quantify the tradeoff when you can**: "strong consistency here costs one cross-region round trip, ~60 ms" lands harder than "it's slower." Second, **volunteer the losing option's best case**: "pull-based feeds would win if follow counts were tiny and posts rare — that's not our workload." Showing you know *when the other answer wins* is the strongest signal in the whole interview. And when the interviewer challenges a choice, the response is never defense — it's *"good push — under that constraint I'd flip to Y, because..."* Updating on new information is a feature, not a retreat.

### Checkpoint
1. Write out the full template sentence for three real decisions in your Phase 17 URL-shortener design (status code, key generation, storage).
2. For each phrasebook pair above, name one system where the *opposite* side wins, in one sentence each.
3. Drill: have a friend challenge any three of your choices; respond to each in ≤ 3 sentences without being defensive, ending with a concrete condition under which you'd switch.

## 06. Communication and Whiteboard Craft

An interviewer can't grade what they can't follow. Half of "strong technical communication" is mechanical, and mechanics are learnable in a week.

**Narrate everything.** Silence while drawing reads as confusion, even when it's deep thought. The fix is a habit phrase: *"I'm drawing the write path first; talking while I go."* If you genuinely need quiet, buy it explicitly: *"Give me 30 seconds to think about the sharding key"* — announced silence is confidence; unannounced silence is dead air.

**Own the board like a document.** Requirements list top-left, and it never gets erased — it's your contract. Estimation numbers in a corner. Main diagram center, flowing left-to-right (client → edge → services → data), so "downstream" literally means rightward. Deep dives get their own region or a fresh area — don't scribble the fan-out detail on top of your clean architecture. Label arrows ("post_id", "2 MB image", "async") — an unlabeled arrow is a question the interviewer now has to ask. Number your components as you draw so speech can be precise: "the race is between 3 and 5."

**Manage the dialogue.** Checkpoint at every phase boundary: *"Before I go deeper — is this the area you want, or would you rather I look at storage?"* This is steering, not permission-seeking, and it means you never spend 10 minutes in a room the interviewer left. When you get a hint, take it *visibly*: "Ah — right, that breaks under partition. Let me fix that" beats plowing on to save face; interviewers report "coachability" directly. When you don't know something, trade honesty plus reasoning: *"I haven't operated Cassandra; I'd reason from what I know about LSM stores and quorum reads — here's how I'd verify."* That answer scores; bluffing about compaction settings does not.

**Time-keeping is a communication act.** Say the time out loud: *"We're at 25 minutes — I want to make sure we deep-dive the matcher, so I'll wrap the high level here."* Candidates who narrate the clock almost never lose to it. Virtual interviews: same rules, plus — practice your drawing tool *before* the interview, keep components small so the diagram fits one screen, and share early so they watch it grow rather than receiving a finished mystery.

### Checkpoint
1. Record yourself designing Pastebin for 10 minutes. Count the narration gaps > 15 seconds and the unlabeled arrows. Redo it.
2. Write your personal phase-transition and checkpoint phrases — five sentences — and drill them until they're automatic.
3. Practice the honest-unknown: draft your response to "how does Kafka replication handle a partition leader failure?" assuming you half-know.

## 07. Leveling: What L4 vs. L5 vs. L6 Answers Look Like

Same question, three transcripts. The question: **"Design a system to deliver in-app notifications."** Watch what changes — it isn't knowledge, it's *scope of ownership*.

**The L4 answer (competent, guided).** Asks a few clarifying questions when prompted. Produces a correct pipeline — API → queue → workers → push provider → device — with reasonable technology picks. Handles the interviewer's probes ("what if the provider is down?") sensibly: adds retries and a DLQ *when asked*. The design works; the interviewer did the steering. Signal: **can build a component correctly inside someone else's plan.** Typical gaps: doesn't volunteer the deep dive, treats estimation as a ritual, tradeoffs stated without costs.

**The L5 answer (owns the problem).** Scopes unprompted ("transactional and campaign traffic have different SLAs — I'll design for both and isolate them"). Estimation produces a *conclusion*: "1B/day is only 12K/sec average, but a 50M-user campaign is a 14K/sec sustained burst — so lane isolation is the design's spine." Volunteers the hard parts — idempotent delivery, token staleness, provider backpressure — and drives deep dives with committed tradeoffs and stated costs. Discusses failure modes before being asked: "if Redis dedup is down, I fail open and accept rare duplicates; here's why that's the right default for this product." Signal: **owns the whole problem, needs no steering.** This is the hiring bar at most companies for "senior."

**The L6 answer (owns the problem-space).** Everything in L5, plus three extra registers. *Product judgment*: "before designing batching, I'd ask whether notification fatigue is the real problem — the best system here might send less." *Evolution and operations*: "v1 is a single queue and a Postgres table, honestly; here are the two seams I'd leave so the lane-isolated design can be migrated to without a rewrite — and here's the dashboard I'd watch to know when." *Organizational reality*: "the provider-adapter boundary is also a team boundary; I'd spec its contract first because two teams will build either side." L6 answers treat the design as one point in a trajectory — cost curves, migration paths, what breaks at 10×, which parts are deliberately boring. Signal: **designs the system, its lifecycle, and the humans around it.**

The uncomfortable takeaway: L4→L5 is not "know more tech," it's *drive, don't ride* — scope it, estimate with conclusions, volunteer the pain, commit with costs. L5→L6 is *lift your horizon* — time (evolution), money (cost), people (boundaries). You can practice all six of those verbs on every Phase 17 case study.

### Checkpoint
1. Take your best Phase 17 answer and honestly grade it L4/L5/L6 against the signals above. Find the two cheapest upgrades.
2. Rewrite one L4-style moment ("added retries when asked") as the L5 version (volunteered, with cost) and the L6 version (with evolution/ops framing).
3. For "design a rate limiter," write the three one-line openings an L4, L5, and L6 candidate would say in their first 60 seconds.

## 08. Mock Interview Rubrics and Self-Grading

You can't improve what you don't score. Real interviewers fill out a rubric within minutes of your interview; you should be filling out the same one about yourself. Here it is — score 1–5 per axis, where 3 = "hire at mid-level," 4 = "hire at senior."

| Axis | 1 — No-hire | 3 — Solid | 5 — Exceptional |
|---|---|---|---|
| Requirements & scoping | Jumped straight to boxes | Asked good questions, agreed a scope | Questions reshaped the problem; scope had a rationale |
| Estimation | Skipped, or math for math's sake | Correct numbers, roughly right sizes | Every estimate ended in a "therefore" that drove design |
| High-level design | Gaps; requirements with no path | Complete, coherent, walked end-to-end | Clean, minimal, with seams left for the deep dives |
| Deep dives | Stayed shallow everywhere | Went deep when steered, correctly | Chose the right hard parts unprompted; multiple options compared |
| Tradeoffs | Choices asserted, no costs | Alternatives named, costs stated | Quantified; knew when the losing option wins |
| Failure & scale reasoning | Happy path only | Handled probes on failures sensibly | Volunteered failure modes, bottlenecks, and the 10× story |
| Communication | Hard to follow; silent stretches | Clear narration, organized board | Steered time, checkpointed, coachable, a pleasure to follow |

**How to run a mock.** 45 minutes, honored strictly — a friend, a peer from this course, or you alone with a recording (solo mocks are ~70% as useful, which is plenty). Interviewer picks any Phase 17 prompt and behaves realistically: mostly quiet, two planted probes ("what if that node dies?", "10× the traffic — what breaks first?"), one redirect mid-deep-dive. Immediately after: both of you fill the rubric independently *before discussing* — the gaps between your self-scores and theirs are your blind spots, and they're the most valuable data the mock produces.

**How to turn scores into a training plan.** Don't retry the whole interview. Take your lowest axis and drill it in isolation: scored 2 on estimation → do Lesson 03's drills daily for a week; scored 2 on tradeoffs → run Lesson 05's challenge drill; scored 2 on communication → record-and-count from Lesson 06. Then a full mock on a *fresh* prompt (never re-mock a system you've just graded — you'll measure memory, not skill). Progress looks like this: most people start averaging ~2.5, reach a stable 3.5 after roughly six spaced mocks, and the last half-point to 4 is almost always communication and tradeoffs, not knowledge. Keep every filled rubric; a stack of seven of them showing the curve is more motivating than any prep book.

### Checkpoint
1. Run one full solo mock this week (record it, prompt from Phase 17 you haven't done recently), fill in the rubric within 10 minutes of finishing.
2. Identify your lowest axis and write a one-week drill plan for it using the earlier lessons in this phase.
3. Grade a *published* mock interview (any system design video) with this rubric. Where do you disagree with your own scores on rewatch? That gap is your calibration error — write it down.
