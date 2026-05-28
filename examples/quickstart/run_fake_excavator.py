# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Quickstart: a fake construction excavator Machine Agent.

Thin (~60 LoC) wrapper around the bundled ``FakeMachineModel`` (rule-based,
no API key) + ``MachineAgentClient``. Connects to a CAP runtime, advertises
the ``construction.excavate_batch`` skill, accepts WorkOrders, and reports
fabricated progress.

This is intentionally minimal — it reuses the canonical fake model from
``cap_sdk.machine_model_construction_fake`` rather than reimplementing
agent logic. For your own agent, copy ``templates/minimal_agent/main.py``.

Usage:
    CAP_SERVER=localhost:50051 CAP_MACHINE_ID=zx120-01 \
        python run_fake_excavator.py
"""

import asyncio
import logging
import os

from cap.v0.core import common_pb2, machine_agent_pb2, runtime_pb2
from cap_sdk.client import MachineAgentClient
from cap_sdk.frame import make_header, wrap_work_order_ack
from cap_sdk.machine_model_construction_fake import FakeMachineModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quickstart.excavator")

MACHINE_ID = os.environ.get("CAP_MACHINE_ID", "zx120-01")
SERVER = os.environ.get("CAP_SERVER", "localhost:50051")
SITE_AGENT = os.environ.get("CAP_SITE_AGENT", "site-agent-01")

_model = FakeMachineModel()

manifest = machine_agent_pb2.CapabilityManifest(
    machine_id=MACHINE_ID,
    machine_type=common_pb2.MACHINE_TYPE_EXCAVATOR,
    capabilities=[machine_agent_pb2.Capability(skill="construction.excavate_batch")],
    current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
    hal_profile="quickstart/fake",
    software_version="0.1.0",
)


def heartbeat() -> machine_agent_pb2.Heartbeat:
    return machine_agent_pb2.Heartbeat(
        machine_id=MACHINE_ID,
        current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
        healthy=True,
        estop_active=False,
        fuel_or_battery_percent=95.0,
    )


async def on_frame(frame: runtime_pb2.CapFrame):
    if frame.HasField("work_order"):
        wo = frame.work_order
        logger.info("WorkOrder task=%s skill=%s — accepting", wo.task_id, wo.skill)
        header = make_header(sender_id=MACHINE_ID, receiver_id=frame.header.sender_id)
        ack = machine_agent_pb2.WorkOrderAck(
            task_id=wo.task_id,
            machine_id=MACHINE_ID,
            status=machine_agent_pb2.WorkOrderAck.ACCEPTED,
        )
        return wrap_work_order_ack(header, ack)
    return None


async def main():
    client = MachineAgentClient(
        machine_id=MACHINE_ID,
        site_agent_id=SITE_AGENT,
        server_address=SERVER,
        manifest=manifest,
        heartbeat_fn=heartbeat,
        on_frame=on_frame,
        model=_model,  # bundled rule-based fake (no API key)
    )
    logger.info("Quickstart excavator %s → %s", MACHINE_ID, SERVER)
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
