from __future__ import annotations

import hashlib
import json
import logging
import smtplib
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from risk_agent_platform.config import Settings
from risk_agent_platform.query_sanitizer import SENSITIVE_PATTERNS, _replacement_for
from risk_agent_platform.schemas import AgentTaskResult, RiskEvent, ScenarioDelta, StrictModel, now_utc


logger = logging.getLogger(__name__)

DEFAULT_RULES_FILENAME = "notification_rules.jsonl"

KNOWN_TRIGGERS = {
    "scenario_completed",
    "risk_score_threshold",
    "review_required_decision",
    "delta_changes",
    "portfolio_owner_gap",
    "portfolio_deadline_conflict",
}


class NotificationRule(StrictModel):
    rule_id: str
    description: str = ""
    enabled: bool = True
    trigger: str
    params: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] = Field(default_factory=list)
    severity: str = "medium"


class NotificationFindingRef(StrictModel):
    agent_name: str
    risk_score: int | None = None
    review_required: bool = False
    summary: str = ""


class NotificationDecisionRef(StrictModel):
    decision_id: str | None = None
    decision: str = ""
    owner: str = ""
    priority: int = 999
    review_required: bool = False


class NotificationDeltaRef(StrictModel):
    run_id: str
    previous_run_id: str | None = None
    baseline: bool = False
    evidence_added_count: int = 0
    evidence_removed_count: int = 0
    score_change_count: int = 0
    decision_change_count: int = 0


class PortfolioOwnerGapRef(StrictModel):
    group_id: str
    decision: str = ""
    missing_owners: list[str] = Field(default_factory=list)
    required_owners: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)


class PortfolioDeadlineConflictRef(StrictModel):
    group_id: str
    decision: str = ""
    owners: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)


class NotificationEvent(StrictModel):
    event_type: Literal["scenario_completed", "portfolio_summary"]
    scenario_id: str
    client_id: str = ""
    trace_id: str = ""
    run_id: str = ""
    findings: list[NotificationFindingRef] = Field(default_factory=list)
    decisions: list[NotificationDecisionRef] = Field(default_factory=list)
    delta: NotificationDeltaRef | None = None
    owner_gaps: list[PortfolioOwnerGapRef] = Field(default_factory=list)
    deadline_conflicts: list[PortfolioDeadlineConflictRef] = Field(default_factory=list)


class NotificationMessage(StrictModel):
    idempotency_key: str
    rule_id: str
    severity: str
    scenario_id: str
    trace_id: str = ""
    target_id: str = ""
    title: str
    body: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)


class NotificationOutcome(StrictModel):
    idempotency_key: str
    rule_id: str
    channel: str
    status: Literal["sent", "skipped:channel_unconfigured", "failed"]
    attempts: int = 0
    error: str | None = None
    generated_at: datetime = Field(default_factory=now_utc)


def _redact(text: str) -> str:
    """Defense-in-depth redaction: reuse the query sanitizer's sensitive-value patterns.

    Notification payloads are already built from a whitelist of fields, so this is a second
    line of defense in case a summary string happens to still carry an identifier or amount.
    """
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        for match in pattern.findall(redacted):
            redacted = redacted.replace(match, _replacement_for(match))
    return redacted


