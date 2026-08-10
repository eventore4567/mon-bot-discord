# SentriX Platform V1 — implementation status

This document mirrors the frozen P0→P6 specification and distinguishes
**deterministic CI proof** from **live external proof**.

- P0: PostgreSQL tenancy/RLS/FK suite (existing CI).
- P1: gVisor execution-plane isolation and quota gate (existing CI).
- P2: webhook HMAC/dedup, pre-build token scan, content-addressed releases,
  disposable gVisor build sandbox contract.
- P3: IdentifyBroker state machine, conservative budget accounting, bucket
  serialization and crash-loop breaker. A live Discord counter comparison needs
  a dedicated Discord application/token and cannot be fabricated in CI.
- P4: durable workflow semantics, leases, attempts, fencing, idempotent effects,
  automatic health rollback, runtime-aware handover planning.
- P5: envelope-encrypted secrets, write-only public view, tmpfs provider,
  environment compatibility provider, log redaction/quota, usage samples and
  Discord alert payloads.
- P6: distinct-application canary gate, configurable bake time, destructive SQL
  guard with explicit human confirmation, dashboard health-level model and
  managed runtime templates for Python/JavaScript.

The repository's deterministic V1 gate proves all logic that does not require
third-party credentials. Live P3/P6 validation is intentionally a separate gate:
a green unit test is never presented as evidence that Discord accepted a real
Gateway session.
