"""Append-only Decision Log for human actions on Decision Queue items (roadmap F4).

State machine (deterministic, no LLM involved):

    pending            -> approve                  -> approved
    pending            -> reject          (reason)  -> rejected
    pending            -> hold            (reason)  -> held
    pending            -> request_recheck           -> recheck_requested
    held               -> approve                    -> approved
    held               -> reject          (reason)  -> rejected
    held               -> request_recheck           -> recheck_requested
    recheck_requested  -> approve                    -> approved
    recheck_requested  -> reject          (reason)  -> rejected
    recheck_requested  -> hold            (reason)  -> held

`reassign` never changes state (`prev_state == new_state`); it is allowed only from
`pending`, `held`, and `recheck_requested`, and always requires `new_owner`.

`approved` and `rejected` are terminal: once a decision reaches either state, every
further action -- including `reassign` -- is rejected as an invalid transition. This
is deliberately strict and simple: corrections are out of scope for this feature.
The log never rewrites or removes an entry; only new, forward-only entries are ever
appended.

Storage: one append-only JSONL file per scenario at
`outputs/<scenario_id>/decision_log.jsonl`, one `DecisionAction` JSON object per
line, in append order. The current state of a decision is always the fold of its
actions in that order; there is no separately stored "current state" record.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from risk_agent_platform.config import Settings
from risk_agent_platform.schemas import DecisionAction, DecisionActionType, DecisionState, now_utc
from risk_agent_platform.stores.neo4j_store import Neo4jStore


logger = logging.getLogger(__name__)

INITIAL_STATE: DecisionState = "pending"
DECISION_STATES: tuple[DecisionState, ...] = ("pending", "approved", "rejected", "held", "recheck_requested")

REASON_REQUIRED_ACTIONS: frozenset[str] = frozenset({"hold", "reject"})
NEW_OWNER_REQUIRED_ACTIONS: frozenset[str] = frozenset({"reassign"})

# current_state -> {action: next_state}. Absence of an action key means the
# transition is invalid from that state.
_TRANSITIONS: dict[DecisionState, dict[DecisionActionType, DecisionState]] = {
    "pending": {
        "approve": "approved",
        "reject": "rejected",
        "hold": "held",
        "request_recheck": "recheck_requested",
        "reassign": "pending",
    },
    "held": {
        "approve": "approved",
        "reject": "rejected",
        "request_recheck": "recheck_requested",
        "reassign": "held",
    },
    "recheck_requested": {
        "approve": "approved",
        "reject": "rejected",
        "hold": "held",
        "reassign": "recheck_requested",
    },
    "approved": {},
    "rejected": {},
}


class DecisionLogError(Exception):
    """Base class for all Decision Log errors."""


class ScenarioNotFoundError(DecisionLogError):
    """Raised when a scenario has no `decision_queue.json` (API maps this to HTTP 404)."""


class DecisionNotFoundError(DecisionLogError):
    """Raised when `decision_id` is not present in the scenario's Decision Queue (API maps this to HTTP 404)."""


class DecisionValidationError(DecisionLogError):
    """Raised when a required field for the requested action is missing (API maps this to HTTP 422)."""


class InvalidTransitionError(DecisionLogError):
    """Raised when an action is not allowed from the decision's current state (API maps this to HTTP 409)."""

    def __init__(self, message: str, *, current_state: DecisionState, action: DecisionActionType) -> None:
        super().__init__(message)
        self.current_state = current_state
        self.action = action


def _decision_queue_path(settings: Settings, scenario_id: str) -> Path:
    return settings.project_root / "outputs" / scenario_id / "decision_queue.json"


def _decision_log_path(settings: Settings, scenario_id: str) -> Path:
    return settings.project_root / "outputs" / scenario_id / "decision_log.jsonl"


def _load_decision_ids(settings: Settings, scenario_id: str) -> set[str]:
    path = _decision_queue_path(settings, scenario_id)
    if not path.exists():
        raise ScenarioNotFoundError(f"no decision queue found for scenario_id={scenario_id!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(item["decision_id"])
        for item in data.get("decisions", [])
        if isinstance(item, dict) and item.get("decision_id")
    }


def fold_state(actions: list[DecisionAction]) -> DecisionState:
    """The current state of a decision is simply the `new_state` of its last recorded action."""
    state: DecisionState = INITIAL_STATE
    for action in actions:
        state = action.new_state
    return state


