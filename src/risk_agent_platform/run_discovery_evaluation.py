from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable

from risk_agent_platform.config import Settings
from risk_agent_platform.risk_discovery import RiskDiscoveryDeepAgent
from risk_agent_platform.schemas import RiskDiscoveryRequest, RiskDiscoveryResult, RiskDiscoveryScope


DiscoveryFactory = Callable[[Settings, bool], Any]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path("data/evaluation/risk_discovery_cases.jsonl"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--embedded-services", action="store_true")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--min-recall", type=float, default=0.75)
    parser.add_argument("--min-question-match", type=float, default=0.25)
    args = parser.parse_args(argv)

    settings = Settings.load(Path.cwd())
    cases = load_cases(settings.project_root / args.cases if not args.cases.is_absolute() else args.cases)
    report = evaluate_cases(
        settings,
        cases,
        embedded_mcp=args.embedded_services,
        top_n=args.top_n,
        min_recall=args.min_recall,
        min_question_match=args.min_question_match,
    )
    paths = write_report(settings, report, args.output)
    summary = report["summary"]
    print("discovery_evaluation_status=completed")
    print(f"case_count={summary['case_count']}")
    print(f"passed={str(summary['passed']).lower()}")
    print(f"average_recall={summary['average_recall']:.3f}")
    print(f"forbidden_top_violation_count={summary['forbidden_top_violation_count']}")
    print(f"average_question_match={summary['average_question_match']:.3f}")
    print(f"evaluation_output_json={paths['json']}")
    print(f"evaluation_output_md={paths['markdown']}")
    return 0 if summary["passed"] else 1


def load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_cases(
    settings: Settings,
    cases: list[dict[str, Any]],
    *,
    embedded_mcp: bool,
    top_n: int = 3,
    min_recall: float = 0.75,
    min_question_match: float = 0.25,
    discovery_factory: DiscoveryFactory | None = None,
) -> dict[str, Any]:
    factory = discovery_factory or (lambda local_settings, embedded: RiskDiscoveryDeepAgent(local_settings, embedded_mcp=embedded))
    results = []
    for case in cases:
        request = _request_from_case(case)
        discovery = factory(settings, embedded_mcp)
        result: RiskDiscoveryResult = discovery.discover(request)
        results.append(_evaluate_case(case, result, top_n=top_n, min_recall=min_recall, min_question_match=min_question_match))
    summary = _summary(results, min_recall=min_recall, min_question_match=min_question_match)
    return {
        "summary": summary,
        "cases": results,
        "thresholds": {
            "top_n": top_n,
            "min_recall": min_recall,
            "min_question_match": min_question_match,
        },
    }


def write_report(settings: Settings, report: dict[str, Any], output: Path | None = None) -> dict[str, str]:
    output_dir = settings.project_root / "outputs" / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output or output_dir / "risk_discovery_evaluation.json"
    if not json_path.is_absolute():
        json_path = settings.project_root / json_path
    md_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _request_from_case(case: dict[str, Any]) -> RiskDiscoveryRequest:
    data = case["input"]
    scope = data["scope"]
    return RiskDiscoveryRequest(
        event_title=data["event_title"],
        event_description=data.get("event_description", ""),
        countries=[str(item) for item in data.get("countries", [])],
        max_risks=int(data.get("max_risks", 3)),
        scope=RiskDiscoveryScope(
            client_id=scope["client_id"],
            scope_type=scope.get("scope_type", "company"),
            scope_name=scope.get("scope_name"),
            department=scope.get("department"),
            region=scope.get("region"),
            site_id=scope.get("site_id"),
            metadata=scope.get("metadata", {}),
        ),
    )


