# Incident Copilot (Google ADK)

An agentic incident response assistant that runs on **Google Agentic Development Kit (ADK)**. It ingests user text and screenshots, classifies the incident, retrieves similar past issues, proposes actions, and creates a Jira ticket.

## Setup
- Python 3.11+ and `pip`
- Create a virtual env (optional): `python -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install google-adk google-genai requests python-dotenv`
- Configure environment (e.g., in `.env`):
  - `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
  - Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, optional `JIRA_PROJECT_KEY`, `JIRA_ISSUE_TYPE`
  - Optional: `GITHUB_TOKEN`, `GITHUB_REPO` for code search tool

## Running the agent
```bash
cd /Users/aditya/Agentic-Soloist
adk web
```
Open the ADK UI, start a conversation, and provide an incident description (plus an image if available). The timeline will show each step executed.

## What it does (happy path)
1. Ingest message and optional screenshot.
2. Classify and structure the incident.
3. Retrieve similar past incidents from `data/incidents.json`.
4. Run code search/insight helpers (GitHub-based).
5. Generate suspected causes and recommended actions.
6. Create a Jira ticket via `src/tools/jira_client.py`.
7. Persist incident + ticket into memory and return a final summary.

## Notes
- Data artifacts live under `data/` (conversations, incidents, images).
- Jira creation is real; ensure env vars are set before running the TICKET_CREATE step.
- The ADK session state keeps short-term context; long-term memory is JSON-backed for demo simplicity.
