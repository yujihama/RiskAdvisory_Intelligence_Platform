# 10x Value Roadmap — Risk Advisory Intelligence Platform

作成日: 2026-07-02
対象: `main` ブランチ現行実装(コミット `aa603f7` 時点)

---

## 1. 現状評価(コードベースレビュー要約)

### 1.1 強み(既に価値の土台がある)

| 領域 | 実装状況 | 根拠 |
|---|---|---|
| マルチエージェント分析パイプライン | Orchestrator + 10 ドメイン DeepAgent が A2A 境界で連携し、動的 `analysis_plan` を生成 | `final_agents.py`, `a2a_http.py` |
| Risk Discovery | イベント+スコープ(自然言語 `--scope-text` 含む)→ 候補生成 → Expert-as-Code ルールで選別 → 複数 `RiskEvent` 並行分析 | `risk_discovery.py`, `run_discovery.py` |
| Evidence Ledger | Tavily 検索 → `EvidenceItem` 正規化 → JSONL + Qdrant + Neo4j 三重登録、ソース信頼度初期スコア | `evidence_repository.py`, `source_reliability.py` |
| Expert-as-Code | ルール/プリミティブ/事例/CTA ノート/スコープ関連ルール/Decision 統合ルールを JSONL で外部化し、Qdrant 索引 + DeepAgent ツールで適用 | `data/expert_knowledge/`, `ExpertAsCodeDeepAgent` |
| 監査可能性 | Langfuse + ローカル JSONL トレース、Evidence ID が Decision に紐づく、bounded autonomy(スコア・登録は Python 側で決定) | `tracing.py`, `tool_policy.py` |
| 品質評価 | `evaluate-discovery` による Discovery 品質のリコール/禁止トップ違反/質問一致等の自動計測 | `run_discovery_evaluation.py` |

### 1.2 ギャップ(ビジョン文書との差分)

`docs/press_release_risk_advisory_intelligence_platform.md` と `docs/risk_advisory_intelligence_platform_design_v3.md` が約束する価値のうち、未実装の主要項目:

1. **継続監視・差分更新・アラート** — 現在は「人がイベントを入力して 1 回分析する」CLI バッチ。プレスリリースの中核差別化「継続監視、差分更新、アラート、意思決定ログ」が存在しない(README Known Constraints にも明記)。
2. **Scenario Delta Ledger / Decision Log** — Evidence Ledger はあるが、「前回からの変化」と「人間の承認・保留・再評価」を記録する台帳がない。`AnalysisPlan.recheck_conditions` は生成されるが**どこからも再評価に使われていない**(`schemas.py:378` 生成のみ)。
3. **UI(Risk Dashboard / Scenario Workspace / Lens Switcher)** — 出力は JSON/Markdown ファイルのみ。設計書 §12 の UI 層が丸ごと未着手。API サーバも A2A 内部境界のみで、外部向け REST API がない。
4. **Risk-to-Cash 定量分析** — Treasury モードは 0–100 のヒューリスティックスコアのみ。Liquidity-at-Risk、Payment Disruption Map 等の金額ベース分析(設計書 §7.2)が未実装。
5. **分析モードの欠落** — Cyber & Operational Resilience、Reputation & Communications、Cross-Mode War Room(部門間矛盾検出、設計書 §7.6–7.8)が未実装。
6. **ソース信頼度 v2** — ドメイン種別による 3 段階のみ。裏取り(corroboration)、鮮度、矛盾検出、来歴が未実装(README Known Constraints)。
7. **Expert Knowledge Studio / 知見のフィードバックループ** — Knowledge Pack は静的 JSONL。専門家レビュー結果を取り込んでパックを成長させる仕組み(設計書 §9.5–9.6)がない。
8. **実データコネクタ** — クライアントデータは CSV フィクスチャ固定。Ariba/ERP/TMS 接続はスコープ外のまま。
9. **認証・RBAC・マルチテナント** — 未実装(意図的スコープ外)。
10. **バックテスト・キャリブレーション** — 評価は Discovery 段のみ。エンドツーエンド(Decision 品質・スコア較正)の評価がない(設計書 §22.3)。

### 1.3 「作ったのに使っていない」即効資産

- `recheck_conditions`(Orchestrator・各ドメインが生成)→ 再評価トリガとして未消費。**F2 の入力にそのまま使える。**
- `rejected_candidates`(理由・スコア付きで保存)→ 専門家が偽陰性をチャレンジする導線がない。**F10 のレビュー UI 対象。**
- `outputs/_traces/*.jsonl` + Langfuse 144 observations/run → コスト・品質分析に未活用。**F11 の原料。**
- ポートフォリオサマリの owner/deadline 矛盾検出 → 通知先がなく Markdown に埋もれる。**F3 のアラート対象。**

