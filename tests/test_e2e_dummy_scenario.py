import json
from pathlib import Path

from risk_agent_platform.agents.orchestrator import OrchestratorDeepAgent
from risk_agent_platform.config import Settings


def test_dummy_scenario_e2e(tmp_path):
    root = Path.cwd()
    settings = Settings.load(root)
    result = OrchestratorDeepAgent(settings).run_from_file(root / "data" / "sample_inputs" / "geopolitical_sanctions_risk.json")

    scenario_dir = Path(result.artifact_dir)
    assert result.scenario_id == "scenario_demo_2026_001"
    assert len(result.findings) >= 6
    assert len(result.decisions) == 3
    assert len(result.evidence) >= 2
    assert (scenario_dir / "plan.md").exists()
    assert (scenario_dir / "graph_imports" / "client_asset_graph.json").exists()
    assert (scenario_dir / "decision_queue.json").exists()
    assert (scenario_dir / "final_brief.md").exists()

    queue = json.loads((scenario_dir / "decision_queue.json").read_text(encoding="utf-8"))
    assert queue[0]["owner"] == "CFO / Legal / Procurement"
    assert queue[0]["review_required"] is True
