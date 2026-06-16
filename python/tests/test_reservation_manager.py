# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the reference ReservationManager (Ch06 §6.3).

Asserts the arbiter realises the formally verified semantics: queued-fair
grants (CAPCoordination, QueuedGrants=TRUE), a monotonically increasing
per-resource fencing epoch (ReservationFencing), and the OPTIONAL deny-on-busy
regime.
"""

from cap.v0.core import events_pb2, site_agent_pb2
from cap_sdk.reservation import ReservationManager

_STATE = events_pb2.ReservationStatus.ReservationState


def _req(rid, resource, holder, priority=0):
    return site_agent_pb2.ReservationRequest(
        reservation_id=rid, resource_id=resource, holder_id=holder, priority=priority
    )


def test_grant_free_resource_issues_epoch_1():
    m = ReservationManager()
    s = m.request(_req("r1", "LP-1", "exc1"))
    assert s.state == _STATE.RESERVATION_STATE_GRANTED
    assert s.grant_epoch == 1
    assert m.holder("LP-1") == "exc1"


def test_busy_resource_queues_in_default_regime():
    m = ReservationManager()  # queued by default
    m.request(_req("r1", "LP-1", "exc1"))
    s = m.request(_req("r2", "LP-1", "dump1"))
    assert s.state == _STATE.RESERVATION_STATE_QUEUED
    assert s.queue_position == 1


def test_release_grants_next_queued_with_monotonic_epoch():
    m = ReservationManager()
    g1 = m.request(_req("r1", "LP-1", "exc1"))
    m.request(_req("r2", "LP-1", "dump1"))
    g2 = m.release("r1")
    assert g2 is not None
    assert g2.state == _STATE.RESERVATION_STATE_GRANTED
    assert g2.holder_id == "dump1"
    # Fencing epoch is monotonic across grants on the same resource.
    assert g2.grant_epoch == g1.grant_epoch + 1 == 2
    assert m.holder("LP-1") == "dump1"


def test_queue_is_fifo_with_priority():
    m = ReservationManager()
    m.request(_req("r1", "LP-1", "exc1"))           # holder
    m.request(_req("r2", "LP-1", "low", priority=0))   # queued, low priority, first
    s_hi = m.request(_req("r3", "LP-1", "high", priority=5))  # higher priority jumps ahead
    assert s_hi.queue_position == 1
    nxt = m.release("r1")
    assert nxt.holder_id == "high"  # priority served before the earlier low-priority waiter


def test_deny_regime_denies_busy_resource():
    m = ReservationManager(queued=False)
    m.request(_req("r1", "LP-1", "exc1"))
    s = m.request(_req("r2", "LP-1", "dump1"))
    assert s.state == _STATE.RESERVATION_STATE_DENIED


def test_fencing_rejects_stale_epoch():
    m = ReservationManager()
    g1 = m.request(_req("r1", "LP-1", "exc1"))       # epoch 1
    m.release("r1")
    m.request(_req("r2", "LP-1", "dump1"))           # epoch 2
    # The first holder's token (epoch 1) is now stale and must be rejected;
    # the current holder's token (epoch 2) is accepted.
    assert m.validate_fence("LP-1", g1.grant_epoch) is False
    assert m.validate_fence("LP-1", 2) is True


def test_release_unknown_is_noop():
    m = ReservationManager()
    assert m.release("nope") is None
