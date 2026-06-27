from pathlib import Path

from risk_agent_platform.llm.model_router import ModelRouter


def test_model_router_loads_profile_from_yaml():
    router = ModelRouter(Path("config/llm_profiles.yaml"))
    profile = router.select(task_type="domain_reasoning", agent="treasury-risk-agent", mode="treasury")
    assert profile.provider == "openrouter"
    assert profile.model
    assert profile.max_tokens > 0