---

## 2. 10x 価値仮説

現在の製品が答える問いは **「この事象は当社にどう影響するか(聞かれたら 1 回答える)」** である。

10x にする転換は次の 3 つ:

| # | 転換 | Before | After |
|---|---|---|---|
| T1 | **単発分析 → 常時稼働** | 人が事象を入力 | プラットフォームが事象を検知し、シナリオを最新に保ち、変化だけを通知する |
| T2 | **レポート → 意思決定のクローズ** | Markdown を出力して終了 | Decision が承認/保留/再評価される所までを追跡し、監査証跡になる |
| T3 | **静的知見 → 複利で成長する知見** | JSONL を手で編集 | 専門家レビューが自動で Knowledge Pack に還流し、次の分析が賢くなる |

価値の算術: 現在 1 クライアント × 1 事象 × 1 回 = 1 レポート。転換後は N クライアント × 常時監視 × 差分更新 × 意思決定追跡となり、利用頻度(週次→常時)・アウトカム(情報→判断)・スイッチングコスト(蓄積された Delta Ledger と知見)のすべてが桁で変わる。

---

## 3. ロードマップ

```
Phase 1 (0–3ヶ月)  意思決定ループを閉じる     F1 API化  F2 Delta Ledger  F3 アラート  F4 Decision Log
Phase 2 (3–6ヶ月)  常時稼働と深い分析          F5 継続監視  F6 Risk-to-Cash  F7 信頼度v2  F8 ダッシュボードUI
Phase 3 (6–12ヶ月) 複利とエンタープライズ化    F9 新モード+War Room  F10 Knowledge Studio  F11 バックテスト  F12 コネクタ  F13 RBAC
```

依存関係: F1 → {F3, F4, F8} / F2 → {F5, F11} / F4 → F10 / F12 → F6 の精度向上。

---

### Phase 1: 意思決定ループを閉じる(0–3ヶ月)

#### F1. Platform API サービス(FastAPI 外部境界)

**概要**: CLI と同等の機能(discover-risks / run-scenario / evaluate-discovery / 成果物取得)を非同期ジョブ実行付き REST API として公開する。既存の `run_discovery.py` / `run_scenario.py` のオーケストレーション関数を薄い API 層でラップする。

**価値**: UI(F8)・アラート(F3)・継続監視(F5)・外部システム連携すべての前提。ファイル受け渡しから製品への第一歩。

**実装方針**:
- `src/risk_agent_platform/api/` に FastAPI アプリを新設。既存 `agent_server.py`(A2A 内部境界)とは分離。
- ジョブは `POST /v1/discoveries` `POST /v1/scenarios` → `202 Accepted` + `job_id`、`GET /v1/jobs/{job_id}` でポーリング。実行本体は既存関数を asyncio タスク/ワーカーで実行。
- 成果物(`final_brief.md`, `decision_queue.json`, `evidence_summary.json`, portfolio summary 等)は `GET /v1/scenarios/{scenario_id}/artifacts/{name}` で取得。
- OpenAPI スキーマは既存 Pydantic モデル(`schemas.py`)を再利用。

**受け入れ基準**:
- [ ] `POST /v1/discoveries` に CLI `discover-risks` と同じパラメータ(scope_text 含む)を JSON で渡すと、CLI 実行と同一構造の `RiskDiscoveryResult` が得られる(同一入力・固定シードでの回帰テストあり)。
- [ ] `--run-analysis` 相当を API で起動でき、ジョブ状態が `submitted → working → completed|failed` と遷移し、`failed` 時はエラー詳細(スタック非露出)が返る。
- [ ] 実行中ジョブがプロセス再起動で消えても、ジョブ状態ストア(SQLite または Postgres)から `failed` として復元され、孤児ジョブが `working` のまま残らない。
- [ ] すべてのエンドポイントが OpenAPI ドキュメントに現れ、`schemas.py` の Pydantic モデルと型が一致する。
- [ ] 既存 CLI・pytest スイートが無変更で全件パスする(API 層追加は既存経路に影響しない)。
- [ ] API 経由の実行も Langfuse / ローカル JSONL トレースに `trace_id` 付きで記録される。

---

#### F2. Scenario Delta Ledger(差分台帳と再分析)

**概要**: 同一シナリオ(または同一 client × event fingerprint)の再実行時に、前回結果との差分 — 新規/消滅した Evidence、スコア変化、Decision 変化、前提(assumptions)の失効、unknowns の解消 — を構造化して記録する。プレスリリース §6 で約束済みの機能。

