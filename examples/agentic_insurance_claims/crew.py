"""CrewAI crew definition for the insurance claims workflow."""

from __future__ import annotations

import os

from crew_tools import tools_for_adjuster, tools_for_fraud_analyst, tools_for_payout_agent

try:
    from crewai import Agent, Crew, Process, Task
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "crewai is required. Install with: pip install -r requirements.txt"
    ) from exc


def build_insurance_claims_crew() -> Crew:
    """Sequential crew: adjuster intake → fraud review → payout decision."""
    adjuster = Agent(
        role="Claims Adjuster",
        goal="Register valid claims with correct policy context",
        backstory=(
            "You intake auto claims. Use lookup_policy then record_claim_intake "
            "with the claim id, amount, and loss_type provided in the task."
        ),
        tools=tools_for_adjuster(),
        verbose=True,
        allow_delegation=False,
    )
    fraud_analyst = Agent(
        role="Fraud Analyst",
        goal="Flag suspicious claims for investigation",
        backstory="You review intake and add fraud flags when appropriate.",
        tools=tools_for_fraud_analyst(),
        verbose=True,
        allow_delegation=False,
    )
    payout_specialist = Agent(
        role="Payout Specialist",
        goal="Issue payouts only when policy allows",
        backstory="You issue claim payouts using issue_claim_payout.",
        tools=tools_for_payout_agent(),
        verbose=True,
        allow_delegation=False,
    )

    intake_task = Task(
        description=(
            "For policy POL-8812, record claim CLM-9001 with amount 12000 and "
            "loss_type auto_collision using your tools."
        ),
        expected_output="JSON confirming intake was recorded",
        agent=adjuster,
    )
    fraud_task = Task(
        description=(
            "Flag claim CLM-9001 for review with reason 'velocity check on new policy'."
        ),
        expected_output="JSON confirming fraud flag",
        agent=fraud_analyst,
    )
    payout_task = Task(
        description=(
            "Issue payout of 12000 on claim CLM-9001 using issue_claim_payout."
        ),
        expected_output="JSON payout confirmation or error",
        agent=payout_specialist,
    )

    return Crew(
        agents=[adjuster, fraud_analyst, payout_specialist],
        tasks=[intake_task, fraud_task, payout_task],
        process=Process.sequential,
        verbose=True,
    )


def kickoff_crew_if_configured() -> str | None:
    """Run the crew when OPENAI_API_KEY is set; otherwise return None."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    crew = build_insurance_claims_crew()
    result = crew.kickoff()
    return str(result)
