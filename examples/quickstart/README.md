<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 CAP Authors
-->

# CAP Quickstart

A self-contained, **cap-platform-independent** demo of the Cooperative
Agent Protocol with the Construction Domain Pack. Mounts only:

- `cap-spec/gen/python` — generated proto bindings
- `cap-reference/python` — the reference SDK

No production platform, no LLM API keys, no external services beyond an
MQTT broker.

## Run it

```bash
cd cap-reference/examples/quickstart
docker-compose up
```

You'll see:

1. The **runtime** servicer start on port 50051.
2. Two fake Machine Agents (`zx120-01` excavator, `ic120-01` dump truck)
   connect, send their `CapabilityManifest`, and begin emitting
   `Heartbeat` every 5 seconds.
3. The runtime logs each received frame.

## Run an agent locally (without Docker)

```bash
# Terminal 1 — runtime
cd cap-reference/python
PYTHONPATH=../../cap-spec/gen/python:. python -m cap_sdk.server

# Terminal 2 — fake excavator
cd cap-reference/examples/quickstart
PYTHONPATH=../../../cap-spec/gen/python:../../python \
  CAP_SERVER=localhost:50051 CAP_MACHINE_ID=zx120-01 \
  python run_fake_excavator.py
```

## What this demonstrates

- **CAP-Core**: manifest handshake, heartbeat loop, WorkOrder/Ack lifecycle.
- **Construction Domain Pack**: the `construction.excavate_batch` skill
  advertised in the manifest.
- **Reference fake model**: `FakeMachineModel` (rule-based, no API key) from
  `cap_sdk.machine_model_construction_fake`.

## Next steps

- Read the [minimal agent template](../../templates/minimal_agent/main.py)
  to build your own Machine Agent.
- Run the [conformance suite](../../../cap-conformance/) against this runtime:

  ```bash
  pytest cap-conformance --target grpc://localhost:50051 --domain construction
  ```

- Explore the [specification](https://cap-protocol.dev) (pending) and the
  [proto definitions](../../../cap-spec/proto/cap/v0/).

## Dependencies

The compose file installs `grpcio`, `protobuf>=7.35`, and `cryptography`
into ephemeral containers. For a persistent local setup, install the SDK:

```bash
pip install -e cap-reference/python
```
