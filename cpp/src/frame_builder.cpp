// Copyright 2026 CAP Authors
// SPDX-License-Identifier: Apache-2.0

#include "cap_sdk_core/frame_builder.h"

#include <chrono>
#include <random>
#include <sstream>
#include <iomanip>

#include <google/protobuf/timestamp.pb.h>

namespace cap::sdk {

namespace {

std::string generate_uuid() {
    static std::random_device rd;
    static std::mt19937 gen(rd());
    static std::uniform_int_distribution<uint64_t> dis;

    uint64_t a = dis(gen);
    uint64_t b = dis(gen);

    std::ostringstream ss;
    ss << std::hex << std::setfill('0')
       << std::setw(8) << (a >> 32) << "-"
       << std::setw(4) << ((a >> 16) & 0xFFFF) << "-"
       << std::setw(4) << (a & 0xFFFF) << "-"
       << std::setw(4) << (b >> 48) << "-"
       << std::setw(12) << (b & 0xFFFFFFFFFFFF);
    return ss.str();
}

google::protobuf::Timestamp now_timestamp() {
    auto now = std::chrono::system_clock::now();
    auto secs = std::chrono::duration_cast<std::chrono::seconds>(
        now.time_since_epoch());
    auto nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(
        now.time_since_epoch()) - std::chrono::duration_cast<std::chrono::nanoseconds>(secs);

    google::protobuf::Timestamp ts;
    ts.set_seconds(secs.count());
    ts.set_nanos(static_cast<int32_t>(nanos.count()));
    return ts;
}

}  // namespace

cap::v0::core::MessageHeader make_header(
    const std::string& sender_id,
    const std::string& receiver_id,
    const std::string& work_package_id,
    const std::string& plan_hash,
    const std::string& correlation_id) {
    cap::v0::core::MessageHeader header;
    header.set_message_id(generate_uuid());
    header.set_sender_id(sender_id);
    header.set_receiver_id(receiver_id);
    header.set_work_package_id(work_package_id);
    header.set_plan_hash(plan_hash);
    header.set_correlation_id(correlation_id);
    *header.mutable_sent_at() = now_timestamp();
    return header;
}

cap::v0::core::ConnectRequest wrap_work_order(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::WorkOrder& work_order) {
    cap::v0::core::ConnectRequest req;
    auto* frame = req.mutable_frame();
    *frame->mutable_header() = header;
    *frame->mutable_work_order() = work_order;
    return req;
}

cap::v0::core::ConnectRequest wrap_capability_manifest(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::CapabilityManifest& manifest) {
    cap::v0::core::ConnectRequest req;
    auto* frame = req.mutable_frame();
    *frame->mutable_header() = header;
    *frame->mutable_capability_manifest() = manifest;
    return req;
}

cap::v0::core::ConnectRequest wrap_heartbeat(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::Heartbeat& heartbeat) {
    cap::v0::core::ConnectRequest req;
    auto* frame = req.mutable_frame();
    *frame->mutable_header() = header;
    *frame->mutable_heartbeat() = heartbeat;
    return req;
}

cap::v0::core::ConnectRequest wrap_work_order_ack(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::WorkOrderAck& ack) {
    cap::v0::core::ConnectRequest req;
    auto* frame = req.mutable_frame();
    *frame->mutable_header() = header;
    *frame->mutable_work_order_ack() = ack;
    return req;
}

cap::v0::core::ConnectRequest wrap_progress_event(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::ProgressEvent& event) {
    cap::v0::core::ConnectRequest req;
    auto* frame = req.mutable_frame();
    *frame->mutable_header() = header;
    *frame->mutable_progress_event() = event;
    return req;
}

cap::v0::core::ConnectRequest wrap_handover_event(
    const cap::v0::core::MessageHeader& header,
    const cap::v0::core::HandoverEvent& event) {
    cap::v0::core::ConnectRequest req;
    auto* frame = req.mutable_frame();
    *frame->mutable_header() = header;
    *frame->mutable_handover_event() = event;
    return req;
}

}  // namespace cap::sdk