**価値**: 「先週から何が変わったか」に答えられるのは単発リサーチとの最大の差別化。F5(継続監視)の通知内容も、F11(バックテスト)の学習データも、この台帳が供給する。

**実装方針**:
- `schemas.py` に `ScenarioDelta`(`scenario_id`, `run_id`, `previous_run_id`, `evidence_added/removed`, `score_changes`, `decision_changes`, `assumption_expirations`, `unknown_resolutions`, `recheck_triggers_fired`)を追加。
- `run_scenario` 完了時に前回 run の成果物(JSONL 化した run 履歴ストア)と突合し、`outputs/<scenario_id>/deltas/<run_id>.json` と Neo4j に登録。
- **既存の `recheck_conditions` を消費する**: 各 run で保存された recheck 条件を次回 run 開始時に評価対象として渡し、発火した条件を `recheck_triggers_fired` に記録する。
- `AssumptionItem.expires_at`(既存フィールド、未活用)を評価し、失効した前提を差分としてフラグする。

**受け入れ基準**:
- [ ] 同一シナリオを 2 回実行すると、2 回目に `deltas/<run_id>.json` が生成され、Evidence の追加/削除・`risk_score` の増減・Decision の新規/変更/消滅が正しく列挙される(モック Tavily で証拠セットを意図的に変えた E2E テストで検証)。
- [ ] 初回実行では delta は `baseline: true` として記録され、エラーにならない。
- [ ] 前回 run の `recheck_conditions` が今回 run のコンテキストに含まれ、発火判定結果(fired / not_fired / not_evaluable)が delta に記録される。
- [ ] `expires_at` を過去日時に設定した `AssumptionItem` が、次回 run の delta で `assumption_expirations` に列挙される。
- [ ] 差分サマリが人間可読 Markdown(`delta_summary.md`)としても出力され、変化ゼロの場合は「変化なし」と明示される。
- [ ] delta 生成の失敗が本体分析を失敗させない(degraded 記録で継続)。

---

#### F3. アラート・通知チャネル

**概要**: 分析完了・スコア閾値超過・delta 発生・owner/deadline 矛盾・review_required Decision を、Webhook / Slack / Email に通知する。通知ルールは Expert-as-Code 流儀で `data/notification_rules.jsonl` に外部化する。

**価値**: 現在はポートフォリオサマリの重要警告(owner 空白、期限矛盾)が Markdown に埋もれる。「危機を早く捉える」というサービス訴求は通知なしには成立しない。

**実装方針**:
- `src/risk_agent_platform/notifications.py` に `NotificationRule`(条件: `risk_score >= N`, `review_required == true`, `delta.score_changes` 等)と `NotificationChannel`(webhook 汎用 + Slack incoming webhook + SMTP)を実装。
- 発火判定は決定的 Python(LLM を使わない)。通知本文テンプレートに scenario/Decision/Evidence へのリンク(F1 の API URL)を含める。

**受け入れ基準**:
- [ ] `risk_score >= 閾値` の Finding を含むシナリオ完了時に、設定済み webhook へ 1 件の POST が送信され、ペイロードに `scenario_id`, `trace_id`, 発火ルール ID, 対象 Decision/Finding の要約が含まれる。
- [ ] 同一 run 内で同一ルール × 同一対象の重複通知が発生しない(冪等キーで担保)。
- [ ] 通知先エンドポイント障害時は指数バックオフで最大 3 回再試行し、最終失敗は `outputs/<scenario_id>/notification_failures.json` に記録され、分析自体は成功のまま完了する。
- [ ] ポートフォリオサマリの owner 欠落・deadline 矛盾が専用ルールで通知可能。
- [ ] ルール追加が JSONL 1 行の追記で完結し、コード変更を要しない(テストで新ルール追記 → 発火を確認)。
- [ ] 秘匿値(金額・取引先実名など Query Sanitizer が守る対象)が通知ペイロードに含まれない。

---

#### F4. Decision Log(人間の判断の記録)

**概要**: Decision Queue の各 `DecisionItem` に対する人間のアクション — 承認 / 却下 / 保留(理由付き)/ 再評価要求 / owner 変更 — を記録する追記専用ログと API を実装する。プレスリリース §6 の「Decision Log」に相当。

**価値**: 「AI が出した判断候補がどう扱われたか」が残ることで、監査対応の成果物になると同時に、F11 バックテストの正解ラベル(専門家が採用した/しなかった)が自然に蓄積される。

