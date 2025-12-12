# Architecture Overview

The **Incident Desk Copilot** is a multimodal, multi-agent incident assistant that takes English **text**, optional **voice (transcribed to text)**, and **screenshots**, then uses Gemini + MCP tools (e.g., Jira) to:

- understand and structure production incidents,
- retrieve similar past incidents from persistent memory,
- propose next actions,
- create/update tickets in external systems,
- and support follow-up questions with both short-term and long-term memory (ChatGPT-style).

---

## Components

### 1. User Interface

**Form factor:** Minimal web UI + simple HTTP API (FastAPI).

- **Web UI**
  - Single-page view with:
    - Text area for incident description.
    - File upload for screenshots (PNG/JPG).
    - (Option slot for audio upload, even if we demo mostly text.)
    - A “Send” button that POSTs to `/api/incident`.
  - Displays, in separate panels:
    - Normalized incident description.
    - Structured incident fields (service, severity, impact, etc.).
    - Similar past incidents (from persistent memory).
    - Proposed actions & owner team.
    - Created Jira ticket key + link.
    - A small timeline of agent steps executed (for demo transparency).

- **HTTP API (FastAPI)**
  - `POST /api/incident`
    - Input: `conversation_id`, `text`, optional `image`, optional `audio`.
    - Output: JSON containing:
      - `reply_text` (what the agent tells the user),
      - `incident` (structured object, if created),
      - `similar_incidents`,
      - `ticket_info` (issue key, URL),
      - `steps_executed` (for observability in the UI).
  - This API is what the UI (and tests) talk to.

*(CLI debugging is possible, but the primary demo surface is the web UI.)*

---

### 2. Agent Core

The Agent Core lives under `src/` and is composed of **Planner**, **Executor**, and **Memory**, plus a set of specialized agents.

#### 2.1 Planner

**Role:** Decide *what* needs to happen, in *what order*, given:

- Current user request (English text),
- Conversation state (short-term memory),
- Whether an image was uploaded.

**Responsibilities:**

- Classify the user’s intent for each turn, e.g.:
  - `new_incident` – describe a fresh problem.
  - `add_comment` – add a comment to the current incident’s ticket.
  - `ask_summary` – “what did we decide for this incident?”
  - `query_past` – ask about similar past incidents.
- For a `new_incident`, assemble a **multi-step plan**, e.g.:

  1. `INGESTION` – normalize user description.
  2. `VISION_ANALYSIS` – if screenshot is present, extract error hints.
  3. `INCIDENT_CLASSIFICATION` – produce structured `Incident` object.
  4. `MEMORY_RETRIEVAL` – retrieve similar past incidents from long-term store.
  5. `PLAYBOOK` – propose causes and next actions.
  6. `TICKET_CREATE` – create a Jira ticket via MCP tool.
  7. `MEMORY_WRITE` – store this incident + ticket into persistent memory.

- For follow-up intents, produce smaller plans, e.g.:
  - `add_comment` → `COMMENT_DRAFT` → `JIRA_ADD_COMMENT`.

**Implementation style:**

- A `Planner` class in `planner.py` returning a `Plan` object (list of `PlanStep`s).
- Uses Gemini once to classify intent and decide which steps to include.

#### 2.2 Executor

**Role:** Actually run the plan: call LLMs, agents, and tools in sequence, passing intermediate results along.

**Responsibilities:**

- Iterate over `PlanStep`s and:
  - Call the correct **agent function** (e.g., ingestion, vision, incident classifier).
  - Call **tools** via an MCP client (e.g., Jira, logs search).
- Maintain a `context` dictionary of intermediate artifacts:
  - `normalized_description`
  - `vision_hints`
  - `incident` object
  - `similar_incidents`
  - `playbook_output`
  - `ticket_info` (issue key, URL)
- Update **short-term memory** (`ConversationState`) at the end of execution:
  - `current_incident`,
  - `current_issue_key`, `current_issue_url`,
  - `recent_messages`, `last_tools_used`.

**Location:**

- Implemented as `Executor` class in `executor.py`.

#### 2.3 Memory

The Memory subsystem is responsible for both **short-term conversation context** and **persistent, semantic long-term memory**, similar to how ChatGPT remembers both current and past threads.

