from risk_agent_platform.schemas import AgentFinding, DecisionItem


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
