"""Spec <-> code refinement: the reference ReservationManager refines the
TLA+ reservation semantics over randomized operation traces.

This is the implementation-side counterpart of the formal models
``cap-spec/formal/tla/CAPCoordination`` (queued-fair grants, NoDoubleGrant) and
``ReservationFencing`` (monotonic grant epoch / fencing token). It closes the
spec<->code gap the way model-based conformance testing does: we drive the
*real* ``ReservationManager`` and an **independent, minimal port of the TLA+
transition relation** through the same seeded sequence of operations and assert
they agree on every observable (holder, grant epoch, status, queue position) at
every step, and that the abstract invariants hold throughout. By equivalence the
real implementation satisfies them too.

The abstract model below is a deliberately tiny, auditable re-statement of the
TLA+ guards (it is NOT the implementation under test); divergence on any trace
fails the test. This is operational refinement over many traces, not a TLC
refinement proof — but it exercises the actual shipped arbiter against the
verified semantics, which a TLC proof over an abstract model does not.
"""

from __future__ import annotations

import copy
import random

from cap.v0.core import events_pb2, site_agent_pb2

from cap_sdk.reservation import ReservationManager

_STATE = events_pb2.ReservationStatus.ReservationState


class AbstractReservation:
    """Minimal port of the TLA+ reservation transition relation (queued regime).

    Guards (cf. CAPCoordination.GrantResource / DenyResource and the queued
    discipline; ReservationFencing for the epoch):
      * Grant requires the resource free (holder == None); on grant the
        per-resource epoch is incremented (monotonic fencing token).
      * A busy resource queues (FIFO-with-priority); on release the head of the
        queue is granted (epoch increments again).
      * NoDoubleGrant: at most one holder per resource at any instant.
    """

    def __init__(self) -> None:
        self.holder: dict[str, str | None] = {}
        self.epoch: dict[str, int] = {}
        self.queue: dict[str, list[tuple[int, int, str, str]]] = {}  # res -> [(-prio, seq, rid, holder)]
        self.resource_of: dict[str, str] = {}
        self.holder_of: dict[str, str] = {}
        self._seq = 0

    def _grant(self, rid: str, res: str, holder: str) -> tuple:
        self.epoch[res] = self.epoch.get(res, 0) + 1
        self.holder[res] = holder
        self.resource_of[rid] = res
        self.holder_of[rid] = holder
        return ("GRANTED", res, holder, self.epoch[res], 0)

    def request(self, rid: str, res: str, holder: str, priority: int) -> tuple:
        if self.holder.get(res) is None:
            return self._grant(rid, res, holder)
        # busy -> queue (FIFO-with-priority)
        self._seq += 1
        q = self.queue.setdefault(res, [])
        q.append((-priority, self._seq, rid, holder))
        q.sort()
        self.resource_of[rid] = res
        self.holder_of[rid] = holder
        pos = next(i for i, w in enumerate(q) if w[2] == rid) + 1
        return ("QUEUED", res, holder, 0, pos)

    def release(self, rid: str) -> tuple | None:
        res = self.resource_of.get(rid)
        if res is None or self.holder.get(res) != self.holder_of.get(rid):
            return None
        self.holder[res] = None
        self.resource_of.pop(rid, None)
        self.holder_of.pop(rid, None)
        q = self.queue.get(res)
        if q:
            _, _, nrid, nholder = q.pop(0)
            return self._grant(nrid, res, nholder)
        return None


def _status_tuple(rs) -> tuple:
    name = _STATE.Name(rs.state).replace("RESERVATION_STATE_", "")
    return (name, rs.resource_id, rs.holder_id, rs.grant_epoch, rs.queue_position)


def _drive(seed: int, *, steps: int = 60) -> None:
    rng = random.Random(seed)
    real = ReservationManager(queued=True)
    abs = AbstractReservation()
    resources = ["LP-1", "LP-2"]
    machines = ["m1", "m2", "m3"]
    live: list[str] = []          # reservation_ids that have been requested
    rid_ctr = 0

    # Invariant accumulators
    seen_epoch: dict[str, int] = {}

    for _ in range(steps):
        if not live or rng.random() < 0.6:
            rid_ctr += 1
            rid = f"r{rid_ctr}"
            res = rng.choice(resources)
            holder = rng.choice(machines)
            prio = rng.randint(0, 2)
            req = site_agent_pb2.ReservationRequest(
                reservation_id=rid, resource_id=res, holder_id=holder, priority=prio
            )
            got = _status_tuple(real.request(req))
            exp = abs.request(rid, res, holder, prio)
            assert got == exp, f"REQUEST diverged seed={seed}: real={got} abstract={exp}"
            live.append(rid)
        else:
            rid = rng.choice(live)
            got_rs = real.release(rid)
            exp = abs.release(rid)
            got = _status_tuple(got_rs) if got_rs is not None else None
            assert got == exp, f"RELEASE diverged seed={seed}: real={got} abstract={exp}"

        # Abstract invariant: NoDoubleGrant — holder map is single-valued by
        # construction; assert the real arbiter agrees on every resource's holder.
        for res in resources:
            assert real.holder(res) == abs.holder.get(res), (
                f"holder diverged seed={seed} res={res}: "
                f"real={real.holder(res)} abstract={abs.holder.get(res)}"
            )
            # Monotonic fencing epoch: never decreases.
            e = real.current_epoch(res)
            assert e >= seen_epoch.get(res, 0), f"epoch regressed seed={seed} res={res}"
            seen_epoch[res] = e
            # Fencing: only the current epoch validates.
            if e > 0:
                assert real.validate_fence(res, e)
                assert not real.validate_fence(res, e - 1)  # stale epoch rejected