**Short-Term Memory (per conversation):**

- **ConversationState** (in-memory + persisted per `conversation_id`):
  - `conversation_id`
  - `current_incident` (structured object)
  - `current_issue_key`, `current_issue_url`
  - `recent_messages` (last few user/agent turns)
  - `last_tools_used`
- Stored and restored from disk as JSON under `data/conversations/`.
- Used so follow-up questions like “also add a comment…” or “what did we decide?” work naturally.

**Long-Term Memory (global, persistent incident knowledge):**

- Stored in `data/incidents.json` as a list of **MemoryEntry** records, each containing:
  - Stable `id` (e.g., `INC-0004`),
  - `jira_issue_key`,
  - `title`, `summary`, `service`, `components`,
  - Optional `root_cause` and `fix`,
  - `tags`,
  - `created_at`, `resolved_at`,
  - **Embedding**: semantic vector from Gemini for this incident.
- On every new incident, a **Memory Agent**:
  - Summarizes the incident,
  - Calls Gemini embeddings,
  - Appends a new record to this store.

**Semantic Retrieval:**

- For a new incident:
  - Construct a query text from its summary + service + components.
  - Embed this text with Gemini.
  - Compute cosine similarity vs stored embeddings in `incidents.json`.
  - Return top-N similar incidents to the Playbook agent.
- Enables cross-session recall:
  - User can ask: “Have we seen a similar booking-service 500 error before?”

**Location:**

- Implemented in `memory.py` + `agents/memory_agent.py`.

---

### 3. Tools / APIs

The agent uses several tools through a clean interface (MCP style) so that LLM calls and external side effects stay separate:

1. **Google Gemini API**
   - **Text model**:
     - Used by Planner (intent classification & planning),
     - Ingestion agent (normalize description),
     - Incident agent (classification & slot filling),
     - Playbook agent (causes + actions),
     - Ticket agent (ticket body and comments).
   - **Vision model**:
     - Used by Vision agent to parse screenshots (error dialogs, logs, dashboards).
   - **Embeddings**:
     - Used by Memory agent to embed incidents for long-term semantic retrieval.

2. **Jira Tool (via MCP-like wrapper)**
   - `create_issue(summary, description, severity, labels) -> { issue_key, url }`
   - `add_comment(issue_key, comment) -> { success: bool }`
   - Called by Ticket agent for:
     - Creating the initial incident ticket,
     - Adding follow-up comments from the user.

3. **Log Search Tool (external API, real or mocked)**
   - `search_logs(service_name, query, time_range) -> snippets[]`
   - Optionally used by Playbook agent:
     - e.g., for backend incidents, the plan can include a log search step and then incorporate Snippets into diagnosis.

4. **Storage / Filesystem**
   - On-disk JSON files for:
     - `data/incidents.json` (long-term memory),
     - `data/conversations/<conversation_id>.json` (short-term memory).
   - Image uploads stored in temp files or memory for Vision model calls.

---

### 4. Observability

**Logging of each reasoning step:**

- For each request, the Executor logs:
  - `conversation_id`,
  - the generated `Plan` (list of steps),
  - each `PlanStep` execution:
    - step name,
    - which agent/tool was called,
    - whether it succeeded or failed.
- Logs can be printed to stdout (for demo) and optionally written to `logs/agent.log`.

**Agent-level introspection:**

- The response sent back to the UI includes a `steps_executed` list, so the UI can render a “timeline” of what the agent did:
  - e.g., `["INGESTION", "VISION_ANALYSIS", "INCIDENT_CLASSIFICATION", "MEMORY_RETRIEVAL", "PLAYBOOK", "TICKET_CREATE", "MEMORY_WRITE"]`.

**Error handling & retries:**

- For LLM calls:
  - Basic retry with backoff on transient errors (network timeouts, 5xx).
- For tool calls (Jira/logs):
  - If Jira creation fails:
    - Agent still returns a full incident summary + recommended actions,
    - And surfaces an error message (e.g., “Ticket creation failed, please check Jira credentials.”)
  - If logs tool fails:
    - Playbook falls back to reasoning without logs and marks that logs were unavailable.
- All critical failures are logged, and the user always gets a graceful English explanation instead of a crash.
