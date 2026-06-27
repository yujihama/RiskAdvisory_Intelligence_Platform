# Risk Advisory Intelligence Platform サービス設計書

**版:** 理想形コンセプト設計 v3  
**作成日:** 2026年6月27日  
**想定提供者:** リスクアドバイザリー／危機管理コンサルティング会社  
**想定利用者:** 経営層、CFO／Treasury、法務、経理、調達、サプライチェーン、サイバー、広報、リスク管理、内部統制部門

---

## 1. サービスコンセプト

本サービスは、クライアント固有の業務データ、外部リスク情報、AIエージェント、リスクアドバイザリー専門家の知見を統合し、エマージェンシーリスクを多面的に分析するためのプラットフォームである。

単なるAIリサーチやレポート生成ではなく、クライアントの拠点、サプライヤー、契約、資金、取引、財務、IT資産、顧客、業務プロセスにリスクを接続し、経営判断に直結するシナリオ、スコア、対応策、プレイブック、専門家コメントを提供する。

本サービスにおけるエマージェンシーリスクは、以下の両方を含む。

- 突発危機リスク：自然災害、地政学的危機、制裁、サイバー攻撃、感染症、港湾停止、金融市場混乱、社会不安など
- エマージングリスク：規制変更、技術変化、AI・量子・サイバーの新興脅威、サプライチェーン構造変化、気候・水資源・人権・地経学的リスクなど

本サービスの中核価値は、以下の一文に集約される。

> 同じクライアントアセットを、CFO、法務部長、経理部長、CPO、CISO、広報責任者、CEOの視点で同時に分析し、危機を経営判断に変換する。

---

## 2. サービスの基本思想

### 2.1 汎用リサーチではなく、クライアント固有分析を行う

一般的なAIリサーチサービスは、公開情報を調査し、要約し、引用付きレポートを作成することに強みがある。一方、本サービスは外部情報をクライアント内部の業務データに接続し、以下の問いに答える。

- このリスクは、どの事業、拠点、取引先、契約、口座、資金、製品、顧客に影響するか
- 影響は何日後、何週間後、どの業務プロセスに現れるか
- 法務、会計、資金、調達、広報、サイバー、経営の各視点で何が問題になるか
- どの対応を、誰が、いつ、どの根拠で実行すべきか
- 専門家が見るべき盲点、前提、反証、追加確認事項は何か

### 2.2 分析モードを切り替えることで、同じデータから複数の価値を生む

本サービスでは、分析単位を「Mode Pack」として定義する。Mode Packは、特定の専門領域におけるデータ、外部情報源、問い、スコアリング、成果物、専門家レビュー観点をまとめた分析レンズである。

```text
Mode Pack =
  対象データ
+ 接続すべき外部ソース
+ 専門的な問い
+ スコアリング軸
+ 出力テンプレート
+ 専門家レビュー観点
+ 対応プレイブック
```

これにより、同じサプライヤー、契約、支払、在庫、口座、拠点を、Treasury、Legal、Accounting、Procurement、Cyber、Reputation、Executiveの各視点で再解釈できる。

### 2.3 専門家知見をサービスの中核資産にする

リスクアドバイザリー会社が提供するサービスであるため、差別化の源泉はAIモデルそのものではなく、以下の組み合わせにある。

- 業界別・機能別のリスク知見
- 専門家が設計したスコアリング基準
- 実務で使えるチェックリスト、赤旗指標、プレイブック
- 専門家レビューとキャリブレーション
- クライアント固有の重要性判断
- 監査可能な証拠台帳と意思決定ログ

専門家の知見は単なるコメントとしてではなく、Expert Knowledge Pack、Expert-as-Code、レビューSLA、業界別テンプレートとしてサービスに組み込む。

---

## 3. 全体アーキテクチャ

```text
外部リスク情報
  - ニュース、政府発表、規制、制裁、気象、地政学、サイバー、開示情報
        ↓
内部クライアントデータ
  - Ariba、ERP、TMS、銀行、契約、財務、GRC、CMDB、文書管理
        ↓
Client Asset Graph
  - 法人、拠点、取引先、契約、口座、支払、請求書、製品、資産、業務プロセス
        ↓
Risk Intelligence Layer
  - Websearch、外部API、専門ソース、証拠台帳、ソース信頼度管理
        ↓
Scenario & Impact Engine
  - リスクイベント検知、波及経路生成、クライアント影響分析
        ↓
Risk Lens / Mode Packs
  - Executive / Treasury / Legal / Accounting / Procurement / Cyber / Reputation
        ↓
Expert Knowledge Layer
  - 業界別知見、スコア重み、赤旗指標、専門家レビュー、プレイブック
        ↓
Decision & Action Layer
  - スコア、経営判断メモ、対応タスク、RACI、文案、訓練台本、監査ログ
```

---

## 4. Client Asset Graph

Client Asset Graphは、本サービスの中心となるクライアント固有の業務知識基盤である。各システムから取得したデータを、リスク分析に使える共通アセットとして正規化する。

### 4.1 主なノード

| ノード | 例 |
|---|---|
| 法人 | 親会社、子会社、海外現法、SPC、JV |
| 拠点 | 本社、工場、倉庫、店舗、データセンター、港湾依存拠点 |
| サプライヤー | 一次サプライヤー、二次サプライヤー、単一調達先、物流会社 |
| 顧客 | 大口顧客、公共顧客、規制産業顧客、海外顧客 |
| 契約 | 供給契約、販売契約、融資契約、保険、SLA、委託契約 |
| 資金 | 銀行口座、現預金、与信枠、借入、社内貸借、為替予約 |
| 取引 | PO、請求書、支払予定、入金予定、売掛金、買掛金、前払金 |
| 財務項目 | 売上、原価、在庫、固定資産、引当、減損、重要性基準 |
| IT資産 | SaaS、クラウド、認証基盤、基幹システム、委託先システム |
| 業務プロセス | 購買、製造、物流、販売、決済、決算、顧客対応 |
| コントロール | BCP、代替調達、保険、承認フロー、内部統制、復旧手順 |

### 4.2 主なリレーション

| リレーション | 例 |
|---|---|
| depends_on | 工場AはサプライヤーBに依存する |
| pays_to | 法人Aは銀行C経由でサプライヤーBに支払う |
| supplies | サプライヤーBは製品Xの重要部材を供給する |
| governed_by | 契約Dは特定国の法令・制裁・輸出規制の影響を受ける |
| funded_by | 子会社Eは本社与信枠または現地銀行借入に依存する |
| reports_to | 財務影響Fは決算、開示、監査に連動する |
| recovered_by | システムGは復旧計画Hに基づき復旧される |
| communicates_to | 危機Iは顧客J、従業員K、当局Lへの説明を要する |

### 4.3 設計上の要点

- システム別のデータ構造ではなく、リスク分析に必要な概念単位に正規化する
- サプライヤー名、法人名、銀行名、国・地域、口座、契約、製品の名寄せを行う
- 重要度、代替可能性、機密度、業務停止許容時間、財務重要性をメタデータとして持たせる
- 各ノードには、データソース、取得日時、品質、更新頻度、権限を付与する
- 機微情報を外部検索に直接渡さないため、外部検索用には匿名化・抽象化された特徴量を生成する



### 4.4 完全接続を前提にしないClient Asset Graph設計

Client Asset Graphは、すべてのクライアントデータに完全接続できることを理想とするが、実務上は以下の制約が存在する。

- セキュリティ、規制、契約上の理由により、AI基盤からアクセスできないデータがある
- Ariba、ERP、TMS、契約管理、文書管理などのデータ構造がクライアントごとに異なる
- 重要な契約、サプライヤー関係、サブティア依存、現場運用が非構造化文書や担当者の暗黙知に残っている
- システム上は取引量が少なく見えても、実際には操業上重要なサプライヤーや金融機関が存在する
- データの鮮度、名寄せ、欠損、権限、粒度が揃わない

そのため、本サービスは「完全なデータ統合ができなければ価値を出せない」設計にはしない。むしろ、アクセスできるデータの範囲で事実を明確化し、不足している情報についてはAIが仮説を立て、専門家とクライアントが検証できる形にする。

```text
Client Asset Graph =
  Source-backed Graph    実データで裏付けられたノード・関係
+ Derived Graph          取引履歴、支払集中、地理情報などから算出した関係
+ Hypothesis Graph       AIが推定した依存関係・波及可能性
+ Assumption Register    専門家またはクライアントが置いた仮定
+ Unknown Register       重要だが未確認の情報
```

#### データ接続レベル

| レベル | 状態 | 分析方針 |
|---|---|---|
| Level 0 | 内部データなし | 公開情報、業界典型シナリオ、専門家知見から仮説を作る |
| Level 1 | メタデータのみ | 国、業界、主要拠点、重要製品など粗い情報で影響範囲を推定する |
| Level 2 | CSV・Excel抽出 | Ariba、ERP、契約台帳などの定期抽出データを使い、静的な分析を行う |
| Level 3 | 構造化API連携 | 支払、PO、請求書、契約、在庫、口座などを定期更新する |
| Level 4 | クライアント環境内連携 | 機微データを外部に出さず、クライアント環境内で分析する |
| Level 5 | 継続学習型連携 | 実際の判断、専門家修正、事後結果を反映して継続改善する |

#### AIの発想力を活かす領域

AIは、事実と仮説を混同しないことを前提に、限られたデータから以下を行う。

- 取引頻度、支払金額、通貨、国、物流経路、契約類型から、潜在的な重要依存関係を推定する
- 過去類似事例や業界パターンから、見落とされやすい波及経路を提示する
- 「このデータがないと判断できない」という確認事項を自動生成する
- 完全なサプライチェーン情報がなくても、単一調達、地域集中、支払集中、契約集中の兆候を検出する
- Legal、Treasury、Accountingなどのモード間で、片方のデータから他方の論点を仮説化する

#### 仮説の扱い

AIの推定結果は、以下のラベルで明示する。

