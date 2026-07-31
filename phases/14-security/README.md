# Phase 14 — 🔐 Security & Identity

> Every box in your diagram is a door someone will try.

You drew a beautiful architecture diagram. Boxes, arrows, a load balancer with a reassuring little shield icon. Here's the uncomfortable truth: every one of those boxes is an attack surface, every arrow is a channel to intercept, and the shield icon does nothing. Security is not a feature you bolt on at the end — it's a property of the design, and this phase teaches you to design for it the way you design for scale: deliberately, with mechanisms you actually understand.

## 01. Threat Modeling for Architects (STRIDE)

**MOTTO:** You can't defend a system you haven't attacked on paper first.

### The Problem

Most teams discover their security holes the same way they discover their scaling limits: in production, from a stranger. Penetration tests happen once a year; architecture changes happen every sprint. Without a systematic way to ask "what could go wrong here?" *during design*, you're relying on luck and the hope that nobody curious ever looks at your system. Luck is not a control.

### The Concept

Threat modeling is a structured walk through your own diagram wearing the attacker's shoes. Think of it like a fire marshal inspecting a building: they don't set fires, they walk every corridor asking "where does smoke go? which exits jam?" STRIDE gives you six lenses to point at every component and every arrow:

```
S  Spoofing          → "Can I pretend to be someone else?"     (Authentication)
T  Tampering         → "Can I modify data I shouldn't?"        (Integrity)
R  Repudiation       → "Can I deny I did it?"                  (Auditing)
I  Information       → "Can I read data I shouldn't?"          (Confidentiality)
   Disclosure
D  Denial of Service → "Can I make it unavailable?"            (Availability)
E  Elevation of      → "Can I gain powers I shouldn't have?"   (Authorization)
   Privilege
```

The key architectural artifact is the **trust boundary**: any line where data crosses from a less-trusted zone to a more-trusted one (internet → load balancer, app → database, service A → service B). Threats cluster at boundaries.

### Build It

