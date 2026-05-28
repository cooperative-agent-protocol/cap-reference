<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 CAP Authors
-->

# CAP Reference Implementation

> CAP (Cooperative Agent Protocol) の参照実装 — SDK, エージェント, シミュレータ。Core (Manifest / WorkOrder / Heartbeat / Dialogue / ALO) + Construction Domain Pack v0 を含む。

## Python SDK (`python/cap_sdk/`)

CAP プロトコルの完全な Python 実装。Machine Agent と Site Agent の両方をサポート。

### 機能一覧

| モジュール | 内容 |
|-----------|------|
| `client.py` | `MachineAgentClient` — gRPC 接続、Manifest 送信、Heartbeat ループ、mTLS 対応 |
| `server.py` | `CapRuntimeServicer` — gRPC サーバー、mTLS CN 検証、RBAC 強制、`serve()` / `serve_secure()` |
| `frame.py` | 全 18 メッセージ型の wrap 関数（`wrap_work_order`, `wrap_heartbeat`, etc.） |
| `validator.py` | 15 メッセージ型の検証 + TaskState 遷移検証 |
| `security/cert_gen.py` | mTLS 証明書生成（site CA + server + per-machine client cert, P-256 EC） |
| `security/rbac.py` | Role × Message 認可マトリクス（Ch09 §9.3.2 準拠） |
| `transport/grpc_adapter.py` | gRPC transport adapter（TLS/mTLS 対応） |
| `transport/mqtt_adapter.py` | MQTT transport adapter（QoS マッピング、LWT、deduplication） |
| `machine_model.py` | LLM/SLM 統合インターフェース（assess, propose, ALO generate/update/validate/interact） |
| `machine_model_*.py` | 5 バックエンド: Claude, Gemini, OpenAI, Ollama, Fake (rule-based) |
| `alo_generator.py` | ALO 記述子生成（Ochiai et al., 2304.04498 Steps 1-10） |

### クイックスタート

```bash
cd cap-reference/python
pip install -e .

# 最小 Machine Agent の実行例
python templates/minimal_agent/main.py
```

詳細ガイド: [docs/getting-started.md](docs/getting-started.md)

## エージェント (`agents/`)

| エージェント | 内容 |
|------------|------|
| `fake_excavator` | Fake 掘削機 — WorkOrder 受理、掘削シミュレーション、ALO Phase 2/3/Step 11、対話 |
| `fake_dump` | Fake ダンプ — 搬出シミュレーション、ALO 状態報告 |
| `fake_site` | Fake Site Agent — WorkOrder dispatch、対話承認、ALO World Model 管理 |
| `sim_excavator` | シミュレータ連携掘削機 — world state から実値取得 |
| `sim_dump` | シミュレータ連携ダンプ — 経路追従、積載状態 |
| `sim_site` | シミュレータ連携 Site Agent — LLM planner + TaskGraph compiler |

## シミュレータ (`simulator/`)

軽量 2D Python シミュレータ。Mac ネイティブ、Gazebo/ROS 2 不要。

- `world.py` — 2D グリッド地形モデル（N×M セル、volume tracking）
- `machines.py` — 掘削機・ダンプの状態モデル
- `engine.py` — ティック制シミュレーションエンジン（10 Hz）
- `server.py` — FastAPI + WebSocket バックエンド

## C++ SDK (`cpp/`)

Frame builder のみ実装済み（7 関数）。MachineAgentClient は今後実装予定。

## TypeScript SDK (`ts/`)

Cross-language interop テスト用。クライアント実装は今後対応予定。

## Docker Compose

```bash
docker-compose up  # 7 サービス起動
```

| サービス | ポート | 内容 |
|---------|--------|------|
| `simulator` | 8100 | 2D シミュレータ |
| `site-agent` | 50051 | gRPC Site Agent |
| `excavator-01` | — | Machine Agent |
| `dump-truck-01` | — | Machine Agent |
| `dashboard` | 8200 | Web ダッシュボード |
| `mosquitto` | 1883 | MQTT ブローカー |

## License

Apache License 2.0
