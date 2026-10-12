# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for CapRuntimeServicer lifecycle fixes: manifest-first
enforcement (Ch10 §10.2.1) and the heartbeat-timeout reaper."""

import asyncio
import time

from cap.v0.core import runtime_pb2, machine_agent_pb2, common_pb2
from cap_sdk.frame import make_header
from cap_sdk.server import CapRuntimeServicer, ConnectedMachine


class _FakeContext:
    """Minimal grpc.aio.ServicerContext stand-in (no mTLS)."""

    def auth_context(self):
        return {}


async def _aiter(frames):
    for f in frames:
        yield runtime_pb2.ConnectRequest(frame=f)


async def _noop_handler(machine_id, frame):
    return None


# ─── Manifest-first enforcement ──────────────────────────────────────

async def _premanifest_scenario():
    servicer = CapRuntimeServicer(on_frame=_noop_handler)
    # First frame is a Heartbeat, NOT a CapabilityManifest.
    hb = runtime_pb2.CapFrame(
        header=make_header(sender_id="m1", receiver_id="site-agent-01"),
        heartbeat=machine_agent_pb2.Heartbeat(machine_id="m1"),
    )
    return [r async for r in servicer.Connect(_aiter([hb]), _FakeContext())]


def test_manifest_first_rejects_premanifest_frame():
    responses = asyncio.run(_premanifest_scenario())
    assert len(responses) == 1
    err = responses[0].frame.cap_error
    assert err.error_code == 2006
    assert err.severity == common_pb2.FAULT_SEVERITY_CRITICAL


async def _manifest_first_ok_scenario():
    received = []

    async def handler(machine_id, frame):
        received.append(frame)
        return None

    servicer = CapRuntimeServicer(on_frame=handler)
    manifest = runtime_pb2.CapFrame(
        header=make_header(sender_id="m1", receiver_id="site-agent-01"),
        capability_manifest=machine_agent_pb2.CapabilityManifest(machine_id="m1"),
    )
    hb = runtime_pb2.CapFrame(
        header=make_header(sender_id="m1", receiver_id="site-agent-01"),
        heartbeat=machine_agent_pb2.Heartbeat(machine_id="m1"),
    )
    out = [r async for r in servicer.Connect(_aiter([manifest, hb]), _FakeContext())]
    return out, received


def test_manifest_first_allows_manifest_then_heartbeat():
    out, received = asyncio.run(_manifest_first_ok_scenario())
    # No CapError emitted; both frames dispatched.
    assert all(not r.frame.HasField("cap_error") for r in out)
    assert len(received) == 2


# ─── Heartbeat reaper ────────────────────────────────────────────────

async def _reaper_scenario():
    fired = []

    async def on_timeout(machine_id):
        fired.append(machine_id)

    servicer = CapRuntimeServicer(
        on_frame=_noop_handler,
        heartbeat_timeout=0.02,
        reaper_interval=0.02,
        on_machine_timeout=on_timeout,
    )
    m = ConnectedMachine("m1", heartbeat_timeout=0.02)
    m.last_heartbeat = time.monotonic() - 1.0  # already stale
    servicer._machines["m1"] = m

    servicer.start_reaper()
    await asyncio.sleep(0.12)
    await servicer.stop_reaper()
    return fired


def test_reaper_reports_timed_out_machine_once():
    fired = asyncio.run(_reaper_scenario())
    assert fired == ["m1"]  # reported exactly once despite multiple sweeps


# ─── Reconnection while an older stream is still open ────────────────

def _manifest_frame(mid="m1"):
    return runtime_pb2.CapFrame(
        header=make_header(sender_id=mid, receiver_id="site-agent-01"),
        capability_manifest=machine_agent_pb2.CapabilityManifest(machine_id=mid),
    )


def _heartbeat_frame(mid="m1"):
    return runtime_pb2.CapFrame(
        header=make_header(sender_id=mid, receiver_id="site-agent-01"),
        heartbeat=machine_agent_pb2.Heartbeat(machine_id=mid),
    )


async def _reconnect_scenario():
    servicer = CapRuntimeServicer(on_frame=_noop_handler)

    async def requests(queue):
        while (frame := await queue.get()) is not None:
            yield runtime_pb2.ConnectRequest(frame=frame)

    async def stream(queue, out):
        async for response in servicer.Connect(requests(queue), _FakeContext()):
            out.append(response)

    older_q, newer_q, older_out, newer_out = asyncio.Queue(), asyncio.Queue(), [], []
    older = asyncio.create_task(stream(older_q, older_out))
    await older_q.put(_manifest_frame())
    await asyncio.sleep(0.01)
    newer = asyncio.create_task(stream(newer_q, newer_out))      # the machine reconnected; the older stream stays open
    await newer_q.put(_manifest_frame())
    await asyncio.sleep(0.01)
    registered = servicer._machines["m1"]
    sent = runtime_pb2.ConnectResponse(frame=_heartbeat_frame("site-agent-01"))
    await servicer.send_to_machine("m1", sent)                   # for the machine as connected now
    await older_q.put(_heartbeat_frame())                         # the older stream goes on, then ends
    await asyncio.sleep(0.01)
    await older_q.put(None)
    await older
    still = servicer._machines.get("m1")
    await newer_q.put(_heartbeat_frame())
    await asyncio.sleep(0.01)
    await newer_q.put(None)
    await newer
    return registered, still, older_out, newer_out, sent, dict(servicer._machines)


def test_a_stream_that_ends_after_its_machine_reconnected_leaves_the_newer_registration():
    """A machine reconnected while its older stream was still open (its link broke on its side first): the older
    stream took the messages queued for the newer one and, when it ended, removed the newer registration - the Site
    could no longer send to a machine connected to it."""
    registered, still, older_out, newer_out, sent, left = asyncio.run(_reconnect_scenario())
    assert still is registered                                   # the newer registration stays
    assert sent not in older_out and sent in newer_out           # its message went out on the newer stream
    assert "m1" not in left                                      # and goes when that stream ends