def _evaluate_case(
    case: dict[str, Any],
    result: RiskDiscoveryResult,
    *,
    top_n: int,
    min_recall: float,
    min_question_match: float,
) -> dict[str, Any]:
    selected_risk_types = [candidate.risk_type for candidate in result.selected_candidates]
    top_risk_types = selected_risk_types[: max(1, top_n)]
    expected = [str(item) for item in case.get("expected_selected_risk_types", [])]
    forbidden = [str(item) for item in case.get("should_not_prioritize", [])]
    selected_set = set(selected_risk_types)
    expected_hits = [item for item in expected if item in selected_set]
    recall = len(expected_hits) / len(expected) if expected else 1.0
    forbidden_in_top = [item for item in forbidden if item in top_risk_types]
    actual_questions = [
        *[str(item) for item in result.metadata.get("additional_questions", [])],
        *[str(item) for item in result.metadata.get("unknowns", [])],
    ]
    expected_questions = [str(item) for item in case.get("expected_questions", [])]
    question_match = _question_match_score(expected_questions, actual_questions)
    passed = recall >= min_recall and not forbidden_in_top and question_match >= min_question_match
    return {
        "case_id": case["case_id"],
        "passed": passed,
        "recall": recall,
        "expected_selected_risk_types": expected,
        "selected_risk_types": selected_risk_types,
        "expected_hits": expected_hits,
        "top_risk_types": top_risk_types,
        "should_not_prioritize": forbidden,
        "forbidden_in_top": forbidden_in_top,
        "question_match": question_match,
        "expected_questions": expected_questions,
        "actual_questions": actual_questions,
        "fallback_used": bool(result.metadata.get("fallback_used")),
        "discovery_confidence": result.metadata.get("discovery_confidence"),
        "rejected_count": len(result.rejected_candidates),
    }


def _summary(results: list[dict[str, Any]], *, min_recall: float, min_question_match: float) -> dict[str, Any]:
    case_count = len(results)
    average_recall = sum(float(item["recall"]) for item in results) / case_count if case_count else 0.0
    average_question_match = sum(float(item["question_match"]) for item in results) / case_count if case_count else 0.0
    forbidden_top_violation_count = sum(1 for item in results if item["forbidden_in_top"])
    failed_case_ids = [str(item["case_id"]) for item in results if not item["passed"]]
    return {
        "case_count": case_count,
        "passed": not failed_case_ids,
        "average_recall": average_recall,
        "average_question_match": average_question_match,
        "forbidden_top_violation_count": forbidden_top_violation_count,
        "failed_case_ids": failed_case_ids,
        "min_recall": min_recall,
        "min_question_match": min_question_match,
    }


def _question_match_score(expected_questions: list[str], actual_questions: list[str]) -> float:
    if not expected_questions:
        return 1.0
    if not actual_questions:
        return 0.0
    scores = []
    actual_tokens = [_tokens(question) for question in actual_questions]
    for expected in expected_questions:
        expected_tokens = _tokens(expected)
        if not expected_tokens:
            continue
        best = 0.0
        for candidate_tokens in actual_tokens:
            union = expected_tokens | candidate_tokens
            score = len(expected_tokens & candidate_tokens) / len(union) if union else 0.0
            best = max(best, score)
        scores.append(best)
    return sum(scores) / len(scores) if scores else 0.0


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in {"the", "and", "for", "with", "which", "what", "are"}
    }


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Risk Discovery Evaluation",
        "",
        f"- Passed: `{summary['passed']}`",
        f"- Cases: {summary['case_count']}",
        f"- Average recall: {summary['average_recall']:.3f}",
        f"- Forbidden top violations: {summary['forbidden_top_violation_count']}",
        f"- Average question match: {summary['average_question_match']:.3f}",
        "",
        "## Cases",
    ]
    for case in report["cases"]:
        lines.extend(
            [
                f"### {case['case_id']}",
                f"- Passed: `{case['passed']}`",
                f"- Recall: {case['recall']:.3f}",
                f"- Question match: {case['question_match']:.3f}",
                f"- Selected risk types: {', '.join(case['selected_risk_types']) or 'None'}",
                f"- Forbidden in top: {', '.join(case['forbidden_in_top']) or 'None'}",
                f"- Discovery confidence: `{case.get('discovery_confidence')}`",
            ]
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