| ラベル | 意味 |
|---|---|
| Known | データまたは信頼できるソースで確認済み |
| Derived | 既存データから計算・名寄せ・集計して導出 |
| Inferred | AIがパターン、類似事例、周辺情報から推定 |
| Assumed | 専門家またはクライアントが明示的に置いた仮定 |
| Unknown | 判断に重要だが未確認 |

InferredまたはAssumedの情報だけで重大な結論を確定しない。ただし、影響が大きい可能性がある場合は、専門家レビューや追加データ要求のトリガーにする。


---

## 5. 外部リスク情報レイヤー

外部リスク情報レイヤーは、Websearchツール、外部API、専門データベース、公開情報を組み合わせ、リスクイベント、弱シグナル、反証情報を収集する。

### 5.1 主な外部ソース

| ソースカテゴリ | 用途 |
|---|---|
| 政府・規制当局 | 法令変更、制裁、輸出規制、業界規制、当局発表 |
| 制裁・AML関連情報 | 取引先、銀行、国・地域、船舶、最終受益者のリスク確認 |
| 財務・開示情報 | EDINET、TDnet、SEC EDGAR、同業他社開示、プレスリリース |
| ニュース・専門メディア | 地政学、企業不祥事、倒産、社会不安、サプライチェーン障害 |
| 気象・災害情報 | 台風、洪水、地震、山火事、干ばつ、港湾・交通障害 |
| サイバー情報 | 脆弱性、攻撃キャンペーン、ベンダー障害、ランサムウェア動向 |
| 市場データ | 為替、金利、商品価格、信用スプレッド、海上運賃 |
| 企業公開情報 | 取引先の決算、プレスリリース、IR、採用、拠点情報 |
| 業界団体・標準化 | 規制前兆、標準変更、業界ガイダンス、技術トレンド |

### 5.2 Websearchの使い方

本サービスにおけるWebsearchは、自由検索によるレポート作成ではなく、統制されたリスクインテリジェンス収集に利用する。

| 利用方法 | 内容 |
|---|---|
| 兆候収集 | 特定国、業界、リスクテーマ、サプライチェーンカテゴリの変化を定期的に確認する |
| 弱シグナル検知 | 規制前兆、価格異常、物流混乱、社会不安、当局発言などを拾う |
| 反証探索 | リスクが過大評価である可能性、沈静化の兆候、代替解釈を探索する |
| ソース比較 | 一次情報、政府発表、専門メディア、企業発表の整合性を確認する |
| 過去類似事例 | 同業他社、他地域、過去危機の事例から波及経路を推定する |
| 差分監視 | 前回分析から新たに増えた証拠、消えた証拠、変わった前提を管理する |

### 5.3 ソース統制

- モードごとに参照可能なソースカタログを設定する
- 政府、規制当局、取引所、企業公式発表、信頼できる専門機関を優先する
- ソースには信頼度、鮮度、直接性、独立性、クライアント関連性を付与する
- 取得日時、URL、要約、引用、抽出項目、AI解釈、専門家コメントをEvidence Ledgerに保存する
- 外部Webページの内容をAIへの命令として扱わないよう、検索結果と実行指示を分離する
- 機密情報を含む検索クエリは生成せず、匿名化・集約化・カテゴリ化された検索を行う

---

## 6. Risk Scenario Model

本サービスでは、リスクシナリオを単なる文章ではなく、構造化された分析オブジェクトとして管理する。

### 6.1 Scenario Genome

```text
Scenario Genome =
  Trigger
+ Hazard
+ Exposed Asset
+ Transmission Path
+ Vulnerability
+ Existing Control
+ Time-to-Impact
+ Financial Impact
+ Legal / Accounting / Operational Consequence
+ Decision Threshold
+ Recommended Action
+ Evidence
+ Confidence
+ Expert Review
```

### 6.2 シナリオの種類

| 種類 | 内容 |
|---|---|
| Immediate Emergency Scenario | 既に発生した危機に対する短期影響分析 |
| Emerging Risk Scenario | 弱シグナルから将来の重大リスクを仮説化する分析 |
| Cascade Scenario | 一次リスクが二次・三次影響へ波及する連鎖分析 |
| Counterfactual Scenario | シナリオが外れる場合の条件、過大評価の可能性を検証する分析 |
| Stress Scenario | 最悪ケース、同時多発ケース、複合危機を想定する分析 |
| Recovery Scenario | 危機発生後の復旧、資金移動、契約対応、開示、広報を扱う分析 |

### 6.3 波及経路の例

```text
地政学的緊張
  ↓
制裁強化・輸出規制
  ↓
特定サプライヤーへの支払・調達制約
  ↓
未納PO、在庫不足、代替調達コスト上昇
  ↓
売上遅延、運転資金悪化、契約違反リスク
  ↓
引当・開示・顧客説明・経営判断
```

---

## 7. 分析モード設計

## 7.1 Executive Emergency Intelligence Mode

経営層向けに、危機の全体像、事業影響、意思決定事項、部門横断の優先順位を提示するモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | CEO、CFO、COO、CRO、リスク委員会、危機対策本部 |
| 主な内部データ | 重要拠点、重要製品、重要顧客、売上構成、BCP、危機対応体制、財務KPI |
| 主な外部情報 | ニュース、政府発表、災害、地政学、制裁、サイバー、規制発表 |
| 主な問い | 何が起きているか。どの事業に影響するか。いつ誰が何を決めるべきか |
| 主な成果物 | 役員向けブリーフ、意思決定メモ、0〜72時間対応表、部門別ToDo、総合リスクスコア |
| 専門家観点 | 危機対応の優先順位、経営判断の遅延リスク、説明責任、対外対応 |

### 代表スコア

- Board Attention Score
- Decision Urgency Score
- Enterprise Impact Score
- Residual Risk after Action
- Confidence Level

---

## 7.2 Treasury & Cash Mobility Mode

エマージェンシーリスクを、資金管理、支払、入金、為替、銀行、与信、資金移動の観点に変換するモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | CFO、Treasurer、財務部、資金管理部、経営企画 |
| 主な内部データ | AribaのPO・請求書・支払予定、ERPのAP/AR、TMS、銀行残高、口座、与信枠、借入、為替予約 |
| 主な外部情報 | 制裁リスト、為替、金利、国別リスク、銀行ニュース、資本規制、災害・地政学ニュース |
| 主な問い | どの資金が動かせなくなるか。どの支払を優先すべきか。どの銀行・国・通貨に集中しているか |
| 主な成果物 | Liquidity-at-Risk、Cash Mobility Map、支払優先順位、資金移動案、為替・資金繰り影響分析 |
| 専門家観点 | 資金繰り、支払統制、制裁・AML、為替ヘッジ、銀行集中リスク、コベナンツ |

### 代表分析

| 分析 | 内容 |
|---|---|
| Liquidity-at-Risk | 危機発生時に実質的に使えなくなる現預金、与信枠、入金を推定する |
| Payment Disruption Map | 制裁、銀行停止、資本規制、災害により止まる可能性のある支払を可視化する |
| Critical Supplier Payment | 支払停止により操業影響が生じるサプライヤーを優先度付けする |
| Cash Repatriation Risk | 海外子会社資金を本社または他拠点へ移動できるかを評価する |
| FX Shock Exposure | 危機に伴う通貨変動が調達、売上、借入、ヘッジに与える影響を推定する |
| Emergency Funding Plan | 代替銀行、代替通貨、社内融通、借入、支払延期の選択肢を整理する |

### 重要な統制

AIは資金移動を自動実行しない。AIは分析、推奨、承認資料、チェックリスト、リスク説明を提供し、実際の送金・支払・ヘッジ実行はクライアントの承認フローと内部統制に従う。

---

## 7.3 Legal & Regulatory Mode

危機や新興リスクを、契約、法令、規制、制裁、訴訟、当局対応、通知義務の観点で分析するモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | 法務、コンプライアンス、経営層、事業部門、外部弁護士連携担当 |
| 主な内部データ | 契約書、契約台帳、取引先、子会社、法務相談履歴、訴訟・紛争、規程、制裁チェック結果 |
| 主な外部情報 | 法令、規制当局発表、制裁リスト、判例・ガイダンス、上場会社開示、企業プレスリリース |
| 主な問い | 契約違反になるか。不可抗力が使えるか。通知義務はあるか。制裁・輸出規制に抵触するか |
| 主な成果物 | 法的論点メモ、契約条項マップ、通知期限リスト、当局対応チェックリスト、外部弁護士相談メモ |
| 専門家観点 | 契約リスク、規制リスク、制裁、紛争化リスク、取締役の説明責任 |

### 代表スコア

- Compliance Criticality
- Contract Breach Risk
- Regulatory Deadline Risk
- Sanctions Proximity Score
- Litigation Escalation Score

### 重要な統制

法務モードの出力は、法的論点の整理、確認事項、文案、相談メモの生成を目的とする。最終的な法的判断は、クライアントの法務部門または弁護士が行う。

---

## 7.4 Accounting & Disclosure Mode

リスクイベントを、会計処理、決算、監査、開示、内部統制の観点で分析するモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | 経理、財務報告、内部統制、監査対応、CFO、監査委員会 |
| 主な内部データ | 総勘定元帳、サブレジャー、在庫、固定資産、予算、見通し、重要性基準、監査調書 |
| 主な外部情報 | 財務開示、同業他社開示、価格・市場データ、規制当局発表、会計基準関連情報 |
| 主な問い | 減損兆候はあるか。引当が必要か。後発事象か。注記・適時開示が必要か。監査人に何を説明するか |
| 主な成果物 | 会計論点メモ、開示影響分析、監査証跡リスト、見積感応度、決算影響シナリオ |
| 専門家観点 | 重要性、会計見積り、継続企業、偶発債務、後発事象、開示統制 |

### 代表スコア

- Materiality Proximity
- Provision Likelihood
- Impairment Trigger Score
- Disclosure Pressure Score
- Audit Evidence Sufficiency

