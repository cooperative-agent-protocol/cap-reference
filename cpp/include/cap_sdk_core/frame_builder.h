// Copyright 2026 CAP Authors
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>
#include "cap/v0/core/common.pb.h"
#include "cap/v0/core/runtime.pb.h"
#include "cap/v0/core/site_agent.pb.h"
#include "cap/v0/core/machine_agent.pb.h"
#include "cap/v0/core/events.pb.h"

namespace cap::sdk {

/// Create a MessageHeader with auto-generated message_id and current timestamp.
cap::v0::core::MessageHeader make_header(
    const std::string& sender_id,
    const std::string& receiver_id,
    const std::string& work_package_id = "",
    const std::string& plan_hash = "",
    const std::string& correlation_id = "");

/// Wrap a WorkOrder into a ConnectRequest.
cap::v0::core::ConnectRequest wrap_work_order(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::WorkOrder& work_order);

/// Wrap a CapabilityManifest into a ConnectRequest.
cap::v0::core::ConnectRequest wrap_capability_manifest(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::CapabilityManifest& manifest);

/// Wrap a Heartbeat into a ConnectRequest.
cap::v0::core::ConnectRequest wrap_heartbeat(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::Heartbeat& heartbeat);

/// Wrap a WorkOrderAck into a ConnectRequest.
cap::v0::core::ConnectRequest wrap_work_order_ack(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::WorkOrderAck& ack);

/// Wrap a ProgressEvent into a ConnectRequest.
cap::v0::core::ConnectRequest wrap_progress_event(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::ProgressEvent& event);

/// Wrap a HandoverEvent into a ConnectRequest.
cap::v0::core::ConnectRequest wrap_handover_event(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::HandoverEvent& event);

}  // namespace cap::sdk