def _idempotency_key(rule_id: str, scenario_id: str, run_or_trace_id: str, target_id: str) -> str:
    digest_input = "|".join([rule_id, scenario_id, run_or_trace_id, target_id])
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_scenario_event(
    settings: Settings,
    event: RiskEvent,
    result: AgentTaskResult,
    delta: ScenarioDelta | None,
) -> NotificationEvent:
    """Project a completed scenario result (+ its delta, if any) into a sanitizable NotificationEvent."""
    output_dir = settings.project_root / "outputs" / event.scenario_id
    metadata = (result.finding.metadata if result.finding else None) or {}
    findings_meta = metadata.get("findings") or []

    findings: list[NotificationFindingRef] = []
    for finding in findings_meta:
        if not isinstance(finding, dict):
            continue
        findings.append(
            NotificationFindingRef(
                agent_name=str(finding.get("agent_name") or ""),
                risk_score=finding.get("risk_score"),
                review_required=bool(finding.get("review_required")),
                summary=str(finding.get("summary") or "")[:200],
            )
        )
    if not findings and result.finding is not None:
        findings.append(
            NotificationFindingRef(
                agent_name=result.finding.agent_name,
                risk_score=result.finding.risk_score,
                review_required=result.finding.review_required,
                summary=(result.finding.summary or "")[:200],
            )
        )

    decisions_data = _read_json(output_dir / "decision_queue.json").get("decisions") or []
    decisions = [
        NotificationDecisionRef(
            decision_id=item.get("decision_id"),
            decision=str(item.get("decision") or "")[:200],
            owner=str(item.get("owner") or "Unassigned"),
            priority=item.get("priority") if isinstance(item.get("priority"), int) else 999,
            review_required=bool(item.get("review_required")),
        )
        for item in decisions_data
        if isinstance(item, dict)
    ]

    delta_ref = None
    if delta is not None:
        delta_ref = NotificationDeltaRef(
            run_id=delta.run_id,
            previous_run_id=delta.previous_run_id,
            baseline=delta.baseline,
            evidence_added_count=len(delta.evidence_added),
            evidence_removed_count=len(delta.evidence_removed),
            score_change_count=len(delta.score_changes),
            decision_change_count=len(delta.decision_changes),
        )

    run_id = (delta.run_id if delta is not None else "") or result.trace_id

    return NotificationEvent(
        event_type="scenario_completed",
        scenario_id=event.scenario_id,
        client_id=event.client_id,
        trace_id=result.trace_id,
        run_id=run_id,
        findings=findings,
        decisions=decisions,
        delta=delta_ref,
    )