class DecisionLogStore:
    """Append-only per-scenario Decision Log. See module docstring for the state machine."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()

    def current_state(self, scenario_id: str, decision_id: str) -> DecisionState:
        return fold_state(self.list_actions(scenario_id, decision_id=decision_id))

    def list_actions(self, scenario_id: str, *, decision_id: str | None = None) -> list[DecisionAction]:
        """Chronological (append-order) actions for a scenario, optionally filtered to one decision_id."""
        path = _decision_log_path(self.settings, scenario_id)
        if not path.exists():
            return []
        actions: list[DecisionAction] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = DecisionAction.model_validate_json(line)
            if decision_id is None or record.decision_id == decision_id:
                actions.append(record)
        return actions

    def append_action(
        self,
        scenario_id: str,
        decision_id: str,
        *,
        action: DecisionActionType,
        actor: str,
        reason: str = "",
        new_owner: str | None = None,
    ) -> DecisionAction:
        decision_ids = _load_decision_ids(self.settings, scenario_id)
        if decision_id not in decision_ids:
            raise DecisionNotFoundError(f"unknown decision_id={decision_id!r} for scenario_id={scenario_id!r}")

        if action in REASON_REQUIRED_ACTIONS and not reason.strip():
            raise DecisionValidationError(f"reason is required for action={action!r}")
        if action in NEW_OWNER_REQUIRED_ACTIONS and not (new_owner or "").strip():
            raise DecisionValidationError(f"new_owner is required for action={action!r}")

        with self._lock:
            prev_state = self.current_state(scenario_id, decision_id)
            transitions = _TRANSITIONS.get(prev_state, {})
            if action not in transitions:
                raise InvalidTransitionError(
                    f"action={action!r} is not allowed from state={prev_state!r} for decision_id={decision_id!r}",
                    current_state=prev_state,
                    action=action,
                )
            new_state = transitions[action]
            record = DecisionAction(
                action_id=f"{decision_id}_action_{uuid4().hex[:12]}",
                scenario_id=scenario_id,
                decision_id=decision_id,
                action=action,
                actor=actor,
                reason=reason,
                new_owner=new_owner,
                prev_state=prev_state,
                new_state=new_state,
                created_at=now_utc(),
            )
            path = _decision_log_path(self.settings, scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
        _register_action_in_neo4j(self.settings, record)
        return record

    def all_current_states(self, scenario_id: str) -> dict[str, DecisionState]:
        """Current state per decision_id for a scenario. Raises ScenarioNotFoundError if unknown."""
        decision_ids = _load_decision_ids(self.settings, scenario_id)
        return {decision_id: self.current_state(scenario_id, decision_id) for decision_id in sorted(decision_ids)}

    def state_summary(self, scenario_id: str) -> dict[str, Any]:
        """Counts by state plus held reasons, for portfolio/dashboard aggregation.

        Decisions with no log entries yet count as `pending`. Unknown scenarios degrade to an
        all-zero summary rather than raising, since this is meant for best-effort aggregation.
        """
        try:
            decision_ids = _load_decision_ids(self.settings, scenario_id)
        except ScenarioNotFoundError:
            decision_ids = set()
        counts: dict[str, int] = {state: 0 for state in DECISION_STATES}
        held_reasons: dict[str, list[str]] = {}
        for decision_id in sorted(decision_ids):
            actions = self.list_actions(scenario_id, decision_id=decision_id)
            state = fold_state(actions)
            counts[state] = counts.get(state, 0) + 1
            if state == "held":
                reasons = [action.reason for action in actions if action.action == "hold" and action.reason]
                if reasons:
                    held_reasons[decision_id] = reasons
        return {
            "total_decisions": len(decision_ids),
            "counts": counts,
            "held_reasons": held_reasons,
        }


def recheck_requested_conditions(settings: Settings, scenario_id: str) -> list[str]:
    """Synthetic recheck conditions for decisions currently `recheck_requested`.

    Consumed by `delta.load_previous_recheck_conditions` so a human's `request_recheck` action
    feeds into the next run's orchestrator plan and delta evaluation, same as any other recheck
    condition.
    """
    store = DecisionLogStore(settings)
    try:
        decision_ids = _load_decision_ids(settings, scenario_id)
    except ScenarioNotFoundError:
        return []
    conditions: list[str] = []
    for decision_id in sorted(decision_ids):
        actions = store.list_actions(scenario_id, decision_id=decision_id)
        if not actions or fold_state(actions) != "recheck_requested":
            continue
        last_recheck = next((a for a in reversed(actions) if a.action == "request_recheck"), actions[-1])
        reason = last_recheck.reason or "no reason provided"
        conditions.append(f"decision_recheck_requested: {decision_id} - {reason}")
    return conditions


def _register_action_in_neo4j(settings: Settings, action: DecisionAction) -> None:
    try:
        store = Neo4jStore(settings)
        try:
            node_id = f"{action.scenario_id}:{action.action_id}"
            store.upsert_asset(
                "DecisionAction",
                node_id,
                {
                    "scenario_id": action.scenario_id,
                    "decision_id": action.decision_id,
                    "action": action.action,
                    "actor": action.actor,
                    "reason": action.reason,
                    "new_owner": action.new_owner,
                    "prev_state": action.prev_state,
                    "new_state": action.new_state,
                    "created_at": action.created_at.isoformat(),
                    "confidence_level": "source_backed",
                    "source_type": "user_input",
                },
            )
            store.upsert_relation(action.decision_id, node_id, "ACTED_ON", {"confidence_level": "source_backed"})
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 - Neo4j registration is strictly best-effort
        logger.warning("neo4j decision action registration failed for %s/%s: %s", action.scenario_id, action.action_id, exc)
