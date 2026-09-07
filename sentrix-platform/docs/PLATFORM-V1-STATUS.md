# SentriX Platform V1 — implementation status

This document mirrors the frozen P0→P6 specification and distinguishes
**deterministic CI proof** from **live external proof**.

- P0: PostgreSQL tenancy/RLS/FK suite (existing CI).
- P1: gVisor execution-plane isolation and quota gate (existing CI).
- P2: GitHub webhook HMAC plus durable PostgreSQL dedup, pre-build token scan,
  content-addressed releases, executable managed build worker and disposable
  gVisor dependency sandbox on a dedicated SentriX-managed egress network.
- P3: IdentifyBroker state machine, conservative budget accounting, bucket
  serialization and crash-loop breaker. A live Discord counter comparison needs
  a dedicated Discord application/token and cannot be fabricated in CI.
- P4: executable deployment orchestrator, durable control queues, leases,
  attempts, fencing, idempotent handover effects, generation-aware health and
  automatic rollback to the previous immutable image. A rollback is terminal
  only after the restored generation itself reports healthy.
- P5: envelope-encrypted secrets, write-only public view, tmpfs provider,
  environment compatibility provider, log redaction/quota, usage samples and
  Discord alert payloads.
- P6: distinct-application canary gate, configurable bake time, destructive SQL
  guard with explicit human confirmation, dashboard health-level model and
  managed runtime templates for Python/JavaScript.

## Hosting execution chain

The repository now contains the complete control flow:

`GitHub push → HMAC ingress → durable build queue → gVisor builder → immutable
release digest → deployment queue → orchestrator → node desired state → gVisor
runtime → node health report → success or verified rollback`.

Global machine workers do not receive `BYPASSRLS`. Their machine credentials are
stored only as SHA-256 digests. Private non-RLS control queues expose only routing
metadata; after a worker claims one item, the SECURITY DEFINER function sets
`app.current_org` transaction-locally before accessing tenant tables.

The builder and runtime node are deliberately separate trust boundaries. The
builder may download untrusted project dependencies and therefore belongs on a
dedicated Linux worker. Dependency installers run under gVisor on a dedicated
`sentrix-build-*` Docker bridge labelled `sentrix.managed=true`; the host egress
policy is applied before any dependency sandbox starts and blocks cloud metadata,
link-local, RFC1918/private ranges, CGNAT and configured control-plane CIDRs.
The real P2 gVisor CI proof exercises that managed network rather than replacing
it with `--network=none`.

Build lease retries are also fenced outside PostgreSQL: every registry push uses
an attempt-scoped tag containing the build id and lease attempt, so a stale worker
cannot share the same mutable registry tag with the current lease holder. The
release identity remains the immutable registry digest.

Builder, orchestrator and node-agent machine credentials may use plain HTTP only
for localhost development. Remote control-plane/API URLs must use HTTPS so worker
or node tokens are not transmitted in clear text.

Hosting read access remains tenant-scoped. Operational mutations (queue build,
deploy, start/stop/restart, GitHub target refresh) and secret metadata are limited
to organisation `owner`/`admin`; a plain `member` is denied before mutation.

The node-agent runs tenant bot images and enforces the runtime sandbox. Neither
the builder nor runtime node executes tenant Docker workloads inside the API
service.

## What CI proves and what still needs live credentials

The deterministic V1 gate proves migrations, RLS isolation, PostgreSQL runtime
state transitions, HMAC/dedup behavior, RBAC contracts, worker transport rules,
gVisor sandbox contracts and the full build/release/deployment/agent state machine
without requiring customer secrets.

A real registry push, a real private GitHub checkout, a Discord Gateway session
and provider-level VPS failure cannot be fabricated by deterministic CI. Those
are deployment acceptance tests and require explicit infrastructure credentials.
A green unit/integration gate must never be presented as proof that those third
parties accepted a live session.

The branch-level `SentriX Platform V1 Gate` is the authoritative integrated
verification gate. P2→P6 must not be promoted from this branch while that gate
is red.