**実装方針**:
- `schemas.py` に `DecisionAction`(`decision_id`, `action`, `actor`, `reason`, `timestamp`, `prev_state`, `new_state`)を追加。追記専用 JSONL + Neo4j `(:Decision)-[:ACTED_ON]->(:DecisionAction)`。
- F1 API に `POST /v1/decisions/{decision_id}/actions` と `GET /v1/scenarios/{scenario_id}/decision-log` を追加。
- `再評価要求` アクションは F2 の recheck トリガとして次回 run に接続する。

**受け入れ基準**:
- [ ] Decision に対し approve / reject / hold / request-recheck / reassign の 5 アクションを API で記録でき、状態機械(例: approved 後の hold は不可)に反する遷移は 409 で拒否される。
- [ ] ログは追記専用で、更新・削除 API が存在しない(訂正は打ち消しアクションで表現)。
- [ ] `request-recheck` されたシナリオの次回 run で、当該 Decision が優先的に再評価され、その旨が delta(F2)に記録される。
- [ ] シナリオ単位の Decision Log を時系列で取得でき、各エントリが actor・理由・前後状態を保持する。
- [ ] ポートフォリオサマリに「未処理 Decision 数 / 承認済み / 保留(理由別)」の集計が追加される。

---

### Phase 2: 常時稼働と深い分析(3–6ヶ月)

#### F5. 継続監視(Autonomous Risk Sensing)

**概要**: クライアントごとの Watchlist(国、リスクテーマ、サプライヤー地域、キーワード — 既存の scope 情報から初期生成)を定義し、スケジューラが定期的に bounded Tavily 検索でイベント兆候を収集、既知イベントと照合して「新規イベント検知」または「既存シナリオの再評価(F2)」を自動起動する。README Known Constraints の筆頭制約を解消する。

**価値**: T1 転換の本体。「人が聞く」から「プラットフォームが気づく」への転換で、利用形態が単発案件から常時契約(Managed Service)に変わる。

**実装方針**:
- `src/risk_agent_platform/monitoring/` に `Watchlist`(client_id, topics, countries, cadence, thresholds)と `SensingRun` を実装。スケジューラは APScheduler 等の軽量なもので開始(K8s CronJob へ移行可能な設計)。
- 検知パイプライン: sanitized 検索(既存 `mcp-web-search` 再利用、回数上限あり)→ イベント候補抽出 → 既存イベントとの同一性判定(embedding 類似 + 国/テーマ一致の決定的ルール)→ 新規なら `RiskDiscoveryRequest` を自動生成し F1 API 経由で discovery 起動、既知ならシナリオ再評価をキュー。
- **自動なのは検知と分析まで**。Decision 実行は従来どおり人間(bounded autonomy 原則の維持)。誤検知抑制のため、自動起動された discovery はデフォルトで「通知のみ」とし、`--run-analysis` 相当は Watchlist 設定でオプトイン。

**受け入れ基準**:
- [ ] Watchlist を登録すると、設定 cadence(例: 6 時間毎)で SensingRun が実行され、実行履歴(検索クエリ数、検知イベント数、起動した discovery/再評価)が記録される。
- [ ] 同一の実世界イベント(モックで同一ニュースを返すテスト)から重複した discovery が起動しない(同一性判定の回帰テストあり)。
- [ ] 検知 → discovery 起動 → F3 通知までがエンドツーエンドで動作する(モック Tavily E2E)。
- [ ] SensingRun あたりの検索回数・LLM 呼び出し回数に上限が設定され、上限到達時は degraded として安全に停止する。
- [ ] Watchlist のクエリは Query Sanitizer を通過し、クライアント固有の秘匿語が外部検索に出ない(既存サニタイザテストを拡張)。
- [ ] スケジューラ停止・再起動で SensingRun が重複実行・欠落しない(実行台帳でリース管理)。
- [ ] 30 日間の擬似運用テスト(圧縮タイムライン)で、誤検知率(専門家が「無関係」と判定した検知の割合)を計測するレポートが出力できる。

---

#### F6. Risk-to-Cash 定量分析(Treasury v2)

**概要**: Treasury モードに金額ベースの決定的分析を追加する: 影響国・影響サプライヤー起点の Payment Disruption Map(期間別の支払停止額)、Liquidity-at-Risk(シナリオ別の資金不足額レンジ)、Critical Supplier Payment(停止時の事業影響が大きい支払の特定)。設計書 §7.2 の中核。

**価値**: 「リスクがある」ではなく「◯◯億円の支払が停止し得る」が出せると、経営会議資料として直接使える成果物になる。スコア 0–100 との違いは説明責任の質。

