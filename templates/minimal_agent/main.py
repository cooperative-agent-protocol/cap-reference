# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Minimal CAP Machine Agent — connect, receive WorkOrders, report progress.

Copy this template and modify it to build your own Machine Agent.
See: cap-spec/docs/specification/ for the full protocol specification.

Usage:
    CAP_SERVER=localhost:50051 python main.py
"""

import asyncio
import logging
import os

from cap.v0.core import (
    runtime_pb2,
    common_pb2,
    machine_agent_pb2,
    events_pb2,
    site_agent_pb2,
)
from cap_sdk.client import MachineAgentClient
from cap_sdk.frame import make_header, wrap_work_order_ack, wrap_progress_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MACHINE_ID = os.environ.get("CAP_MACHINE_ID", "my-machine-01")
SERVER = os.environ.get("CAP_SERVER", "localhost:50051")


# ─── Define your machine's capabilities ──────────────────────────────

manifest = machine_agent_pb2.CapabilityManifest(
    machine_id=MACHINE_ID,
    machine_type=common_pb2.MACHINE_TYPE_EXCAVATOR,
    capabilities=[
        machine_agent_pb2.Capability(skill="construction.excavate_batch"),
    ],
    current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
    hal_profile="template/minimal",
    software_version="0.1.0",
)


# ─── Define heartbeat (called every 5 seconds) ──────────────────────

def heartbeat() -> machine_agent_pb2.Heartbeat:
    return machine_agent_pb2.Heartbeat(
        machine_id=MACHINE_ID,
        current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
        healthy=True,
        estop_active=False,
        fuel_or_battery_percent=90.0,
    )


# ─── Handle incoming messages from Site Agent ────────────────────────

async def on_frame(frame: runtime_pb2.CapFrame):
    """Process incoming CapFrame from the Site Agent."""

    # WorkOrder received → accept and execute
    if frame.HasField("work_order"):
        wo = frame.work_order
        logger.info("Received WorkOrder: task=%s, skill=%s", wo.task_id, wo.skill)

        # Send ACK (ACCEPTED)
        header = make_header(sender_id=MACHINE_ID, receiver_id=frame.header.sender_id)
        ack = machine_agent_pb2.WorkOrderAck(
            task_id=wo.task_id,
            machine_id=MACHINE_ID,
            status=machine_agent_pb2.WorkOrderAck.ACCEPTED,
        )
        return wrap_work_order_ack(header, ack)

    # ModeCommand → log it
    if frame.HasField("mode_command"):
        mc = frame.mode_command
        logger.info("ModeCommand: target=%s", common_pb2.MachineMode.Name(mc.target_mode))

    return None


# ─── Run the agent ───────────────────────────────────────────────────

async def main():
    client = MachineAgentClient(
        machine_id=MACHINE_ID,
        site_agent_id="site-agent-01",
        server_address=SERVER,
        manifest=manifest,
        heartbeat_fn=heartbeat,
        on_frame=on_frame,
    )

    logger.info("Starting minimal machine agent: %s → %s", MACHINE_ID, SERVER)
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