1. Draw the data flow diagram: external entities, processes, data stores, data flows.
2. Mark every trust boundary with a dashed line. Be honest — "internal network" is a weaker boundary than you think.
3. For each element crossing a boundary, run all six STRIDE questions. Write down every plausible threat, even dumb-sounding ones.
4. Rate each threat (likelihood × impact is fine; don't over-engineer the scoring).
5. For each accepted threat, record a mitigation *and the component that owns it*. Unowned mitigations don't exist.
6. Re-run the exercise whenever an arrow or box changes. A threat model is a living document, not a compliance PDF.

### Use It

| Tool | What it does | Tradeoff |
|---|---|---|
| Microsoft Threat Modeling Tool | Draws DFDs, auto-suggests STRIDE threats | Windows-centric, template-driven |
| OWASP Threat Dragon | Open-source diagram + threat tracking | Lighter analysis, more manual |
| Whiteboard + STRIDE checklist | The 80% solution | Requires discipline, no tooling to nag you |

### War Story

STRIDE came out of Microsoft in 1999 (Kohnfelder and Garg) and became institutional practice after Bill Gates's 2002 "Trustworthy Computing" memo halted Windows development so every team could threat-model and fix their components — a direct response to worms like Code Red and Nimda shredding Microsoft's reputation. The lesson stuck: it's cheaper to reason about threats before shipping than to patch a worm-storm after.

### Checkpoint

- Which STRIDE category does "an attacker replays a captured API request to re-trigger a payment" fall under, and which property does it violate?
- Why do threats cluster at trust boundaries rather than inside components?
- Your threat model lists a mitigation with no owning component. What's wrong with that, concretely?

## 02. Authentication: Sessions, Tokens, JWTs

**MOTTO:** Authentication answers "who are you?" — and the hard part is remembering the answer safely.

### The Problem

HTTP is stateless. The user proved who they were at login, but the very next request arrives with no memory of that. You need to hand the client something it can present on every request that says "it's still me" — without letting an attacker forge it, steal it, or keep using it after logout. Every auth architecture is a different answer to *where the memory lives*.

### The Concept

Two philosophies, like two kinds of gym passes:

- **Session (stateful):** the gym keeps a member register; your pass is just an opaque number they look up. Server stores state, client holds a meaningless key.
- **Token / JWT (stateless):** the gym hands you a tamper-evident laminated card listing your privileges and expiry. Nobody looks anything up — they just verify the lamination (signature).

```
SESSION:  client ──cookie: sid=abc123──▶ server ──▶ session store ──▶ "abc123 = alice"
JWT:      client ──Authorization: Bearer <header.payload.signature>──▶ server
                                          verify signature locally, trust payload
```

The tradeoff is revocation vs. lookup cost: sessions are revocable instantly (delete the row) but need a shared store; JWTs verify locally at any scale but *cannot be un-issued* — they're valid until expiry unless you build a denylist, which quietly reinvents the session store.

### Build It

1. Session flow: on login, generate a session ID from a CSPRNG (≥128 bits of entropy), store `{sid → user, expiry}` server-side, set cookie with `HttpOnly; Secure; SameSite=Lax`.
2. JWT flow: on login, sign `{sub, exp, iat, scope}` with a server-held key. Prefer asymmetric (RS256/EdDSA) so verifying services never hold the signing key.
3. Verify pseudocode — the order matters:

```python
def verify_jwt(token):
    header, payload, sig = split(token)
    if header.alg not in ALLOWED_ALGS:      # never trust alg from the token ("alg":"none" attack)
        reject()
    if not verify_signature(key_for(header.kid), sig):
        reject()
    if payload.exp < now() or payload.iss != EXPECTED_ISSUER or payload.aud != ME:
        reject()
    return payload
```

4. Keep access tokens short-lived (minutes) and pair with a refresh token that *is* server-tracked — you get local verification for the hot path and revocation on the slow path.

### Use It

| Approach | Revocation | Scale cost | Best for |
|---|---|---|---|
| Server sessions (Redis) | Instant | Shared store on every request | Monoliths, admin panels |
| JWT access + refresh | On refresh (minutes) | Near zero per request | Microservices, APIs |
| Opaque token + introspection | Instant | Network call (cacheable) | High-security APIs |

### War Story

In 2015, security researchers (Tim McLean) documented that many JWT libraries honored the `alg` field from the attacker-controlled header — including `"none"` — allowing anyone to mint "signed" tokens with no signature at all. Multiple mainstream libraries were vulnerable. The design lesson outlived the patch: never let untrusted input select its own verification algorithm.

### Checkpoint

- Why does "logout" fundamentally not work for a pure stateless JWT, and what are the two standard workarounds?
- What do `HttpOnly`, `Secure`, and `SameSite` each defend against on a session cookie?
- You need auth checks in 40 microservices. Argue for JWTs over shared sessions — then name the risk you just accepted.

## 03. OAuth 2.0 and OpenID Connect

**MOTTO:** OAuth is about delegation, not login — OIDC is the login part everyone actually wanted.

### The Problem

Your app needs to read a user's Google Calendar. The dark-ages solution: ask for their Google password and impersonate them — full access, no expiry, no revocation, and now you're storing other people's Google passwords. You need a way for a user to grant your app *limited, revocable* access to their stuff on another service, without ever handing over credentials.

### The Concept

OAuth 2.0 is a valet key: it starts the car and opens the driver's door, but not the trunk. The user (resource owner) tells the authorization server "give this app a key that only opens the calendar," and the app gets an access token — never the password.

```
User(browser)        Your App           Auth Server         Resource API
    │  "connect calendar"  │                 │                   │
    │──────────────────────▶ redirect to ────▶                   │
    │◀── login + consent screen ─────────────│                   │
    │──── approve ───────────────────────────▶                   │
    │◀─ redirect back with CODE ─────────────│                   │
    │── code ─────────────▶│                 │                   │
    │                      │─ code + client_secret + verifier ──▶│
    │                      │◀──── access_token (+ id_token) ─────│
    │                      │──── Bearer access_token ────────────────▶ calendar data
```

Why the two-step code dance? The code travels through the browser (untrusted front channel); the token exchange happens server-to-server (back channel) and requires the client's own credentials — so a stolen code alone is useless. **OIDC** is a thin identity layer on top: it adds a signed `id_token` (a JWT about *who logged in*), turning OAuth's delegation machinery into the "Sign in with Google" button.

### Build It

1. Use the **authorization code flow with PKCE** for everything user-facing (SPAs and mobile included; the implicit flow is deprecated).
2. PKCE mechanics: client generates random `code_verifier`, sends `code_challenge = SHA256(verifier)` up front, and must present the original verifier to redeem the code — an intercepted code can't be exchanged without it.
3. Validate `state` on the redirect (CSRF defense) and register exact redirect URIs — open redirects turn into token theft.
4. On the API side, check the token's `aud`, `scope`, and expiry. Delegation ≠ authorization: "has a valid token" is not "may do this."
5. Machine-to-machine (no user)? That's the **client credentials** flow — plain OAuth, no OIDC needed.

### Use It

| Tool | Role | Tradeoff |
|---|---|---|
| Auth0 / Okta | Hosted auth server | Fast, costly at scale, vendor lock-in |
| Keycloak | Self-hosted, open source | You operate and patch it |
| ory / Dex | Lightweight OIDC providers | More assembly required |

### War Story

Facebook's September 2018 breach chained bugs in the "View As" feature and video uploader to mint OAuth access tokens for roughly 50 million users — attackers didn't steal a single password, they stole the *token-minting machinery*. It's the canonical reminder that in a delegated-auth world, the token issuance path is the crown jewels.

### Checkpoint

- Why is the authorization code exchanged on the back channel instead of returning the access token directly in the redirect?
- What specific attack does PKCE prevent, and why does it matter most for mobile/SPA clients?
- Your teammate says "we use OAuth for login." What's technically sloppy about that sentence, and what makes it correct?

## 04. Authorization: RBAC, ABAC, and Policy Engines

**MOTTO:** Authentication opens the front door; authorization decides which rooms you can enter.

### The Problem

Knowing the request comes from Alice is useless until you answer: may Alice delete *this* invoice? Teams start with `if user.is_admin` sprinkled across the codebase, and two years later authorization logic lives in 300 files, no one can answer "who can access customer data?", and the auditor is asking exactly that. Permission checks scattered through business logic are unreviewable, untestable, and inconsistent.

### The Concept

Three models, increasing in expressiveness:

- **RBAC** (role-based): permissions attach to roles, users get roles. Like job titles — "nurses may access patient charts."
- **ABAC** (attribute-based): rules over attributes of user, resource, and context. "Nurses may access charts *of patients on their own ward, during their shift*."
- **ReBAC** (relationship-based): permissions follow a relationship graph — "you can edit this doc because you're in a group that owns the folder that contains it." This is Google's Zanzibar model.

```
Request: (subject, action, resource, context)
                     │
                     ▼
        ┌─────────────────────────┐
        │  Policy Decision Point   │  ← policies live HERE, in one place
        │  (evaluates rules)       │
        └───────────┬─────────────┘
                    ▼ ALLOW / DENY
        Policy Enforcement Point (your service) obeys
```

The architectural move that matters: **separate the decision from the enforcement.** Services ask; a policy engine answers.

### Build It

1. Model RBAC as three tables: `user_roles(user, role)`, `role_permissions(role, permission)`; a check is a join. Deny by default.
2. When RBAC rules sprout conditions ("...but only their own department"), you've hit role explosion — graduate to ABAC instead of minting `editor_dept_finance_emea`.
3. ABAC check, conceptually:

```python
def allowed(subject, action, resource, ctx):
    for policy in policies_for(action, resource.type):
        if policy.matches(subject.attrs, resource.attrs, ctx):
            return policy.effect            # explicit ALLOW or DENY
    return DENY                             # default deny, always
```

4. Enforce at a chokepoint (middleware, sidecar, or library) so a check can't be forgotten, and log every decision — that's your audit trail for the R in STRIDE.
5. Watch decision latency: authz sits on every request's hot path, so cache decisions or co-locate the engine (sidecar).

### Use It

| Tool | Model | Tradeoff |
|---|---|---|
| Open Policy Agent (OPA) | ABAC via Rego policies | Powerful; Rego has a learning curve |
| AWS Cedar / Amazon Verified Permissions | RBAC+ABAC, formally analyzable | Newer ecosystem |
| SpiceDB / OpenFGA | ReBAC (Zanzibar-style) | Best for nested sharing; you run a graph store |

### War Story

Google's 2019 Zanzibar paper revealed the global authorization system behind Drive, YouTube, and Calendar: trillions of relationship tuples, ~10 million checks per second, at 95th-percentile latency around 10ms — while solving the "new enemy" consistency problem (a revoked user seeing content via a stale ACL) with versioned snapshot tokens. It spawned an entire industry of open-source clones.

### Checkpoint

- What is "role explosion," and which model is the standard escape hatch?
- Why should policy *decision* be separated from policy *enforcement* architecturally?
- Google Docs-style nested sharing (user → group → folder → doc): why does plain RBAC fit badly, and which model fits?

## 05. Encryption in Transit and at Rest

**MOTTO:** Assume every wire is tapped and every disk will be stolen — because eventually, one will be.

### The Problem

Your data spends its life in two vulnerable states: moving through networks you don't control, and sitting on disks you'll eventually decommission, resell, or have stolen. Plaintext in either state means one tapped switch or one un-wiped drive equals total disclosure. And "we encrypt everything" is meaningless until you answer the real question: *who holds the keys, and what does the encryption actually protect against?*

### The Concept

- **In transit** = a sealed armored courier: nobody along the route can read or alter the package, and you verified the recipient's ID before handing it over. That's TLS: authenticate the server via certificates, agree on a symmetric session key, then encrypt everything.
- **At rest** = a safe in your house: protects if the disk walks away, but does nothing while the safe is open — i.e., against an attacker with live application-level access.

```
TLS 1.3 handshake (simplified):
Client ──ClientHello: supported ciphers + key share──▶ Server
Client ◀─ServerHello: key share + certificate chain──  Server
Client: verify cert chain up to trusted CA, derive session keys
Both:   ══ symmetric encryption (AES-GCM / ChaCha20-Poly1305) ══
```

At-rest layers, weakest protection to strongest: full-disk (stolen hardware only) → database/file-level (per-tenant keys possible) → application/field-level (DBA can't read it; ciphertext even in backups).

### Build It

1. Never invent crypto. Your job is *key management architecture*, not algorithms.
2. Use **envelope encryption**: encrypt each object with its own data-encryption key (DEK); encrypt the DEK with a key-encryption key (KEK) that lives in a KMS/HSM and never leaves it. Store the wrapped DEK beside the data.

```
object ──AES-256-GCM──▶ ciphertext        (DEK, random per object)
DEK    ──KMS encrypt──▶ wrapped DEK       (KEK never leaves the KMS)
store: [ciphertext | wrapped DEK | KEK id]
```

3. Rotation now becomes cheap: rotate the KEK and re-wrap the DEKs — no re-encrypting terabytes.
4. In transit: TLS 1.2 minimum (prefer 1.3), and use **mTLS** service-to-service so both ends prove identity. "It's inside the VPC" is not an encryption strategy.
5. For every dataset, write down the threat it's encrypted against. Full-disk encryption on a running server protects against exactly nothing an attacker with a shell cares about.

### Use It

| Tool | Layer | Tradeoff |
|---|---|---|
| AWS KMS / GCP Cloud KMS | Managed keys, envelope encryption | Cloud trust required; per-call cost |
| HashiCorp Vault (transit engine) | Encryption-as-a-service | You operate Vault, and it's critical path |
| Let's Encrypt / cert-manager | Free automated TLS certs | 90-day expiry forces (healthy) automation |

### War Story

Heartbleed (April 2014) was a missing bounds check in OpenSSL's heartbeat extension that let anyone read up to 64KB of server memory per probe — leaking session data and, catastrophically, private TLS keys, from an estimated 17% of the internet's "secure" web servers. The bitter irony: the vulnerability lived *inside the encryption library itself*, which is why key rotation ability and certificate revocation are architectural requirements, not nice-to-haves.

### Checkpoint

- Full-disk encryption is enabled on your database server. Name two realistic attacks it does *not* mitigate.
- Walk through envelope encryption: what's the DEK, what's the KEK, and why does the split make rotation cheap?
- What extra guarantee does mTLS add over plain TLS, and where in a microservices mesh does that matter?

## 06. Secrets Management

**MOTTO:** A secret in a config file is a secret published on a delay.

### The Problem

Your services need database passwords, API keys, and signing keys. The path of least resistance — env vars in a config file, committed "temporarily" — has a failure mode with a name: credential leak via repo. Scanners crawl public GitHub for AWS keys and typically find fresh ones within minutes of a push. And even unleaked static secrets rot: shared across services, never rotated because rotation breaks things, and known to every engineer who ever touched the deploy.

### The Concept

Treat secrets like hotel keycards, not brass keys. A brass key is copied freely, works forever, and nobody knows how many exist. A keycard is issued per guest, expires at checkout, is logged on every door, and is revoked by pressing a button. That's a secrets manager: central vault, per-identity issuance, automatic expiry, full audit log.

```
   Service ──authenticate (platform identity: IAM role /
       │      k8s service account — NOT a password)──▶ ┌──────────┐
       │                                               │  Vault    │
       │ ◀── short-lived credential (TTL: 1h) ──────── │  - issue  │
       │                                               │  - audit  │
       ▼                                               │  - revoke │
   Database (credential auto-expires; leak has a       └──────────┘
             half-life measured in minutes, not years)
```

The endgame is **dynamic secrets**: the vault *creates* a fresh database user on demand and deletes it after TTL. Nothing long-lived exists to steal. Note the bootstrap trick: the service authenticates with a platform-attested identity, not "secret zero," or you've just moved the problem.

### Build It

1. Inventory every secret: what it unlocks, who holds it, when it last rotated. The list will be longer and scarier than expected.
2. Centralize in a secrets manager; inject at runtime (mounted tmpfs file or env at process start) — never bake into images or commit to git.
3. Solve secret-zero with platform identity: cloud IAM roles, Kubernetes service account tokens, SPIFFE.
4. Make rotation a routine no-op: dual-credential pattern — issue new, roll services over, revoke old. If rotation is scary, that fear is your finding.
5. Add pre-commit and CI secret scanning (gitleaks, trufflehog). Cheap insurance against the most common leak path.
6. Assume breach: alert on anomalous secret access (new IP, odd hour, unusual volume). The audit log is only useful if something reads it.

### Use It

| Tool | Model | Tradeoff |
|---|---|---|
| HashiCorp Vault | Dynamic secrets, many backends | Powerful; serious operational burden |
| AWS/GCP Secrets Manager | Managed, IAM-integrated | Cloud-coupled, per-secret pricing |
| SOPS + KMS | Encrypted secrets in git | Simple GitOps fit; static, manual rotation |

### War Story

Uber's 2016 breach of 57 million riders' and drivers' data started with credentials found in a private GitHub repo, which unlocked an AWS S3 bucket full of user data — and the company then paid the attackers $100,000 to keep quiet, a cover-up that later cost far more in fines and reputation. One static secret in one repo; that's the entire kill chain.

### Checkpoint

- What is the "secret zero" problem, and how do platform identities (IAM roles, k8s service accounts) dissolve it?
- Why do dynamic short-TTL secrets reduce breach impact even if the vault itself is never touched by the attacker?
- Design a zero-downtime rotation for a database password shared by 12 services.

## 07. DDoS Protection

**MOTTO:** You can't out-scale a botnet — you can only make yourself cheap to defend and expensive to hurt.

### The Problem

A distributed denial of service attack needs no vulnerability at all: the attacker simply generates more work than you can absorb, using thousands of hijacked machines. It's asymmetric warfare — a $50/day booter service can generate traffic that costs you thousands per hour to absorb. And the target isn't always bandwidth; a modest stream of expensive requests (search queries, login attempts, report generation) can kneecap your database while your network graphs look calm.

### The Concept

Think of a stadium under siege. Three ways to overwhelm it, three layers of defense:

```
L3/4 Volumetric ─ flood the roads (UDP floods, amplification: attacker sends
                  small spoofed queries; servers reflect huge answers at you)
                  ↳ defend: anycast — spread traffic across global scrubbing
                    centers so no single pipe saturates
L4 Protocol     ─ jam the turnstiles (SYN floods: half-open connections
                  exhausting the accept queue)
                  ↳ defend: SYN cookies — statelessly encode the connection
                    in the sequence number; commit no memory until the
                    handshake completes
L7 Application  ─ send fake ticket-holders to the box office (legit-looking
                  HTTP hitting expensive endpoints)
                  ↳ defend: rate limiting, caching, bot scoring, challenges
```

The organizing principle: absorb what you can at the cheapest layer, and never let cheap requests trigger expensive work unauthenticated.

### Build It

1. Front everything with anycast + CDN so volumetric floods hit a globally distributed edge, not your origin. Lock the origin down to accept traffic *only* from the CDN, or attackers will find its IP and go around.
2. Rate limit at the edge — token bucket per client, per endpoint:

```python
def allow(bucket, now):
    bucket.tokens = min(bucket.cap, bucket.tokens + bucket.rate * (now - bucket.last))
    bucket.last = now
    if bucket.tokens >= 1:
        bucket.tokens -= 1
        return True
    return False   # 429, with Retry-After
```

3. Rank your endpoints by cost-per-request; cap or queue the expensive ones. Cache aggressively — a cached response is a free response.
4. Add load-shedding: past a utilization threshold, reject cheap-to-reject traffic early so paid-up work still completes. Degraded beats down.
5. Don't be an amplifier yourself: rate-limit responses on any UDP service you expose, and validate source addresses.

### Use It

| Tool | Layer | Tradeoff |
|---|---|---|
| Cloudflare / Akamai | All layers, massive anycast | Traffic transits a third party |
| AWS Shield + WAF | L3/4 managed + L7 rules | Advanced tier is pricey; AWS-only |
| Envoy/NGINX rate limiting | L7 at your edge | Last line, not first — your pipe still fills |

### War Story

The October 2016 Dyn attack used the Mirai botnet — hundreds of thousands of hacked IoT cameras and DVRs with default passwords — to flood a major DNS provider, taking Twitter, Netflix, Reddit, and Spotify offline for much of the US East Coast. The architectural lesson wasn't about bandwidth: it was a shared-dependency lesson. Companies with a single DNS provider went dark; multi-provider DNS survived. In 2018, GitHub absorbed a then-record 1.35 Tbps memcached amplification attack and recovered in about 10 minutes — because scrubbing (Akamai Prolexic) was pre-arranged, not scrambled for mid-incident.

### Checkpoint

- How do SYN cookies let a server survive a SYN flood without allocating per-connection state?
- Why can an L7 attack succeed with a tiny fraction of the bandwidth a volumetric attack needs?
- Your origin sits behind a CDN, but attacks still reach it directly. What did you forget?

## 08. OWASP for System Designers

**MOTTO:** The top ten haven't changed much in twenty years — because we keep rebuilding the same doors.

### The Problem

The OWASP Top 10 is the recurring cast of web-security failure: injection, broken access control, misconfiguration, vulnerable dependencies. Treating them as "developer bugs" misses the point for an architect — most have *architectural* causes and *architectural* cures. A design that requires every developer to remember the right escaping function in every code path is a design that guarantees the vulnerability ships.

### The Concept

Reframe each risk as a design smell. Injection isn't "someone forgot to sanitize" — it's *data and code sharing a channel*, like a mail clerk who executes any letter that looks like an instruction. Broken access control (the #1 risk in OWASP's 2021 list) is *authorization enforced in scattered spots instead of a chokepoint*. SSRF is *the server acting as a confused deputy*, making requests on an attacker's behalf with its own privileges.

```
Injection, the one diagram that matters:

  BAD:  "SELECT * FROM users WHERE name = '" + input + "'"
         └── data and code interleaved in one string; the parser
             can't tell your SQL from the attacker's

  GOOD:  execute("SELECT * FROM users WHERE name = ?", [input])
         └── code and data travel on separate channels; input can
             NEVER be promoted to code
```

### Build It

Turn each top risk into a structural control — something that works even on a developer's worst day:

1. **Injection** → parameterized queries only; make the raw string-concat API unavailable (lint rule, wrapper library).
2. **Broken access control** → single authorization chokepoint (Lesson 04); deny by default; object-level checks ("is this *your* invoice?"), not just endpoint-level.
3. **SSRF** → egress allowlists on any service that fetches user-supplied URLs; block link-local metadata addresses (169.254.169.254) outright.
4. **Vulnerable components** → dependency scanning in CI plus an actual patch SLA with an owner. Scanners that page nobody are decoration.
5. **Misconfiguration** → golden paths: hardened base images and IaC modules so the secure setup is the default setup.
6. **XSS** → auto-escaping template engines plus Content-Security-Policy as backstop.
7. Validate at every trust boundary, allowlist over denylist, and canonicalize before validating.

### Use It

| Tool | Catches | Tradeoff |
|---|---|---|
| Dependabot / Snyk | Known-vulnerable dependencies | Noisy; needs triage discipline |
| Semgrep / CodeQL | Insecure code patterns in CI | Rules need tuning per codebase |
| OWASP ZAP | Running-app scanning (DAST) | Finds surface issues, not logic flaws |

### War Story

Equifax, 2017: attackers exploited a known Apache Struts vulnerability (CVE-2017-5638, an injection-class RCE) that had a patch available for two months, and exfiltrated personal data on about 147 million people. An expired certificate on an internal traffic-inspection device meant the exfiltration went unseen for ~76 days. Not one exotic technique in the whole chain — just OWASP-list basics, unpatched and unmonitored, at scale.

### Checkpoint

- What is the common structural root of SQL injection, XSS, and command injection, and what channel-separation cure applies to all three?
- Why is endpoint-level authorization ("only admins reach /admin/*") insufficient? Give the object-level counterexample.
- Your image-fetching service takes user URLs. List three SSRF controls, and name the cloud-specific address you must block.

## 09. Zero Trust Architecture

**MOTTO:** The castle has no walls anymore — check ID at every door instead.

### The Problem

The perimeter model — hard shell, gooey center — assumes "inside the network" means "trustworthy." Then one phished laptop VPNs in, and the attacker moves laterally through flat internal networks where services trust each other by IP and nobody re-checks anything. With cloud, SaaS, and remote work, the perimeter barely exists anyway; you're defending a wall around a city that has already sprawled outside it.

### The Concept

Zero trust replaces one wall with checks at every door: an office where the lobby badge-check disappears but every room, cabinet, and terminal verifies your badge — and the badge reader also inspects *the badge-holder's laptop* (patched? managed? healthy?) and the context (usual hour? usual location?) before each unlock.

```
Perimeter model:                Zero trust:
┌───────wall───────┐            every arrow independently verified
│  A ──▶ B ──▶ C   │            A ══mTLS + policy check══▶ B
│  (implicit trust │            B ══mTLS + policy check══▶ C
│   inside)        │            trust derives from IDENTITY + DEVICE
└──────────────────┘            + CONTEXT — never from network location
```

Three commandments: verify explicitly (authN + authZ per request), least privilege (minimum access, short-lived), assume breach (design so a compromised node is contained, not catastrophic).

### Build It

1. Give every workload a cryptographic identity — SPIFFE/SPIRE-style certs or mesh-issued mTLS identities. "Source IP 10.0.3.7" is not an identity.
2. mTLS everywhere internally; both ends authenticate. A service mesh (sidecar or ambient) retrofits this without touching app code.
3. Put a policy decision point on every service-to-service call: *may service A call B's endpoint X, given A's identity and context?* Default deny.
4. Microsegment the network so even successful compromise of one pod reaches only its declared dependencies — the blast radius is the policy graph, not the subnet.
5. For humans: SSO + phishing-resistant MFA (hardware keys, not SMS) + device posture, via an access proxy instead of a VPN.
6. Migrate incrementally: inventory flows → observe/log in permissive mode → enforce service by service. Big-bang zero trust is an outage generator.

### Use It

| Tool | Covers | Tradeoff |
|---|---|---|
| Istio / Linkerd | Workload mTLS + authz policy | Operational complexity, some latency |
| Cloudflare Access / Google BeyondCorp (IAP) | Human access, VPN replacement | Identity provider becomes critical path |
| Tailscale | Identity-based private networking | Simpler; coarser policy than a mesh |

### War Story

Zero trust's origin story is Operation Aurora (2009), the nation-state intrusion into Google that spurred the company to rebuild internal access from scratch as **BeyondCorp** — published as a series of papers from 2014 onward — moving all employee access off the privileged network and onto per-request checks of user identity plus device state. The papers are the field's founding documents: the perimeter didn't shrink, it was abolished.

### Checkpoint

- Why is source-IP-based trust between services incompatible with zero trust? Name two ways an IP claim goes wrong.
- What are the three signal categories a zero-trust decision combines beyond "valid credentials"?
- An attacker fully compromises one service in a well-built zero-trust system. What bounds their lateral movement, and what should light up while they try?

## 10. Compliance and Data Privacy by Design

**MOTTO:** "Delete my data" is a feature request that arrives after the architecture that makes it impossible.

### The Problem

GDPR, CCPA, HIPAA, PCI-DSS, SOC 2 — regulations turn into engineering requirements with sharp edges: delete a user's data across every store within 30 days, prove who accessed a record, keep EU data in the EU. Retrofitting these onto a system that has scattered user data through logs, caches, backups, analytics warehouses, and third-party tools is somewhere between agonizing and impossible. And GDPR fines scale to 4% of global revenue, so "we'll deal with it later" has a price tag.

### The Concept

Treat personal data like radioactive material: incredibly useful, but every gram must be tracked from intake to disposal, handled with purpose, and stored only as long as needed. Nobody keeps spare plutonium "in case it's useful later." Privacy by design means the data's lifecycle is an architectural input, not a legal afterthought:

```
Personal data lifecycle — design for every stage on day one:
COLLECT ──▶ STORE ──▶ USE ──▶ SHARE ──▶ RETAIN ──▶ DELETE
minimize    tagged +  purpose  processor  TTL from   provable,
at intake   located   -bound   contracts  day one    complete
```

The two keystones: **data minimization** (uncollected data can't be breached, subpoenaed, or fined) and **data mapping** (you cannot delete, export, or localize what you cannot find).

### Build It

1. Build a data inventory: every store, which personal-data categories it holds, why (the lawful purpose), and its retention clock. This document is the foundation for literally every compliance regime.
2. Tag personal data at the schema level (`pii: true`, category, retention class) so tooling can find it mechanically instead of archaeologically.
3. Design deletion as a first-class flow: key every piece of PII to a durable `user_id`, then implement `delete(user_id)` as a fan-out to all stores — including caches and search indexes. For backups and append-only logs, use **crypto-shredding**: encrypt each user's data with a per-user key; deleting the key deletes the data everywhere at once.
4. Keep PII out of application logs structurally — scrubbing middleware at the log pipeline, not per-developer vigilance.
5. For residency: partition-by-region at the data layer (EU rows on EU storage), with global metadata kept PII-free.
6. Make audit logs append-only and access to sensitive records logged by default — "who saw this record" must be a query, not an investigation.

### Use It

| Regime | Core demand on your design | Architectural implication |
|---|---|---|
| GDPR / CCPA | Deletion, export, consent, minimization | Data mapping, per-user keying, purpose tags |
| PCI-DSS | Protect card data | Tokenize and shrink scope — don't touch PANs at all if you can |
| SOC 2 / HIPAA | Access control + audit evidence | Centralized authz (Lesson 04) + immutable audit logs |

### War Story

GDPR enforcement got real fast: Amazon drew a €746M fine (2021, Luxembourg DPA) and Meta a €1.2B fine (2023, Irish DPC) over EU–US data transfers — the largest GDPR penalty to date and a direct consequence of *where data physically flows*, which is an architecture decision. Meanwhile in 2019, Facebook disclosed it had stored hundreds of millions of user passwords in plaintext in internal logs for years — nobody attacked anything; the logging pipeline was simply never designed with data sensitivity in mind.

### Checkpoint

- Why does crypto-shredding solve the "delete user data from immutable backups" problem, and what new operational risk does it introduce?
- What is data minimization, and how does it reduce breach cost, compliance scope, and fine exposure simultaneously?
- A product manager wants to log full request bodies "for debugging." Walk through the privacy-by-design objections and the compliant alternative.