**実装方針**:
- 計算はすべて決定的 Python(`mcp-structured-data` の raw ツール側)。既存の tool_policy 原則を維持し、LLM には bucketed 結果のみ渡す。
- 入力: payments.csv / suppliers.csv / contracts.csv(既存)+ 通貨・支払期日・口座国(スキーマ拡張)。シナリオの影響国/影響カテゴリ(既存 `RiskEvent.countries`, `affected_categories`)でフィルタ。
- 出力: `AgentFinding.metadata.risk_to_cash` に構造化(期間バケット × 金額レンジ × 前提)+ Executive Brief に金額サマリ節を追加。全金額に `confidence_layer`(source_backed / derived / assumption)を付与。
- データ欠損時(通貨不明等)は金額を出さず `unknowns` に転記する — 幻の精度を出さない。

**受け入れ基準**:
- [ ] 影響国を含むシナリオで、30/60/90 日バケット別の「影響下にある支払予定額」が通貨別に算出され、フィクスチャデータに対する期待値が単体テストで固定される。
- [ ] 各金額に根拠(対象レコード件数、フィルタ条件、為替換算の有無と前提)が付き、Executive Brief から Evidence/前提まで追跡できる。
- [ ] 支払期日・通貨が欠損したレコードは金額集計から除外され、除外件数と欠損理由が `unknowns` / missing-data リクエストに現れる。
- [ ] LLM プロンプトに raw 支払行が渡らない(tool_policy テストを拡張し、LLM スロットのツール入出力に金額明細が含まれないことを検証)。
- [ ] Liquidity-at-Risk は点推定ではなくレンジ(悲観/中位/楽観)で出力され、各レンジの前提が明記される。
- [ ] 数値ゼロ件のシナリオ(影響国に支払がない)で「定量影響は検出されなかった」と明示され、スコアだけが独り歩きしない。

---

#### F7. ソース信頼度 v2(裏取り・鮮度・矛盾)

**概要**: 現行のドメイン 3 段階に、(a) corroboration — 同一主張を独立ソースが支持する数、(b) recency — 取得時点とイベント時点の整合、(c) contradiction — Evidence 間の矛盾検出、(d) provenance — 一次/二次ソース区別、を加えた合成信頼度を実装する。

**価値**: Red Team エージェントの矛盾検索が「信頼度の低い証拠に基づく Decision」を定量的に指摘できるようになり、レポートの守り(監査・役員会での耐性)が一段上がる。

**実装方針**:
- `source_reliability.py` を拡張。corroboration は既存 Qdrant `evidence_chunks` の類似検索 + 主張単位のクラスタリング(決定的閾値)。contradiction は既存 `EvidenceItem.contradicts` フィールド(現在ほぼ未活用)への書き込みを Red Team ツールから実施。
- 合成スコアの重みは `data/expert_knowledge/source_reliability_seed.yaml` に外部化(Expert-as-Code 原則)。
- Decision との接続: `review_required` の自動判定条件に「単一ソース依存の Decision」を追加。

**受け入れ基準**:
- [ ] 同一主張を 3 独立ドメインが支持する Evidence の合成信頼度が、単一ソースの同種 Evidence より高くなる(モック証拠セットでの回帰テスト)。
- [ ] イベント日より古い Evidence(例: 1 年前の記事)の recency 減点が適用され、スコア内訳(domain/corroboration/recency/contradiction の各要素)が Evidence Summary に表示される。
- [ ] 相互に矛盾する 2 つの Evidence が検出されると、両者の `contradicts` が相互設定され、Red Team レビューに矛盾ペアとして列挙される。
- [ ] 1 つの Evidence にのみ依拠する Decision が `review_required: true` に自動昇格し、理由に「single-source dependency」が記録される。
- [ ] 重み変更が YAML 編集のみで反映される(コード変更なしテスト)。
- [ ] 信頼度再計算は再実行時に冪等(同一入力 → 同一スコア)。

---

#### F8. Risk Dashboard / Scenario Workspace(Web UI)

**概要**: F1 API の上に、(1) クライアント横断のリスクダッシュボード(進行中シナリオ、スコア推移、未処理 Decision、直近 delta)、(2) シナリオワークスペース(Finding / Evidence / Decision / Red Team 指摘 / delta を 1 画面で追跡、Evidence クリックで原文スニペットと信頼度内訳)、(3) Lens Switcher(同一シナリオを Treasury/Legal/Accounting/Procurement レンズで切替表示)を実装する。設計書 §12。

**価値**: 現在の消費体験は「outputs/ ディレクトリの JSON を開く」。役員・部門長が直接触れる UI は、Managed Service から SaaS への転換点であり、Decision Log(F4)の入力面でもある。

