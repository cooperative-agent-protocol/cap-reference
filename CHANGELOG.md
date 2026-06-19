<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 CAP Authors
-->

# Changelog — `cap-reference`

[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format,
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) per
[cap-spec ADR-008](../cap-spec/docs/adr/008-versioning.md).

## [Unreleased]

### Added
- SPDX-License-Identifier headers across all sources.
- Repo-level governance: LICENSE, NOTICE, CODE_OF_CONDUCT.md,
  TRADEMARK_POLICY.md, `.github/` issue + PR templates, FUNDING.yml.
- Construction Domain Pack shim — file rename
  `machine_model_fake.py` → `machine_model_construction_fake.py` signals
  the construction-specific scope of the bundled fake LLM.

### Changed
- Python imports updated `from cap.v0 import ...` → `from cap.v0.core import ...`
  per cap-spec Phase 0.3 namespace reorganization.

### Pending
- C++ SDK v0.1 minimum viable: MachineAgentClient + validator + HAL ABC
  + CMake install + Conan recipe + ABI guard (Autonomous backlog A10).
- `cap-reference/examples/quickstart/` with platform-independent
  docker-compose and a 60-LoC wrapper around the bundled fake LLM.

## [0.1.0] — Unreleased
First public tag — planned alongside cap-spec v0.1.0.