### Legal-Accounting Bridge

法務モードと会計モードは密接に接続する。

```text
規制調査・訴訟・契約違反可能性
  ↓
偶発債務・引当・注記・開示要否
  ↓
監査人説明・経営者確認書・適時開示・投資家説明
```

---

## 7.5 Procurement & Supplier Resilience Mode

サプライヤー、購買、在庫、物流、代替調達の観点から、事業継続への影響を分析するモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | 調達、サプライチェーン、製造、在庫管理、事業部門、CPO |
| 主な内部データ | Ariba、購買履歴、PO、サプライヤーマスター、支出分類、在庫、リードタイム、品質情報 |
| 主な外部情報 | サプライヤー所在国ニュース、物流、災害、制裁、倒産、業界価格、港湾・交通情報 |
| 主な問い | どのサプライヤーが止まると操業に影響するか。代替先はあるか。何日で在庫が尽きるか |
| 主な成果物 | Spend-at-Risk、単一調達リスク、代替サプライヤー候補、価格上昇影響、在庫ランウェイ |
| 専門家観点 | 調達戦略、サプライヤー分散、契約条件、価格転嫁、在庫政策 |

### 代表スコア

- Spend-at-Risk
- Sole Source Dependency
- Inventory Runway
- Supplier Substitution Friction
- Supplier Resilience Score

---

## 7.6 Cyber & Operational Resilience Mode

サイバー攻撃、システム障害、第三者障害、ITサプライチェーンリスクを、業務継続と復旧優先順位の観点で分析するモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | CISO、IT、事業継続、リスク管理、法務、広報、経営層 |
| 主な内部データ | IT資産、SaaS、クラウド、認証基盤、RTO/RPO、委託先、インシデント履歴、BCP |
| 主な外部情報 | 脆弱性情報、ベンダーアドバイザリ、業界インシデント、攻撃キャンペーン、規制報告要件 |
| 主な問い | どの業務プロセスが止まるか。復旧順序はどうするか。通知・開示・顧客対応は必要か |
| 主な成果物 | 業務影響マップ、復旧優先順位、サイバー危機シナリオ、顧客通知案、規制報告チェック |
| 専門家観点 | インシデント対応、証拠保全、委託先管理、法令報告、復旧計画 |

### 代表スコア

- Business Service Impact
- Recovery Gap
- Third-party Cyber Exposure
- Notification Urgency
- Cyber-to-Financial Impact

---

## 7.7 Reputation & Communications Mode

危機時のステークホルダー対応、社内外コミュニケーション、レピュテーションリスク、メディア対応を分析するモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | 広報、IR、法務、経営層、人事、顧客対応、リスク管理 |
| 主な内部データ | 過去プレスリリース、FAQ、顧客対応履歴、ステークホルダー一覧、ブランド方針、開示基準 |
| 主な外部情報 | ニュース、SNS公開情報、同業他社事例、規制当局発表、メディア論調 |
| 主な問い | 誰に、いつ、何を説明すべきか。炎上・誤情報リスクはあるか。法務確認が必要な文言は何か |
| 主な成果物 | 初期声明、Q&A、顧客説明文、社内通知、メディア想定問答、IR向け論点 |
| 専門家観点 | 危機広報、法務確認、開示統制、顧客信頼、従業員コミュニケーション |

### 代表スコア

- Narrative Risk
- Stakeholder Sensitivity
- Media Escalation Probability
- Trust Recovery Difficulty
- Message Consistency Score

---

## 7.8 Cross-Mode War Room

複数モードの分析結果を統合し、部門横断で経営判断を行うためのモード。

| 項目 | 内容 |
|---|---|
| 主な利用者 | 危機対策本部、経営会議、リスク委員会、プロジェクトチーム |
| 主な機能 | 各モードの分析結果統合、部門間の矛盾検出、意思決定事項整理、RACI生成 |
| 主な成果物 | 統合リスクブリーフ、部門別ToDo、意思決定ログ、経営会議資料、訓練台本 |

### 部門間の矛盾検出例

| 矛盾 | 例 |
|---|---|
| Treasury vs Procurement | 調達は前払を求めるが、Treasuryは資金移動制約を懸念している |
| Legal vs Communications | 広報は謝罪を強めたいが、法務は責任認定につながる文言を避けたい |
| Accounting vs Executive | 経営は影響軽微と説明したいが、経理は開示・引当の検討が必要と判断している |
| Cyber vs Operations | ITは完全復旧を待ちたいが、事業部門は代替運用で再開したい |

---

## 8. スコアリング設計

### 8.1 共通リスクスコア

共通リスクスコアは、全モードで共有される基礎評価である。

```text
Common Emergency Risk Score =
  発生可能性
+ 事業影響
+ クライアント曝露度
+ 脆弱性
+ 影響速度
+ 連鎖可能性
+ 検知困難性
+ コントロール有効性
+ 証拠信頼度補正
```

### 8.2 モード別スコア

| モード | 代表スコア |
|---|---|
| Executive | Board Attention、Decision Urgency、Enterprise Impact |
| Treasury | Liquidity-at-Risk、Cash Mobility、Payment Disruption、FX Shock Exposure |
| Legal | Compliance Criticality、Contract Breach Risk、Sanctions Proximity |
| Accounting | Materiality Proximity、Provision Likelihood、Disclosure Pressure |
| Procurement | Spend-at-Risk、Inventory Runway、Sole Source Dependency |
| Cyber | Business Service Impact、Recovery Gap、Notification Urgency |
| Reputation | Narrative Risk、Media Escalation、Stakeholder Sensitivity |

### 8.3 スコアの説明責任

すべてのスコアには、以下を必ず付与する。

- スコアの根拠となる内部データ
- スコアの根拠となる外部ソース
- 仮定
- 不足情報
- 反証情報
- 前回からの変化
- AIの信頼度
- 専門家レビューの有無
- 専門家による修正履歴



### 8.4 専門家知見を組み込んだDecision-firstスコアリング

本サービスのスコアリングは、単に「危険度が高い順」に並べるものではない。経営・部門長が実際に行うべき判断を優先順位化するため、専門家が設計した判断基準、赤旗指標、業界別重み、規制・会計・資金上の期限を組み込む。

```text
Decision Priority Score =
  事業影響
+ 判断期限
+ 不可逆性
+ コントロール不足
+ 部門横断の矛盾
+ 専門家懸念度
+ 証拠信頼度
+ 規制・開示・対外説明の可視性
```

#### 専門家知見の反映方法

| 反映方法 | 内容 |
|---|---|
| Expert Weighting | 業界、地域、機能ごとにスコア重みを専門家が設定する |
| Red Flag Escalation | 制裁、開示、資金移動、重大契約違反などは一定条件で自動的にレビュー対象にする |
| Expert Concern Factor | 専門家が経験上強く懸念する兆候をスコアに反映する |
| Review Threshold | 影響が大きく証拠が弱い案件は、AIが断定せず専門家確認へ回す |
| Calibration | 実際の危機結果、専門家修正、クライアント判断を用いて重みを調整する |
| Override Log | 専門家がAIスコアを修正した場合、理由と履歴を保存する |

#### Decision Queue

リスクランキングに加えて、以下のようなDecision Queueを標準出力とする。

| 項目 | 内容 |
|---|---|
| 判断事項 | 支払を継続するか、停止するか、条件付きにするか |
| 判断期限 | 24時間以内、72時間以内、次回役員会まで、決算締め前など |
| 判断責任者 | CFO、CLO、CPO、CRO、危機対策本部、取締役会など |
| 選択肢 | 継続、停止、延期、代替策、追加調査、外部専門家確認など |
| 推奨案 | AIと専門家知見に基づく推奨対応 |
| 主な根拠 | 内部データ、外部ソース、専門家ルール、過去事例 |
| 反対論点 | 推奨案を採用しない理由、リスク、未確認事項 |
| 実行タスク | RACI、期限、承認、通知文案、証跡保管 |

この設計により、サービスの主画面は「Top 10 Risks」ではなく、「今、判断すべきこと」に変わる。


---

## 9. Expert Knowledge Layer

### 9.1 Expert Knowledge Pack

専門家知見を、再利用可能なパッケージとして管理する。

```text
Expert Knowledge Pack =
  業界別リスク分類
+ 典型シナリオ
+ 赤旗指標
+ スコアリング重み
+ チェックリスト
+ プレイブック
+ 役員会向け説明テンプレート
+ 過去事例
+ ソース信頼度基準
+ 専門家レビュー基準
```

### 9.2 Expert-as-Code

専門家の判断基準を、AIエージェントが実行可能なルール、チェック、重み、警告条件として実装する。

例：

```text
制裁強化の兆候がある国に所在するサプライヤーについて、
未払い債務が存在し、
支払銀行が高リスク地域に所在し、
代替サプライヤーが未登録であり、
対象部材の在庫ランウェイが30日未満の場合、
Treasury RiskとProcurement RiskをHigh以上に設定し、
Legal Modeで制裁・契約・通知義務レビューを必須化する。
```

### 9.3 専門家レビュー

| レビュー種別 | 内容 |
|---|---|
| 初期設定レビュー | クライアントのアセット分類、重要KPI、閾値、データ接続範囲を確認する |
| 高リスクレビュー | 一定スコア以上のシナリオを専門家が確認する |
| モード別レビュー | Treasury、Legal、Accountingなどの専門領域ごとに確認する |
| 月次キャリブレーション | スコアの過大・過小評価、誤検知、見落としを補正する |
| 危機時レビュー | 緊急時の意思決定メモ、外部説明、対応策を確認する |
| 事後レビュー | 実際の結果とAI予測を比較し、知見パックを更新する |

### 9.4 AIと専門家の役割分担