**実装方針**:
- フロントエンドは SPA(React + TypeScript)を `web/` に新設。API は F1 を拡張(一覧・集計エンドポイント追加)。認証は Phase 3 の F13 まで単一テナント前提の簡易トークンで開始。
- 画面は既存成果物スキーマの写像に徹する(UI 専用の分析ロジックを持たない)。

**受け入れ基準**:
- [ ] ダッシュボードで全シナリオが状態(working/completed/failed/review-required)別に一覧でき、各行からワークスペースへ遷移できる。
- [ ] ワークスペースで Decision → 根拠 Evidence → 原文スニペット/URL → 信頼度内訳(F7)まで 3 クリック以内で追跡できる。
- [ ] Lens Switcher でレンズを切り替えると、Finding・推奨アクション・関連 Decision が当該ドメインのものにフィルタされる。
- [ ] F4 の Decision アクション(承認/保留/再評価要求)が UI から実行でき、Decision Log に反映される。
- [ ] F2 の delta が「前回からの変化」パネルとして表示され、変化なしの場合はその旨が表示される。
- [ ] 日本語 UI で提供され、成果物(Brief 等)の日本語出力と整合する。
- [ ] Playwright による主要 3 フロー(一覧→詳細、Decision 承認、レンズ切替)の E2E テストが CI で通る。

---

### Phase 3: 複利とエンタープライズ化(6–12ヶ月)

#### F9. 新分析モード(Cyber / Communications)+ Cross-Mode War Room

**概要**: (1) Cyber & Operational Resilience エージェント(IT 資産・委託先障害の業務影響、規制報告要否)、(2) Reputation & Communications エージェント(初期声明・Q&A・社内通知ドラフト生成、法務モードとの整合チェック)、(3) Cross-Mode War Room — 全ドメイン Finding を突合し、部門間矛盾(例: 調達「代替調達可能」vs 財務「前払必須で資金不足」)を検出する統合ステージ。設計書 §7.6–7.8。

**価値**: 「同じ危機を CFO/法務/経理/CPO/CISO/広報の視点で同時に」というプレスリリースの表の残り 2 行を埋め、War Room はどの単機能競合も持たない部門横断矛盾検出という独自価値になる。

**実装方針**:
- 新エージェント 2 種は既存 `DomainDeepAgentService` パターン(bounded 探索スロット + 決定的スコアリング)を踏襲。Cyber 用に `it_assets.csv` / `vendors.csv` フィクスチャとスキーマを追加。
- War Room は decision-synthesis の前段に決定的な矛盾検出(owner 重複・deadline 競合の既存ロジックを拡張し、リソース競合・前提矛盾を Finding metadata の構造化フィールドで突合)+ LLM による矛盾候補の説明生成(判定自体は決定的)。

**受け入れ基準**:
- [ ] Cyber エージェントがランサムウェア型シナリオで、影響業務プロセス・復旧優先順位仮説・規制報告要否の Finding を出し、E2E テストに組み込まれる。
- [ ] Communications エージェントが初期声明・想定 Q&A ドラフトを生成し、法務 Finding の `review_required` 項目と矛盾する記述(例: 責任認定を先行する文言)がガードレール違反としてフラグされる。
- [ ] War Room がフィクスチャシナリオで既知の部門間矛盾(テストデータに仕込んだ資金前提の食い違い)を検出し、Executive Brief に「部門間で要調整の論点」節として出力する。
- [ ] 新モード追加後も Orchestrator の `analysis_plan` が新エージェントを選択/スキップでき、無効プラン時のフォールバック順序に含まれる。
- [ ] 既存 4 ドメインの出力に回帰がない(既存 E2E の期待値維持)。

---

#### F10. Expert Knowledge Studio(知見の還流ループ)

**概要**: 専門家が (1) rejected_candidates への異議、(2) Decision Log での却下理由、(3) Red Team 指摘への裁定、(4) 新規ルール/事例の起票をブラウザで行い、承認された知見が版管理付きで Knowledge Pack(JSONL)に反映される編集・レビューワークフロー。設計書 §9.5–9.6。

**価値**: T3 転換の本体。現在の知見更新は「エンジニアが JSONL を編集」。専門家が直接知見を育てられると、Knowledge Pack がファーム固有の蓄積資産(=解約障壁)になる。

**実装方針**:
- F8 UI に Studio セクションを追加。knowledge 変更は Git ライクな提案 → レビュー → 承認 → `knowledge_pack_version.json` の版更新、のワークフローで管理(承認者ロールは F13 前は設定ファイルで指定)。
- Decision Log(F4)から「AI 提案が却下された Decision」を自動で知見起票候補として提示する(却下理由 → CTA ノート/ルール素案を LLM が下書き、採否は人間)。
- 版ごとの評価: 知見パック更新時に `evaluate-discovery` を自動実行し、品質メトリクスの前版比較を承認画面に表示する。

