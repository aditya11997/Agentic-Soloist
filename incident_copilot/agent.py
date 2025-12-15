from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event
from google.genai import types

# Import your step agents (these should each expose an ADK Agent object)
from src.agents.vision_agent import vision_agent
from src.agents.incident_agent import incident_agent
from src.agents.playbook_agent import playbook_agent
from src.agents.jira_ticket_agent import jira_ticket_agent
from src.agents.memory_agent import memory_agent

from src.agents.code_search_agent import code_search_agent
from src.agents.code_insight_agent import code_insight_agent

from src.agents.final_agent import final_summary_agent

from src.agents.code_search_agent import code_search_agent

# Import your stores (capabilities)
from src.tools.memory import ConversationStore, IncidentMemoryStore


DATA_DIR = "data"
IMAGES_DIR = os.path.join(DATA_DIR, "images")


@dataclass
class ExecutorContext:
    """
    This is the 'shared scratchpad' for the whole turn.
    We store it in ctx.session.state so all step-agents can read/write.
    """
    normalized_description: Optional[str] = None
    image_path: Optional[str] = None
    vision_hints: Optional[dict] = None
    incident: Optional[dict] = None
    similar_incidents: Optional[list] = None
    code_search: Optional[list] = None
    ticket: Optional[dict] = None

def _emit_status(ctx: InvocationContext, step: str, msg: str) -> Event:
    # Track steps executed for UI introspection
    timeline = ctx.session.state.get("timeline", [])
    if not isinstance(timeline, list):
        timeline = []
    if step not in timeline:
        timeline.append(step)
    ctx.session.state["timeline"] = timeline

    # Emit a small “thinking” event
    return Event(
        author="incident_copilot",
        content={"parts": [{"text": f"**{step}** — {msg}"}]},
    )

def _ensure_dirs() -> None:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "conversations"), exist_ok=True)
    # incidents.json should already exist, but this keeps startup robust.
    os.makedirs(DATA_DIR, exist_ok=True)


def _extract_text(user_content: Optional[types.Content]) -> str:
    if not user_content or not user_content.parts:
        return ""
    texts = []
    for p in user_content.parts:
        if getattr(p, "text", None):
            texts.append(p.text)
    return "\n".join(texts).strip()


def _maybe_save_image(user_content: Optional[types.Content], conversation_id: str) -> Optional[str]:
    """
    ADK user content can include image parts. If present, persist deterministically
    to data/images/<conversation_id>_<timestamp>.png and return that path.
    """
    if not user_content or not user_content.parts:
        return None

    for p in user_content.parts:
        inline = getattr(p, "inline_data", None)
        if inline and getattr(inline, "data", None):
            mime = getattr(inline, "mime_type", "image/png")
            ext = "png"
            if "jpeg" in mime or "jpg" in mime:
                ext = "jpg"

            ts = int(time.time())
            path = os.path.join(IMAGES_DIR, f"{conversation_id}_{ts}.{ext}")

            with open(path, "wb") as f:
                f.write(inline.data)

            return path

    return None


