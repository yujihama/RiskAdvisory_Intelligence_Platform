from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCENARIO_PREFIX = "experiment_major_escalation_of_war_involving_ir_agg_"
DEFAULT_DISCOVERY_JSON = Path("outputs/risk_discovery_experiments/iran_war_parallel_response_format_e2e_v3.json")
DEFAULT_PORTFOLIO_JSON = Path(
    "outputs/risk_discovery/experiment_major_escalation_of_war_involving_ir_agg_001_portfolio_summary.json"
)
DEFAULT_PORTFOLIO_MD = Path(
    "outputs/risk_discovery/experiment_major_escalation_of_war_involving_ir_agg_001_portfolio_summary.md"
)
DEFAULT_PORTFOLIO_JA_MD = Path(
    "outputs/risk_discovery/experiment_major_escalation_of_war_involving_ir_agg_001_portfolio_summary_ja.md"
)
DEFAULT_OUTPUT_HTML = Path("outputs/risk_discovery/iran_war_dashboard_embedded.html")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--discovery-json", type=Path, default=DEFAULT_DISCOVERY_JSON)
    parser.add_argument("--portfolio-json", type=Path, default=DEFAULT_PORTFOLIO_JSON)
    parser.add_argument("--portfolio-md", type=Path, default=DEFAULT_PORTFOLIO_MD)
    parser.add_argument("--portfolio-ja-md", type=Path, default=DEFAULT_PORTFOLIO_JA_MD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--scenario-count", type=int, default=6)
    args = parser.parse_args()

    root = args.project_root.resolve()
    payload = build_payload(root, args)
    output_path = resolve_path(root, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(payload), encoding="utf-8")
    print(f"dashboard={output_path}")
    print(f"embedded_scenarios={len(payload['scenarios'])}")
    print(f"embedded_total_bytes={payload['metadata']['embedded_total_bytes']}")
    return 0


def build_payload(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    discovery_json_path = resolve_path(root, args.discovery_json)
    portfolio_json_path = resolve_path(root, args.portfolio_json)
    portfolio_md_path = resolve_path(root, args.portfolio_md)
    portfolio_ja_md_path = resolve_path(root, args.portfolio_ja_md)

    scenarios = []
    for idx in range(1, args.scenario_count + 1):
        scenario_id = f"{SCENARIO_PREFIX}{idx:03d}"
        scenario_dir = root / "outputs" / scenario_id
        scenarios.append(load_scenario(root, scenario_id, scenario_dir))

    payload: dict[str, Any] = {
        "metadata": {
            "dashboard_generated_at": datetime.now(timezone.utc).isoformat(),
            "project_root": str(root),
            "note": (
                "This dashboard embeds full source JSON and Markdown artifacts loaded at build time. "
                "Executive views derive from embedded data; raw tabs preserve the full payload."
            ),
        },
        "sources": {
            "discovery_json": load_json_file(root, discovery_json_path),
            "portfolio_summary_json": load_json_file(root, portfolio_json_path),
            "portfolio_summary_md": load_text_file(root, portfolio_md_path),
            "portfolio_summary_ja_md": load_text_file(root, portfolio_ja_md_path),
        },
        "scenarios": scenarios,
    }
    payload["metadata"]["embedded_total_bytes"] = estimate_embedded_bytes(payload)
    payload["metadata"]["source_file_count"] = count_source_files(payload)
    return payload


def load_scenario(root: Path, scenario_id: str, scenario_dir: Path) -> dict[str, Any]:
    files = {
        "final_brief_md": load_text_file(root, scenario_dir / "final_brief.md"),
        "final_brief_ja_md": load_text_file(root, scenario_dir / "final_brief_ja.md"),
        "red_team_review_md": load_text_file(root, scenario_dir / "red_team_review.md"),
        "decision_queue_json": load_json_file(root, scenario_dir / "decision_queue.json"),
        "evidence_summary_json": load_json_file(root, scenario_dir / "evidence_summary.json"),
        "assumptions_and_unknowns_json": load_json_file(root, scenario_dir / "assumptions_and_unknowns.json"),
        "trace_metadata_json": load_json_file(root, scenario_dir / "trace_metadata.json"),
    }
    trace = files["trace_metadata_json"].get("data") if files["trace_metadata_json"].get("exists") else {}
    return {
        "scenario_id": scenario_id,
        "directory": relative_to_root(root, scenario_dir),
        "trace_id": trace.get("trace_id") if isinstance(trace, dict) else None,
        "files": files,
    }


def load_json_file(root: Path, path: Path) -> dict[str, Any]:
    record = file_record(root, path)
    if not path.exists():
        record["data"] = None
        return record
    text = path.read_text(encoding="utf-8")
    record["raw_text"] = text
    record["data"] = json.loads(text)
    return record


def load_text_file(root: Path, path: Path) -> dict[str, Any]:
    record = file_record(root, path)
    record["text"] = path.read_text(encoding="utf-8") if path.exists() else None
    return record


def file_record(root: Path, path: Path) -> dict[str, Any]:
    exists = path.exists()
    stat = path.stat() if exists else None
    return {
        "path": relative_to_root(root, path),
        "absolute_path": str(path),
        "exists": exists,
        "size_bytes": stat.st_size if stat else 0,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat() if stat else None,
    }


def resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path.resolve())


def estimate_embedded_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def count_source_files(value: Any) -> int:
    if isinstance(value, dict):
        if "exists" in value and "path" in value:
            return 1 if value.get("exists") else 0
        return sum(count_source_files(item) for item in value.values())
    if isinstance(value, list):
        return sum(count_source_files(item) for item in value)
    return 0


def render_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    title = "イラン戦争リスク分析 | 意思決定ダッシュボード"
    template = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fb;
      --surface: #ffffff;
      --surface-2: #f1f5f9;
      --ink: #111827;
      --muted: #64748b;
      --line: #d7dee8;
      --accent: #0f766e;
      --accent-2: #175cd3;
      --urgent: #b42318;
      --amber: #b54708;
      --ok: #16794c;
      --code: #101828;
      --code-ink: #f8fafc;
      --shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    html { max-width: 100%; overflow-x: hidden; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", "Yu Gothic UI", Meiryo, sans-serif;
      max-width: 100%;
      overflow-x: hidden;
    }
    header {
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      padding: 22px 28px 18px;
      position: sticky;
      top: 0;
      z-index: 20;
    }
    h1 {
      font-size: 24px;
      line-height: 1.25;
      margin: 0 0 8px;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }
    h2 {
      font-size: 18px;
      line-height: 1.35;
      margin: 0 0 12px;
      letter-spacing: 0;
    }
    h3 {
      font-size: 15px;
      line-height: 1.35;
      margin: 0 0 8px;
      letter-spacing: 0;
    }
    .topline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    .subtitle {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      max-width: 960px;
      overflow-wrap: anywhere;
    }
    .meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: #334155;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.2;
      white-space: nowrap;
      min-width: 0;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .pill.urgent { color: var(--urgent); background: #fff1f0; border-color: #ffc9c4; }
    .pill.warn { color: var(--amber); background: #fff7e6; border-color: #ffd89a; }
    .pill.ok { color: var(--ok); background: #ecfdf3; border-color: #abe5c1; }
    .controls {
      display: grid;
      grid-template-columns: minmax(260px, 1.4fr) minmax(180px, 0.7fr) minmax(220px, 1fr);
      gap: 10px;
      margin-top: 14px;
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      margin: 0 0 5px;
    }
    select, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font-size: 14px;
      padding: 9px 10px;
    }
    main {
      width: min(1500px, calc(100vw - 36px));
      margin: 0 auto;
      padding: 18px 0 34px;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 18px;
    }
    .tab {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--ink);
      border-radius: 6px;
      padding: 9px 12px;
      font-size: 14px;
      cursor: pointer;
    }
    .tab.active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
      font-weight: 700;
    }
    .section {
      margin-bottom: 24px;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 16px;
      margin-bottom: 10px;
    }
    .section-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      max-width: 780px;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 10px;
    }
    .metric-card, .decision-card, .signal-card, .evidence-card, .source-card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .metric-card {
      padding: 14px;
      min-height: 104px;
    }
    .metric-value {
      font-size: 28px;
      line-height: 1.05;
      font-weight: 800;
      color: #0f172a;
    }
    .metric-label {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .metric-card.alert .metric-value { color: var(--urgent); }
    .metric-card.warn .metric-value { color: var(--amber); }
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
      gap: 14px;
      align-items: stretch;
    }
    .lead-panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: var(--shadow);
    }
    .lead-title {
      font-size: 20px;
      font-weight: 800;
      line-height: 1.35;
      margin-bottom: 8px;
      overflow-wrap: anywhere;
    }
    .lead-text {
      font-size: 14px;
      line-height: 1.75;
      color: #253244;
      margin: 0 0 10px;
      overflow-wrap: anywhere;
    }
    .decision-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .decision-card {
      display: grid;
      gap: 10px;
      padding: 14px;
      min-height: 250px;
    }
    .decision-card.selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.16), var(--shadow);
    }
    .decision-card h3 {
      font-size: 15px;
      line-height: 1.45;
    }
    .card-text {
      color: #334155;
      font-size: 13px;
      line-height: 1.65;
      margin: 0;
      overflow-wrap: anywhere;
    }
    .card-footer {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
      align-self: end;
    }
    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .signal-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .signal-card {
      padding: 14px;
    }
    .signal-card strong {
      display: block;
      margin-bottom: 6px;
      font-size: 13px;
    }
    .signal-card p, .signal-card li {
      color: #334155;
      font-size: 13px;
      line-height: 1.65;
    }
    ul.clean {
      margin: 8px 0 0;
      padding-left: 18px;
    }
    .timeline {
      display: grid;
      gap: 8px;
    }
    .timeline-row {
      display: grid;
      grid-template-columns: 110px 1fr 80px;
      gap: 10px;
      align-items: center;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
    }
    .bar-track {
      height: 12px;
      background: #e2e8f0;
      border-radius: 999px;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--urgent), var(--amber), var(--accent));
      border-radius: 999px;
      min-width: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: var(--shadow);
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    th {
      background: #eef2f7;
      color: #334155;
      font-size: 12px;
      font-weight: 800;
    }
    tr:last-child td { border-bottom: none; }
    .clickable { cursor: pointer; }
    .clickable:hover { background: #f8fafc; }
    details {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      margin: 8px 0;
      overflow: hidden;
    }
    summary {
      cursor: pointer;
      padding: 10px 12px;
      font-weight: 800;
      font-size: 13px;
      background: #f8fafc;
    }
    pre {
      margin: 0;
      padding: 12px;
      max-height: 620px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: var(--code);
      color: var(--code-ink);
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      line-height: 1.5;
    }
    .markdown {
      background: #fff;
      color: var(--ink);
      border-top: 1px solid var(--line);
    }
    .empty {
      color: var(--muted);
      font-size: 13px;
      padding: 12px;
      background: #f8fafc;
      border: 1px dashed var(--line);
      border-radius: 8px;
    }
    .source-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .source-card {
      padding: 12px;
    }
    .source-card a {
      color: var(--accent-2);
      text-decoration: none;
      font-weight: 700;
    }
    .source-card a:hover { text-decoration: underline; }
    .muted { color: var(--muted); }
    .compact { font-size: 12px; line-height: 1.45; }
    @media (max-width: 1100px) {
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .hero-grid, .split, .decision-grid, .signal-grid, .source-grid { grid-template-columns: 1fr; }
      .controls { grid-template-columns: 1fr; }
      .pill { white-space: normal; }
      header { position: static; }
      main { width: calc(100vw - 24px); }
    }
    @media (max-width: 600px) {
      header { padding: 20px 12px 16px; }
      .topline { display: block; }
      .meta { align-items: flex-start; }
      .metric-grid { grid-template-columns: 1fr; }
      .tabs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .tab { width: 100%; }
      th, td { font-size: 12px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topline">
      <div>
        <h1>__TITLE__</h1>
        <div class="subtitle">対象リスクイベント: イランを巻き込む戦争の大規模な激化。Discoveryで抽出した6つの統合シナリオを、後続分析の意思決定・根拠・未確認事項まで追える形で表示します。</div>
      </div>
      <div class="meta" id="top-meta"></div>
    </div>
    <div class="controls">
      <div>
        <label for="scenario-select">フォーカスシナリオ</label>
        <select id="scenario-select"></select>
      </div>
      <div>
        <label for="risk-filter">リスク領域</label>
        <select id="risk-filter"></select>
      </div>
      <div>
        <label for="search-box">検索</label>
        <input id="search-box" type="search" placeholder="例: 支払、制裁、契約、調達、CISO">
      </div>
    </div>
  </header>
  <main>
    <nav class="tabs" id="tabs"></nav>
    <div id="content"></div>
  </main>
  <script id="risk-dashboard-data" type="application/json">__DATA_JSON__</script>
  <script>
    const DATA = JSON.parse(document.getElementById('risk-dashboard-data').textContent);
    const state = { tab: 'overview', scenarioIndex: 0, riskType: 'all', query: '' };
    const tabs = [
      ['overview', 'Executive View'],
      ['matrix', '優先順位と責任者'],
      ['scenario', 'シナリオ詳細'],
      ['evidence', '根拠と未確認事項'],
      ['lineage', 'Discoveryの由来'],
      ['raw', '監査用Raw']
    ];
    const agentLabels = {
      'client-context-agent': '自社データ',
      'source-intelligence-agent': '外部情報',
      'treasury-risk-agent': '財務・支払',
      'legal-risk-agent': '法務・制裁',
      'accounting-risk-agent': '会計・開示',
      'procurement-risk-agent': '調達',
      'expert-as-code-agent': '専門知',
      'evidence-redteam-agent': '検証',
      'orchestrator-agent': '統括'
    };
    const riskLabels = {
      supplier_resilience: 'サプライチェーン',
      payment_disruption: '財務・支払',
      legal_compliance: '法務・制裁',
      executive_resilience: '経営危機対応'
    };

    const portfolio = DATA.sources.portfolio_summary_json.data || {};
    const discovery = DATA.sources.discovery_json.data || {};
    const eventsById = Object.fromEntries((portfolio.selected_events || []).map(item => [item.scenario_id, item]));
    const candidatesById = Object.fromEntries((portfolio.selected_candidates || []).map(item => [item.candidate_id, item]));
    const aggregatedByIndex = discovery.aggregated_scenarios || [];

    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    }
    function jsonBlock(value) {
      return '<pre>' + esc(JSON.stringify(value, null, 2)) + '</pre>';
    }
    function textBlock(value, klass = '') {
      return '<pre class="' + klass + '">' + esc(value || '') + '</pre>';
    }
    function firstDecision(s) {
      return s.files.decision_queue_json.data?.decisions?.[0] || {};
    }
    function evidenceItems(s) {
      return s.files.evidence_summary_json.data?.evidence || [];
    }
    function findingItems(s) {
      return s.files.assumptions_and_unknowns_json.data?.findings || [];
    }
    function priorityEvidenceItems(decision) {
      const value = decision.priority_evidence;
      if (!value) return [];
      if (Array.isArray(value)) return value;
      if (typeof value === 'object') return Object.entries(value).map(([key, item]) => ({ key, value: item }));
      return [value];
    }
    function finalBriefJa(s) {
      return s.files.final_brief_ja_md.text || '';
    }
    function parseLocalizedDecision(text) {
      const lines = String(text || '').split(/\r?\n/);
      const start = lines.findIndex(line => /^##\s*(意思決定キュー|決定キュー|Decision Queue)/i.test(line.trim()));
      if (start < 0) return {};
      const result = {};
      for (let i = start + 1; i < lines.length; i++) {
        const line = lines[i];
        if (/^##\s+/.test(line.trim())) break;
        const decisionMatch = line.match(/^\s*1\.\s*(.+)$/);
        if (decisionMatch && !result.decision) result.decision = decisionMatch[1].trim();
        const ownerMatch = line.match(/^\s*-\s*(担当者|Owner|担当)\s*[:：]\s*(.+)$/i);
        if (ownerMatch && !result.owner) result.owner = ownerMatch[2].trim();
        const deadlineMatch = line.match(/^\s*-\s*(期限|締切|Deadline)\s*[:：]\s*(.+)$/i);
        if (deadlineMatch && !result.deadline) result.deadline = deadlineMatch[2].trim();
      }
      return result;
    }
    function parseBriefSection(text, headingPatterns) {
      const lines = String(text || '').split(/\r?\n/);
      const start = lines.findIndex(line => headingPatterns.some(pattern => pattern.test(line.trim())));
      if (start < 0) return '';
      const collected = [];
      for (let i = start + 1; i < lines.length; i++) {
        if (/^##\s+/.test(lines[i].trim())) break;
        collected.push(lines[i]);
      }
      return collected.join('\n').trim();
    }
    function localizedPriorityEvidenceBlocks(s) {
      const section = parseBriefSection(finalBriefJa(s.raw), [/^##\s*優先証拠/, /^##\s*Priority Evidence/i]);
      if (!section) return [];
      return section.split(/\n(?=- \*\*)/).map(chunk => chunk.trim()).filter(Boolean);
    }
    function truncate(value, max = 220) {
      const text = String(value || '').replace(/\\s+/g, ' ').trim();
      return text.length > max ? text.slice(0, max - 1) + '…' : text;
    }
    function formatDate(value) {
      if (!value) return '未設定';
      return String(value).replace(/T.*/, '');
    }
    function daysUntil(value) {
      if (!value) return null;
      const generated = new Date(DATA.metadata.dashboard_generated_at);
      const base = new Date(Date.UTC(generated.getUTCFullYear(), generated.getUTCMonth(), generated.getUTCDate()));
      const target = new Date(value + 'T00:00:00Z');
      return Math.ceil((target - base) / 86400000);
    }
    function deadlinePill(value) {
      const days = daysUntil(value);
      if (days === null) return '<span class="pill warn">期限未設定</span>';
      if (days < 0) return '<span class="pill urgent">期限超過 ' + Math.abs(days) + '日</span>';
      if (days <= 14) return '<span class="pill warn">残り ' + days + '日</span>';
      return '<span class="pill ok">残り ' + days + '日</span>';
    }
    function priorityPill(priority) {
      const cls = Number(priority) <= 2 ? 'urgent' : Number(priority) <= 3 ? 'warn' : 'ok';
      return '<span class="pill ' + cls + '">優先度 ' + esc(priority ?? '未設定') + '</span>';
    }
    function riskLabel(type) {
      return riskLabels[type] || type || '未分類';
    }
    function scenarioNumber(index) {
      return 'S' + String(index + 1).padStart(2, '0');
    }
    function scenarioViewModel(s, index) {
      const event = eventsById[s.scenario_id] || {};
      const candidate = candidatesById[s.scenario_id] || {};
      const aggregated = aggregatedByIndex[index] || {};
      const decision = firstDecision(s);
      const localized = parseLocalizedDecision(finalBriefJa(s));
      const findings = findingItems(s);
      const evidence = evidenceItems(s);
      const priorityEvidence = priorityEvidenceItems(decision);
      const riskType = event.risk_type || candidate.risk_type || aggregated.risk_type || '';
      return {
        raw: s,
        index,
        number: scenarioNumber(index),
        id: s.scenario_id,
        title: event.title || candidate.title || aggregated.title || s.scenario_id,
        riskType,
        riskLabel: riskLabel(riskType),
        urgency: event.urgency || candidate.urgency || aggregated.urgency || '',
        countries: event.countries || candidate.countries || aggregated.countries || [],
        themes: event.risk_themes || candidate.risk_themes || aggregated.risk_themes || [],
        categories: event.affected_categories || candidate.affected_categories || aggregated.affected_categories || [],
        description: event.description || candidate.description || aggregated.scenario_story || '',
        recommendedActions: splitActions(event.description || candidate.description || aggregated.recommended_actions || ''),
        decision,
        decisionText: localized.decision || decision.decision || '',
        owner: localized.owner || decision.owner || '未設定',
        deadline: decision.deadline || localized.deadline || '',
        deadlineRationale: decision.deadline_rationale || '',
        rationale: decision.rationale || '',
        riskIfDelayed: decision.risk_if_delayed || '',
        reviewRequired: Boolean(decision.review_required),
        priority: decision.priority,
        options: decision.options || [],
        evidence,
        findings,
        priorityEvidence,
        traceId: s.trace_id,
        event,
        candidate,
        aggregated
      };
    }
    function splitActions(text) {
      const marker = 'Recommended actions:';
      if (!text || !text.includes(marker)) return [];
      return text.split(marker).pop().split(/[;；]/).map(x => x.trim()).filter(Boolean);
    }
    function allScenarios() {
      return DATA.scenarios.map((s, i) => scenarioViewModel(s, i));
    }
    function visibleScenarios() {
      const q = state.query.trim().toLowerCase();
      return allScenarios().filter(s => {
        const riskOk = state.riskType === 'all' || s.riskType === state.riskType;
        if (!riskOk) return false;
        if (!q) return true;
        return JSON.stringify({
          title: s.title,
          riskType: s.riskType,
          owner: s.owner,
          decision: s.decisionText,
          findings: s.findings,
          evidence: s.evidence,
          priorityEvidence: s.priorityEvidence
        }).toLowerCase().includes(q);
      });
    }
    function selectedScenario() {
      return scenarioViewModel(DATA.scenarios[state.scenarioIndex], state.scenarioIndex);
    }
    function sortByDecisionUrgency(rows) {
      return [...rows].sort((a, b) => {
        const pa = Number(a.priority ?? 99);
        const pb = Number(b.priority ?? 99);
        if (pa !== pb) return pa - pb;
        return String(a.deadline || '9999').localeCompare(String(b.deadline || '9999'));
      });
    }
    function groupedByAgent(items) {
      const groups = {};
      for (const item of items) {
        const key = item.source_agent || item.agent_name || 'unknown';
        groups[key] = groups[key] || [];
        groups[key].push(item);
      }
      return groups;
    }
    function riskSignalFlags(s) {
      const text = JSON.stringify([s.findings, s.priorityEvidence, s.decisionText], null, 0).toLowerCase();
      return [
        ['支払', /payment|支払|送金|treasury/.test(text)],
        ['契約', /contract|契約|force majeure|制裁条項/.test(text)],
        ['調達', /supplier|procurement|サプライヤー|調達/.test(text)],
        ['制裁', /sanction|制裁|ofac|export control/.test(text)],
        ['会計', /accounting|invoice|provision|開示|会計/.test(text)],
        ['危機対応', /executive|crisis|ciso|incident|危機|情報セキュリティ/.test(text)]
      ].filter(([, ok]) => ok).map(([label]) => label);
    }
    function localizedDelayImpact(s) {
      const flags = new Set(riskSignalFlags(s));
      const phrases = [];
      if (flags.has('支払')) phrases.push('支払停止や送金遅延により、重要サプライヤー・財務オペレーションへの影響が拡大する');
      if (flags.has('契約')) phrases.push('不可抗力・制裁条項・通知義務の確認が遅れ、契約違反や顧客コミットメント不履行の余地が広がる');
      if (flags.has('調達')) phrases.push('代替調達や在庫ランウェイの検証が遅れ、供給停止時の選択肢が減る');
      if (flags.has('制裁')) phrases.push('制裁・輸出管理・受益者確認の遅れにより、違反・二次制裁・取引停止リスクが高まる');
      if (flags.has('会計')) phrases.push('引当金、偶発債務、後発事象、開示判断の遅れが監査・経営報告に波及する');
      if (flags.has('危機対応')) phrases.push('危機委員会、インシデント対応、経営判断の立ち上げが遅れ、部門横断の統制が弱まる');
      return phrases.join('。') || '遅延時影響は構造化Decision JSONに保持されています。';
    }
    function sourceQuality(evidence) {
      const reliable = evidence.filter(e => ['high', 'medium'].includes(String(e.reliability || '').toLowerCase())).length;
      return reliable + '/' + evidence.length;
    }
    function render() {
      renderChrome();
      const content = document.getElementById('content');
      if (state.tab === 'overview') content.innerHTML = renderOverview();
      if (state.tab === 'matrix') content.innerHTML = renderMatrix();
      if (state.tab === 'scenario') content.innerHTML = renderScenario();
      if (state.tab === 'evidence') content.innerHTML = renderEvidence();
      if (state.tab === 'lineage') content.innerHTML = renderLineage();
      if (state.tab === 'raw') content.innerHTML = renderRaw();
    }
    function renderChrome() {
      const scenarios = allScenarios();
      const overview = portfolio.portfolio_overview || {};
      document.getElementById('top-meta').innerHTML = [
        '<span class="pill">生成 ' + esc(formatDate(DATA.metadata.dashboard_generated_at)) + '</span>',
        '<span class="pill">シナリオ ' + scenarios.length + '</span>',
        '<span class="pill">証拠 ' + esc(overview.total_evidence ?? scenarios.reduce((n, s) => n + s.evidence.length, 0)) + '</span>',
        '<span class="pill">全量埋込 ' + Number(DATA.metadata.embedded_total_bytes || 0).toLocaleString('ja-JP') + ' bytes</span>'
      ].join('');
      document.getElementById('tabs').innerHTML = tabs.map(([id, label]) =>
        '<button class="tab ' + (state.tab === id ? 'active' : '') + '" onclick="state.tab=\'' + id + '\'; render()">' + esc(label) + '</button>'
      ).join('');
      const select = document.getElementById('scenario-select');
      select.innerHTML = scenarios.map(s =>
        '<option value="' + s.index + '">' + esc(s.number + ' ' + s.title) + '</option>'
      ).join('');
      select.value = String(state.scenarioIndex);
      const risks = [...new Set(scenarios.map(s => s.riskType).filter(Boolean))];
      document.getElementById('risk-filter').innerHTML =
        '<option value="all">全領域</option>' + risks.map(r => '<option value="' + esc(r) + '">' + esc(riskLabel(r)) + '</option>').join('');
      document.getElementById('risk-filter').value = state.riskType;
    }
    function renderOverview() {
      const scenarios = allScenarios();
      const visible = visibleScenarios();
      const sorted = sortByDecisionUrgency(visible);
      const overdue = scenarios.filter(s => (daysUntil(s.deadline) ?? 999) < 0).length;
      const soon = scenarios.filter(s => {
        const d = daysUntil(s.deadline);
        return d !== null && d >= 0 && d <= 14;
      }).length;
      const allReview = scenarios.filter(s => s.reviewRequired).length;
      const earliest = sortByDecisionUrgency(scenarios)[0];
      return [
        '<section class="section"><div class="metric-grid">',
        metricCard(scenarios.length, '統合シナリオ', 'Discovery後に後続分析へ流した対象数'),
        metricCard(allReview + '/' + scenarios.length, 'レビュー要', 'Decision Synthesisで人手確認が必要とされた件数', 'warn'),
        metricCard(overdue, '期限超過', '生成日時基準で既に期限を過ぎた意思決定', overdue ? 'alert' : ''),
        metricCard(soon, '14日以内', '直近で対応期限が来る意思決定', soon ? 'warn' : ''),
        metricCard(scenarios.reduce((n, s) => n + s.priorityEvidence.length, 0), '優先度根拠', '各agentから引き継がれた根拠項目数'),
        '</div></section>',
        '<section class="section hero-grid">',
        '<div class="lead-panel">',
        '<h2>最初に確認すべき判断</h2>',
        '<div class="lead-title">' + esc(earliest.number + ' ' + earliest.title) + '</div>',
        '<p class="lead-text">' + esc(earliest.decisionText) + '</p>',
        '<div class="card-footer">' + priorityPill(earliest.priority) + deadlinePill(earliest.deadline) +
          '<span class="pill">' + esc(earliest.owner) + '</span><span class="pill">' + esc(earliest.riskLabel) + '</span></div>',
        '</div>',
        '<div class="lead-panel">',
        '<h2>ポートフォリオの読み取り</h2>',
        '<p class="lead-text">6件すべてが優先度2かつレビュー要です。最短期限は' + esc(formatDate(earliest.deadline)) +
          'で、経営危機対応、支払、契約、調達、会計開示が横断的に絡むため、単一部門ではなく責任者を明確化したクロスファンクショナルな意思決定が必要です。</p>',
        '<div class="card-footer">' + [...new Set(scenarios.flatMap(s => riskSignalFlags(s)))].map(x => '<span class="pill">' + esc(x) + '</span>').join('') + '</div>',
        '</div>',
        '</section>',
        '<section class="section"><div class="section-head"><h2>シナリオ別アクション</h2><div class="section-note">' + visible.length + '件表示</div></div>',
        '<div class="decision-grid">' + sorted.map(renderDecisionCard).join('') + '</div></section>',
        '<section class="section"><div class="section-head"><h2>期限レーン</h2><div class="section-note">優先度と期限を同時に確認</div></div>' + renderTimeline(sorted) + '</section>'
      ].join('');
    }
    function metricCard(value, label, note, cls = '') {
      return '<div class="metric-card ' + cls + '"><div class="metric-value">' + esc(value) + '</div><div class="metric-label"><strong>' + esc(label) + '</strong><br>' + esc(note) + '</div></div>';
    }
    function renderDecisionCard(s) {
      const selected = s.index === state.scenarioIndex ? ' selected' : '';
      const signals = riskSignalFlags(s).map(x => '<span class="pill">' + esc(x) + '</span>').join('');
      return '<article class="decision-card' + selected + '">' +
        '<div><div class="card-footer">' + priorityPill(s.priority) + deadlinePill(s.deadline) + '<span class="pill">' + esc(s.riskLabel) + '</span></div>' +
        '<h3>' + esc(s.number + ' ' + s.title) + '</h3>' +
        '<p class="card-text">' + esc(truncate(s.decisionText, 340)) + '</p></div>' +
        '<div><p class="card-text"><strong>担当:</strong> ' + esc(s.owner) + '</p><p class="card-text"><strong>確認論点:</strong> ' + esc(truncate(localizedPriorityEvidenceBlocks(s)[0] || s.rationale || s.deadlineRationale, 220)) + '</p></div>' +
        '<div class="card-footer">' + signals + '<button class="tab" onclick="state.scenarioIndex=' + s.index + '; state.tab=\'scenario\'; render()">詳細</button></div>' +
        '</article>';
    }
    function renderTimeline(rows) {
      const maxDays = Math.max(...rows.map(s => Math.max(0, daysUntil(s.deadline) ?? 0)), 14);
      return '<div class="timeline">' + rows.map(s => {
        const d = daysUntil(s.deadline);
        const width = d === null ? 15 : Math.max(8, Math.min(100, ((Math.max(0, d) + 1) / (maxDays + 1)) * 100));
        return '<div class="timeline-row clickable" onclick="state.scenarioIndex=' + s.index + '; state.tab=\'scenario\'; render()">' +
          '<strong>' + esc(formatDate(s.deadline)) + '</strong><div><div class="bar-track"><div class="bar-fill" style="width:' + width + '%"></div></div>' +
          '<div class="compact">' + esc(s.number + ' ' + s.title) + '</div></div><div>' + priorityPill(s.priority) + '</div></div>';
      }).join('') + '</div>';
    }
    function renderMatrix() {
      const rows = sortByDecisionUrgency(visibleScenarios());
      const ownerCounts = {};
      rows.forEach(s => ownerCounts[s.owner] = (ownerCounts[s.owner] || 0) + 1);
      return [
        '<section class="section"><div class="section-head"><h2>優先順位テーブル</h2><div class="section-note">行を選択すると詳細へ移動</div></div>',
        '<table><thead><tr><th style="width:76px">ID</th><th>シナリオ</th><th style="width:120px">領域</th><th style="width:90px">優先度</th><th style="width:120px">期限</th><th>責任者</th><th>主な論点</th></tr></thead><tbody>',
        rows.map(s => '<tr class="clickable" onclick="state.scenarioIndex=' + s.index + '; state.tab=\'scenario\'; render()"><td><strong>' + esc(s.number) + '</strong></td><td>' + esc(s.title) + '</td><td>' + esc(s.riskLabel) + '</td><td>' + priorityPill(s.priority) + '</td><td>' + deadlinePill(s.deadline) + '</td><td>' + esc(s.owner) + '</td><td>' + riskSignalFlags(s).map(x => '<span class="pill">' + esc(x) + '</span>').join('') + '</td></tr>').join(''),
        '</tbody></table></section>',
        '<section class="section"><div class="section-head"><h2>責任者別の集中</h2><div class="section-note">意思決定の実行負荷</div></div><div class="signal-grid">',
        Object.entries(ownerCounts).map(([owner, count]) => '<div class="signal-card"><strong>' + esc(owner) + '</strong><p>' + count + '件の意思決定を担当。</p></div>').join(''),
        '</div></section>'
      ].join('');
    }
    function renderScenario() {
      const s = selectedScenario();
      return [
        '<section class="section lead-panel">',
        '<div class="card-footer">' + priorityPill(s.priority) + deadlinePill(s.deadline) + '<span class="pill">' + esc(s.riskLabel) + '</span><span class="pill">' + esc(s.urgency || 'urgency未設定') + '</span></div>',
        '<h2>' + esc(s.number + ' ' + s.title) + '</h2>',
        '<p class="lead-text">' + esc(s.description.split('\\n\\n')[0] || s.description) + '</p>',
        '</section>',
        '<section class="section signal-grid">',
        signalCard('何を決めるか', s.decisionText, ['担当: ' + s.owner, '期限: ' + formatDate(s.deadline)]),
        signalCard('なぜ優先度2か', truncate(localizedPriorityEvidenceBlocks(s)[0] || s.rationale || '未設定', 520), []),
        signalCard('遅れた場合の影響', localizedDelayImpact(s), []),
        '</section>',
        '<section class="section split">',
        '<div>' + renderPriorityEvidenceForScenario(s) + '</div>',
        '<div>' + renderUnknownsForScenario(s) + '</div>',
        '</section>',
        '<section class="section"><div class="section-head"><h2>次アクション候補</h2><div class="section-note">Decision options と Discovery推奨アクション</div></div>',
        renderActions(s),
        '</section>',
        '<section class="section"><details><summary>日本語Final Brief全文</summary>' + textBlock(s.raw.files.final_brief_ja_md.text, 'markdown') + '</details></section>'
      ].join('');
    }
    function signalCard(title, text, pills) {
      return '<div class="signal-card"><strong>' + esc(title) + '</strong><p>' + esc(text) + '</p><div class="card-footer">' + pills.map(p => '<span class="pill">' + esc(p) + '</span>').join('') + '</div></div>';
    }
    function renderPriorityEvidenceForScenario(s) {
      const localizedBlocks = localizedPriorityEvidenceBlocks(s);
      if (localizedBlocks.length) {
        return '<div class="section-head"><h2>優先度を上げた根拠</h2><div class="section-note">' + localizedBlocks.length + 'ブロック</div></div>' +
          localizedBlocks.map((block, i) => '<details ' + (i < 3 ? 'open' : '') + '><summary>根拠 ' + (i + 1) + '</summary>' + textBlock(block, 'markdown') + '</details>').join('') +
          '<details><summary>構造化priority_evidence JSON</summary>' + jsonBlock(s.priorityEvidence) + '</details>';
      }
      const groups = groupedByAgent(s.priorityEvidence);
      const body = Object.entries(groups).map(([agent, items]) => {
        return '<details open><summary>' + esc(agentLabels[agent] || agent) + ' / ' + items.length + '件</summary>' +
          items.map(item => '<div class="signal-card" style="box-shadow:none;border-left:0;border-right:0;border-bottom:0;border-radius:0"><p>' + esc(item.evidence_text || item.value || item) + '</p>' +
          (item.limitations ? '<p class="compact muted"><strong>Limitations:</strong> ' + esc(item.limitations) + '</p>' : '') +
          (item.source_refs?.length ? '<div class="card-footer">' + item.source_refs.map(ref => '<span class="pill">' + esc(ref) + '</span>').join('') + '</div>' : '') +
          '</div>').join('') + '</details>';
      }).join('');
      return '<div class="section-head"><h2>優先度を上げた根拠</h2><div class="section-note">' + s.priorityEvidence.length + '件</div></div>' + (body || '<div class="empty">根拠なし</div>');
    }
    function renderUnknownsForScenario(s) {
      const unknowns = [];
      s.findings.forEach(f => {
        (f.unknowns || []).forEach(x => unknowns.push({ agent: f.agent_name, text: x }));
        const meta = f.metadata || {};
        const issue = meta.issue_exploration || {};
        (issue.missing_data || []).forEach(x => unknowns.push({ agent: f.agent_name, text: x }));
      });
      return '<div class="section-head"><h2>未確認事項</h2><div class="section-note">' + unknowns.length + '件</div></div>' +
        (unknowns.length ? '<table><thead><tr><th style="width:150px">Agent</th><th>内容</th></tr></thead><tbody>' +
        unknowns.map(x => '<tr><td>' + esc(agentLabels[x.agent] || x.agent || '') + '</td><td>' + esc(x.text) + '</td></tr>').join('') + '</tbody></table>' :
        '<div class="empty">未確認事項なし</div>');
    }
    function renderActions(s) {
      const options = (s.options || []).map(x => typeof x === 'string' ? x : JSON.stringify(x));
      const actions = [...options, ...s.recommendedActions];
      return actions.length ? '<table><thead><tr><th style="width:80px">No.</th><th>アクション</th></tr></thead><tbody>' +
        actions.map((x, i) => '<tr><td>' + (i + 1) + '</td><td>' + esc(x) + '</td></tr>').join('') + '</tbody></table>' :
        '<div class="empty">アクション候補なし</div>';
    }
    function renderEvidence() {
      const s = selectedScenario();
      const findings = s.findings;
      const evidence = s.evidence;
      return [
        '<section class="section"><div class="section-head"><h2>Agent別の分析結果</h2><div class="section-note">' + findings.length + '件</div></div>',
        '<table><thead><tr><th style="width:150px">Agent</th><th>要旨</th><th style="width:95px">Score</th><th style="width:110px">Confidence</th><th>推奨アクション</th></tr></thead><tbody>',
        findings.map(f => '<tr><td>' + esc(agentLabels[f.agent_name] || f.agent_name) + '</td><td>' + esc(f.summary || '') + '</td><td>' + esc(f.risk_score ?? '-') + '</td><td>' + esc(f.confidence || '-') + '</td><td>' + esc((f.recommended_actions || []).join('; ')) + '</td></tr>').join(''),
        '</tbody></table></section>',
        '<section class="section"><div class="section-head"><h2>外部・内部証拠</h2><div class="section-note">reliable/total: ' + esc(sourceQuality(evidence)) + '</div></div>',
        '<div class="source-grid">' + evidence.map(renderEvidenceCard).join('') + '</div></section>',
        '<section class="section"><details><summary>Evidence Summary JSON全文</summary>' + jsonBlock(s.raw.files.evidence_summary_json.data) + '</details>',
        '<details><summary>Assumptions / Unknowns JSON全文</summary>' + jsonBlock(s.raw.files.assumptions_and_unknowns_json.data) + '</details></section>'
      ].join('');
    }
    function renderEvidenceCard(e) {
      const link = e.source_url ? '<a href="' + esc(e.source_url) + '">' + esc(e.source_title || e.source_domain || e.source_url) + '</a>' : '<strong>' + esc(e.source_title || e.evidence_id) + '</strong>';
      return '<div class="source-card">' +
        '<div class="card-footer"><span class="pill">' + esc(e.source_domain || e.source_type || '') + '</span><span class="pill">' + esc(e.reliability || 'reliability未設定') + '</span><span class="pill">' + esc(e.confidence || 'confidence未設定') + '</span></div>' +
        '<h3>' + link + '</h3><p class="card-text">' + esc(truncate(e.summary || e.raw_snippet || '', 360)) + '</p>' +
        '<details><summary>全文</summary>' + jsonBlock(e) + '</details></div>';
    }
    function renderLineage() {
      const rows = visibleScenarios();
      const lensRows = discovery.lens_results || [];
      return [
        '<section class="section"><div class="section-head"><h2>Discoveryから分析対象への変換</h2><div class="section-note">統合前候補、選定イベント、後続分析IDの対応</div></div>',
        '<table><thead><tr><th style="width:80px">ID</th><th>タイトル</th><th style="width:140px">Lens</th><th>Discovery上の説明</th><th style="width:130px">Relevance</th></tr></thead><tbody>',
        rows.map(s => '<tr><td>' + esc(s.number) + '</td><td>' + esc(s.title) + '</td><td>' + esc((s.candidate.scope_matches || []).join(', ').replace(/.*source_lenses:/, '')) + '</td><td>' + esc(truncate(s.candidate.description || s.aggregated.scenario_story || '', 420)) + '</td><td>' + esc(s.candidate.relevance_score ?? '-') + '</td></tr>').join(''),
        '</tbody></table></section>',
        '<section class="section"><div class="section-head"><h2>Lens別Discovery結果</h2><div class="section-note">' + lensRows.length + ' lens</div></div>',
        lensRows.map((item, i) => '<details><summary>Lens ' + (i + 1) + '</summary>' + jsonBlock(item) + '</details>').join(''),
        '</section>'
      ].join('');
    }
    function renderRaw() {
      return [
        '<section class="section"><div class="section-head"><h2>埋め込みRawデータ</h2><div class="section-note">UI表示は読みやすさのために整形していますが、このHTMLには元JSON/Markdownを全量保持しています。</div></div>',
        '<details open><summary>全Payload JSON</summary>' + jsonBlock(DATA) + '</details>',
        '<details><summary>Portfolio Markdown全文</summary>' + textBlock(DATA.sources.portfolio_summary_md.text, 'markdown') + '</details>',
        '<details><summary>Portfolio JSON全文</summary>' + jsonBlock(DATA.sources.portfolio_summary_json.data) + '</details>',
        '<details><summary>Discovery JSON全文</summary>' + jsonBlock(DATA.sources.discovery_json.data) + '</details></section>'
      ].join('');
    }

    document.getElementById('scenario-select').addEventListener('change', event => {
      state.scenarioIndex = Number(event.target.value);
      render();
    });
    document.getElementById('risk-filter').addEventListener('change', event => {
      state.riskType = event.target.value;
      render();
    });
    document.getElementById('search-box').addEventListener('input', event => {
      state.query = event.target.value;
      render();
    });
    render();
  </script>
</body>
</html>
"""
    return template.replace("__TITLE__", html.escape(title)).replace("__DATA_JSON__", data_json)


if __name__ == "__main__":
    raise SystemExit(main())
