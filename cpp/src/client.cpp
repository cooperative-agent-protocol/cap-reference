// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors
//
// MachineAgentClient implementation using the gRPC C++ synchronous
// bidi-streaming API. v0.1 uses the classic ClientReaderWriter (stable,
// widely supported). A v0.2 refactor may move to the callback API and
// add a PImpl + mTLS path.

#include "cap_sdk_core/client.h"

#include <thread>

#include <grpcpp/grpcpp.h>

#include "cap/v0/core/runtime.grpc.pb.h"
#include "cap_sdk_core/frame_builder.h"

namespace cap::sdk {

MachineAgentClient::MachineAgentClient(
    MachineAgentClientConfig config,
    cap::v0::core::CapabilityManifest manifest,
    HeartbeatCallback heartbeat_fn,
    OnFrameCallback on_frame)
    : config_(std::move(config)),
      manifest_(std::move(manifest)),
      heartbeat_fn_(std::move(heartbeat_fn)),
      on_frame_(std::move(on_frame)) {}

MachineAgentClient::~MachineAgentClient() { stop(); }

void MachineAgentClient::stop() { running_.store(false); }

void MachineAgentClient::run() {
  using cap::v0::core::CapRuntimeService;
  using cap::v0::core::ConnectRequest;
  using cap::v0::core::ConnectResponse;

  // v0.1: insecure channel only. mTLS (config_.use_tls) is reserved for
  // v0.2 — the secure-credentials path is not compiled in yet.
  auto channel = grpc::CreateChannel(config_.server_address,
                                     grpc::InsecureChannelCredentials());
  auto stub = CapRuntimeService::NewStub(channel);

  grpc::ClientContext context;
  std::shared_ptr<grpc::ClientReaderWriter<ConnectRequest, ConnectResponse>>
      stream(stub->Connect(&context));

  running_.store(true);

  // 1. Send the CapabilityManifest as the first frame.
  {
    auto header = make_header(config_.machine_id, config_.site_agent_id);
    ConnectRequest req = wrap_capability_manifest(header, manifest_);
    if (!stream->Write(req)) {
      running_.store(false);
      return;
    }
  }

  // 2. Heartbeat thread.
  std::thread hb_thread([&]() {
    while (running_.load()) {
      auto header = make_header(config_.machine_id, config_.site_agent_id);
      ConnectRequest req = wrap_heartbeat(header, heartbeat_fn_());
      if (!stream->Write(req)) {
        running_.store(false);
        break;
      }
      std::this_thread::sleep_for(config_.heartbeat_interval);
    }
  });

  // 3. Read loop — dispatch inbound frames to the callback.
  ConnectResponse resp;
  while (running_.load() && stream->Read(&resp)) {
    if (resp.has_frame()) {
      auto reply = on_frame_(resp.frame());
      if (reply.has_value()) {
        stream->Write(reply.value());
      }
    }
  }

  running_.store(false);
  if (hb_thread.joinable()) {
    hb_thread.join();
  }
  stream->WritesDone();
  context.TryCancel();
  stream->Finish();
}

}  // namespace cap::sdk
