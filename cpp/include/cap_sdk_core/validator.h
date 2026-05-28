// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors
//
// Header-only message validators for CAP-Core. Ports the validation rules
// from the Python reference (cap_sdk/validator.py). Each validator returns
// an empty string on success or a human-readable error on failure.
//
// Header-only at v0.1 (per ADR-011 C++ ABI decision); compiled PImpl
// internals arrive at v0.2.

#pragma once

#include <string>
#include <vector>

#include "cap/v0/core/common.pb.h"
#include "cap/v0/core/machine_agent.pb.h"
#include "cap/v0/core/site_agent.pb.h"
#include "cap/v0/core/events.pb.h"
#include "cap/v0/core/runtime.pb.h"

namespace cap::sdk {

/// Result of a validation: ok() == true means valid.
struct ValidationResult {
  bool valid = true;
  std::string error;

  static ValidationResult ok() { return {true, ""}; }
  static ValidationResult fail(const std::string& msg) { return {false, msg}; }
  explicit operator bool() const { return valid; }
};

// ─── CapabilityManifest ──────────────────────────────────────────────

inline ValidationResult validate_manifest(
    const cap::v0::core::CapabilityManifest& m) {
  if (m.machine_id().empty()) {
    return ValidationResult::fail("CapabilityManifest.machine_id is required");
  }
  if (m.machine_type() == cap::v0::core::MACHINE_TYPE_UNSPECIFIED) {
    return ValidationResult::fail(
        "CapabilityManifest.machine_type must not be UNSPECIFIED");
  }
  return ValidationResult::ok();
}

// ─── Heartbeat ───────────────────────────────────────────────────────

inline ValidationResult validate_heartbeat(
    const cap::v0::core::Heartbeat& h) {
  if (h.machine_id().empty()) {
    return ValidationResult::fail("Heartbeat.machine_id is required");
  }
  const double pct = h.fuel_or_battery_percent();
  if (pct < 0.0 || pct > 100.0) {
    return ValidationResult::fail(
        "Heartbeat.fuel_or_battery_percent out of range [0,100]");
  }
  return ValidationResult::ok();
}

// ─── WorkOrder ───────────────────────────────────────────────────────

inline ValidationResult validate_work_order(
    const cap::v0::core::WorkOrder& wo) {
  if (wo.task_id().empty()) {
    return ValidationResult::fail("WorkOrder.task_id is required");
  }
  if (wo.skill().empty()) {
    return ValidationResult::fail("WorkOrder.skill is required");
  }
  return ValidationResult::ok();
}

// ─── ProgressEvent ───────────────────────────────────────────────────

inline ValidationResult validate_progress_event(
    const cap::v0::core::ProgressEvent& ev) {
  if (ev.task_id().empty()) {
    return ValidationResult::fail("ProgressEvent.task_id is required");
  }
  const double r = ev.completion_ratio();
  if (r < 0.0 || r > 1.0) {
    return ValidationResult::fail(
        "ProgressEvent.completion_ratio out of range [0,1]");
  }
  return ValidationResult::ok();
}

// ─── TaskState transition ────────────────────────────────────────────
//
// Mirrors the normative state machine in cap-spec Ch06. Terminal states
// (SUCCEEDED / FAILED / CANCELLED) absorb; no further transition allowed.

inline bool is_terminal_task_state(cap::v0::core::TaskState s) {
  return s == cap::v0::core::TASK_STATE_SUCCEEDED ||
         s == cap::v0::core::TASK_STATE_FAILED ||
         s == cap::v0::core::TASK_STATE_CANCELLED ||
         s == cap::v0::core::TASK_STATE_REJECTED ||
         s == cap::v0::core::TASK_STATE_EXPIRED;
}

inline ValidationResult validate_task_transition(
    cap::v0::core::TaskState from, cap::v0::core::TaskState to) {
  if (from == to) {
    return ValidationResult::ok();  // idempotent no-op
  }
  if (is_terminal_task_state(from)) {
    return ValidationResult::fail(
        "Invalid TaskState transition: cannot leave a terminal state");
  }
  return ValidationResult::ok();
}

}  // namespace cap::sdk
