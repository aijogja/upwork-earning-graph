# upworkapi/services/tenant.py
from __future__ import annotations

import requests

UPWORK_GQL_URL = "https://api.upwork.com/graphql"


def get_tenant_id(access_token: str) -> str | None:
    query = """
    query {
      companySelector {
        items {
          title
          organizationId
        }
      }
    }
    """
    resp = requests.post(
        UPWORK_GQL_URL,
        headers={
            "Authorization": f"bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"query": query},
        timeout=30,
    )

    try:
        payload = resp.json()
    except Exception:
        return None

    items = (((payload.get("data") or {}).get("companySelector") or {}).get("items")) or []
    if not items:
        return None

    org_id = items[0].get("organizationId")
    return str(org_id) if org_id else None
