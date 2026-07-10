"use strict";

const Api = {
  async request(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = body && typeof body === "object" ? body.detail : body;
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return body;
  },

  state(scenarioId) {
    const query = scenarioId ? `?scenario_id=${encodeURIComponent(scenarioId)}` : "";
    return this.request(`/api/ui/state${query}`);
  },

  submitScenario(event, embeddedServices) {
    return this.request("/v1/scenarios", {
      method: "POST",
      body: JSON.stringify({ event, embedded_services: embeddedServices }),
    });
  },

  job(jobId) {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}`);
  },

  decisionAction(scenarioId, decisionId, payload) {
    return this.request(
      `/v1/scenarios/${encodeURIComponent(scenarioId)}/decisions/${encodeURIComponent(decisionId)}/actions`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },
};

const Store = {
  data: null,
  queueFilter: "all",
  activeAction: null,
  activeJobId: null,
  drawerTrigger: null,
  showAllScenarios: false,
  loading: false,
};

const drawerMedia = {
  "app-navigation": "(max-width: 767px)",
  "scenario-panel": "(max-width: 1023px)",
  "evidence-panel": "(max-width: 1279px)",
};

const stateLabels = {
  pending: "レビュー待ち",
  approved: "承認済み",
  rejected: "却下",
  held: "保留中",
  recheck_requested: "再評価待ち",
};

const jobLabels = {
  submitted: "分析受付済み",
  working: "分析中",
  completed: "分析完了・レビュー待ち",
  failed: "分析失敗",
};

const confidenceLabels = {
  low: "確信度: 低",
  medium: "確信度: 中",
  high: "確信度: 高",
};

const riskAgentLabels = {
  "treasury-risk-agent": "財務リスク評価",
  "legal-risk-agent": "法務リスク評価",
  "accounting-risk-agent": "会計リスク評価",
  "procurement-risk-agent": "調達リスク評価",
};

const actionMeta = {
  approve: {
    title: "推奨判断を承認",
    description: "この操作はDecision Logへ追記され、以後の変更はできません。",
    submit: "承認を記録",
    reasonRequired: false,
    ownerRequired: false,
  },
  hold: {
    title: "判断を保留",
    description: "保留理由を記録し、追加確認が終わるまで意思決定を停止します。",
    submit: "保留を記録",
    reasonRequired: true,
    ownerRequired: false,
  },
  request_recheck: {
    title: "再評価を依頼",
    description: "確認事項を次回分析の再評価条件としてDecision Logへ追加します。",
    submit: "再評価条件を登録",
    reasonRequired: true,
    ownerRequired: false,
  },
  reassign: {
    title: "担当者を変更",
    description: "現在の状態は変えず、新しい責任者を追記専用ログへ記録します。",
    submit: "担当変更を記録",
    reasonRequired: false,
    ownerRequired: true,
  },
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function icon(name) {
  const element = node("i", `ti ti-${name}`);
  element.setAttribute("aria-hidden", "true");
  return element;
}

function setText(selector, value, fallback = "—") {
  const element = $(selector);
  if (element) element.textContent = value === undefined || value === null || value === "" ? fallback : String(value);
}

function stateLabel(state) {
  return stateLabels[state] || state || "状態不明";
}

function jobLabel(status) {
  return jobLabels[status] || status || "状態不明";
}

function formatDate(value, options = {}) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("ja-JP", {
    year: options.year ? "numeric" : undefined,
    month: "2-digit",
    day: "2-digit",
    hour: options.time ? "2-digit" : undefined,
    minute: options.time ? "2-digit" : undefined,
    hour12: false,
  }).format(parsed);
}

function safeHttpUrl(value) {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch (_error) {
    return null;
  }
}

function showError(message) {
  const banner = $('[data-ui="error-banner"]');
  banner.textContent = message;
  banner.hidden = false;
}

function clearError() {
  const banner = $('[data-ui="error-banner"]');
  banner.textContent = "";
  banner.hidden = true;
}

let toastTimer;
function toast(message) {
  const element = $('[data-ui="toast"]');
  element.textContent = message;
  element.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    element.hidden = true;
  }, 3200);
}

async function loadState(scenarioId = null, options = {}) {
  if (Store.loading) return;
  Store.loading = true;
  document.querySelector(".app-shell").dataset.appState = "loading";
  clearError();
  try {
    const data = await Api.state(scenarioId);
    if (
      Store.activeJobId
      && data.job?.job_id === Store.activeJobId
      && ["completed", "failed"].includes(data.job?.status)
    ) {
      Store.activeJobId = null;
    }
    Store.data = data;
    renderAll();
    const url = new URL(window.location.href);
    url.searchParams.set("scenario_id", data.scenario_id);
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
    if (!options.silent) toast("最新の分析状態を読み込みました");
    if (["submitted", "working"].includes(data.job?.status) && data.job?.job_id) {
      Store.activeJobId = data.job.job_id;
      void pollJob(data.job.job_id);
    }
  } catch (error) {
    showError(`画面データを取得できませんでした: ${error.message}`);
  } finally {
    Store.loading = false;
    document.querySelector(".app-shell").dataset.appState = "ready";
  }
}

function renderAll() {
  renderScenarioQueue();
  renderDecision();
  renderEvidence();
  renderHistory();
}

function renderScenarioQueue() {
  const list = $('[data-ui="scenario-list"]');
  list.replaceChildren();
  const queue = Array.isArray(Store.data?.scenario_queue) ? Store.data.scenario_queue : [];
  const matching = queue.filter((item) => {
    if (Store.queueFilter === "pending") return !["approved", "rejected"].includes(item.state);
    if (Store.queueFilter === "terminal") return ["approved", "rejected"].includes(item.state);
    return true;
  });
  const filtered = Store.showAllScenarios ? matching : matching.slice(0, 3);
  setText('[data-ui="scenario-count"]', `${queue.length}件`);
  $('[data-action="show-all-scenarios"]').textContent = Store.showAllScenarios
    ? "上位3件に戻す"
    : "すべてのシナリオを表示";

  if (!filtered.length) {
    list.append(node("p", "empty-state", "この条件に一致するシナリオはありません。"));
    return;
  }

  filtered.forEach((item) => {
    const card = node("button", `scenario-card${item.selected ? " is-selected" : ""}`);
    card.type = "button";
    card.dataset.scenarioId = item.scenario_id;
    card.dataset.state = item.state || "pending";
    card.setAttribute("aria-pressed", item.selected ? "true" : "false");

    const top = node("div", "scenario-card-top");
    top.append(node("span", "", Number(item.priority) === 1 ? "高優先度" : "シナリオ"));
    top.append(node("span", "", item.updated_at ? formatDate(item.updated_at) : ""));

    const title = node("h3", "", item.title || item.scenario_id);
    const meta = node("div", "scenario-card-meta");
    meta.append(node("span", "", item.owner || "担当未設定"));
    meta.append(node("span", "", item.deadline || "期限未設定"));

    const status = node("div", "scenario-card-status");
    status.append(node("span", "", item.review_required ? "人間レビュー" : "レビュー不要"));
    status.append(node("strong", "", stateLabel(item.state)));

    card.append(top, title, meta, status);
    list.append(card);
  });
}

function renderDecision() {
  const data = Store.data || {};
  const decision = data.decision || {};
  const event = data.event || {};
  const metrics = data.metrics || {};
  const job = data.job || {};
  const assessment = data.risk_assessment || {};
  const owner = decision.effective_owner || decision.owner;

  setText('[data-ui="header-owner"]', owner);
  setText('[data-ui="header-deadline"]', decision.deadline);
  setText('[data-ui="decision-title"]', event.title || decision.decision, "分析タイトル未設定");
  setText('[data-ui="decision-rationale"]', event.summary || decision.rationale, "説明はまだ生成されていません。");
  setText('[data-ui="impact-amount"]', metrics.payment_exposure_display ? `${metrics.payment_exposure_display}（通貨未設定）` : "未算出");

  const domains = event.affected_categories?.length
    ? event.affected_categories.join(" / ")
    : event.risk_themes?.length
      ? event.risk_themes.join(" / ")
      : decision.risk_if_delayed;
  setText('[data-ui="impact-domains"]', domains, "未設定");
  setText('[data-ui="impact-region"]', event.countries?.length ? event.countries.join(" / ") : "未設定");
  setText('[data-ui="decision-owner"]', owner, "未設定");

  const statusPill = $(".status-pill");
  statusPill.dataset.status = job.status || "completed";
  setText('[data-ui="header-job-status"]', jobLabel(job.status));
  setText('[data-ui="job-status"]', jobLabel(job.status));
  setText(
    '[data-ui="risk-score-label"]',
    riskAgentLabels[assessment.source_agent] || assessment.source_agent || "リスク評価",
  );
  setText('[data-ui="risk-score"]', Number.isFinite(assessment.risk_score) ? `${assessment.risk_score} / 100` : "未算出");
  setText('[data-ui="risk-confidence"]', confidenceLabels[assessment.confidence], "確信度: 未設定");
  setText('[data-ui="contradiction-count"]', `${Number(data.contradiction_count || 0)}件`);

  const priority = Number(decision.priority);
  setText('[data-ui="priority-label"]', priority === 1 ? "高優先度の意思決定" : stateLabel(decision.state));
  setText('[data-ui="recommendation-text"]', decision.decision, "推奨判断はまだ生成されていません。");
  setText('[data-ui="recommendation-detail"]', decision.rationale, "判断根拠を確認してください。");

  const state = decision.state || "pending";
  const analysisBusy = ["submitted", "working"].includes(job.status) || Boolean(Store.activeJobId);
  const stateBadge = $('[data-ui="decision-state"]');
  stateBadge.dataset.state = state;
  stateBadge.textContent = stateLabel(state);

  const allowed = new Set(decision.allowed_actions || []);
  $$('[data-decision-action]').forEach((button) => {
    const action = button.dataset.decisionAction;
    button.disabled = !decision.decision_id || !allowed.has(action) || analysisBusy;
    button.setAttribute("aria-disabled", button.disabled ? "true" : "false");
  });

  const rerun = $('[data-action="open-rerun"]');
  rerun.disabled = !data.can_rerun || analysisBusy;

  setText('[data-ui="last-updated"]', `最終更新: ${formatDate(data.loaded_at, { year: true, time: true })}`);
}

function renderEvidence() {
  const list = $('[data-ui="evidence-items"]');
  list.replaceChildren();
  const evidence = Array.isArray(Store.data?.evidence) ? Store.data.evidence : [];
  setText('[data-ui="evidence-count"]', `${evidence.length}件`);

  if (!evidence.length) {
    list.append(node("li", "empty-state", "この意思決定に紐づく根拠はありません。"));
  }

  evidence.forEach((item, index) => {
    const row = node("li", "evidence-item");
    row.dataset.evidenceId = item.evidence_id || "";
    row.append(node("span", "evidence-index", index + 1));

    const url = safeHttpUrl(item.source_url);
    const title = url ? node("a") : node("strong");
    title.textContent = item.title || item.domain || "無題の根拠";
    if (url) {
      title.href = url;
      title.target = "_blank";
      title.rel = "noopener noreferrer";
      title.append(icon("external-link"));
    }
    row.append(title);
    row.append(node("span", "evidence-domain", item.domain || "出典不明"));

    const badges = node("div", "evidence-badges");
    badges.append(node("span", "evidence-badge", `信頼性: ${item.reliability || "未設定"}`));
    (item.supports || []).slice(0, 2).forEach((value) => badges.append(node("span", "evidence-badge", value)));
    if ((item.contradicts || []).length) {
      badges.append(node("span", "evidence-badge is-warning", `反証 ${item.contradicts.length}`));
    }
    row.append(badges);
    row.append(node("span", "evidence-date", formatDate(item.retrieved_at)));
    list.append(row);
  });

  const unknownList = $('[data-ui="unknown-list"]');
  unknownList.replaceChildren();
  const unknowns = Array.isArray(Store.data?.unknowns) ? Store.data.unknowns : [];
  const assumptions = Array.isArray(Store.data?.assumptions) ? Store.data.assumptions : [];
  const insights = [
    ...unknowns.map((text) => ({ text, type: "未確認" })),
    ...assumptions.map((text) => ({ text, type: "前提" })),
  ].slice(0, 5);
  setText('[data-ui="unknown-count"]', `${insights.length}件`);
  if (!insights.length) {
    unknownList.append(node("li", "", "登録された未確認事項はありません。"));
  } else {
    insights.forEach((item) => unknownList.append(node("li", "", `${item.type}: ${item.text}`)));
  }
}

function renderHistory() {
  const list = $('[data-ui="decision-history"]');
  list.replaceChildren();
  const activity = Array.isArray(Store.data?.activity) ? Store.data.activity : [];
  setText('[data-ui="history-count"]', `${activity.length}件`);
  if (!activity.length) {
    list.append(node("li", "empty-state", "履歴はまだありません。"));
    return;
  }

  activity.forEach((item) => {
    const row = node("li", "history-row");
    if (item.decision_id) row.dataset.decisionId = item.decision_id;
    const label = item.decision_title ? `${item.label || "更新"} · ${item.decision_title}` : item.label || "更新";
    const attribution = [
      item.actor,
      item.reason,
      item.new_owner ? `新担当: ${item.new_owner}` : null,
      !item.reason && !item.new_owner ? item.detail : null,
    ].filter(Boolean).join(" / ") || "—";
    row.append(node("time", "", formatDate(item.created_at, { time: true })));
    row.append(node("strong", "", label));
    row.append(node("span", "", attribution));
    list.append(row);
  });
}

function openActionDialog(action) {
  const decision = Store.data?.decision;
  const meta = actionMeta[action];
  if (!decision?.decision_id || !meta) return;
  Store.activeAction = action;
  const dialog = $("#decision-action-dialog");
  const form = $("#decision-action-form");
  form.reset();
  form.elements.action.value = action;
  $("#action-dialog-title").textContent = meta.title;
  $('[data-ui="action-dialog-description"]').textContent = meta.description;
  $('[data-ui="action-submit"]').textContent = meta.submit;
  const reasonField = $('[data-field="reason"]');
  reasonField.hidden = false;
  form.elements.reason.required = meta.reasonRequired;
  const ownerField = $('[data-field="new-owner"]');
  ownerField.hidden = !meta.ownerRequired;
  form.elements.new_owner.required = meta.ownerRequired;
  $('[data-ui="action-error"]').hidden = true;
  dialog.showModal();
  form.elements.actor.focus();
}

async function submitDecisionAction(event) {
  const submitter = event.submitter;
  if (!submitter || submitter.value !== "confirm") return;
  event.preventDefault();
  const form = event.currentTarget;
  const decision = Store.data?.decision;
  const scenarioId = Store.data?.scenario_id;
  const action = form.elements.action.value;
  const payload = {
    action,
    actor: form.elements.actor.value.trim(),
    reason: form.elements.reason.value.trim(),
    new_owner: form.elements.new_owner.value.trim() || null,
  };
  const errorBox = $('[data-ui="action-error"]');
  const submitButton = $('[data-ui="action-submit"]');
  submitButton.disabled = true;
  errorBox.hidden = true;
  try {
    await Api.decisionAction(scenarioId, decision.decision_id, payload);
    $("#decision-action-dialog").close();
    toast("Decision Logへ追記しました");
    await loadState(scenarioId, { silent: true });
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submitButton.disabled = false;
  }
}

function openRerunDialog() {
  if (!Store.data?.can_rerun) {
    toast("再実行できるRiskEventが成果物に含まれていません");
    return;
  }
  $('[data-ui="rerun-error"]').hidden = true;
  $("#rerun-dialog").showModal();
}

async function submitRerun(event) {
  const submitter = event.submitter;
  if (!submitter || submitter.value !== "confirm") return;
  event.preventDefault();
  const form = event.currentTarget;
  const errorBox = $('[data-ui="rerun-error"]');
  const submitButton = $('[data-ui="rerun-submit"]');
  errorBox.hidden = true;
  submitButton.disabled = true;
  try {
    const submitted = await Api.submitScenario(Store.data.event_payload, form.elements.embedded_services.checked);
    Store.activeJobId = submitted.job_id;
    Store.data.job = { ...(Store.data.job || {}), job_id: submitted.job_id, status: "submitted" };
    $("#rerun-dialog").close();
    renderDecision();
    toast("分析ジョブを登録しました");
    await pollJob(submitted.job_id);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submitButton.disabled = false;
  }
}

function updateJobIndicator(job) {
  const status = job.status || "submitted";
  if (Store.data) {
    Store.data.job = { ...(Store.data.job || {}), ...job, status };
    renderDecision();
    return;
  }
  $(".status-pill").dataset.status = status;
  setText('[data-ui="header-job-status"]', jobLabel(status));
  setText('[data-ui="job-status"]', jobLabel(status));
}

async function pollJob(jobId) {
  if (!jobId || Store.activeJobId !== jobId) return;
  try {
    const job = await Api.job(jobId);
    if (job.status === "completed") {
      updateJobIndicator(job);
      const scenarioId = job.result?.scenario_id || job.result?.selected_scenario_id || Store.data?.scenario_id;
      toast("分析が完了しました");
      await loadState(scenarioId, { silent: true });
      return;
    }
    if (job.status === "failed") {
      Store.activeJobId = null;
      updateJobIndicator(job);
      showError(`分析に失敗しました: ${job.error || "原因不明"}`);
      return;
    }
    updateJobIndicator(job);
    window.setTimeout(() => void pollJob(jobId), 1400);
  } catch (error) {
    showError(`ジョブ状態を取得できませんでした: ${error.message}`);
  }
}

function openDrawer(id) {
  const drawer = document.getElementById(id);
  if (!drawer) return;
  const media = drawerMedia[id];
  if (!media || !window.matchMedia(media).matches) return;
  Store.drawerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  drawer.dataset.open = "true";
  $$(`[data-drawer-target="${id}"]`).forEach((button) => button.setAttribute("aria-expanded", "true"));
  const scrim = $(".drawer-scrim");
  scrim.hidden = false;
  syncDrawerAccessibility();
  window.requestAnimationFrame(() => {
    const initialFocus = drawer.querySelector("[data-close-drawer]") || drawerFocusableElements(drawer)[0];
    initialFocus?.focus();
  });
}

function closeDrawers() {
  const focusTarget = Store.drawerTrigger;
  $$("[data-open='true']").forEach((drawer) => {
    delete drawer.dataset.open;
    $$(`[data-drawer-target="${drawer.id}"]`).forEach((button) => button.setAttribute("aria-expanded", "false"));
  });
  $(".drawer-scrim").hidden = true;
  syncDrawerAccessibility();
  Store.drawerTrigger = null;
  if (focusTarget?.isConnected) focusTarget.focus();
}

function syncDrawerAccessibility() {
  const openDrawerElement = $("[data-open='true']");
  ["app-navigation", "app-header", "scenario-panel", "decision-workspace", "evidence-panel"].forEach((id) => {
    const region = document.getElementById(id);
    if (!region) return;
    const media = drawerMedia[id];
    const concealed = Boolean(media) && window.matchMedia(media).matches && region.dataset.open !== "true";
    const obscured = Boolean(openDrawerElement) && region !== openDrawerElement;
    const inactive = concealed || obscured;
    region.toggleAttribute("inert", inactive);
    if (inactive) region.setAttribute("aria-hidden", "true");
    else region.removeAttribute("aria-hidden");
  });
}

function drawerFocusableElements(drawer) {
  return $$('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])', drawer)
    .filter((element) => !element.hidden);
}

function trapDrawerFocus(event) {
  const drawer = $("[data-open='true']");
  if (!drawer || event.key !== "Tab") return;
  const focusable = drawerFocusableElements(drawer);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (!drawer.contains(document.activeElement)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const scenarioButton = event.target.closest("[data-scenario-id]");
    if (scenarioButton) {
      closeDrawers();
      void loadState(scenarioButton.dataset.scenarioId);
      return;
    }

    const actionButton = event.target.closest("[data-decision-action]");
    if (actionButton && !actionButton.disabled) {
      openActionDialog(actionButton.dataset.decisionAction);
      return;
    }

    const drawerButton = event.target.closest("[data-drawer-target]");
    if (drawerButton) {
      openDrawer(drawerButton.dataset.drawerTarget);
      return;
    }

    const closeButton = event.target.closest("[data-close-drawer]");
    if (closeButton) {
      closeDrawers();
      return;
    }

    const dialogCloseButton = event.target.closest("[data-close-dialog]");
    if (dialogCloseButton) {
      dialogCloseButton.closest("dialog")?.close();
      return;
    }

    const navButton = event.target.closest("[data-nav-target]");
    if (navButton && navButton.dataset.navTarget !== "cockpit") {
      toast("この刷新では意思決定コックピットを実装対象にしています");
    }
  });

  $$('[data-action="refresh-state"]').forEach((button) => {
    button.addEventListener("click", () => void loadState(Store.data?.scenario_id));
  });
  $('[data-action="close-drawers"]').addEventListener("click", closeDrawers);
  $('[data-action="open-rerun"]').addEventListener("click", openRerunDialog);
  $('[data-action="show-all-scenarios"]').addEventListener("click", () => {
    Store.showAllScenarios = !Store.showAllScenarios;
    renderScenarioQueue();
    $('[data-ui="scenario-list"]').scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $('[data-ui="queue-filter"]').addEventListener("change", (event) => {
    Store.queueFilter = event.target.value;
    Store.showAllScenarios = false;
    renderScenarioQueue();
  });
  $('[data-action="copy-trace"]').addEventListener("click", async () => {
    const traceId = Store.data?.trace_id;
    if (!traceId) return toast("Trace IDはありません");
    try {
      await navigator.clipboard.writeText(traceId);
      toast("Trace IDをコピーしました");
    } catch (_error) {
      toast(`Trace: ${traceId}`);
    }
  });
  $("#decision-action-form").addEventListener("submit", submitDecisionAction);
  $("#rerun-form").addEventListener("submit", submitRerun);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("[data-open='true']")) closeDrawers();
    else trapDrawerFocus(event);
  });
  window.addEventListener("resize", () => {
    if (window.matchMedia("(min-width: 1280px)").matches) closeDrawers();
    else syncDrawerAccessibility();
  });
}

async function init() {
  bindEvents();
  syncDrawerAccessibility();
  if (window.location.protocol === "file:") {
    showError("実データを表示するには python -m risk_agent_platform.ui_server で起動してください。");
    document.querySelector(".app-shell").dataset.appState = "ready";
    return;
  }
  const scenarioId = new URLSearchParams(window.location.search).get("scenario_id");
  await loadState(scenarioId, { silent: true });
}

document.addEventListener("DOMContentLoaded", () => void init());