**受け入れ基準**:
- [ ] 専門家が rejected candidate に「これは選ぶべきだった」と異議を登録すると、スコープ関連ルールの修正提案が下書きされ、承認すると `scope_relevance_rules.jsonl` に新版として反映される。
- [ ] 知見変更はすべて提案 → 承認の 2 段階を経由し、直接編集の経路が存在しない。全変更に提案者・承認者・理由・対象パック版が記録される。
- [ ] パック版更新時に評価スイートが自動実行され、`average_recall` 等の主要メトリクスが前版から劣化した場合は承認画面に警告が表示される(ブロックは任意設定)。
- [ ] 任意の過去パック版を指定して discovery を再実行できる(版ピン留め)。
- [ ] Decision 却下 10 件からの知見起票 → 承認 → 次回分析での適用、が擬似データで一巡する E2E シナリオテストが存在する。

---

#### F11. バックテスト・キャリブレーション フレームワーク

**概要**: Discovery 段のみの現行評価を、パイプライン全体に拡張する: (a) エンドツーエンド評価(期待 Decision・期待 Evidence 特性を含むゴールデンケース)、(b) スコア較正(risk_score と専門家判定/実際の帰結の突合)、(c) 回帰ゲート(モデル・プロンプト・知見パック変更時の品質差分検出)、(d) コスト計測(トレースからの LLM トークン/レイテンシ集計)。設計書 §22.3。

**価値**: モデル変更(現に Qwen 3.6 → 3.7 の切替が行われている)や知見更新のたびに品質が守られている保証がないと、スケール時に信頼が崩れる。10x の前提となる品質インフラ。

**実装方針**:
- `data/evaluation/` にエンドツーエンドケース形式を追加(入力シナリオ + 期待 Decision 属性 + 期待 review_required + 禁止出力)。`run_discovery_evaluation.py` のパターンを `run_pipeline_evaluation.py` に一般化。
- 較正データは F4 Decision Log(承認/却下)を正解ラベルとして自動抽出。信頼度バケット別の的中率(calibration curve)をレポート。
- コストは `outputs/_traces/*.jsonl` の OpenRouter イベントから集計し、シナリオあたりトークン・回数・レイテンシをメトリクス化。

**受け入れ基準**:
- [ ] エンドツーエンド評価が 10 ケース以上のゴールデンセットで実行でき、Decision 一致率・review_required 的中率・禁止出力違反数がレポートされる。
- [ ] モデルプロファイル変更(例: DEFAULT_MODEL 差替)前後で評価を実行し、メトリクス差分が Markdown レポートで比較できる。
- [ ] CI で縮小ゴールデンセット(モック LLM/Tavily)による回帰ゲートが走り、主要メトリクスの閾値割れでビルドが fail する。
- [ ] Decision Log 蓄積 50 件以上を入力に、confidence バケット(low/medium/high)別の専門家承認率が算出され、較正曲線が出力される。
- [ ] シナリオ 1 件あたりの LLM 呼び出し回数・トークン・推定コスト・所要時間がトレースから自動集計され、評価レポートに併記される。

---

#### F12. クライアントデータコネクタ フレームワーク

**概要**: 現在の「`data/clients/<id>/structured/*.csv` 固定」を、コネクタインターフェース(スキーマ検証付き取り込み → 正規化 → 増分同期 → データ鮮度メタデータ)に置き換える。第一弾は CSV/SFTP バッチと汎用 REST 取り込み、次に Ariba/SAP 系アダプタの設計検証。設計書 §4.4 の Sparse-to-Rich Context を実装に落とす。

**価値**: プレスリリースの根幹訴求「クライアント固有の業務データに接続」の実体化。データ鮮度が明示されることで、F6 の金額分析・F5 の監視の信頼性が実務水準になる。

**実装方針**:
- `src/risk_agent_platform/connectors/` に `Connector` プロトコル(discover_schema / validate / sync / freshness)を定義。取り込み結果は現行 CSV 相当の正規化テーブル + `data_freshness.json`(ソース別最終同期時刻、レコード数、検証エラー)。
- 既存の feature view / safe summary 層は正規化テーブルの上で無変更で動くことを維持(取り込み層の差し替えのみ)。
- 鮮度の下流接続: 分析時にソース鮮度が閾値超過なら `assumptions` に「データは N 日前時点」を自動注入し、Executive Brief に鮮度注記を出す。

