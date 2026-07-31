// System Design From Scratch — canonical curriculum data
// 20 phases · 226 lessons
const CURRICULUM = [
  {
    id: 0, slug: "00-setup-and-mental-models", emoji: "🧠", name: "Setup & Mental Models",
    tagline: "Learn to think in boxes, arrows, and orders of magnitude.",
    lessons: [
      "What is system design (and why intuition beats memorization)",
      "Thinking in boxes and arrows",
      "Latency numbers every engineer should know",
      "Back-of-the-envelope math",
      "Powers of two, units, and napkin conversions",
      "Functional vs non-functional requirements",
      "How to read (and draw) architecture diagrams",
      "Your lab setup: Docker, tooling, and the playground"
    ]
  },
  {
    id: 1, slug: "01-hardware-and-os", emoji: "⚙️", name: "Hardware & OS Foundations",
    tagline: "Every distributed system is just computers. Know the computer.",
    lessons: [
      "The CPU and the memory hierarchy",
      "RAM vs disk: the great divide",
      "HDD vs SSD vs NVMe",
      "Sequential vs random I/O",
      "Processes, threads, and context switches",
      "Concurrency primitives: locks, semaphores, atomics",
      "Event loops and async I/O",
      "File systems: what happens when you save a file",
      "Memory management and garbage collection",
      "Zero-copy and the page cache",
      "The network path through the kernel",
      "The cost of everything (a benchmark tour)"
    ]
  },
  {
    id: 2, slug: "02-networking", emoji: "🌐", name: "Networking From First Principles",
    tagline: "The internet is held together with retries and optimism.",
    lessons: [
      "OSI vs TCP/IP: the maps of the internet",
      "IP addressing and routing",
      "TCP: handshakes, flow control, congestion",
      "UDP: when losing packets is fine",
      "DNS from scratch",
      "HTTP/1.1: keep-alive and head-of-line blocking",
      "HTTP/2: multiplexing and server push",
      "HTTP/3 and QUIC",
      "TLS: the handshake that secures the web",
      "WebSockets, SSE, and long polling",
      "Sockets lab: build a TCP server by hand",
      "NAT, firewalls, and proxies",
      "Anycast and BGP basics",
      "Build a tiny HTTP server from scratch"
    ]
  },
  {
    id: 3, slug: "03-apis-and-serialization", emoji: "🔌", name: "APIs & Serialization",
    tagline: "Contracts between machines — and the humans who break them.",
    lessons: [
      "REST API design that doesn't hurt",
      "gRPC and Protocol Buffers",
      "GraphQL: queries, mutations, and the N+1 trap",
      "JSON vs binary formats: the serialization showdown",
      "API versioning without tears",
      "Idempotency: the art of safe retries",
      "Pagination, filtering, and sorting at scale",
      "Errors, retries, timeouts, and deadlines",
      "Webhooks: APIs in reverse",
      "The API gateway pattern"
    ]
  },
  {
    id: 4, slug: "04-storage-engines", emoji: "💾", name: "Databases I — Storage Engines",
    tagline: "Open the hood of a database and find trees, logs, and locks.",
    lessons: [
      "How a database actually stores your data",
      "B-trees: the workhorse of storage",
      "LSM trees: write-optimized storage",
      "The write-ahead log (WAL)",
      "Indexes deep dive: covering, composite, partial",
      "ACID transactions",
      "Isolation levels and their anomalies",
      "MVCC: reading without blocking",
      "Locking and deadlocks",
      "Query planning and optimization",
      "Build a key-value store from scratch",
      "Postgres vs MySQL internals tour"
    ]
  },
  {
    id: 5, slug: "05-distributed-data", emoji: "🗄️", name: "Databases II — Distributed Data",
    tagline: "One database is a pet. A hundred shards is a farm.",
    lessons: [
      "Replication: leader-follower",
      "Multi-leader and leaderless replication",
      "Replication lag and read-your-writes",
      "Partitioning (sharding) strategies",
      "Consistent hashing",
      "Rebalancing without downtime",
      "Secondary indexes in a sharded world",
      "Document stores: MongoDB and friends",
      "Wide-column stores: Cassandra internals",
      "Key-value at scale: the Dynamo paper",
      "Graph databases",
      "NewSQL: Spanner and CockroachDB",
      "Choosing a database: a decision framework",
      "Build consistent hashing from scratch"
    ]
  },
  {
    id: 6, slug: "06-caching", emoji: "⚡", name: "Caching",
    tagline: "The two hardest problems: naming, caching, and off-by-one errors.",
    lessons: [
      "Why caching works: locality and the 80/20 rule",
      "Cache patterns: aside, through, back, ahead",
      "Eviction policies: LRU, LFU, and friends",
      "Redis internals",
      "Memcached vs Redis",
      "CDNs: caching at the edge of the world",
      "Cache invalidation (the hard problem)",
      "Thundering herds and cache stampedes",
      "Hot keys and cache skew",
      "Build an LRU cache from scratch"
    ]
  },
  {
    id: 7, slug: "07-messaging-and-async", emoji: "📬", name: "Messaging & Async Processing",
    tagline: "Don't call me, I'll queue you.",
    lessons: [
      "Why async: decoupling time from work",
      "Message queues: the fundamentals",
      "Kafka architecture deep dive",
      "RabbitMQ and AMQP",
      "Pub/sub vs queues",
      "Delivery semantics: at-most, at-least, exactly-once",
      "Ordering, partitions, and keys",
      "Dead letter queues and retry strategies",
      "The transactional outbox pattern",
      "Event sourcing",
      "CQRS",
      "Build a message queue from scratch"
    ]
  },
  {
    id: 8, slug: "08-distributed-theory", emoji: "🎲", name: "Distributed Systems Theory",
    tagline: "Where clocks lie, networks fail, and consensus is expensive.",
    lessons: [
      "The eight fallacies of distributed computing",
      "Time, clocks, and the ordering of events",
      "Lamport clocks and vector clocks",
      "The CAP theorem (what it actually says)",
      "PACELC: CAP's more useful cousin",
      "Consistency models: linearizability to eventual",
      "Quorums: majority rules",
      "Leader election",
      "Paxos (gently)",
      "Raft: consensus you can understand",
      "Two-phase and three-phase commit",
      "Sagas: transactions without transactions",
      "CRDTs: merge without conflict",
      "Gossip protocols"
    ]
  },
  {
    id: 9, slug: "09-scalability-patterns", emoji: "📈", name: "Scalability Patterns",
    tagline: "From one server to one million requests per second.",
    lessons: [
      "Vertical vs horizontal scaling",
      "Stateless services: the golden rule",
      "Load balancing algorithms",
      "L4 vs L7 load balancing",
      "Rate limiting algorithms",
      "Backpressure: saying no gracefully",
      "Autoscaling: policies and pitfalls",
      "The database scaling playbook",
      "Fan-out: push vs pull",
      "Bloom filters and probabilistic data structures",
      "Build a rate limiter from scratch",
      "Build a load balancer from scratch"
    ]
  },
  {
    id: 10, slug: "10-microservices", emoji: "🧩", name: "Microservices & Service Architecture",
    tagline: "Distributed monoliths are still monoliths — with extra latency.",
    lessons: [
      "Monolith first: when NOT to use microservices",
      "Service boundaries and domain-driven design",
      "Service discovery",
      "API gateways in depth",
      "Backend-for-frontend (BFF)",
      "Circuit breakers and bulkheads",
      "Service mesh: sidecar armies",
      "Distributed transactions in practice",
      "The strangler fig migration",
      "Serverless architectures",
      "The modular monolith",
      "Microservices antipatterns hall of shame"
    ]
  },
  {
    id: 11, slug: "11-search-and-analytics", emoji: "🔍", name: "Search & Analytics",
    tagline: "Finding needles in exabyte haystacks.",
    lessons: [
      "Inverted indexes: how search works",
      "Tokenization, TF-IDF, and BM25",
      "Elasticsearch architecture",
      "Vector search and embeddings",
      "OLTP vs OLAP",
      "Columnar storage: why analytics is sideways",
      "Warehouses, lakes, and lakehouses",
      "ETL vs ELT",
      "Real-time analytics",
      "Build a search engine from scratch"
    ]
  },
  {
    id: 12, slug: "12-big-data-and-streams", emoji: "🌊", name: "Big Data & Stream Processing",
    tagline: "When the data is too big to fit anywhere, move the compute.",
    lessons: [
      "MapReduce: the paper that started it all",
      "HDFS and object storage",
      "Spark: memory beats disk",
      "Stream processing fundamentals",
      "Flink and exactly-once state",
      "Windowing and watermarks",
      "Lambda vs Kappa architectures",
      "Stream joins and state stores",
      "Schema registries and evolution",
      "Build a stream processor from scratch"
    ]
  },
  {
    id: 13, slug: "13-observability-and-reliability", emoji: "🔭", name: "Observability & Reliability",
    tagline: "Hope is not a strategy. Dashboards are.",
    lessons: [
      "The three pillars: logs, metrics, traces",
      "Structured logging done right",
      "Metrics and Prometheus",
      "Distributed tracing",
      "SLIs, SLOs, and error budgets",
      "Alerting without fatigue",
      "Health checks and probes",
      "Graceful degradation and feature flags",
      "Chaos engineering",
      "Incident response",
      "Blameless postmortems",
      "Disaster recovery: RTO and RPO"
    ]
  },
  {
    id: 14, slug: "14-security", emoji: "🔐", name: "Security & Identity",
    tagline: "Every box in your diagram is a door someone will try.",
    lessons: [
      "Threat modeling for architects",
      "Authentication: sessions, tokens, JWTs",
      "OAuth 2.0 and OpenID Connect",
      "Authorization: RBAC, ABAC, and policy engines",
      "Encryption in transit and at rest",
      "Secrets management",
      "DDoS protection",
      "OWASP for system designers",
      "Zero trust architecture",
      "Compliance and data privacy by design"
    ]
  },
  {
    id: 15, slug: "15-cloud-and-infrastructure", emoji: "☁️", name: "Cloud, Containers & Infrastructure",
    tagline: "Someone else's computer, industrialized.",
    lessons: [
      "VMs vs containers",
      "Docker internals: namespaces and cgroups",
      "Kubernetes architecture",
      "Kubernetes patterns: deployments to operators",
      "Serverless and FaaS",
      "Infrastructure as code",
      "CI/CD pipelines",
      "Blue-green and canary deployments",
      "Multi-region architectures",
      "Cell-based architecture",
      "Edge computing",
      "Cloud cost optimization"
    ]
  },
  {
    id: 16, slug: "16-performance-engineering", emoji: "🏎️", name: "Performance Engineering",
    tagline: "Milliseconds are money. Percentiles are truth.",
    lessons: [
      "Profiling and flame graphs",
      "Queueing theory and Little's Law",
      "Tail latency: the tyranny of p99",
      "Connection pooling",
      "Batching and pipelining",
      "Compression tradeoffs",
      "Capacity planning",
      "Load testing that means something",
      "Runtime tuning: GC, JIT, and friends",
      "The performance review checklist"
    ]
  },
  {
    id: 17, slug: "17-case-studies", emoji: "🏗️", name: "Case Studies — Design the Classics",
    tagline: "Every famous system, taken apart and rebuilt on a whiteboard.",
    lessons: [
      "Design a URL shortener",
      "Design Pastebin",
      "Design a distributed rate limiter",
      "Design a notification system",
      "Design a news feed",
      "Design a chat system (WhatsApp)",
      "Design Twitter/X",
      "Design Instagram",
      "Design YouTube",
      "Design Dropbox / Google Drive",
      "Design Uber",
      "Design Ticketmaster",
      "Design a payment system",
      "Design a web crawler",
      "Design Google Docs (collaborative editing)",
      "Design an ad-click aggregator"
    ]
  },
  {
    id: 18, slug: "18-interview-mastery", emoji: "🎤", name: "Interview Mastery",
    tagline: "45 minutes, one whiteboard, zero panic.",
    lessons: [
      "The 4-step interview framework",
      "Requirements clarification: questions that impress",
      "Capacity estimation drills",
      "High-level design, then deep dives",
      "The tradeoff vocabulary",
      "Communication and whiteboard craft",
      "Leveling: what L4 vs L5 vs L6 answers look like",
      "Mock interview rubrics and self-grading"
    ]
  },
  {
    id: 19, slug: "19-capstones", emoji: "🏆", name: "Capstone Projects",
    tagline: "Stop reading. Start building. Ship all of it.",
    lessons: [
      "Capstone: a distributed key-value store",
      "Capstone: an end-to-end chat system",
      "Capstone: a URL shortener, deployed",
      "Capstone: a metrics pipeline",
      "Capstone: a mini CDN",
      "Capstone: a distributed job scheduler",
      "Capstone: a feature-flag service",
      "Capstone: the grand design (your system, defended)"
    ]
  }
];

const STATS = {
  lessons: CURRICULUM.reduce((n, p) => n + p.lessons.length, 0),
  phases: CURRICULUM.length,
  codeExamples: 12,
  hours: 180
};
