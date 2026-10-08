"""Agent registry.

Importing this package imports the tool modules first, so every agent's
declared tool allow-list can be validated against the real registry at
construction time.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent
from app.agents.data_agent import DataAgent
from app.agents.investigator import InvestigatorAgent
from app.agents.planner import PlannerAgent
from app.agents.reporter import ReporterAgent
from app.agents.retrieval_agent import RetrievalAgent
from app.agents.risk_agent import RiskAgent
from app.agents.verifier import VerifierAgent
from app.models.enums import AgentType
from app.tools import customer_tools as _customer_tools  # noqa: F401 - registers tools

AGENT_CLASSES: dict[AgentType, type[BaseAgent]] = {
    AgentType.PLANNER: PlannerAgent,
    AgentType.DATA: DataAgent,
    AgentType.RISK: RiskAgent,
    AgentType.RETRIEVAL: RetrievalAgent,
    AgentType.INVESTIGATOR: InvestigatorAgent,
    AgentType.VERIFIER: VerifierAgent,
    AgentType.REPORTER: ReporterAgent,
}


def describe_agents() -> list[dict[str, Any]]:
    """Agent cards for the API/UI — built from the real declarations."""
    return [AGENT_CLASSES[agent_type]().describe() for agent_type in AGENT_CLASSES]


__all__ = [
    "AGENT_CLASSES",
    "AgentConfig",
    "AgentRunContext",
    "BaseAgent",
    "DataAgent",
    "InvestigatorAgent",
    "PlannerAgent",
    "ReporterAgent",
    "RetrievalAgent",
    "RiskAgent",
    "VerifierAgent",
    "describe_agents",
]
