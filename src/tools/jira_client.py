from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


class JiraError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _jira_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def create_jira_issue(
    *,
    summary: str,
    description: str,
    project_key: Optional[str] = None,
    issue_type: Optional[str] = None,
    priority_name: Optional[str] = None,
    labels: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """
    Creates a Jira Cloud issue and returns: { key, url, id }.

    Required env vars:
      - JIRA_BASE_URL (e.g. https://aditya11997.atlassian.net)
      - JIRA_EMAIL
      - JIRA_API_TOKEN

    Optional env vars:
      - JIRA_PROJECT_KEY (default: KAN)
      - JIRA_ISSUE_TYPE  (default: Task)
    """
    base_url = _env("JIRA_BASE_URL")
    email = _env("JIRA_EMAIL")
    token = _env("JIRA_API_TOKEN")

    if not base_url or not email or not token:
        raise JiraError("Missing Jira env vars. Need JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.")

    project_key = project_key or _env("JIRA_PROJECT_KEY", "KAN")
    issue_type = issue_type or _env("JIRA_ISSUE_TYPE", "Task")

    payload: Dict[str, Any] = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            # Jira Cloud supports ADF for description; plain string works in many setups,
            # but ADF is safest.
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description[:5000]}],
                    }
                ],
            },
        }
    }

    if priority_name:
        payload["fields"]["priority"] = {"name": priority_name}

    if labels:
        payload["fields"]["labels"] = labels[:10]

    url = f"{base_url}/rest/api/3/issue"
    r = requests.post(
        url,
        headers=_jira_headers(),
        auth=(email, token),
        json=payload,
        timeout=30,
    )

    if r.status_code not in (200, 201):
        try:
            detail = r.json()
        except Exception:
            detail = {"raw": r.text}
        raise JiraError(f"Jira create issue failed ({r.status_code}): {detail}")

    data = r.json() or {}
    key = data.get("key")
    issue_id = data.get("id")
    browse_url = f"{base_url}/browse/{key}" if key else base_url

    return {"key": key, "id": issue_id, "url": browse_url}