def build_portfolio_event(portfolio_id: str, overview: dict[str, Any]) -> NotificationEvent:
    """Project a portfolio_overview dict (from run_discovery._portfolio_overview) into a NotificationEvent."""
    owner_gaps: list[PortfolioOwnerGapRef] = []
    deadline_conflicts: list[PortfolioDeadlineConflictRef] = []
    for conflict in overview.get("decision_conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        group_id = str(conflict.get("group_id") or "")
        scenario_ids = [str(item) for item in conflict.get("scenario_ids") or []]
        if conflict.get("missing_owners"):
            owner_gaps.append(
                PortfolioOwnerGapRef(
                    group_id=group_id,
                    missing_owners=[str(item) for item in conflict.get("missing_owners") or []],
                    required_owners=[str(item) for item in conflict.get("required_owners") or []],
                    owners=[str(item) for item in conflict.get("owners") or []],
                    scenario_ids=scenario_ids,
                )
            )
        else:
            deadline_conflicts.append(
                PortfolioDeadlineConflictRef(
                    group_id=group_id,
                    owners=[str(item) for item in conflict.get("owners") or []],
                    deadlines=[str(item) for item in conflict.get("deadlines") or []],
                    scenario_ids=scenario_ids,
                )
            )
    return NotificationEvent(
        event_type="portfolio_summary",
        scenario_id=portfolio_id,
        run_id=portfolio_id,
        owner_gaps=owner_gaps,
        deadline_conflicts=deadline_conflicts,
    )


class NotificationChannel:
    name = "base"

    def is_configured(self, settings: Settings) -> bool:
        raise NotImplementedError

    def send(self, settings: Settings, message: NotificationMessage) -> None:
        raise NotImplementedError


def send_http_post_json(url: str, payload: dict[str, Any], *, timeout_seconds: float = 10.0) -> None:
    """Low-level JSON POST transport, isolated into its own function so tests can stub it."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status >= 400:
            raise urllib.error.HTTPError(url, response.status, "notification webhook post failed", response.headers, None)


class WebhookChannel(NotificationChannel):
    name = "webhook"

    def is_configured(self, settings: Settings) -> bool:
        return bool(settings.notifications.webhook_url)

    def send(self, settings: Settings, message: NotificationMessage) -> None:
        payload = {
            "idempotency_key": message.idempotency_key,
            "rule_id": message.rule_id,
            "severity": message.severity,
            "scenario_id": message.scenario_id,
            "trace_id": message.trace_id,
            "title": message.title,
            "body": message.body,
            "links": message.links,
        }
        send_http_post_json(str(settings.notifications.webhook_url), payload)


class SlackChannel(NotificationChannel):
    name = "slack"

    def is_configured(self, settings: Settings) -> bool:
        return bool(settings.notifications.slack_webhook_url)

    def send(self, settings: Settings, message: NotificationMessage) -> None:
        text_lines = [f"*[{message.severity.upper()}] {message.title}*", *message.body]
        if message.links:
            text_lines.append("Links: " + " ".join(message.links))
        payload = {"text": "\n".join(text_lines)}
        send_http_post_json(str(settings.notifications.slack_webhook_url), payload)


def send_smtp_message(
    host: str,
    port: int,
    sender: str,
    recipients: list[str],
    subject: str,
    body: str,
) -> None:
    """Low-level SMTP transport, isolated into its own function so tests can stub it."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    with smtplib.SMTP(host, port, timeout=10) as client:
        client.sendmail(sender, recipients, msg.as_string())


class SmtpChannel(NotificationChannel):
    name = "smtp"

    def is_configured(self, settings: Settings) -> bool:
        notify = settings.notifications
        return bool(notify.smtp_host and notify.smtp_from and notify.smtp_to)

    def send(self, settings: Settings, message: NotificationMessage) -> None:
        notify = settings.notifications
        subject = f"[{message.severity.upper()}] {message.title}"
        body = "\n".join(message.body + ([""] + message.links if message.links else []))
        send_smtp_message(
            str(notify.smtp_host),
            notify.smtp_port,
            str(notify.smtp_from),
            list(notify.smtp_to),
            subject,
            body,
        )


CHANNEL_REGISTRY: dict[str, NotificationChannel] = {
    "webhook": WebhookChannel(),
    "slack": SlackChannel(),
    "smtp": SmtpChannel(),
}


class NotificationEngine:
    def __init__(self, settings: Settings, *, rules_path: Path | None = None, channels: dict[str, NotificationChannel] | None = None) -> None:
        self.settings = settings
        self.rules_path = rules_path or (settings.data_dir / DEFAULT_RULES_FILENAME)
        self.channels = channels if channels is not None else CHANNEL_REGISTRY
        self._seen_keys: set[str] = set()

    def load_rules(self) -> list[NotificationRule]:
        if not self.rules_path.exists():
            return []
        rules: list[NotificationRule] = []
        for line in self.rules_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rules.append(NotificationRule.model_validate(json.loads(line)))
        return rules

    def evaluate(self, event: NotificationEvent) -> list[NotificationMessage]:
        """Deterministically match enabled rules against the event, deduping by idempotency key."""
        messages: list[NotificationMessage] = []
        run_or_trace_id = event.run_id or event.trace_id
        for rule in self.load_rules():
            if not rule.enabled or rule.trigger not in KNOWN_TRIGGERS:
                continue
            for target_id, title, body in _rule_candidates(rule, event):
                key = _idempotency_key(rule.rule_id, event.scenario_id, run_or_trace_id, target_id)
                if key in self._seen_keys:
                    continue
                self._seen_keys.add(key)
                messages.append(
                    NotificationMessage(
                        idempotency_key=key,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        scenario_id=event.scenario_id,
                        trace_id=event.trace_id,
                        target_id=target_id,
                        title=_redact(title),
                        body=[_redact(line) for line in body],
                        links=_scenario_links(self.settings, event.scenario_id),
                        channels=list(rule.channels),
                    )
                )
        return messages

    def dispatch(self, messages: list[NotificationMessage]) -> list[NotificationOutcome]:
        """Send every message to every referenced channel, retrying transient failures.

        Never raises: channel failures are captured as outcomes, and unexpected exceptions
        while sending are treated as a failed attempt for that channel.
        """
        outcomes: list[NotificationOutcome] = []
        failures: list[dict[str, Any]] = []
        for message in messages:
            for channel_name in message.channels:
                channel = self.channels.get(channel_name)
                if channel is None or not channel.is_configured(self.settings):
                    outcomes.append(
                        NotificationOutcome(
                            idempotency_key=message.idempotency_key,
                            rule_id=message.rule_id,
                            channel=channel_name,
                            status="skipped:channel_unconfigured",
                        )
                    )
                    continue
                success, error, attempts = _send_with_retry(self.settings, channel, message)
                if success:
                    outcomes.append(
                        NotificationOutcome(
                            idempotency_key=message.idempotency_key,
                            rule_id=message.rule_id,
                            channel=channel_name,
                            status="sent",
                            attempts=attempts,
                        )
                    )
                else:
                    outcomes.append(
                        NotificationOutcome(
                            idempotency_key=message.idempotency_key,
                            rule_id=message.rule_id,
                            channel=channel_name,
                            status="failed",
                            attempts=attempts,
                            error=error,
                        )
                    )
                    failures.append(
                        {
                            "message": message.model_dump(mode="json"),
                            "channel": channel_name,
                            "error": error,
                            "attempts": attempts,
                        }
                    )
        _write_notifications_log(self.settings, messages, outcomes)
        if failures:
            _write_notification_failures(self.settings, failures)
        return outcomes


def _rule_candidates(rule: NotificationRule, event: NotificationEvent) -> list[tuple[str, str, list[str]]]:
    """Return (target_id, title, body_lines) for every target this rule fires on for this event."""
    candidates: list[tuple[str, str, list[str]]] = []
    if rule.trigger == "scenario_completed":
        if event.event_type != "scenario_completed":
            return candidates
        candidates.append(
            (
                "",
                f"Scenario analysis completed: {event.scenario_id}",
                [f"scenario_id={event.scenario_id}", f"trace_id={event.trace_id}"],
            )
        )
    elif rule.trigger == "risk_score_threshold":
        if event.event_type != "scenario_completed":
            return candidates
        min_score = int(rule.params.get("min_risk_score", 70))
        for finding in event.findings:
            if finding.risk_score is not None and finding.risk_score >= min_score:
                candidates.append(
                    (
                        finding.agent_name,
                        f"High risk score ({finding.risk_score}) from {finding.agent_name}",
                        [
                            f"scenario_id={event.scenario_id}",
                            f"agent={finding.agent_name}",
                            f"risk_score={finding.risk_score}",
                            f"summary={finding.summary}" if finding.summary else "",
                        ],
                    )
                )
    elif rule.trigger == "review_required_decision":
        if event.event_type != "scenario_completed":
            return candidates
        for decision in event.decisions:
            if decision.review_required:
                target_id = decision.decision_id or hashlib.sha256(decision.decision.encode("utf-8")).hexdigest()[:12]
                candidates.append(
                    (
                        target_id,
                        f"Decision requires review: {decision.decision[:80]}",
                        [
                            f"scenario_id={event.scenario_id}",
                            f"owner={decision.owner}",
                            f"priority={decision.priority}",
                        ],
                    )
                )
    elif rule.trigger == "delta_changes":
        if event.event_type != "scenario_completed" or event.delta is None or event.delta.baseline:
            return candidates
        min_changes = int(rule.params.get("min_changes", 1))
        total_changes = (
            event.delta.evidence_added_count
            + event.delta.evidence_removed_count
            + event.delta.score_change_count
            + event.delta.decision_change_count
        )
        if total_changes >= min_changes:
            candidates.append(
                (
                    event.delta.run_id,
                    f"Scenario delta detected {total_changes} change(s): {event.scenario_id}",
                    [
                        f"scenario_id={event.scenario_id}",
                        f"run_id={event.delta.run_id}",
                        f"evidence_added={event.delta.evidence_added_count}",
                        f"evidence_removed={event.delta.evidence_removed_count}",
                        f"score_changes={event.delta.score_change_count}",
                        f"decision_changes={event.delta.decision_change_count}",
                    ],
                )
            )
    elif rule.trigger == "portfolio_owner_gap":
        if event.event_type != "portfolio_summary":
            return candidates
        for gap in event.owner_gaps:
            candidates.append(
                (
                    gap.group_id,
                    f"Portfolio owner gap: {gap.group_id}",
                    [
                        f"portfolio_id={event.scenario_id}",
                        f"missing_owners={', '.join(gap.missing_owners)}",
                        f"required_owners={', '.join(gap.required_owners)}",
                        f"owners={', '.join(gap.owners)}",
                        f"scenario_count={len(gap.scenario_ids)}",
                    ],
                )
            )
    elif rule.trigger == "portfolio_deadline_conflict":
        if event.event_type != "portfolio_summary":
            return candidates
        for conflict in event.deadline_conflicts:
            candidates.append(
                (
                    conflict.group_id,
                    f"Portfolio deadline/owner conflict: {conflict.group_id}",
                    [
                        f"portfolio_id={event.scenario_id}",
                        f"owners={', '.join(conflict.owners)}",
                        f"deadlines={', '.join(conflict.deadlines)}",
                        f"scenario_count={len(conflict.scenario_ids)}",
                    ],
                )
            )
    return candidates


def _scenario_links(settings: Settings, scenario_id: str) -> list[str]:
    base_url = settings.notifications.platform_api_base_url.rstrip("/")
    return [f"{base_url}/v1/scenarios/{scenario_id}/artifacts"]


def _send_with_retry(settings: Settings, channel: NotificationChannel, message: NotificationMessage) -> tuple[bool, str | None, int]:
    max_retries = max(0, settings.notifications.retry_max_attempts)
    base_delay = max(0.0, settings.notifications.retry_base_delay_seconds)
    attempts = 0
    last_error: str | None = None
    while attempts <= max_retries:
        attempts += 1
        try:
            channel.send(settings, message)
            return True, None, attempts
        except Exception as exc:  # noqa: BLE001 - any transport failure is retried/recorded, never raised
            last_error = f"{type(exc).__name__}: {exc}"
            if attempts > max_retries:
                break
            time.sleep(base_delay * (2 ** (attempts - 1)))
    return False, last_error, attempts


def _write_notifications_log(settings: Settings, messages: list[NotificationMessage], outcomes: list[NotificationOutcome]) -> None:
    if not messages:
        return
    scenario_id = messages[0].scenario_id
    output_dir = settings.project_root / "outputs" / scenario_id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "notifications.json"
    existing = _read_json(path).get("entries") or []
    outcomes_by_key: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes:
        outcomes_by_key.setdefault(outcome.idempotency_key, []).append(outcome.model_dump(mode="json"))
    for message in messages:
        existing.append(
            {
                "message": message.model_dump(mode="json"),
                "outcomes": outcomes_by_key.get(message.idempotency_key, []),
            }
        )
    path.write_text(json.dumps({"entries": existing}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_notification_failures(settings: Settings, failures: list[dict[str, Any]]) -> None:
    scenario_id = failures[0]["message"]["scenario_id"]
    output_dir = settings.project_root / "outputs" / scenario_id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "notification_failures.json"
    existing = _read_json(path).get("failures") or []
    existing.extend(failures)
    path.write_text(json.dumps({"failures": existing}, ensure_ascii=False, indent=2), encoding="utf-8")


def dispatch_scenario_notifications(
    settings: Settings,
    event: RiskEvent,
    result: AgentTaskResult,
    delta: ScenarioDelta | None,
) -> list[NotificationOutcome]:
    """Build a NotificationEvent for a completed scenario run and dispatch it. Never raises."""
    if result.status != "completed":
        return []
    try:
        notification_event = build_scenario_event(settings, event, result, delta)
        engine = NotificationEngine(settings)
        messages = engine.evaluate(notification_event)
        return engine.dispatch(messages)
    except Exception as exc:  # noqa: BLE001 - notification dispatch must never fail scenario analysis
        logger.warning("notification dispatch failed for %s: %s", event.scenario_id, exc)
        return []


def dispatch_portfolio_notifications(
    settings: Settings,
    portfolio_id: str,
    overview: dict[str, Any],
) -> list[NotificationOutcome]:
    """Build a NotificationEvent for a portfolio summary and dispatch owner-gap/deadline-conflict rules. Never raises."""
    try:
        notification_event = build_portfolio_event(portfolio_id, overview)
        engine = NotificationEngine(settings)
        messages = engine.evaluate(notification_event)
        return engine.dispatch(messages)
    except Exception as exc:  # noqa: BLE001 - notification dispatch must never fail the discovery pipeline
        logger.warning("portfolio notification dispatch failed for %s: %s", portfolio_id, exc)
        return []