| 領域 | AIが担うこと | 専門家が担うこと |
|---|---|---|
| 情報収集 | 大量の公開情報・社内データの整理 | ソース妥当性、重要性判断 |
| シナリオ生成 | 複数パターンの洗い出し、波及経路生成 | 現実性、優先順位、盲点確認 |
| スコアリング | 初期スコア、差分検知、トリガー判定 | 重み調整、キャリブレーション、最終判断補助 |
| 法務・会計 | 論点抽出、文案、確認事項整理 | 法的・会計的な最終見解、責任ある助言 |
| トレジャリー | 資金影響、支払優先度、資金移動案 | 実行可否、統制、承認判断、銀行対応 |
| 危機対応 | プレイブック、RACI、通知案 | 経営判断支援、利害調整、対外説明 |



### 9.5 Expert-as-Code化の方法論：個別回答方式 × Cognitive Task Analysis

Expert-as-Codeは、専門家の暗黙知を単純なif-thenルールへ置き換えることではない。専門家の判断結果だけでなく、判断に至る問い、着眼点、違和感、例外、反証、エスカレーション基準を、AIエージェントが参照・適用・検証できる知識部品へ変換する方法論である。

本サービスでは、専門家知見の抽出手法として、**個別回答方式**と**Cognitive Task Analysis（CTA）方式**を組み合わせる。個別回答方式は、複数の専門家が同じケースに対して独立に判断することで、専門家ごとの評価、重視点、判断のばらつきを収集する。CTA方式は、専門家がケースを読んだときの違和感、確認順序、見落としやすい兆候、判断が変わる条件を深掘りし、言語化されにくい実務知を抽出する。

```text
Scenario / Case
  ↓
個別回答方式
  - 専門家ごとの初期判断、スコア、理由、赤旗、不足情報を収集
  ↓
Cognitive Task Analysis
  - 判断順序、違和感、例外、反証、追加確認の思考プロセスを抽出
  ↓
Knowledge Primitive化
  - Red Flag、Rule、Rubric、Threshold、Exception、Evidence Standardへ分解
  ↓
Mode Pack / Scoring / Review Workflowへ実装
  ↓
運用結果と専門家修正でキャリブレーション
```

#### 9.5.1 なぜこの組み合わせにするか

| 観点 | 個別回答方式 | Cognitive Task Analysis方式 | 組み合わせによる価値 |
|---|---|---|---|
| 取得できる知見 | 専門家ごとの結論、スコア、判断理由 | 判断順序、違和感、暗黙の確認観点 | 結論とプロセスの両方を知見化できる |
| バイアス対策 | 合議前に回答するため、声の大きい人に引っ張られにくい | 事後説明ではなく、判断中の思考を掘り下げる | 形式知と暗黙知の偏りを補正できる |
| AI実装との相性 | スコア、ルーブリック、レビュー条件にしやすい | Red Flag、Missing Data、Counterfactualにしやすい | スコアリングと発想支援の両方に使える |
| 差別化 | 専門家の多数意見・少数意見を残せる | 専門家の「なぜ気づけるか」を再利用できる | 単なる専門家監修ではなく判断体系を実装できる |

#### 9.5.2 Scenario Bankの設計

専門家に回答してもらうシナリオは、読み物ではなく、判断訓練と知見抽出に使える構造化ケースとして管理する。

```text
Scenario Card =
  Scenario ID
+ リスクカテゴリ
+ 発生地域・法域
+ 発生イベント
+ 影響対象アセット
+ 利用可能な内部データ
+ 利用できない内部データ
+ 外部証拠と信頼度
+ 時間軸
+ 事業影響の仮説
+ モード別論点
+ 意思決定期限
+ 専門家に問うべき判断事項
```

シナリオは、実務に合わせて**不完全な情報**を意図的に含める。契約書が未接続、銀行データが欠落、サブサプライヤーが不明、在庫日数が古い、外部情報が報道段階に留まる、といった状態でも、AIと専門家が何を疑い、何を確認し、どこまで助言してよいかを知見化する。

| 設計軸 | バリエーション例 |
|---|---|
| リスクタイプ | 地政学、制裁、災害、サイバー、規制変更、物流停止、金融市場混乱 |
| 影響アセット | サプライヤー、口座、契約、拠点、顧客、在庫、IT、子会社 |
| データ充足度 | 十分、一部欠落、ほぼ不明、矛盾あり |
| 時間制約 | 即時、72時間以内、1週間以内、決算前、役員会前 |
| 証拠信頼度 | 政府発表、当局通知、企業開示、報道、専門メディア、SNS、噂 |
| 判断の難しさ | 明確、グレー、専門家間で割れる、部門間で衝突する |

特に重視するのは、明らかなHighリスクだけでなく、**境界ケース**である。たとえば、「証拠は弱いが影響が大きい」「LegalではHighだがTreasuryではMedium」「支払停止は制裁リスクを下げるが操業リスクを上げる」といったケースを多く用意する。

#### 9.5.3 Question Bankの設計

Question Bankは、専門家の回答を再利用可能な知見に変換できるよう、判断を分解する質問で構成する。

```text
共通質問
1. このケースで最初に見るべき情報は何か
2. どの情報が不足しているか
3. どの赤旗があるか
4. High / Medium / Lowを分ける条件は何か
5. 判断を変える追加情報は何か
6. どの部門、専門家、役員にエスカレーションすべきか
7. どの意思決定が最も時間制約を受けるか
8. この判断が過大評価だった場合、どの前提が崩れているか
9. この判断が過小評価だった場合、何を見落としている可能性があるか
10. クライアントに今すぐ確認すべき質問は何か
```

モード別には、専門領域ごとの問いを用意する。

| モード | 代表的な質問 |
|---|---|
| Treasury | 支払を継続、停止、延期、代替経路にする判断基準は何か。資金移動リスクをHighにする条件は何か |
| Legal | 制裁、輸出規制、契約違反、通知義務のうち何を最初に確認すべきか。外部弁護士確認が必須になる条件は何か |
| Accounting | 引当、減損、後発事象、開示のどの論点を優先するか。重要性基準が未入力の場合に何を仮定するか |
| Procurement | 代替調達の可否、在庫ランウェイ、単一調達、サブティア依存のどれを優先確認するか |
| Communications | 顧客、従業員、当局、メディアのうち、誰にどのタイミングで説明すべきか |

#### 9.5.4 個別回答方式の運用

専門家には、合議や相互参照の前に個別で回答してもらう。これにより、専門家ごとの判断基準、少数意見、専門領域の違いを収集できる。

```text
Expert Response Template

1. 初期評価
- 総合リスク
- Treasury Risk
- Legal Risk
- Accounting Risk
- Procurement Risk
- Evidence Confidence
- Decision Urgency

2. 判断理由
- 重視した事実
- 無視した、または重みを低く見た事実
- 不足情報
- 判断を変える条件

3. 赤旗と確認事項
- Red Flag
- Missing Data
- Client Question
- External Source to Check

4. 推奨アクション
- 0-24h
- 24-72h
- 1 week
- Board / Executive Decision

5. AI出力上の注意
- 言ってよい表現
- 言ってはいけない表現
- 専門家レビューが必要な条件
```

個別回答は、最終合意を作るためだけでなく、**専門家間のばらつきそのもの**を知見として扱う。ばらつきが大きいケースは、AIが断定を避け、Context Sufficiency、Evidence Confidence、Expert Review Requiredを強く表示する対象にする。

#### 9.5.5 Cognitive Task Analysis方式の運用

CTAでは、専門家にケースまたはAIの初期分析を見せ、どこで違和感を持ったか、どの順番で確認したか、何があれば判断が変わるかを深掘りする。

```text
CTA Interview Guide

1. 最初に目に入った情報は何か
2. どの時点で「危ない」「まだ断定できない」と感じたか
3. その違和感は、過去のどの経験やパターンに由来するか
4. AIの初期分析で足りない観点は何か
5. AIが過大評価している可能性はどこにあるか
6. AIが過小評価している可能性はどこにあるか
7. 判断を一段階上げる条件は何か
8. 判断を一段階下げる条件は何か
9. クライアントに最初に聞くべき質問は何か
10. 役員会に出すなら、どの問いに変換するか
```

CTAで抽出すべき対象は、最終結論ではなく、以下のような判断プロセスである。

| 抽出対象 | 内容 | Expert-as-Codeへの変換先 |
|---|---|---|
| 判断順序 | まず支払銀行、次に最終受益者、最後に契約通知を見る | Decision Tree、Checklist |
| 違和感 | 請求元と契約相手が異なる、急な前払要求がある | Red Flag、Review Trigger |
| 例外 | 政府ライセンスがある場合は制裁リスクを下げる | Exception Rule |
| 反証 | 代替サプライヤー認定済みなら調達リスクは下がる | Counterfactual |
| 表現制約 | 違法と断定せず、抵触可能性として記載する | Language Guardrail |
| 経営への翻訳 | 支払継続リスクと操業停止リスクのどちらを取るか | Board Challenge Question |

#### 9.5.6 Knowledge Primitiveへの分解

個別回答とCTAから得た知見は、以下のプリミティブに分解する。

| プリミティブ | 内容 | 例 |
|---|---|---|
| Red Flag | 注意すべき兆候 | 支払先銀行変更、最終受益者不明、急な前払要求 |
| Data Requirement | 追加で必要な情報 | 契約通知期限、支払通貨、代替サプライヤー認定状況 |
| Rule | 条件付き判断 | 制裁近接先かつ未払い額大ならLegal Review必須 |
| Rubric | 段階評価基準 | Sanctions Proximity 1〜5、Disclosure Pressure 1〜5 |
| Threshold | 閾値 | 14日以内の支払期日、在庫10日未満、決算30日以内 |
| Exception | 例外条件 | 政府許可、代替銀行確保、契約上ペナルティなし |
| Evidence Standard | 必要な根拠水準 | 当局ソースなしにHigh Confidenceにしない |
| Review Trigger | 専門家確認条件 | 影響大かつ証拠弱、法務・会計判断を含む |
| Language Guardrail | 出力表現の制約 | 「違反」と断定せず「抵触可能性」と表現 |
| Board Question | 経営向け論点 | 支払停止リスクと操業停止リスクのどちらを優先するか |
| Counterfactual | 判断を下げる反証条件 | 代替調達済み、在庫十分、支払経路に制約なし |

