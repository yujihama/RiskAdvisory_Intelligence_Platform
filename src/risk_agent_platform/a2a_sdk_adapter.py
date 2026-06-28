from __future__ import annotations

import re
from typing import Any

from a2a.compat.v0_3.types import AgentCapabilities, AgentCard as SDKAgentCard, AgentSkill

from risk_agent_platform.schemas import AgentCard


def to_sdk_agent_card(card: AgentCard, *, base_url: str = "http://localhost") -> SDKAgentCard:
    base_url = base_url.rstrip("/")
    return SDKAgentCard(
        name=card.name,
        description=card.description,
        version=card.version,
        url=f"{base_url}{card.endpoints.get('a2a', '/a2a')}",
        preferredTransport="HTTP+JSON",
        protocolVersion="0.3.0",
        defaultInputModes=["application/json"],
        defaultOutputModes=["application/json"],
        capabilities=AgentCapabilities(
            streaming=False,
            pushNotifications=False,
            stateTransitionHistory=True,
        ),
        skills=[
            AgentSkill(
                id=_skill_id(skill),
                name=skill,
                description=f"{card.name} capability: {skill}",
                tags=[skill, *card.modes],
                inputModes=["application/json"],
                outputModes=["application/json"],
            )
            for skill in card.skills
        ],
    )


def sdk_agent_card_dict(card: AgentCard, *, base_url: str = "http://localhost") -> dict[str, Any]:
    sdk_card = to_sdk_agent_card(card, base_url=base_url)
    return sdk_card.model_dump(mode="json", by_alias=True, exclude_none=True)


def _skill_id(skill: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", skill.strip().lower()).strip("-")
    return slug or "skill"
