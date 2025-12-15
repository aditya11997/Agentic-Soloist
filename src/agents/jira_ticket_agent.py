from __future__ import annotations

from typing import Any, AsyncGenerator, Dict

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from src.tools.jira_client import create_jira_issue, JiraError


def _as_text(x: Any) -> str:
    return str(x or "").strip()


class JiraTicketAgent(BaseAgent):
    """
    Creates a REAL Jira ticket and stores it into:
      - ctx.session.state["ticket"]
      - ctx.session.state["executor_context"]["ticket"]
    """

    def __init__(self):
        super().__init__(name="jira_ticket_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        exec_ctx: Dict[str, Any] = ctx.session.state.get("executor_context", {}) or {}

        incident = ctx.session.state.get("incident") or exec_ctx.get("incident") or {}
        playbook = exec_ctx.get("playbook") or {}

        title = _as_text(incident.get("title")) or f"Incident: {_as_text(incident.get('service')) or 'unknown'}"
        severity = _as_text(incident.get("severity")) or "P?"
        service = _as_text(incident.get("service")) or "unknown"
        components = incident.get("components") or []

        # Compose a compact Jira description (demo-friendly)
        desc_lines = []
        desc_lines.append(f"Severity: {severity}")
        desc_lines.append(f"Service: {service}")
        if components:
            desc_lines.append(f"Components: {', '.join(map(str, components))}")
        nd = _as_text(incident.get("normalized_description"))
        if nd:
            desc_lines.append("")
            desc_lines.append("Summary:")
            desc_lines.append(nd)

        causes = playbook.get("suspected_causes") or []
        actions = playbook.get("recommended_actions") or []

        if causes:
            desc_lines.append("")
            desc_lines.append("Likely causes:")
            for c in causes[:5]:
                desc_lines.append(f"- {c}")

        if actions:
            desc_lines.append("")
            desc_lines.append("Recommended actions:")
            for a in actions[:7]:
                desc_lines.append(f"- {a}")

        description = "\n".join(desc_lines).strip()

        # Optional: map P0/P1 -> Jira priority names (adjust later if your Jira uses different names)
        priority = None
        sev_upper = severity.upper()
        if "P0" in sev_upper:
            priority = "Highest"
        elif "P1" in sev_upper:
            priority = "High"

        labels = ["incident-copilot", f"sev-{severity.lower()}".replace("?", "unknown")]

        try:
            ticket = create_jira_issue(
                summary=title[:250],
                description=description,
                priority_name=priority,
                labels=labels,
            )
        except JiraError as e:
            # Do NOT crash the run — keep pipeline alive.
            err = _as_text(e)
            ctx.session.state["ticket_error"] = err
            yield Event(
                author="jira_ticket_agent",
                content={"parts": [{"text": f"Ticket creation failed (Jira). Continuing without ticket. Error: {err}"}]},
            )
            return

        # Save to state (so final agent can show it)
        ctx.session.state["ticket"] = ticket
        exec_ctx["ticket"] = ticket
        ctx.session.state["executor_context"] = exec_ctx

        yield Event(
            author="jira_ticket_agent",
            content={"parts": [{"text": f"Ticket created in Jira: {ticket.get('key')} — {ticket.get('url')}"}]},
        )


jira_ticket_agent = JiraTicketAgent()
