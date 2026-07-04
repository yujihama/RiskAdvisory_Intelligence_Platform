from __future__ import annotations

from pathlib import Path


SCENARIO_ARTIFACT_NAMES: tuple[str, ...] = (
    "final_brief.md",
    "decision_queue.json",
    "evidence_summary.json",
    "red_team_review.md",
    "assumptions_and_unknowns.json",
    "trace_metadata.json",
)

DISCOVERY_SUFFIXES: tuple[str, ...] = (
    ".json",
    "_portfolio_summary.json",
    "_portfolio_summary.md",
)


class ArtifactPathError(ValueError):
    """Raised when a scenario_id/artifact name/path fails traversal or shape validation."""


class ArtifactNotFoundError(LookupError):
    """Raised when an artifact name is well-formed but not in the allowed listing for a scenario."""


def validate_scenario_id(scenario_id: str) -> None:
    if not scenario_id or ".." in scenario_id or "/" in scenario_id or "\\" in scenario_id:
        raise ArtifactPathError(f"invalid scenario_id: {scenario_id!r}")


def list_artifacts(outputs_root: Path, scenario_id: str) -> list[str]:
    validate_scenario_id(scenario_id)
    names: list[str] = []
    scenario_dir = outputs_root / scenario_id
    if scenario_dir.is_dir():
        for name in SCENARIO_ARTIFACT_NAMES:
            if (scenario_dir / name).is_file():
                names.append(name)
        deltas_dir = scenario_dir / "deltas"
        if deltas_dir.is_dir():
            for path in sorted(deltas_dir.iterdir()):
                if path.is_file() and (path.suffix == ".json" or path.name.endswith("_summary.md")):
                    names.append(f"deltas/{path.name}")
    discovery_dir = outputs_root / "risk_discovery"
    if discovery_dir.is_dir():
        for suffix in DISCOVERY_SUFFIXES:
            candidate = discovery_dir / f"{scenario_id}{suffix}"
            if candidate.is_file():
                names.append(f"risk_discovery/{scenario_id}{suffix}")
    return names


def resolve_artifact_path(outputs_root: Path, scenario_id: str, name: str) -> Path:
    validate_scenario_id(scenario_id)
    if not name or name.startswith("/") or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ArtifactPathError(f"invalid artifact name: {name!r}")

    allowed = list_artifacts(outputs_root, scenario_id)
    if name not in allowed:
        raise ArtifactNotFoundError(f"artifact not found: {name!r}")

    path = (outputs_root / name) if name.startswith("risk_discovery/") else (outputs_root / scenario_id / name)
    resolved = path.resolve()
    root_resolved = outputs_root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ArtifactPathError(f"artifact path escapes outputs root: {name!r}")
    return resolved


def artifact_media_type(name: str) -> str:
    if name.endswith(".md"):
        return "text/markdown"
    if name.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


def resolve_scenario_input_path(scenarios_root: Path, scenario_path: str) -> Path:
    if not scenario_path or scenario_path.startswith("/") or Path(scenario_path).is_absolute() or ".." in Path(scenario_path).parts:
        raise ArtifactPathError(f"invalid scenario_path: {scenario_path!r}")

    root_resolved = scenarios_root.resolve()
    candidate = (scenarios_root / scenario_path).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ArtifactPathError(f"scenario_path escapes data/scenarios: {scenario_path!r}")
    if not candidate.is_file():
        raise ArtifactNotFoundError(f"scenario file not found: {scenario_path!r}")
    return candidate
