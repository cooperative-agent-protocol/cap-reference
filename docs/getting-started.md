<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 CAP Authors
-->

# Build Your First CAP Machine Agent

This guide walks you through building a minimal Machine Agent that connects to
a CAP Site Agent, receives WorkOrders, and reports progress.

## Prerequisites

- Python 3.11+
- The `cap-reference` package installed:
  ```bash
  cd cap-reference/python
  pip install -e .
  ```

## Architecture Overview

```
Site Agent (gRPC server)        Machine Agent (gRPC client)
    │                                │
    │ ← CapabilityManifest ──────────│  (on connect)
    │ ← Heartbeat ───────────────────│  (every 5s)
    │ ── WorkOrder ─────────────────→│
    │ ← WorkOrderAck(ACCEPTED) ─────│
    │ ← ProgressEvent(RUNNING) ─────│
    │ ← ProgressEvent(SUCCEEDED) ───│
```

## Step 1: Define Your Machine's Capabilities

```python
from cap.v0 import common_pb2, machine_agent_pb2

manifest = machine_agent_pb2.CapabilityManifest(
    machine_id="my-excavator-01",
    machine_type=common_pb2.MACHINE_TYPE_EXCAVATOR,
    capabilities=[
        machine_agent_pb2.Capability(skill="excavate_batch"),
    ],
    current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
    hal_profile="my-company/pc200",
    software_version="1.0.0",
)
```

The `CapabilityManifest` is the first message sent on connection. It tells the
Site Agent what your machine can do. See Ch07 for all fields.

## Step 2: Define the Heartbeat

```python
def heartbeat() -> machine_agent_pb2.Heartbeat:
    return machine_agent_pb2.Heartbeat(
        machine_id="my-excavator-01",
        current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
        healthy=True,
        fuel_or_battery_percent=85.0,
    )
```

Heartbeats are sent automatically every 5 seconds (configurable). If the
Site Agent doesn't receive a heartbeat within 15 seconds, it marks the
machine as disconnected (Ch08 §8.3.2).

## Step 3: Handle Incoming Messages

```python
async def on_frame(frame):
    if frame.HasField("work_order"):
        wo = frame.work_order
        print(f"Received WorkOrder: {wo.task_id}, skill={wo.skill}")

        # Accept the work order
        header = make_header(sender_id="my-excavator-01", receiver_id="site-agent-01")
        ack = machine_agent_pb2.WorkOrderAck(
            task_id=wo.task_id,
            machine_id="my-excavator-01",
            status=machine_agent_pb2.WorkOrderAck.ACCEPTED,
        )
        return wrap_work_order_ack(header, ack)

    return None
```

The `on_frame` callback is called for every message from the Site Agent.
You MUST respond to WorkOrders with an ACK (Ch06 §6.1.3).

## Step 4: Connect and Run

```python
from cap_sdk.client import MachineAgentClient

client = MachineAgentClient(
    machine_id="my-excavator-01",
    site_agent_id="site-agent-01",
    server_address="localhost:50051",
    manifest=manifest,
    heartbeat_fn=heartbeat,
    on_frame=on_frame,
)

asyncio.run(client.run())
```

## Step 5: Run the Demo

Start the fake site agent:
```bash
cd cap-reference
docker-compose up site-agent
```

In another terminal, run your agent:
```bash
python templates/minimal_agent/main.py
```

## Adding TLS/mTLS (Conformance Level 2+)

For production deployments, enable mTLS per Ch09:

```python
client = MachineAgentClient(
    machine_id="my-excavator-01",
    site_agent_id="site-agent-01",
    server_address="site-agent.example.com:50051",
    manifest=manifest,
    heartbeat_fn=heartbeat,
    on_frame=on_frame,
    tls_ca_path="certs/ca.pem",
    tls_cert_path="certs/my-excavator-01.pem",
    tls_key_path="certs/my-excavator-01-key.pem",
)
```

Generate certificates:
```python
from cap_sdk.security.cert_gen import generate_site_certs
generate_site_certs("my-site", ["my-excavator-01"], output_dir="certs")
```

## Adding Message Validation

Use the validator to check your messages before sending:

```python
from cap_sdk.validator import validate_frame, validate_state_transition

errors = validate_frame(frame)
if errors:
    print(f"Invalid frame: {errors}")

valid, reason = validate_state_transition(TASK_STATE_RUNNING, TASK_STATE_SUCCEEDED)
```

## Next Steps

- Read the full specification: `cap-spec/docs/specification/`
- Explore the fake agents: `cap-reference/agents/`
- Run conformance tests: `cd cap-conformance && pytest`
- Add LLM-based situation awareness: see `cap_sdk.machine_model`
