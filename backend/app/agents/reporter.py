"""Reporter agent.

The report is *assembled by the application* from verified rows; the model only
writes prose. Scores, rankings, evidence references and the supported/rejected
split come from the database, so the model cannot reorder accounts, invent a
number, or resurrect a claim the verifier rejected.

Rejected and contradicted claims are not silently dropped: they are listed as
*excluded conclusions* so a reader can see what the system refused to assert.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent, system_prompt
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.client import CallRecord
from app.models.enums import AgentType, ClaimStatus, RiskLevel
from app.models.workflow import Claim, Evidence, Investigation
from app.schemas.agent import (
    FinalReport,
    RecommendedAction,
    ReportAccountSection,
    ReportNarrative,
)

logger = get_logger(__name__)


@dataclass
class ReportBundle:
    report: FinalReport
    markdown: str
    payload: dict[str, Any]
    call_record: CallRecord | None = None


@dataclass
class AccountInput:
    """One investigated account, already filtered to verified material."""

    investigation: Investigation
    company_name: str
    external_id: str
    renewal_date: date | None
    monthly_recurring_revenue: float | None
    annual_contract_value: float | None
    claims: list[Claim]
    evidence: list[Evidence]


class ReporterAgent(BaseAgent):
    config = AgentConfig(
        agent_type=AgentType.REPORTER,
        role=(
            "Composes the executive report from verified conclusions only. Numbers, rankings and "
            "citations are supplied by the platform, not generated."
        ),
        allowed_tools=(),
        temperature=0.2,
        timeout_seconds=180.0,
        max_retries=2,
    )

    def output_schema_name(self) -> str:
        return ReportNarrative.__name__

    def compose(
        self,
        context: AgentRunContext,
        *,
        objective: str,
        accounts: list[AccountInput],
        parameters: dict[str, Any],
        stats: dict[str, Any],
    ) -> ReportBundle:
        settings = get_settings()
        with self.traced(context, "report_generation"):
            sections = [_build_section(account) for account in accounts]
            sections.sort(key=lambda section: section.risk_score, reverse=True)

            narrative, record = self.call_model(
                context,
                operation="report",
                system_prompt=_system_prompt(),
                user_prompt=_user_prompt(objective, sections, parameters, stats),
                output_model=ReportNarrative,
                payload={
                    "objective": objective,
                    "parameters": parameters,
                    "stats": stats,
                    "accounts": [
                        {
                            **section.model_dump(mode="json"),
                            "driver_keys": [
                                factor.get("factor", "") for factor in (account.investigation.risk_factors or [])
                            ],
                            "data_gaps": list(account.investigation.data_gaps or []),
                        }
                        for section, account in zip(sections, _reorder(accounts, sections), strict=False)
                    ],
                },
            )

            report = FinalReport(
                title=narrative.title,
                executive_summary=narrative.executive_summary,
                accounts=[
                    section.model_copy(
                        update={
                            "verified_conclusions": _with_narrative(
                                section, narrative.account_narratives.get(section.customer_external_id)
                            )
                        }
                    )
                    for section in sections
                ],
                portfolio_observations=narrative.portfolio_observations,
                unresolved_uncertainties=narrative.unresolved_uncertainties,
                methodology_notes=_methodology_notes(parameters, stats),
            )

            payload = {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "product": settings.product_name,
                "objective": objective,
                "parameters": parameters,
                "statistics": stats,
                "report": report.model_dump(mode="json"),
                "evidence_index": _evidence_index(accounts),
            }
            markdown = render_markdown(report, objective=objective, stats=stats, accounts=accounts)

            logger.info(
                "report composed",
                extra={"accounts": len(sections), "markdown_chars": len(markdown)},
            )
            return ReportBundle(report=report, markdown=markdown, payload=payload, call_record=record)


def _reorder(accounts: list[AccountInput], sections: list[ReportAccountSection]) -> list[AccountInput]:
    by_external = {account.external_id: account for account in accounts}
    return [by_external[section.customer_external_id] for section in sections]


def _build_section(account: AccountInput) -> ReportAccountSection:
    investigation = account.investigation
    supported = [claim for claim in account.claims if claim.status == ClaimStatus.SUPPORTED.value]
    partial = [claim for claim in account.claims if claim.status == ClaimStatus.PARTIALLY_SUPPORTED.value]
    rejected = [
        claim
        for claim in account.claims
        if claim.status in {ClaimStatus.UNSUPPORTED.value, ClaimStatus.CONTRADICTED.value}
    ]

    quantitative = [
        claim.final_text or claim.claim_text for claim in supported if claim.claim_type == "CALCULATED_METRIC"
    ]
    qualitative = [claim.final_text or claim.claim_text for claim in supported if claim.claim_type == "OBSERVED_FACT"]
    # Only fully supported claims become asserted conclusions.
    conclusions = [claim.final_text or claim.claim_text for claim in supported]

    # Partially supported claims are reported separately, in their qualified
    # form, so a reader gets the signal *and* its limits.
    qualified = [
        (claim.final_text or claim.claim_text)
        + (f" [{claim.verification_reason}]" if claim.verification_reason else "")
        for claim in partial
    ]

    excluded = [
        f"{claim.claim_text} — excluded ({claim.status}): "
        f"{claim.verification_reason or 'not supported by the cited evidence'}"
        for claim in rejected
    ]

    return ReportAccountSection(
        customer_external_id=account.external_id,
        company_name=account.company_name,
        risk_score=float(investigation.risk_score),
        risk_level=RiskLevel(investigation.risk_level),
        confidence=float(investigation.confidence),
        renewal_date=account.renewal_date,
        monthly_recurring_revenue=account.monthly_recurring_revenue,
        quantitative_indicators=quantitative[:20],
        qualitative_evidence=qualitative[:20],
        verified_conclusions=conclusions[:20],
        qualified_findings=qualified[:20],
        excluded_conclusions=excluded[:20],
        recommended_actions=[
            RecommendedAction.model_validate(action) for action in (investigation.recommended_actions or [])
        ][:10],
        evidence_references=sorted({evidence.reference for evidence in account.evidence})[:40],
        uncertainties=list(investigation.data_gaps or [])[:12],
    )


def _with_narrative(section: ReportAccountSection, narrative: str | None) -> list[str]:
    if not narrative:
        return section.verified_conclusions
    # The narrative is prose *about* verified material; it is appended, never
    # substituted for the verified conclusions themselves.
    return [*section.verified_conclusions, narrative][:20]


def _methodology_notes(parameters: dict[str, Any], stats: dict[str, Any]) -> list[str]:
    return [
        "Candidate accounts were selected by deterministic SQL on renewal date and tier — no model "
        "chose which accounts to look at.",
        "Risk scores come from a transparent weighted heuristic over usage, support, sentiment and "
        "billing signals. It is not a trained predictive model.",
        "Every factual statement in this report cites an evidence record and was verified "
        "independently of the agent that produced it.",
        f"{stats.get('rejected_claims', 0)} of {stats.get('total_claims', 0)} material claims were "
        "rejected or rewritten during verification and are listed as excluded conclusions.",
        f"Screening threshold: risk score >= {parameters.get('risk_threshold')}; renewal window: "
        f"{parameters.get('renewal_window_days')} days.",
    ]


def _evidence_index(accounts: list[AccountInput]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for account in accounts:
        for evidence in account.evidence:
            index.append(
                {
                    "reference": evidence.reference,
                    "customer_external_id": account.external_id,
                    "source_type": evidence.source_type,
                    "source_id": evidence.source_id,
                    "source_date": evidence.source_date.isoformat() if evidence.source_date else None,
                    "title": evidence.title,
                    "relevance_score": (
                        float(evidence.relevance_score) if evidence.relevance_score is not None else None
                    ),
                    "content": evidence.content,
                }
            )
    return index


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #


def render_markdown(
    report: FinalReport,
    *,
    objective: str,
    stats: dict[str, Any],
    accounts: list[AccountInput],
) -> str:
    settings = get_settings()
    evidence_by_reference: dict[str, Evidence] = {
        evidence.reference: evidence for account in accounts for evidence in account.evidence
    }
    lines: list[str] = [
        f"# {report.title}",
        "",
        f"*Generated by {settings.product_name} on {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "## Objective",
        "",
        f"> {objective}",
        "",
        "## Executive summary",
        "",
        report.executive_summary,
        "",
    ]

    if report.accounts:
        lines += [
            "## Ranked at-risk accounts",
            "",
            "| # | Account | Risk score | Level | Confidence | Renewal | MRR |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for index, section in enumerate(report.accounts, start=1):
            mrr = f"${section.monthly_recurring_revenue:,.0f}" if section.monthly_recurring_revenue else "—"
            lines.append(
                f"| {index} | {section.company_name} ({section.customer_external_id}) | "
                f"{section.risk_score:.1f} | {section.risk_level.value} | "
                f"{section.confidence:.0%} | {section.renewal_date or '—'} | {mrr} |"
            )
        lines.append("")

    for section in report.accounts:
        lines += [f"## {section.company_name} — {section.risk_level.value} ({section.risk_score:.1f}/100)", ""]
        if section.quantitative_indicators:
            lines += ["**Verified quantitative indicators**", ""]
            lines += [f"- {item}" for item in section.quantitative_indicators]
            lines.append("")
        if section.qualitative_evidence:
            lines += ["**Verified qualitative evidence**", ""]
            lines += [f"- {item}" for item in section.qualitative_evidence]
            lines.append("")
        if section.verified_conclusions:
            lines += ["**Verified conclusions**", ""]
            lines += [f"- {item}" for item in section.verified_conclusions]
            lines.append("")
        if section.qualified_findings:
            lines += [
                "**Qualified findings** (the evidence supports the direction, not the full wording)",
                "",
            ]
            lines += [f"- {item}" for item in section.qualified_findings]
            lines.append("")
        if section.excluded_conclusions:
            lines += [
                "**Excluded conclusions** (the evidence did not support these, so they are not asserted)",
                "",
            ]
            lines += [f"- {item}" for item in section.excluded_conclusions]
            lines.append("")
        if section.recommended_actions:
            lines += ["**Recommended interventions**", ""]
            for action in section.recommended_actions:
                lines.append(
                    f"- `{action.action_type.value}` (priority {action.priority}): {action.description}"
                    + (f" — {action.rationale}" if action.rationale else "")
                )
            lines.append("")
        if section.uncertainties:
            lines += ["**Open uncertainties**", ""]
            lines += [f"- {item}" for item in section.uncertainties]
            lines.append("")
        if section.evidence_references:
            lines += [
                "**Evidence**: " + ", ".join(f"`{reference}`" for reference in section.evidence_references),
                "",
            ]

    if report.portfolio_observations:
        lines += ["## Portfolio observations", ""]
        lines += [f"- {item}" for item in report.portfolio_observations]
        lines.append("")

    if report.unresolved_uncertainties:
        lines += ["## Unresolved uncertainties", ""]
        lines += [f"- {item}" for item in report.unresolved_uncertainties]
        lines.append("")

    lines += ["## Methodology", ""]
    lines += [f"- {note}" for note in report.methodology_notes]
    lines.append("")

    if evidence_by_reference:
        lines += ["## Evidence appendix", ""]
        for reference in sorted(evidence_by_reference, key=lambda ref: (len(ref), ref)):
            evidence = evidence_by_reference[reference]
            relevance = (
                f" · relevance {float(evidence.relevance_score):.2f}" if evidence.relevance_score is not None else ""
            )
            lines += [
                f"**`{reference}`** — {evidence.source_type} · {evidence.source_date or 'date unknown'}{relevance}",
                "",
                f"> {evidence.content.strip()[:1200]}",
                "",
            ]

    return "\n".join(lines)


def _system_prompt() -> str:
    return system_prompt(
        "Your role: REPORTER.\n\n"
        "You write the prose of an executive report for a revenue leader. You are given ONLY "
        "verified material: every statement handed to you has already passed independent "
        "verification against evidence.\n\n"
        "You must not introduce any new fact, number, account, date or conclusion. You may "
        "summarise, prioritise and explain what you are given. Where accounts were excluded or "
        "data was missing, say so plainly — an honest report that names its gaps is the goal.\n\n"
        "Keep the executive summary to one tight paragraph that a CRO can act on. Account "
        "narratives are one to three sentences each, keyed by customer_external_id."
    )


def _user_prompt(
    objective: str,
    sections: list[ReportAccountSection],
    parameters: dict[str, Any],
    stats: dict[str, Any],
) -> str:
    if not sections:
        return (
            f"Objective:\n{objective}\n\n"
            f"Screening statistics: {stats}\n"
            f"Parameters: {parameters}\n\n"
            "No account crossed the configured risk threshold. Write a valid report that states "
            "this clearly, explains what was screened, and recommends no retention action. Return "
            "an empty account_narratives object."
        )

    blocks: list[str] = []
    for section in sections:
        blocks.append(
            f"ACCOUNT {section.customer_external_id} — {section.company_name}\n"
            f"risk_score={section.risk_score} level={section.risk_level.value} "
            f"confidence={section.confidence} renewal={section.renewal_date} "
            f"mrr={section.monthly_recurring_revenue}\n"
            "verified quantitative indicators:\n"
            + ("\n".join(f"  - {item}" for item in section.quantitative_indicators) or "  - (none)")
            + "\nverified qualitative evidence:\n"
            + ("\n".join(f"  - {item}" for item in section.qualitative_evidence) or "  - (none)")
            + "\nverified conclusions:\n"
            + ("\n".join(f"  - {item}" for item in section.verified_conclusions) or "  - (none)")
            + "\nqualified (support the direction only — always keep the qualifier):\n"
            + ("\n".join(f"  - {item}" for item in section.qualified_findings) or "  - (none)")
            + "\nexcluded (NOT supported — never assert these):\n"
            + ("\n".join(f"  - {item}" for item in section.excluded_conclusions) or "  - (none)")
            + "\nopen uncertainties:\n"
            + ("\n".join(f"  - {item}" for item in section.uncertainties) or "  - (none)")
        )

    return (
        f"Objective:\n{objective}\n\n"
        f"Parameters: {parameters}\n"
        f"Verification statistics: {stats}\n\n"
        f"{len(sections)} investigated account(s), already ranked by risk score:\n\n"
        + "\n\n====\n\n".join(blocks)
        + "\n\nReturn the ReportNarrative."
    )


def customer_key(investigation: Investigation) -> uuid.UUID:
    return investigation.customer_id
