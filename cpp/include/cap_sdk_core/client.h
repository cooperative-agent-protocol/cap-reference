// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors
//
// MachineAgentClient — connects to a CAP runtime over the bidirectional
// streaming RPC CapRuntimeService.Connect, sends the CapabilityManifest,
// runs a heartbeat loop, and dispatches inbound CapFrames to a callback.
//
// v0.1: declaration + compiled implementation (client.cpp). gRPC bidi
// streaming is not practical to inline, so this is the one compiled unit
// alongside the header-only validator / hal. mTLS is interface-only at
// v0.1 (use_tls flag reserved); the secure-credentials path lands at v0.2.

#pragma once

#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <optional>
#include <string>

#include "cap/v0/core/common.pb.h"
#include "cap/v0/core/machine_agent.pb.h"
#include "cap/v0/core/runtime.pb.h"

namespace cap::sdk {

/// Configuration for a MachineAgentClient.
struct MachineAgentClientConfig {
  std::string machine_id;
  std::string site_agent_id = "site-agent-01";
  std::string server_address = "localhost:50051";
  std::chrono::milliseconds heartbeat_interval{5000};

  // mTLS (v0.2 — reserved at v0.1; ignored unless use_tls is set and the
  // v0.2 secure path is compiled in).
  bool use_tls = false;
  std::string ca_cert_path;
  std::string client_cert_path;
  std::string client_key_path;
};

/// Callback invoked for each inbound CapFrame. Returning a ConnectRequest
/// sends a reply on the stream; returning std::nullopt sends nothing.
using OnFrameCallback = std::function<std::optional<cap::v0::core::ConnectRequest>(
    const cap::v0::core::CapFrame&)>;

/// Callback producing the current Heartbeat (called every interval).
using HeartbeatCallback = std::function<cap::v0::core::Heartbeat()>;

class MachineAgentClient {
 public:
  MachineAgentClient(MachineAgentClientConfig config,
                     cap::v0::core::CapabilityManifest manifest,
                     HeartbeatCallback heartbeat_fn,
                     OnFrameCallback on_frame);
  ~MachineAgentClient();

  MachineAgentClient(const MachineAgentClient&) = delete;
  MachineAgentClient& operator=(const MachineAgentClient&) = delete;

  /// Connect, send the manifest, and run until stop() or stream end.
  /// Blocking; run on a dedicated thread if you need concurrency.
  void run();

  /// Request a graceful shutdown of the run loop.
  void stop();

 private:
  class Impl;                      // PImpl arrives in v0.2; fwd-declared now.
  std::unique_ptr<Impl> impl_;     // null at v0.1 (direct members below).

  MachineAgentClientConfig config_;
  cap::v0::core::CapabilityManifest manifest_;
  HeartbeatCallback heartbeat_fn_;
  OnFrameCallback on_frame_;
  std::atomic<bool> running_{false};
};

}  // namespace cap::sdk