#### 9.5.7 Knowledge Objectへの変換

Knowledge Primitiveは、AIエージェントが使えるKnowledge Objectへ変換する。

| Knowledge Object | 用途 | 主な適用先 |
|---|---|---|
| Rule-as-Code | 明確な条件で処理を発動する | Review Trigger、エスカレーション、期限管理 |
| Rubric-as-Code | 専門家の段階評価をスコアにする | Legal Risk、Disclosure Pressure、Cash Mobility |
| Pattern-as-Code | 複合リスクの典型連鎖を保持する | Scenario Engine、Analogical Reasoning |
| Playbook-as-Code | 推奨対応を時間軸・担当別に出す | Decision & Action Layer |
| Review-as-Code | 専門家レビュー要否を判定する | Expert Review Queue |
| Evidence-as-Code | 必要な証拠水準と信頼度を制御する | Evidence Ledger、Quality Layer |
| Language-as-Code | 出力の断定度、注意書き、禁止表現を制御する | Legal、Accounting、Reputation |

#### 9.5.8 実装例

```text
Scenario:
高リスク国で銀行規制が発生。
現地サプライヤーへの支払期日が10日後。
Aribaには未払い請求書あり。
銀行口座情報は未接続。
契約書は未接続。
代替サプライヤー情報は不明。

個別回答から抽出された知見:
- 支払期日が近く、重要サプライヤーであればTreasury Review必須
- 銀行情報が欠落している場合、支払可能性をHigh Confidenceで言わない
- 代替先不明なら、支払停止推奨を単独では出さない

CTAから抽出された知見:
- 専門家は最初に支払経路、次に最終受益者、最後に契約通知を確認する
- 「支払を止めるべき」ではなく、「支払継続・延期・代替経路・調達影響を合同判断すべき」と表現する
- 代替サプライヤーが認定済みなら、Procurement Riskは一段階下がる

Code化:
- Treasury Review Required = True
- Legal Review Required = True
- Cash Mobility Confidence <= Medium
- Payment Hold Recommendation cannot be issued alone
- Decision QueueにCFO / Legal / Procurement合同判断を追加
```

#### 9.5.9 知見化のライフサイクル

```text
Draft Scenario
  ↓
Individual Expert Response
  ↓
CTA Interview
  ↓
Knowledge Primitive Extraction
  ↓
Knowledge Object Draft
  ↓
Expert Review
  ↓
Validation on Cases
  ↓
Approved Knowledge Pack
  ↓
Runtime Use
  ↓
Expert Correction / Backtesting
  ↓
Recalibration / Deprecation
```

各Knowledge Objectには、作成者、レビュー者、承認者、対象業界、対象地域、対象モード、適用開始日、失効条件、バージョン、過去の修正履歴を付与する。これにより、専門家知見を属人的な助言ではなく、監査可能で継続改善可能なサービス資産として管理する。

### 9.6 Expert Knowledge Studio

専門家知見を継続的に資産化するため、アドバイザリー会社側にはExpert Knowledge Studioを設ける。

| 機能 | 内容 |
|---|---|
| Scenario Bank Manager | 公開事例、匿名化案件、仮想ケース、境界ケースを構造化して管理する |
| Question Bank Manager | 共通質問、モード別質問、経営向け質問、反証質問を管理する |
| Individual Response Collector | 専門家ごとの個別回答、初期スコア、判断理由、少数意見を収集する |
| CTA Interview Workbench | 専門家の判断順序、違和感、例外、反証、表現制約をインタビュー形式で抽出する |
| Knowledge Primitive Extractor | 回答とCTA記録からRed Flag、Rule、Rubric、Exception、Evidence Standardを抽出する |
| Rule / Rubric Editor | 専門家がルール、ルーブリック、閾値、レビュー条件を編集・承認する |
| Pattern Library | 制裁、災害、サイバー、物流停止などの典型的な波及パターンを管理する |
| Playbook Library | 0〜24時間、24〜72時間、1週間以内などの対応手順を管理する |
| Validation Bench | 過去ケース、仮想ケース、専門家回答との照合でKnowledge Objectを検証する |
| Calibration Console | スコア重み、閾値、専門家懸念度、誤検知・見落としを補正する |
| Release Manager | 業界、地域、法域、提供形態ごとにKnowledge Packを版管理・配布する |
| Feedback Loop | クライアント判断、専門家修正、実際の結果を知見更新に反映する |


---

## 10. AIエージェントの分析フロー

```text
1. リスクイベントまたは弱シグナルを検知
   ↓
2. 関連するクライアントアセットを特定
   ↓
3. モード別に必要データと外部ソースを選択
   ↓
4. Websearchおよび外部ソースから証拠を収集
   ↓
5. 内部データと外部情報をClient Asset Graph上で接続
   ↓
6. シナリオ、波及経路、影響対象を生成
   ↓
7. 共通スコアとモード別スコアを算出
   ↓
8. 反証探索と不確実性評価を実施
   ↓
9. 部門間の矛盾と意思決定論点を抽出
   ↓
10. 専門家レビューが必要な箇所を特定
   ↓
11. 専門家コメント、修正、承認を反映
   ↓
12. 経営判断メモ、プレイブック、タスク、文案を生成
   ↓
13. Evidence Ledger、Decision Log、Scenario Delta Ledgerに保存
```

---

## 11. 主な成果物

| 成果物 | 内容 |
|---|---|
| Scenario Card | リスクシナリオ、影響対象、波及経路、スコア、推奨対応を1枚で表示する |
| Executive Brief | 経営層向けに、何をいつ決めるべきかを整理する |
| Risk-to-Cash Report | 危機が資金、支払、入金、為替、与信に与える影響を示す |
| Legal Issue Memo | 契約、法令、制裁、通知義務、外部弁護士確認事項を整理する |
| Accounting Impact Memo | 引当、減損、後発事象、開示、監査証跡を整理する |
| Supplier Resilience Report | サプライヤー停止、在庫、代替調達、価格影響を分析する |
| Cyber-to-Operation Map | サイバー障害が業務プロセス、顧客対応、法務・広報に与える影響を示す |
| Crisis Communication Kit | 初期声明、Q&A、社内通知、顧客説明、メディア想定問答を生成する |
| RACI & Action Plan | 誰が、何を、いつ、どの承認で実行するかを整理する |
| Scenario Delta Ledger | 前回分析からの証拠、前提、スコア、専門家コメントの差分を記録する |
| Evidence Ledger | すべての根拠、ソース、取得日時、信頼度、AI解釈、専門家コメントを記録する |
| Decision Log | 経営判断、承認、保留、再評価条件を記録する |
| War-game Script | 役員・部門横断訓練用の危機シミュレーション台本を生成する |

---

## 12. UI / UX設計

### 12.1 Lens Switcher

同じリスクイベントを、分析モードごとに切り替えて表示する。

```text
リスクイベント：主要港湾停止

Executive Lens:
  売上、操業、顧客影響、経営判断

Treasury Lens:
  支払予定、運転資金、代替輸送費、為替、資金移動

Legal Lens:
  契約履行、不可抗力、顧客通知、規制対応

Accounting Lens:
  在庫評価、引当、後発事象、開示

Procurement Lens:
  代替調達、在庫日数、価格上昇、サプライヤー集中

Reputation Lens:
  顧客説明、メディア対応、社内通知、炎上リスク
```

### 12.2 Risk Dashboard

- Critical / High / Medium / Lowの件数
- スコア急上昇リスク
- 経営判断が必要なリスク
- 専門家レビュー待ちリスク
- 証拠信頼度が低いが影響が大きいリスク
- 部門横断の未解決論点
- 期限超過タスク

### 12.3 Scenario Workspace

- シナリオ本文
- クライアント影響マップ
- モード別分析タブ
- スコア根拠
- 反証情報
- 専門家コメント
- 推奨対応
- RACI
- 文案生成
- 証拠台帳
- 変更履歴

---

## 13. ガバナンス・セキュリティ設計

### 13.1 基本原則

- AIは意思決定を支援するが、重要判断を自動実行しない
- 資金移動、支払、契約通知、開示、法的見解、会計判断は人間の承認を必須とする
- クライアント機密情報は、検索クエリや外部APIに直接送信しない
- すべての出力に根拠、仮定、不確実性、更新日時、レビュー状況を付与する
- 専門家修正履歴を保存し、AI出力との差分を追跡する

### 13.2 主要統制

| リスク | 統制 |
|---|---|
| 機密情報漏洩 | データ分類、匿名化検索、権限管理、暗号化、クライアント環境分離 |
| 誤情報 | ソース信頼度、複数ソース確認、一次情報優先、反証探索 |
| 古い情報 | 取得日時、鮮度スコア、差分監視、再取得トリガー |
| 過剰警告 | 過去事例比較、反証探索、専門家キャリブレーション |
| 見落とし | レッドチームエージェント、部門横断レビュー、弱シグナル監視 |
| プロンプトインジェクション | 外部コンテンツと実行命令の分離、ソースサニタイズ、ツール実行制御 |
| ブラックボックス化 | スコア根拠、重み、仮定、データソース、専門家修正を表示 |
| 責任所在不明 | 承認フロー、Decision Log、レビュー履歴、利用者権限 |

---

## 14. 提供形態

本サービスは、クライアントの機密性、規制要件、運用体制に応じて、複数の提供形態を選択できる。

### 14.1 Managed Risk Advisory Service

リスクアドバイザリー会社がAI分析と専門家レビューを一体で提供するモデル。

