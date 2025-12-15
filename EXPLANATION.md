# Technical Explanation

## Reasoning flow
1. **Ingestion:** The orchestrator reads user text/image, saves the image (if any), seeds `executor_context`, and emits a status event.
2. **Vision (conditional):** VisionAgent calls Gemini Vision to extract error hints from the screenshot and stores them in state.
3. **Incident classification:** IncidentAgent calls its LLM helper to produce structured JSON (service, severity, components, title, normalized_description); parsed JSON is written to session state.
4. **Memory retrieval:** MemoryAgent loads `data/incidents.json`, embeds the current incident, and returns similar incidents into state.
5. **Code search/insight:** CodeSearchAgent queries GitHub; CodeInsightAgent summarizes findings via Gemini text.
6. **Playbook:** PlaybookAgent uses Gemini text to suggest suspected causes and recommended actions (saved to `executor_context`).
7. **Ticketing:** JiraTicketAgent formats a compact description and calls `create_jira_issue`; on failure it records `ticket_error` and keeps the run alive.
8. **Final summary:** FinalSummaryAgent produces the closing response using all context in state.

## Memory usage
- **Short-term:** ADK `ctx.session.state` holds the working set (incident JSON, playbook, ticket, errors, timeline). Images are persisted under `data/images/` and referenced from state.
- **Long-term:** `IncidentMemoryStore` (JSON in `data/incidents.json`) appends each new incident and rehydrates similar incidents for retrieval. `ConversationStore` snapshots full session state under `data/conversations/` for replay/debug.

## Planning style
- The orchestrator imposes a fixed ordered pipeline (ingestion → vision → incident → memory → code search → code insight → playbook → ticket → final). Within each step, ADK agents can issue tool calls and stream partial outputs. Error handling is resilient: failures in non-critical tools (e.g., Jira) are captured but do not stop the run.

## Tool integration
- **Gemini text/vision/embeddings:** Used across incident parsing, playbook generation, vision analysis, and summarization.
- **GitHub search:** `src/tools/github_search.py` surfaces repository snippets for code-centric insight steps.
- **Jira:** `src/tools/jira_client.py` performs REST issue creation with auth from environment; wrapped by `JiraTicketAgent`.

## Known limitations
- No automated retries/backoff around external APIs.
- Jira priority mapping is simplistic (P0→Highest, P1→High).
- Memory store is JSON-based and in-memory loaded; not suitable for large-scale embedding search.
- No formal evaluation or unit tests; manual verification via ADK UI is required.
