# Architecture

## High-level flow
```
User (text + optional image)
    ↓
ADK Web UI / Session
    ↓
IncidentCopilotOrchestrator (incident_copilot/agent.py)
    ├─ VisionAgent → Gemini Vision
    ├─ IncidentAgent → Gemini text (JSON incident)
    ├─ MemoryAgent → data/incidents.json (embedding/retrieval)
    ├─ CodeSearchAgent → GitHub Search tool
    ├─ CodeInsightAgent → Gemini text reasoning
    ├─ PlaybookAgent → Gemini text (causes/actions)
    ├─ JiraTicketAgent → src/tools/jira_client.py → Jira Cloud
    └─ FinalSummaryAgent → Gemini text
```

The orchestrator streams ADK `Event`s so the UI shows a timeline per step.

## Planner / executor / memory
- **Planner / executor:** Implemented by ADK’s async agent loop. `IncidentCopilotOrchestrator` decides the step order and delegates to specialized agents; each agent is a `BaseAgent` with `_run_async_impl`.
- **Short-term memory:** `ctx.session.state` stores the working context (incident JSON, playbook, ticket, errors) plus a `timeline` list for observability. Images are persisted under `data/images/` and referenced from state.
- **Long-term memory:** `src/tools/memory.py` provides `IncidentMemoryStore` backed by `data/incidents.json` and `ConversationStore` under `data/conversations/`. MemoryAgent reads/writes these stores and attaches results back into session state.

## Tool integrations
- **Gemini (text/vision/embeddings):** Used by Incident, Vision, CodeInsight, Playbook, and Final agents for reasoning and parsing. Keys pulled from `GEMINI_API_KEY` / `GOOGLE_API_KEY`.
- **GitHub search tool:** `src/tools/github_search.py` uses `GITHUB_TOKEN` + `GITHUB_REPO` to surface code snippets for code search/insight steps.
- **Jira client:** `src/tools/jira_client.py` performs authenticated REST calls to Jira Cloud (env: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, optional `JIRA_PROJECT_KEY`, `JIRA_ISSUE_TYPE`). Wrapped by `JiraTicketAgent`.
- **Local persistence:** JSON stores in `data/` hold incidents and conversation state for demo-friendly replayability.

## Logging and observability
- Each orchestrator step emits a status event via `_emit_status`, updating the `timeline` list in session state (visible in ADK UI).
- Agents stream their own `Event`s, so LLM/tool outputs are inspectable live.
- Persistent artifacts:
  - `data/conversations/` — full session state per conversation_id.
  - `data/incidents.json` — structured incidents + tickets (append-only).
- Errors in Jira ticket creation are captured in `ctx.session.state["ticket_error"]` without crashing the run.

## Files of interest
- Orchestrator: `incident_copilot/agent.py`
- Specialized agents: `src/agents/*.py`
- Jira client + ticket agent: `src/tools/jira_client.py`, `src/agents/jira_ticket_agent.py`
- Memory stores: `src/tools/memory.py`