| 観点 | 内容 |
|---|---|
| 向いている顧客 | リスク管理部門が小さい企業、グローバル展開企業、外部専門家支援を求める企業 |
| 強み | 専門家知見を継続的に反映できる。高度な分析を運用負荷少なく利用できる |
| 留意点 | 機密データ共有、データ処理場所、権限、契約上の責任範囲を明確化する必要がある |
| 主な収益 | 月額監視、モード別利用料、専門家レビューSLA、危機時支援、役員会ブリーフ |

### 14.2 Standalone Client Environment

クライアントのクラウド、VPC、オンプレミス、閉域環境で実行するモデル。

| 観点 | 内容 |
|---|---|
| 向いている顧客 | 金融、インフラ、防衛、製薬、大企業、機密性が極めて高い企業 |
| 強み | 機密データを外部に出さない。内部統制・監査に乗せやすい |
| 留意点 | クライアント側の運用負荷、知見更新、外部情報の取り込み方式を設計する必要がある |
| 主な収益 | ライセンス、Mode Pack、Knowledge Pack、年次アップデート、専門家レビュー別料金 |

### 14.3 Hybrid Secure Advisory Model

機密データ処理はクライアント環境で行い、外部リスク情報と専門家知見はアドバイザリー会社側から提供するモデル。

| 観点 | 内容 |
|---|---|
| 向いている顧客 | データ保護と専門家レビューの両方を重視する企業 |
| 強み | 機密性と専門家知見を両立できる。最も汎用性が高い |
| 留意点 | 匿名化された特徴量、証拠パッケージ、レビュー対象範囲の設計が重要 |
| 主な収益 | 基本ライセンス、マネージドレビュー、知見更新、緊急対応、訓練支援 |

---

## 15. 代表ユースケース

### 15.1 地政学・制裁リスクと資金管理

```text
外部リスク：特定国への制裁強化の兆候
内部データ：Aribaの未払い請求書、TMSの支払予定、銀行口座、サプライヤー契約
分析：
  - 未払い債務と支払銀行の制裁・資金移動リスク
  - 重要サプライヤーへの支払停止による操業影響
  - 契約上の通知義務、不可抗力、解除条項
  - 引当、開示、監査人説明の要否
成果物：
  - Cash Mobility Map
  - Legal Issue Memo
  - Accounting Impact Memo
  - 経営判断メモ
  - 支払優先順位と承認資料
```

### 15.2 サイバー攻撃と業務・法務・広報への波及

```text
外部リスク：同業界でランサムウェア攻撃が急増
内部データ：CMDB、SaaS利用状況、重要業務プロセス、RTO/RPO、顧客契約
分析：
  - 攻撃対象になりやすいシステムと事業影響
  - 復旧優先順位と代替運用
  - 顧客通知義務、規制報告、契約違反リスク
  - 社内外コミュニケーションとメディア対応
成果物：
  - Cyber-to-Operation Map
  - 通知義務チェックリスト
  - 顧客説明文
  - 危機対応プレイブック
```

### 15.3 気候・災害リスクとサプライチェーン・会計影響

```text
外部リスク：主要サプライヤー地域で大規模洪水
内部データ：サプライヤーマスター、PO、在庫、リードタイム、売上予測、契約
分析：
  - 供給停止時の在庫ランウェイ
  - 代替調達コストと価格転嫁可能性
  - 納期遅延による契約違反・顧客対応
  - 在庫評価、減損、引当、後発事象の可能性
成果物：
  - Supplier Resilience Report
  - Risk-to-Cash Report
  - Legal Issue Memo
  - Accounting Impact Memo
  - 役員向け判断メモ
```

---

## 16. サービスの差別化

| 一般的なAIサービス / リサーチサービス | 本サービス |
|---|---|
| 公開情報を調査してレポート化する | 外部リスクをクライアント固有の業務データに接続する |
| 汎用的な回答を生成する | Treasury、Legal、Accountingなど専門モードで分析する |
| 単発の調査に強い | 継続監視、差分更新、アラート、履歴管理に強い |
| 引用付き要約が中心 | スコア、判断事項、RACI、プレイブック、文案まで生成する |
| AIの出力品質に依存する | 専門家知見、レビュー、Expert-as-Codeで品質を担保する |
| 部門ごとに分断されやすい | 同じアセットを複数レンズで横断分析する |
| 結果の監査性が限定的 | Evidence Ledger、Scenario Delta Ledger、Decision Logを標準装備する |
| クライアントごとの差異を反映しにくい | 拠点、契約、資金、取引、KPI、BCPに合わせて個別化する |

---

## 17. 事業化の方向性

本サービスは、単一のSaaSではなく、以下を組み合わせた高付加価値型サービスとして提供する。

```text
Platform License
+ Mode Pack
+ Expert Knowledge Pack
+ Expert Review SLA
+ Managed Advisory
+ Standalone Deployment
+ Hybrid Secure Operation
+ War-game / Training
+ Crisis Response Add-on
```

### 17.1 収益構成

| 収益項目 | 内容 |
|---|---|
| 基本プラットフォーム利用料 | Client Asset Graph、ダッシュボード、証拠台帳、基本分析機能 |
| Mode Pack利用料 | Treasury、Legal、Accounting、Procurementなどの専門モード |
| データ接続料 | Ariba、ERP、TMS、銀行、契約管理、GRCなどとの接続 |
| Expert Knowledge Pack | 業界別・地域別・リスク別の知見パッケージ |
| 専門家レビューSLA | 高リスクシナリオ、月次レビュー、危機時レビュー |
| マネージドサービス | 継続監視、週次・月次ブリーフ、緊急アラート |
| スタンドアロン導入 | クライアント環境への導入、更新、保守 |
| 訓練・ウォーゲーム | 役員向け危機対応訓練、部門横断演習 |

---

## 18. 最終的なポジショニング

本サービスは、AI調査ツールでも、従来型GRCツールでも、単発のコンサルティングレポートでもない。

本サービスは、以下を統合した新しいリスクアドバイザリー基盤である。

- クライアント固有の業務アセット
- Websearchを含む外部リスクインテリジェンス
- Treasury、Legal、Accountingなどの専門分析モード
- リスクアドバイザリー専門家の知見
- 監査可能な証拠と意思決定ログ
- 実行可能な対応策と危機訓練

最終的な訴求メッセージは以下である。

> Risk Advisory Intelligence Platformは、危機を「ニュース」や「レポート」で終わらせず、クライアント固有の資金、契約、会計、調達、IT、広報、経営判断に変換する。  
> AIと専門家知見を組み合わせ、企業が危機の兆候を早く捉え、影響を正しく読み、説明責任を果たしながら動くための、次世代リスクアドバイザリー基盤である。


---

## 19. 先行レポート・サービスから取り込む設計原則

本サービスは、一般的なAIリサーチやDeep Research型サービスとの差別化を明確にするため、コンサルティング会社、リスクインテリジェンス会社、調査会社が従来行ってきた工夫を、プロダクト仕様と運用仕様に落とし込む。

### 19.1 参考にした先行事例

| 先行事例 | 主な差別化要素 | 本サービスへの反映 |
|---|---|---|
| WEF / Marsh Global Risks Report | 複数時間軸、大規模専門家サーベイ、リスク相互連関 | 時間軸別シナリオ、複合リスク、Risk Causal Graph |
| Aon Global Risk Management Survey | 業界・地域別ベンチマーク、Top Riskランキング | 業界・地域・機能別ベンチマーク、成熟度比較 |
| PwC Crisis and Resilience Survey | レジリエンス成熟度、危機対応力のギャップ分析 | Resilience Readiness Score、備えの不足可視化 |
| KPMG Risk and Resilience Survey | 統合リスク管理、部門横断ビュー、ガバナンス | Cross-Mode War Room、部門間矛盾検出 |
| EY Global Risk Transformation Study | Risk Strategist、将来兆候、戦略との接続 | Risk Intelligence Maturity、Board Challenge Questions |
| McKinsey Operational Resilience | 重要業務サービス、ストレステスト、ウォーゲーム | Scenario Object、Intervention Library、War-game Script |
| Deloitte Risk Sensing / TPRM / Risk Intelligence | ノイズ削減、レッドフラグ、統制、専門IP | Risk Intelligence Quality Layer、Expert-as-Code |
| Seerist / Control Risks | AI検知、検証済みイベント、人間専門家分析 | Expert-verified Intelligence、Evidence Board |
| Everstream Analytics | サプライチェーンネットワーク、サブティア可視化、Insights-to-Action | Client Asset Graph、Supplier-Payment-Contract連携 |
| Gartner Emerging Risk Report | エマージングリスク、原因・結果の接続、経営向け簡素化 | Decision-first Output、Emerging Risk Radar |

### 19.2 差別化の型

| 差別化の型 | 従来サービスでの工夫 | 本サービスでの実装 |
|---|---|---|
| 独自分類 | リスク分類、リスク宇宙図、国別レーティング | Emergency Risk Taxonomy、Mode-specific Taxonomy |
| ベンチマーク | 業界・地域・役職別サーベイ | 匿名化ベンチマーク、成熟度モデル、Peer Pattern |
| 専門家性 | 専門家インタビュー、アナリストレポート | Expert Knowledge Pack、Expert-as-Code、Expert Review Queue |
| 継続更新 | 四半期レポート、リアルタイムモニタリング | Scenario Delta Ledger、差分アラート、Evidence Ledger |
| 相互連関 | 複合リスク、リスクマップ | Risk Causal Graph、Cascade Scenario |
| 実行可能性 | プレイブック、ストレステスト、ウォーゲーム | RACI、Action Board、War-game Script、Intervention Library |
| 品質統制 | ソース選別、専門家確認、監査ログ | Source Reliability、Expert Validation、Backtesting |
| 経営向け変換 | 取締役会向け論点、What-if質問 | Decision Queue、Board Challenge Questions |

### 19.3 本サービス固有の設計原則

1. **Research-to-Decision**  
   調査結果を読む資料で終わらせず、意思決定、担当、期限、証跡へ変換する。

2. **Client Context over Generic Intelligence**  
   一般論のリスクではなく、クライアントの資金、契約、取引、会計、拠点、業務プロセスに接続する。