class IncidentCopilotOrchestrator(BaseAgent):
    """
    Custom ADK agent that orchestrates your workflow by running sub-agents
    and yielding their events. This is the cleanest way to get a full timeline
    in ADK Dev UI.
    """

    def __init__(self, name: str = "incident_copilot"):
        super().__init__(name=name)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        _ensure_dirs()

        ctx.session.state["timeline"] = []

        # ----------------------------
        # 1) Build initial executor context from the user's message
        # ----------------------------
        user_text = _extract_text(ctx.user_content)

        # Use ADK session_id as our conversation_id (stable per thread)
        conversation_id = getattr(ctx.session, "id", "unknown_session")

        image_path = _maybe_save_image(ctx.user_content, conversation_id)

        exec_ctx = ExecutorContext(
            normalized_description=user_text,
            image_path=image_path,
        )

        yield _emit_status(ctx, "INGESTION", "Reading your message and preparing context.")

        # --- FOLLOW-UP DETECTION ---
        state = ctx.session.state

        jira_key = (
            state.get("jira.issue_key")
            or (state.get("ticket") or {}).get("issue_key")
            or (state.get("ticket") or {}).get("key")
        )
        has_incident = bool(state.get("incident"))
        is_followup = bool(jira_key or has_incident)

        state["is_followup"] = is_followup
        state["jira.issue_key"] = jira_key  # normalize if present


        # Put it into ADK session state so every step-agent can access it
        ctx.session.state["executor_context"] = exec_ctx.__dict__

        # ----------------------------
        # 2) Load short-term + long-term stores (file-backed)
        # ----------------------------
        convo_store = ConversationStore(base_dir=os.path.join(DATA_DIR, "conversations"))
        incident_store = IncidentMemoryStore(path=os.path.join(DATA_DIR, "incidents.json"))

        # You can optionally mirror ADK state → your JSON stores
        # (keeps your own "data/" artifacts independent of ADK internals)
        convo_store.save(conversation_id, ctx.session.state)

        # ----------------------------
        # 3) Run steps in order, yielding events to ADK Dev UI timeline
        # ----------------------------
        # VISION (only if we actually saved an image)
        if image_path:
            yield _emit_status(ctx, "VISION_ANALYSIS", "Analyzing screenshot for error codes and signals.")
            async for event in vision_agent.run_async(ctx):
                yield event

        if not ctx.session.state.get("is_followup"):
            yield _emit_status(ctx, "INCIDENT_CLASSIFICATION", "Extracting structured incident fields (service, severity, components).")
            async for event in incident_agent.run_async(ctx):
                yield event
        else:
            yield _emit_status(ctx, "FOLLOW_UP_ROUTING", f"Follow-up detected for ticket {ctx.session.state.get('jira.issue_key') or '(unknown)'} — skipping incident classification.")


        # VISION (only if we actually saved an image)
        if image_path:
            yield _emit_status(ctx, "VISION_ANALYSIS", "Analyzing screenshot for error codes and signals.")
            async for event in vision_agent.run_async(ctx):
                yield event

        # CLASSIFICATION (skip for follow-ups)
        if not ctx.session.state.get("is_followup"):
            yield _emit_status(ctx, "INCIDENT_CLASSIFICATION", "Extracting structured incident fields (service, severity, components).")
            async for event in incident_agent.run_async(ctx):
                yield event
        else:
            yield _emit_status(
                ctx,
                "FOLLOW_UP_ROUTING",
                f"Follow-up detected for ticket {ctx.session.state.get('jira.issue_key') or '(unknown)'} — skipping incident classification."
            )

        # MEMORY_RETRIEVAL (find similar past incidents)
        yield _emit_status(ctx, "MEMORY_RETRIEVAL", "Searching past incidents for similarities.")
        async for event in memory_agent.run_async(ctx):
            yield event
        # MEMORY_RETRIEVAL (find similar past incidents)
        yield _emit_status(ctx, "MEMORY_RETRIEVAL", "Searching past incidents for similarities.")
        async for event in memory_agent.run_async(ctx):
            yield event

        # CODE_SEARCH (Step 4)
        async for event in code_search_agent.run_async(ctx):
            yield event

        # CODE_INSIGHT (Step 5)
        async for event in code_insight_agent.run_async(ctx):
            yield event


        # PLAYBOOK (actions, causes, debugging steps)
        yield _emit_status(ctx, "PLAYBOOK", "Generating likely causes and recommended actions.")
        async for event in playbook_agent.run_async(ctx):
            yield event

        # TICKET_CREATE (stub/Jira MCP)
        yield _emit_status(ctx, "TICKET_CREATE", "Creating an incident ticket (or using fallback).")
        async for event in jira_ticket_agent.run_async(ctx):
            yield event

        # MEMORY_WRITE (persist the incident into incidents.json + save convo state)
        # Your memory_agent can do this itself, but we also ensure persistence here.
        convo_store.save(conversation_id, ctx.session.state)

        # If your incident_agent stored the parsed JSON into state, persist it:
        incident_obj = ctx.session.state.get("incident")
        ticket_obj = ctx.session.state.get("ticket")

        if incident_obj and not ctx.session.state.get("incident_persisted"):
            incident_store.append_incident(
                incident=incident_obj,
                ticket=ticket_obj,
                conversation_id=conversation_id,
            )
            ctx.session.state["incident_persisted"] = True


        # Done — last yielded event from ticket/playbook/etc will be the visible reply.
        yield _emit_status(ctx, "FINAL_SUMMARY", "Preparing the final summary for you.")
        async for event in final_summary_agent.run_async(ctx):
            yield event



# ADK entrypoint variable name usually expected by adk web
root_agent = IncidentCopilotOrchestrator(name="incident_copilot")
