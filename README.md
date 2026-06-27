# Risk Advisory Intelligence Platform

UIなしの初期バックエンドPoCです。`docs/` の設計書に合わせ、Python中心で以下を実装しています。

- 共通Pydanticスキーマ
- OpenRouter互換LLM Adapter
- Agent間通信のA2Aローカル境界
- MCP風のFilesystem / Structured Data / Evidence Ledger / Expert Knowledge境界
- Orchestrator + 初期Domain Agents
- ダミーデータによるE2Eシナリオ実行

アーキテクチャ図は [docs/architecture_diagrams.md](docs/architecture_diagrams.md) にあります。

## Quickstart

```powershell
python -m pip install -e .[dev]
python -m risk_agent_platform.cli run-scenario --input data/sample_inputs/geopolitical_sanctions_risk.json
pytest
```

出力は `data/scenarios/<scenario_id>/` に保存されます。

## OpenRouter

`.env` は `C:\Users\nyham\work\PoC_Automation\.env` から OpenRouter 関連行のみコピー済みです。値はログに出さない前提で扱います。

疎通確認:

```powershell
python -m risk_agent_platform.cli llm-smoke --max-tokens 16
```

E2Eテストはコストと外部依存を避けるため、デフォルトではOpenRouterを呼びません。OpenRouter Adapter自体は `.env` を読み、OpenAI互換の `/chat/completions` を呼ぶ実装です。