3. **Sparse Contextでも価値を出す**  
   完全なデータ統合を前提にせず、限られたデータから仮説を立て、Unknownを明示し、追加確認へつなげる。

4. **Expert Knowledgeを実行可能にする**  
   専門家の知見をコメントではなく、ルール、KRI、ルーブリック、チェックリスト、プレイブックとして実装する。

5. **Evidence and Delta by Design**  
   すべての根拠、反証、変更、専門家修正、判断履歴を追跡できるようにする。

6. **Decision-first Scoring**  
   危険度ランキングではなく、経営判断の優先順位、判断期限、選択肢、反対論点を提示する。

7. **AI + Expert + Client Feedback Loop**  
   AIの発見力、専門家の判断力、クライアントの業務知識を循環させ、知見を継続的に改善する。

---

## 20. 独自メソドロジー：Sense, Map, Imagine, Challenge, Decide

本サービスの方法論は、以下の7ステップで構成する。

```text
1. Sense
   外部リスクシグナルを検知する

2. Contextualize
   アクセス可能なクライアント情報で文脈化する

3. Map
   確認済みデータをClient Asset Graphへ接続する

4. Imagine
   不足情報を前提に、AIが仮説、類似事例、波及経路を生成する

5. Challenge
   反証探索、レッドチーム、専門家レビューで過大評価・過小評価を検証する

6. Score & Decide
   専門家知見を組み込んだスコアとDecision Queueを生成する

7. Learn
   実際の結果、専門家修正、クライアント判断を知見パックへ反映する
```

### 20.1 Imagineを公式な分析工程に入れる理由

エマージェンシーリスク分析では、必要なデータが常に揃っているとは限らない。むしろ、危機発生時には、サプライヤーのサブティア、現地銀行の制約、契約条項、在庫実態、現場の代替策などが不完全な状態で判断を迫られる。

このときAIの強みは、断定ではなく、以下のような発想支援にある。

- あり得る波及経路を複数提示する
- 見落としやすい部門横断の論点を出す
- 過去類似事例から確認すべき仮説を作る
- 追加データがあれば結論がどう変わるかを示す
- どのUnknownを先に潰すべきかを優先順位化する

ただし、Imagineで生成された内容は、必ずKnown、Derived、Inferred、Assumed、Unknownのラベルを持つ。AIの発想力を使いながら、事実と仮説を混同しないことが、本サービスの品質要件である。

---

## 21. 差別化ポイントの詳細設計

### 21.1 Client Asset Graph：完全接続ではなく、Sparse-to-Rich Contextを前提にする

Client Asset Graphは理想的にはすべての業務データに接続するが、実務では完全接続は難しい。そのため、サービス設計上は以下の考え方を採用する。

#### 基本方針

```text
完全なデータがあるから分析できる
ではなく、
限られたデータから、確認済み事実・推定・仮定・不足情報を分けて、判断に使える形にする。
```

#### Sparse-to-Rich Context Model

| 層 | 内容 | 役割 |
|---|---|---|
| Minimum Context | 業界、国、主要拠点、重要製品、主要リスクテーマ | 初期仮説と外部リスク監視に使う |
| Extracted Context | Ariba、ERP、契約台帳などのCSV・Excel抽出 | 静的なスコアリングと影響推定に使う |
| Connected Context | APIやデータレイク経由の構造化データ | 継続監視、差分更新、アラートに使う |
| Secured Context | クライアント環境内でのみ処理できる機微データ | 高精度分析、ただし外部送信はしない |
| Expert Context | 現場・専門家・過去事例から得た暗黙知 | 仮説補正、レビュー、判断基準に使う |

#### AIが担う発想支援

| 機能 | 内容 | 統制 |
|---|---|---|
| Dependency Inference | 支払集中、取引頻度、地理情報から潜在依存を推定する | Inferredとしてラベル付けする |
| Scenario Expansion | 一つのリスクから複数の波及経路を生成する | 反証探索と専門家レビューを付ける |
| Missing Data Prioritization | 追加取得すべきデータを優先順位化する | 判断影響度を表示する |
| Analogical Reasoning | 他社・他地域・過去事例から類似パターンを提示する | 類似度と相違点を表示する |
| Safe Search Abstraction | 機密名を使わず、地域・業界・部材カテゴリで検索する | 検索クエリを監査ログに残す |

#### Context Sufficiency Score

各シナリオには、分析に必要な文脈がどれだけ揃っているかを示すContext Sufficiency Scoreを付与する。

| スコア | 状態 | 解釈 |
|---|---|---|
| High | 主要な内部データ、外部証拠、専門家確認が揃っている | 具体的な対応判断に使いやすい |
| Medium | 主要データはあるが、契約・サブティア・現場情報などに不足がある | 追加確認付きで判断する |
| Low | 外部情報と限定的な内部情報のみ | 仮説生成、初期警戒、レビュー依頼に使う |

重要なのは、Context SufficiencyがLowでも分析を止めないことである。Lowの場合は、断定を避けつつ、想定される影響、確認すべきデータ、専門家レビューの優先度を提示する。

### 21.2 Expert-as-Code：個別回答とCTAで専門家判断を実行可能部品へ変換する

Expert-as-Codeは、専門家の判断を一気に自動化する取り組みではない。専門家が日々行っている判断を、AIと人間が再利用できる形へ段階的に変換する取り組みである。

本サービスでは、専門家知見の抽出を、**個別回答方式**と**Cognitive Task Analysis方式**の組み合わせで行う。

- 個別回答方式：複数の専門家が同一シナリオに対して独立に回答し、スコア、判断理由、不足情報、赤旗、推奨対応、出力上の注意を収集する
- Cognitive Task Analysis方式：専門家が何に違和感を持ち、どの順番で確認し、どの条件で判断を変えるかを深掘りし、暗黙知を抽出する

#### 変換対象

| 専門家の知見 | 変換後の形 |
|---|---|
| 「この兆候は危ない」 | Red Flag、KRI、Review Trigger |
| 「この情報がないと判断できない」 | Data Requirement、Unknown Register、Context Sufficiency Rule |
| 「この場合は法務確認が必要」 | Rule、Checklist、Escalation Condition |
| 「この業界では影響が大きい」 | Industry Weight、Scenario Pattern |
| 「この証拠だけでは弱い」 | Evidence Standard、Confidence Rule |
| 「この順番で確認すべき」 | Decision Tree、Workflow、RACI |
| 「過去に似た事例がある」 | Case Pattern、Analogical Reference |
| 「この表現は危ない」 | Language Guardrail、Disclosure Guardrail |
| 「経営にはこの問いを投げるべき」 | Board Challenge Question、Decision Object |

#### 方法論の中核

1. **判断場面を定義する**  
   例：支払継続判断、契約通知判断、引当検討判断、顧客公表判断、サプライヤー切替判断。

2. **Scenario Bankを作る**  
   実案件を匿名化・抽象化したケース、公開事例、専門家が作る仮想シナリオを蓄積する。完全なデータがあるケースだけでなく、契約、銀行、在庫、サブティア、重要性基準が欠落しているケースを意図的に含める。

3. **Question Bankを作る**  
   「何を最初に見るか」「何が不足しているか」「HighとMediumの境界は何か」「判断を下げる反証は何か」「クライアントに何を聞くべきか」といった質問を、共通質問とモード別質問に分けて管理する。

4. **個別回答を収集する**  
   専門家ごとに、初期評価、判断理由、重視した事実、無視した事実、不足情報、推奨アクション、AI出力上の注意を収集する。合議前に個別回答を取ることで、専門家間のばらつきと少数意見を残す。

5. **CTAで暗黙知を抽出する**  
   専門家にケースまたはAIの初期分析を見せ、どこで違和感を持ったか、どの順番で確認したか、何があれば判断を変えるかを聞く。特に、過大評価を避ける反証条件、過小評価を避ける赤旗、断定を避ける表現制約を重視する。

6. **Knowledge Primitiveに分解する**  
   回答とCTA記録を、Red Flag、Data Requirement、Rule、Rubric、Threshold、Exception、Evidence Standard、Review Trigger、Language Guardrail、Board Question、Counterfactualに分解する。

7. **Knowledge Objectとして実装する**  
   Rule-as-Code、Rubric-as-Code、Pattern-as-Code、Playbook-as-Code、Review-as-Code、Evidence-as-Code、Language-as-CodeとしてMode Packに組み込む。

8. **専門家レビューと運用結果で補正する**  
   過去ケース、仮想ケース、実運用ログで、過大評価、過小評価、見落とし、危険な断定、専門家修正の有効性を検証する。

#### 実装例

```text
専門家の個別回答:
高リスク国のサプライヤーで支払期日が近い場合、Treasury単独ではなくLegalとProcurementを同時に見るべき。
銀行情報が欠落している場合、支払可能性をHigh Confidenceで言ってはいけない。

CTAで抽出された暗黙知:
専門家はまず支払経路、次に最終受益者、次に契約通知義務、最後に代替サプライヤーを確認していた。
「支払停止すべき」とは断定せず、「支払継続・延期・代替経路・供給停止影響を合同判断すべき」と表現する。

Code化:
IF supplier_country_risk >= High
AND payment_due_days <= 14
AND bank_account_data = Missing
THEN
  Treasury Review Required = True
  Legal Review Required = True
  Cash Mobility Confidence <= Medium
  Payment Hold Recommendation cannot be issued alone
  Decision Queue includes CFO / Legal / Procurement joint decision
```

#### Expert-as-Codeの設計原則

- 例外が多い法務・会計・トレジャリー領域では、完全自動判断ではなく、レビュー条件、論点整理、不足情報提示を重視する
- ルールは硬くしすぎず、ルーブリック、信頼度、専門家懸念度、反証条件を併用する
- 個別回答で専門家間のばらつきを残し、ばらつきが大きい領域はAIが断定を避ける
- CTAで抽出した違和感、確認順序、表現制約を、Red Flag、Decision Tree、Language Guardrailとして実装する
- 重要なKnowledge Objectには作成者、承認者、適用範囲、失効条件、版を持たせる
- AIスコアと専門家修正の差分を保存し、どこで専門家価値が出たかを可視化する
- Knowledge Packは業界別、地域別、機能別、提供形態別に分ける