def test_reservation_refines_spec_many_traces():
    """The shipped ReservationManager refines the TLA+ reservation semantics
    over many randomized traces (step-by-step equivalence + invariants)."""
    for seed in range(200):
        _drive(seed)


def test_deny_regime_refinement():
    """Deny-on-busy regime: a busy resource is DENIED, never granted to a
    second holder (the regime the TLA+ model shows can starve, but which still
    upholds exclusivity)."""
    real = ReservationManager(queued=False)
    g = real.request(site_agent_pb2.ReservationRequest(
        reservation_id="a", resource_id="LP-1", holder_id="m1"))
    assert g.state == _STATE.RESERVATION_STATE_GRANTED
    d = real.request(site_agent_pb2.ReservationRequest(
        reservation_id="b", resource_id="LP-1", holder_id="m2"))
    assert d.state == _STATE.RESERVATION_STATE_DENIED
    assert real.holder("LP-1") == "m1"  # exclusivity upheld


def _check_invariants(real, abs, resources: list[str], seen_epoch: dict) -> None:
    """At every reached state: holder agreement, monotonic fencing epoch, fence validity."""
    for res in resources:
        assert real.holder(res) == abs.holder.get(res), (
            f"holder diverged res={res}: real={real.holder(res)} abstract={abs.holder.get(res)}")
        e = real.current_epoch(res)
        assert e >= seen_epoch.get(res, 0), f"epoch regressed res={res}"
        seen_epoch[res] = e
        if e > 0:
            assert real.validate_fence(res, e)
            assert not real.validate_fence(res, e - 1)  # only the current epoch validates


def _enumerate(real, abs, live: set, rid_ctr: int, depth: int, max_depth: int,
               machines: list[str], resources: list[str], seen_epoch: dict, stats: dict) -> None:
    """DFS over every reachable operation sequence (request/release) up to ``max_depth``,
    branching by deep-copy so each path is explored independently. At every node the shipped
    ReservationManager is asserted to agree with the abstract TLA+ port (REQUEST/RELEASE result
    + invariants). No randomness: this is exhaustive within the bound."""
    if depth >= max_depth or stats["n"] >= stats["cap"]:
        return
    ops = [("request", res, m) for res in resources for m in machines]
    ops += [("release", rid) for rid in sorted(live)]
    for op in ops:
        if stats["n"] >= stats["cap"]:
            return
        r2, a2 = copy.deepcopy(real), copy.deepcopy(abs)
        live2, se2, rc2 = set(live), dict(seen_epoch), rid_ctr
        if op[0] == "request":
            rc2 += 1
            rid = f"r{rc2}"
            got = _status_tuple(r2.request(site_agent_pb2.ReservationRequest(
                reservation_id=rid, resource_id=op[1], holder_id=op[2], priority=0)))
            exp = a2.request(rid, op[1], op[2], 0)
            assert got == exp, f"REQUEST diverged: real={got} abstract={exp}"
            live2.add(rid)
        else:
            got_rs = r2.release(op[1])
            exp = a2.release(op[1])
            got = _status_tuple(got_rs) if got_rs is not None else None
            assert got == exp, f"RELEASE diverged: real={got} abstract={exp}"
        _check_invariants(r2, a2, resources, se2)
        stats["n"] += 1
        _enumerate(r2, a2, live2, rc2, depth + 1, max_depth, machines, resources, se2, stats)


def test_exhaustive_small_traces():
    """Exhaustive (not sampled) refinement: enumerate EVERY reachable operation sequence up to a
    bounded length over a small machine/resource configuration, asserting the shipped
    ReservationManager agrees with the TLA+ transition-relation port at every step (holder, grant
    epoch, status, fencing). This complements the 200 randomized traces with full coverage of the
    small-instance state space, and the runtime monitor of the reference consumer with an
    exhaustive (rather than observed) check of the arbiter against the specification."""
    machines, resources = ["m1", "m2"], ["LP-1"]
    stats = {"n": 0, "cap": 200_000}
    _enumerate(ReservationManager(queued=True), AbstractReservation(), set(), 0, 0,
               6, machines, resources, {}, stats)
    assert stats["n"] > 200, f"expected a non-trivial exhaustive enumeration, got {stats['n']}"
    assert stats["n"] < stats["cap"], "enumeration hit the safety cap; the bound is not exhaustive"
