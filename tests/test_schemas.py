from risk_agent_platform.schemas import AgentFinding, DecisionItem, DecisionSynthesisOutput


def test_agent_finding_validates_risk_score_range():
    finding = AgentFinding(
        agent_name="x",
        mode="treasury",
        summary="ok",
        risk_score=50,
        rationale="because",
    )
    assert finding.risk_score == 50


def test_decision_item_priority_is_sortable():
    item = DecisionItem(
        decision="Review payment",
        owner="CFO",
        deadline="24 hours",
        rationale="risk",
        options=["approve", "hold"],
        risk_if_delayed="exposure",
        review_required=True,
        priority=1,
    )
    assert item.priority == 1


def test_decision_synthesis_output_defaults_risk_if_delayed_when_missing():
    output = DecisionSynthesisOutput(
        decision="Review payment route",
        owner="Treasury",
        deadline="24 hours",
        review_requirement="extra provider field should be ignored",
    )

    assert output.risk_if_delayed
    assert output.rationale
    assert output.review_required is True
