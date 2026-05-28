<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 CAP Authors
-->

# Governance — `cap-reference`

This repository follows the CAP project umbrella governance defined in
[cap-spec/GOVERNANCE.md](../cap-spec/GOVERNANCE.md).

Repository-specific points:

## Maintainership

`cap-reference` is maintained per-SDK. The Python SDK and C++ SDK may
have distinct maintainer groups long-term; for now, all SDKs share the
CAP steering committee.

Domain Pack contributors (per [ADR-011](../cap-spec/docs/adr/011-domain-pack-architecture.md))
are expected to maintain their per-Domain-Pack SDK module (e.g.,
`python/cap_sdk_agriculture/`) for at least 12 months after acceptance.

## Decision authority

| Decision | Authority |
|---|---|
| New SDK feature within Core | Maintainer review |
| New SDK feature requiring Core proto change | RFC in cap-spec |
| New Domain Pack SDK module | Domain Pack RFC in cap-spec + Pack maintainer commitment |
| C++ ABI policy change | Steering committee + RFC |
| Adding a new language SDK (Rust, Go, ...) | RFC + maintainer commitment |

## Stability

SDK MAJOR bumps are decoupled from proto majors per
[ADR-008](../cap-spec/docs/adr/008-versioning.md). The reference SDKs
follow SemVer; the compatibility matrix between SDK and Core proto
versions is pinned in
[cap-spec/docs/compatibility.md](../cap-spec/docs/compatibility.md).
