<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 CAP Authors
-->

# Contributing to `cap-reference`

Thank you for your interest. The CAP project's umbrella contribution
rules are in [cap-spec/CONTRIBUTING.md](../cap-spec/CONTRIBUTING.md);
this document covers reference-SDK-specific points.

## DCO

All commits must be signed off with `git commit -s`. See the upstream
DCO section in [cap-spec/CONTRIBUTING.md](../cap-spec/CONTRIBUTING.md).

## SPDX headers

All source files carry `SPDX-License-Identifier: Apache-2.0`. New files
must follow the same pattern. Use `scripts/add_spdx_headers.sh` if
helpful.

## Project layout

```
cap-reference/
├── python/      Python SDK (Core + Construction Domain Pack)
├── cpp/         C++ SDK (Core + Construction Domain Pack)
├── ts/          TypeScript SDK
├── templates/   Minimal agent templates
└── examples/    Quick-start examples (post-A9)
```

## How to contribute

### Python SDK

- Source: `python/cap_sdk/`.
- Tests: `python/tests/` — run with `pytest`.
- Dependencies via `python/pyproject.toml`. Avoid adding heavy
  dependencies without prior discussion (file a feature issue first).

### C++ SDK

- Source: `cpp/include/` (headers) + `cpp/src/` (compiled units).
- The v0.1 target is header-only; please keep new public APIs in headers
  with inline definitions unless there's a good reason otherwise.
- Build with `cmake -B build && cmake --build build`.

### TypeScript SDK

- Source: `ts/src/`.
- Build with `npm install && npm run build`.

## Domain Pack contributions

Construction is the v0 reference Domain Pack. To propose a new Domain
Pack (Agriculture, Mining, Forestry, Intralogistics, ...), follow
[cap-spec/rfcs/domain-pack-template.md](../cap-spec/rfcs/domain-pack-template.md).
A new Domain Pack typically lands as `<lang>/cap_sdk_<domain>/`
alongside the existing `cap_sdk_construction/` namespace.

## Style

- Python: ruff + black-compatible.
- C++: clang-format with the in-repo style (`cpp/.clang-format` — to be
  added).
- TypeScript: tsc + prettier defaults.

## License

Contributions are Apache License 2.0 — see [LICENSE](LICENSE).