### 21.3 Decision-first Output：専門家知見で判断の優先順位を作る

一般的なリスクレポートは、リスクを順位付けする。一方、本サービスは、リスクそのものではなく、判断すべきことを順位付けする。

#### Risk RankingからDecision Queueへ

| Risk Ranking | Decision Queue |
|---|---|
| 何が危ないか | 何を決めるべきか |
| 影響度・発生可能性が中心 | 判断期限、不可逆性、部門間矛盾、専門家懸念を含む |
| 読み手が行動に変換する必要がある | 行動、担当、期限、証跡まで示す |
| AI要約と相性がよい | 専門家レビュー、役員会、危機対応と相性がよい |

#### Decision Object

```text
Decision Object =
  判断事項
+ 背景リスク
+ 影響対象アセット
+ 判断期限
+ 選択肢
+ 推奨案
+ 反対論点
+ 必要な追加情報
+ 専門家懸念
+ 実行タスク
+ 承認者
+ 証拠
+ 判断後のモニタリング条件
```

#### 専門家知見を使った優先順位付け

| 専門家知見 | Decision Queueへの反映 |
|---|---|
| Treasury専門家 | 資金移動期限、支払停止影響、銀行・通貨制約を反映する |
| Legal専門家 | 通知義務、制裁、規制報告、契約違反の期限を反映する |
| Accounting専門家 | 決算締め、監査人説明、重要性基準、開示要否を反映する |
| Procurement専門家 | 在庫ランウェイ、代替調達リードタイム、単一調達を反映する |
| Communications専門家 | 顧客・従業員・メディアへの説明タイミングを反映する |
| Executive専門家 | 取締役会判断、資本配分、撤退・継続判断を反映する |

#### 出力例

| 優先 | 判断事項 | 判断期限 | 主担当 | 専門家懸念 | 推奨 |
|---:|---|---|---|---|---|
| 1 | 高リスク地域サプライヤーへの支払を継続するか | 24時間以内 | CFO / Legal | 制裁近接、支払停止で操業影響 | 条件付き保留、法務確認後に代替支払案を検討 |
| 2 | 代替調達を緊急発注するか | 72時間以内 | CPO | 在庫ランウェイ20日、認定未了 | 代替先の認定短縮と価格上昇試算を開始 |
| 3 | 顧客への納期リスク説明を行うか | 1週間以内 | COO / 広報 | 説明遅延による信用低下 | 法務確認済みの顧客FAQを準備 |
| 4 | 会計上の引当・後発事象検討を開始するか | 決算締め前 | 経理 / CFO | 見込損失が重要性基準に接近 | 監査人説明用Evidence Packを作成 |

---

## 22. Quality and Precision Framework

差別化には、分析の深さだけでなく、品質管理が不可欠である。本サービスでは、AI出力の「精度」を単一指標で扱わず、複数の品質軸で管理する。

### 22.1 品質軸

| 品質軸 | 意味 | 主な管理方法 |
|---|---|---|
| Factual Accuracy | 事実が正しいか | 一次情報優先、複数ソース確認、取得日時管理 |
| Source Quality | ソースが信頼できるか | Source Reliability Score、専門家確認 |
| Client Relevance | クライアントアセットに本当に関係するか | Client Asset Graph、Relevance Score |
| Context Sufficiency | 判断に必要な文脈が足りているか | Context Sufficiency Score、Unknown Register |
| Scenario Plausibility | シナリオが現実的か | 過去事例、専門家レビュー、反証探索 |
| Impact Estimation Quality | 影響額・影響範囲が妥当か | 内部データ、感応度分析、専門家補正 |
| Actionability | 実行可能な助言か | RACI、期限、承認、プレイブック |
| Expert Alignment | 専門家判断と整合しているか | Expert Review Queue、Override Log |
| Timeliness | 危機対応に間に合うか | Decision Urgency、アラートSLA |
| Traceability | 根拠を追えるか | Evidence Ledger、Scenario Delta Ledger、Decision Log |
| Calibration | 過大・過小評価が補正されているか | Backtesting、月次キャリブレーション |

### 22.2 Risk Intelligence Quality Layer

```text
Risk Intelligence Quality Layer =
  Source Reliability
+ Client Relevance
+ Context Sufficiency
+ Evidence Strength
+ Counter-evidence
+ Expert Validation
+ Model Confidence
+ Human Override
+ Backtesting Result
```

この品質レイヤーは、すべてのシナリオ、スコア、判断、プレイブックに付与される。これにより、AIが「もっともらしい」回答を出すだけでなく、どの程度使える分析なのかを利用者が判断できる。

### 22.3 Backtesting and Calibration

運用後は、以下を定期的に検証する。

- AIが検知したリスクは実際に顕在化したか
- 顕在化しなかったリスクは過大評価だったか、予防策が効いたのか
- 見落としたリスクはどのデータ・ソース・専門家ルールが不足していたのか
- 専門家修正はスコアや判断の質を改善したか
- クライアントの対応は推奨案と比べて妥当だったか
- どのMode Pack、Knowledge Pack、スコア重みを更新すべきか

---

## 23. Benchmark and Maturity Model

先行レポートの強みであるベンチマーク性を、本サービスでは匿名化・集約化された形で提供する。

### 23.1 ベンチマーク対象

| 対象 | 内容 |
|---|---|
| 業界別 | 製造、金融、商社、小売、製薬、インフラなど |
| 地域別 | 日本、APAC、EMEA、北米、グローバルなど |
| 機能別 | Treasury、Legal、Accounting、Procurement、Cyber、Reputation |
| リスク別 | 制裁、サイバー、災害、調達停止、開示、資金移動など |
| 成熟度別 | Traditionalist、Responder、Integrator、Strategist、Leader |

### 23.2 Risk Intelligence Maturity

| レベル | 名称 | 特徴 |
|---|---|---|
| 1 | Risk Traditionalist | 部門別・事後対応中心。外部リスクと内部データが分断されている |
| 2 | Risk Responder | 危機発生後の対応はできるが、予兆検知と横断分析が弱い |
| 3 | Risk Integrator | 複数部門のデータと対応を一定程度統合できる |
| 4 | Risk Strategist | リスクを資金、契約、会計、投資、戦略に接続できる |
| 5 | Risk Intelligence Leader | AI、専門家知見、内部データ、外部情報を継続運用できる |

ベンチマークは、クライアントに「自社のリスクは高いか」だけでなく、「自社の備えは同業・同地域と比べてどこが弱いか」を示すために使う。

---

## 24. Product Capabilities to Support Differentiation

追加すべき中核機能は以下である。

| 機能 | 目的 |
|---|---|
| Client Context Builder | 限定的・非構造化データからClient Asset Graphを構築する |
| Hypothesis Workspace | AIが生成した仮説、Unknown、追加確認事項を管理する |
| Expert Knowledge Studio | 専門家知見をKnowledge Objectとして登録・更新する |
| Mode Pack Manager | Treasury、Legal、Accountingなどのモード別ルールと出力を管理する |
| Evidence Ledger | 根拠、反証、信頼度、専門家確認を追跡する |
| Scenario Delta Ledger | 前回からの変化、スコア差分、専門家修正を追跡する |
| Decision Queue | リスクを判断事項、期限、担当、選択肢へ変換する |
| Expert Review Queue | 専門家が確認すべき案件を優先順位化する |
| Benchmark Engine | 業界・地域・機能別の成熟度比較を提供する |
| Backtesting & Calibration | 過去予測、実際の結果、専門家修正をもとに改善する |
| Safe Search Proxy | 機密情報を外部検索に出さず、抽象化された検索を実行する |

---

## 25. 参考ソース

本設計の追加検討では、以下の公開情報・サービス紹介を参考にした。

- World Economic Forum, Global Risks Report 2026: https://www.weforum.org/publications/global-risks-report-2026/
- Marsh, Global Risks Report 2026 overview: https://www.marsh.com/en/risks/global-risk.html
- Aon, Global Risk Management Survey: https://www.aon.com/en/insights/reports/global-risk-management-survey
- PwC, Global Crisis and Resilience Survey 2023: https://www.pwc.com/gx/en/issues/crisis-solutions/global-crisis-survey.html
- KPMG, 2025 Risk and Resilience Survey: https://kpmg.com/us/en/articles/2025/kpmg-risk-resilience-survey.html
- EY, Global Risk Transformation Study: https://www.ey.com/en_gl/insights/consulting/how-can-reimagining-risk-prepare-you-for-an-unpredictable-world
- McKinsey, Operational resilience has become critical: https://www.mckinsey.com/capabilities/risk-and-resilience/our-insights/operational-resilience-has-become-critical-how-are-banks-responding
- Deloitte, Advanced Risk Sensing: https://www.deloitte.com/nl/en/services/audit-assurance/services/advanced-risk-sensing.html
- Deloitte, Risk Intelligence Illuminator: https://www.deloitte.com/southeast-asia/en/services/consulting/services/risk-intelligence-illuminator.html
- Seerist, Decision-Ready Intelligence: https://seerist.com/
- Control Risks, Seerist: https://www.controlrisks.com/seerist
- Everstream Analytics: https://www.everstream.ai/
- Gartner, Emerging Risks in Audit & Risk Management: https://www.gartner.com/en/audit-risk/trends/emerging-risks


---

## 変更履歴

- v3: Expert-as-Codeの知見抽出手法を、個別回答方式とCognitive Task Analysis方式の組み合わせとして具体化。Scenario Bank、Question Bank、Individual Response Collector、CTA Interview Workbench、Knowledge Primitive化、Knowledge Object化、Expert Knowledge Studio機能を更新。