**受け入れ基準**:
- [ ] CSV/SFTP コネクタで既存フィクスチャと同一スキーマのデータを取り込み、既存の discovery / scenario E2E が取り込みデータ上で無変更にパスする。
- [ ] スキーマ検証エラー(必須列欠落、型不整合)が取り込み時に行番号付きで報告され、不正データが正規化テーブルに混入しない。
- [ ] 増分同期が upsert として動作し、同一データ再同期で重複レコードが発生しない。
- [ ] すべての分析成果物にデータ鮮度注記(ソース別最終同期時刻)が含まれ、閾値超過時は assumption として明示される。
- [ ] コネクタ追加がプロトコル実装 + 設定登録のみで完結する(サンプル: 汎用 REST コネクタの参照実装)。
- [ ] 取り込みデータが tool_policy の raw/safe 分離に従う(LLM スロットに raw 行が渡らないことのテストを取り込み経路にも拡張)。

---

#### F13. 認証・RBAC・マルチテナント分離

**概要**: OIDC ベースの認証、ロール(閲覧者 / アナリスト / 専門家レビュアー / 管理者)、クライアント(テナント)単位のデータ分離(Qdrant コレクション/Neo4j ラベル/成果物ディレクトリ/API スコープ)を実装する。

**価値**: Managed Service を超えて Standalone / Hybrid 提供形態(プレスリリース §提供形態)を成立させる前提条件。専門家レビュー(F10)のロール分離もここに依存。

**実装方針**:
- F1 API に OIDC(汎用: Auth0/Entra ID/Keycloak 互換)ミドルウェアを追加。テナント ID をすべての読み書きパスの必須キーにする(現行 `client_id` を昇格)。
- Qdrant はコレクション接頭辞、Neo4j はノードプロパティ + 全クエリへの tenant フィルタ強制(ストア層で一元化)、ファイル成果物はテナント別ルート。

**受け入れ基準**:
- [ ] 未認証リクエストが全 API で 401、権限不足が 403 となり、匿名アクセス可能なエンドポイントはヘルスチェックのみ。
- [ ] テナント A のトークンでテナント B のシナリオ・Evidence・Decision・知見パックが一切取得できない(横断アクセステストをストア層 3 種すべてで実施)。
- [ ] 閲覧者ロールは Decision アクション(F4)と知見承認(F10)を実行できない。
- [ ] Decision Log・知見変更・通知設定変更のすべてに actor(認証主体)が記録される。
- [ ] テナント削除でそのテナントの Qdrant ポイント・Neo4j ノード・成果物・トレース参照が完全に削除される(検証スクリプト付き)。
- [ ] セキュリティレビュー(認可の抜け・インジェクション・秘匿情報ログ出力)を通過し、指摘ゼロまたは受容済みリスクとして文書化される。

---

## 4. 横断的な品質ゲート(全フェーズ共通)

各フェーズの完了条件として、機能別受け入れ基準に加えて以下を満たすこと:

1. **bounded autonomy の維持** — 新機能でも「LLM は探索・仮説、決定的 Python が判定・登録」の分離を守る。tool_policy テストを新ツールに拡張する。
2. **明示的失敗** — 新しい外部依存(通知先、コネクタ、スケジューラ)はすべて「サイレントフォールバック禁止・degraded 明示」の既存原則に従う。
3. **トレース完全性** — 新規の LLM/MCP/A2A 呼び出しがすべて `TraceRecorder` を通過し、Langfuse とローカル JSONL に記録される。
4. **秘匿統制** — 外部に出るペイロード(検索、通知、UI 経由の共有)はすべて Query Sanitizer 相当の検査を通す。
5. **回帰** — 既存 pytest スイート + F11 導入後は回帰ゲートを全 PR で通す。

## 5. 成功指標(10x の計測)

| 指標 | 現状 | Phase 1 後 | Phase 3 後 |
|---|---|---|---|
| 事象検知から初期ブリーフまでの時間 | 人依存(数時間〜数日) | 人が入力後 30 分以内 | 自動検知で 1 時間以内 |
| 1 クライアントあたり月間分析回数 | 単発(〜数回) | 週次運用(〜20 回) | 常時監視(delta 更新含め 100 回超) |
| Decision のクローズ率(承認/却下まで到達) | 計測不能(ログなし) | 計測可能 + 50% | 80% |
| 専門家知見の更新頻度 | エンジニア依存(不定期) | — | 専門家自身が週次で更新 |
| 品質回帰の検出 | 手動 | Discovery 段のみ自動 | 全パイプライン CI ゲート |

---

## 変更履歴

- 2026-07-02: 初版作成(コードベースレビュー + ビジョン文書ギャップ分析に基づく)
