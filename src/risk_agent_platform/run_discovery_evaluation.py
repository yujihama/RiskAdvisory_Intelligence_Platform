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


MISSING_DATA_CATEGORY_TERMS: dict[str, set[str]] = {
    "payment_route": {"payment", "payments", "bank", "route", "routes", "cash", "liquidity", "correspondent"},
    "sanctions_screening": {"sanction", "sanctions", "screening", "restricted", "counterparty", "ownership", "beneficial"},
    "contract_terms": {"contract", "contracts", "notice", "termination", "force", "majeure", "clause", "clauses"},
    "supplier_continuity": {"supplier", "suppliers", "inventory", "logistics", "alternative", "source", "continuity"},
    "materiality_reporting": {"material", "materiality", "impairment", "provision", "disclosure", "auditor", "evidence"},
    "executive_ownership": {"executive", "ownership", "owner", "decision", "cross", "functional"},
    "evidence_gap": {"evidence", "gap", "gaps", "unknown", "validate", "validation", "confirmed"},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path("data/evaluation/risk_discovery_cases.jsonl"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--embedded-services", action="store_true")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--min-recall", type=float, default=0.75)
    parser.add_argument("--min-question-match", type=float, default=0.25)
    parser.add_argument("--min-missing-data-match", type=float, default=0.5)
    parser.add_argument("--min-reason-quality", type=float, default=0.75)
    parser.add_argument("--min-rubric-coverage", type=float, default=0.5)
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
        min_missing_data_match=args.min_missing_data_match,
        min_reason_quality=args.min_reason_quality,
        min_rubric_coverage=args.min_rubric_coverage,
    )
    paths = write_report(settings, report, args.output)
    summary = report["summary"]
    print("discovery_evaluation_status=completed")
    print(f"case_count={summary['case_count']}")
    print(f"passed={str(summary['passed']).lower()}")
    print(f"average_recall={summary['average_recall']:.3f}")
    print(f"forbidden_top_violation_count={summary['forbidden_top_violation_count']}")
    print(f"average_question_match={summary['average_question_match']:.3f}")
    print(f"average_question_semantic_match={summary['average_question_semantic_match']:.3f}")
    print(f"average_missing_data_category_match={summary['average_missing_data_category_match']:.3f}")
    print(f"average_reason_quality={summary['average_reason_quality']:.3f}")
    print(f"average_expert_rubric_coverage={summary['average_expert_rubric_coverage']:.3f}")
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
    min_missing_data_match: float = 0.5,
    min_reason_quality: float = 0.75,
    min_rubric_coverage: float = 0.5,
    discovery_factory: DiscoveryFactory | None = None,
) -> dict[str, Any]:
    factory = discovery_factory or (lambda local_settings, embedded: RiskDiscoveryDeepAgent(local_settings, embedded_mcp=embedded))
    results = []
    for case in cases:
        request = _request_from_case(case)
        discovery = factory(settings, embedded_mcp)
        result: RiskDiscoveryResult = discovery.discover(request)
        results.append(
            _evaluate_case(
                case,
                result,
                top_n=top_n,
                min_recall=min_recall,
                min_question_match=min_question_match,
                min_missing_data_match=min_missing_data_match,
                min_reason_quality=min_reason_quality,
                min_rubric_coverage=min_rubric_coverage,
            )
        )
    summary = _summary(
        results,
        min_recall=min_recall,
        min_question_match=min_question_match,
        min_missing_data_match=min_missing_data_match,
        min_reason_quality=min_reason_quality,
        min_rubric_coverage=min_rubric_coverage,
    )
    return {
        "summary": summary,
        "cases": results,
        "thresholds": {
            "top_n": top_n,
            "min_recall": min_recall,
            "min_question_match": min_question_match,
            "min_missing_data_match": min_missing_data_match,
            "min_reason_quality": min_reason_quality,
            "min_rubric_coverage": min_rubric_coverage,
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
    min_missing_data_match: float,
    min_reason_quality: float,
    min_rubric_coverage: float,
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
    question_semantic_match = _question_semantic_match_score(expected_questions, actual_questions)
    expected_missing_categories = [str(item) for item in case.get("expected_missing_data_categories", [])]
    missing_category_match, expected_category_hits, actual_missing_categories = _category_match_score(
        expected_missing_categories,
        actual_questions,
    )
    reason_quality = _reason_quality_score(result)
    expected_rubric_ids = [str(item) for item in case.get("expected_rubric_ids", [])]
    rubric_coverage, rubric_hits, actual_rubric_ids = _expert_rubric_coverage_score(expected_rubric_ids, result)
    passed = (
        recall >= min_recall
        and not forbidden_in_top
        and question_semantic_match >= min_question_match
        and missing_category_match >= min_missing_data_match
        and reason_quality >= min_reason_quality
        and rubric_coverage >= min_rubric_coverage
    )
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
        "question_semantic_match": question_semantic_match,
        "expected_questions": expected_questions,
        "actual_questions": actual_questions,
        "expected_missing_data_categories": expected_missing_categories,
        "actual_missing_data_categories": actual_missing_categories,
        "missing_data_category_hits": expected_category_hits,
        "missing_data_category_match": missing_category_match,
        "reason_quality": reason_quality,
        "expected_rubric_ids": expected_rubric_ids,
        "actual_rubric_ids": actual_rubric_ids,
        "rubric_hits": rubric_hits,
        "expert_rubric_coverage": rubric_coverage,
        "fallback_used": bool(result.metadata.get("fallback_used")),
        "discovery_confidence": result.metadata.get("discovery_confidence"),
        "rejected_count": len(result.rejected_candidates),
    }


def _summary(
    results: list[dict[str, Any]],
    *,
    min_recall: float,
    min_question_match: float,
    min_missing_data_match: float,
    min_reason_quality: float,
    min_rubric_coverage: float,
) -> dict[str, Any]:
    case_count = len(results)
    average_recall = sum(float(item["recall"]) for item in results) / case_count if case_count else 0.0
    average_question_match = sum(float(item["question_match"]) for item in results) / case_count if case_count else 0.0
    average_question_semantic_match = sum(float(item["question_semantic_match"]) for item in results) / case_count if case_count else 0.0
    average_missing_data_category_match = sum(float(item["missing_data_category_match"]) for item in results) / case_count if case_count else 0.0
    average_reason_quality = sum(float(item["reason_quality"]) for item in results) / case_count if case_count else 0.0
    average_expert_rubric_coverage = sum(float(item["expert_rubric_coverage"]) for item in results) / case_count if case_count else 0.0
    forbidden_top_violation_count = sum(1 for item in results if item["forbidden_in_top"])
    failed_case_ids = [str(item["case_id"]) for item in results if not item["passed"]]
    return {
        "case_count": case_count,
        "passed": not failed_case_ids,
        "average_recall": average_recall,
        "average_question_match": average_question_match,
        "average_question_semantic_match": average_question_semantic_match,
        "average_missing_data_category_match": average_missing_data_category_match,
        "average_reason_quality": average_reason_quality,
        "average_expert_rubric_coverage": average_expert_rubric_coverage,
        "forbidden_top_violation_count": forbidden_top_violation_count,
        "failed_case_ids": failed_case_ids,
        "min_recall": min_recall,
        "min_question_match": min_question_match,
        "min_missing_data_match": min_missing_data_match,
        "min_reason_quality": min_reason_quality,
        "min_rubric_coverage": min_rubric_coverage,
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


def _question_semantic_match_score(expected_questions: list[str], actual_questions: list[str]) -> float:
    lexical = _question_match_score(expected_questions, actual_questions)
    expected_categories = _categories_from_texts(expected_questions)
    if not expected_categories:
        return lexical
    actual_categories = _categories_from_texts(actual_questions)
    category_score = len(expected_categories & actual_categories) / len(expected_categories)
    return max(lexical, category_score)


def _category_match_score(expected_categories: list[str], actual_texts: list[str]) -> tuple[float, list[str], list[str]]:
    if not expected_categories:
        return 1.0, [], sorted(_categories_from_texts(actual_texts))
    actual = _categories_from_texts(actual_texts)
    expected = {item for item in expected_categories if item}
    hits = sorted(expected & actual)
    score = len(hits) / len(expected) if expected else 1.0
    return score, hits, sorted(actual)


def _categories_from_texts(texts: list[str]) -> set[str]:
    tokens = set()
    for text in texts:
        tokens.update(_tokens(text))
    categories = set()
    for category, terms in MISSING_DATA_CATEGORY_TERMS.items():
        if tokens & terms:
            categories.add(category)
    return categories


def _reason_quality_score(result: RiskDiscoveryResult) -> float:
    items = [*result.selected_candidates, *result.rejected_candidates]
    if not items:
        return 0.0
    passed = 0
    for candidate in result.selected_candidates:
        if candidate.rationale and isinstance(candidate.relevance_score, int) and candidate.selected_for_analysis:
            passed += 1
    for candidate in result.rejected_candidates:
        reason = candidate.reason.lower()
        if (
            candidate.reason
            and isinstance(candidate.relevance_score, int)
            and any(term in reason for term in ("scope", "relevance", "threshold", "below"))
        ):
            passed += 1
    return passed / len(items)


def _expert_rubric_coverage_score(expected_rubric_ids: list[str], result: RiskDiscoveryResult) -> tuple[float, list[str], list[str]]:
    actual = _scope_rule_ids(result)
    expected = {item for item in expected_rubric_ids if item}
    if not expected:
        return 1.0, [], sorted(actual)
    hits = sorted(expected & actual)
    score = len(hits) / len(expected)
    return score, hits, sorted(actual)


def _scope_rule_ids(result: RiskDiscoveryResult) -> set[str]:
    ids: set[str] = set()
    for candidate in [*result.selected_candidates, *result.rejected_candidates]:
        for match in candidate.scope_matches:
            rule_id = str(match).split(":", 1)[0]
            if rule_id.startswith("SCOPE-"):
                ids.add(rule_id)
    return ids


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
        f"- Average question semantic match: {summary['average_question_semantic_match']:.3f}",
        f"- Average missing-data category match: {summary['average_missing_data_category_match']:.3f}",
        f"- Average selected/rejected reason quality: {summary['average_reason_quality']:.3f}",
        f"- Average expert rubric coverage: {summary['average_expert_rubric_coverage']:.3f}",
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
                f"- Question semantic match: {case['question_semantic_match']:.3f}",
                f"- Missing-data category match: {case['missing_data_category_match']:.3f}",
                f"- Reason quality: {case['reason_quality']:.3f}",
                f"- Expert rubric coverage: {case['expert_rubric_coverage']:.3f}",
                f"- Selected risk types: {', '.join(case['selected_risk_types']) or 'None'}",
                f"- Forbidden in top: {', '.join(case['forbidden_in_top']) or 'None'}",
                f"- Missing-data category hits: {', '.join(case['missing_data_category_hits']) or 'None'}",
                f"- Rubric hits: {', '.join(case['rubric_hits']) or 'None'}",
                f"- Discovery confidence: `{case.get('discovery_confidence')}`",
            ]
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
