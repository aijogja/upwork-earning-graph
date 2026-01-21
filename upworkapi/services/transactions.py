# upworkapi/services/transactions.py
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from upwork.routers import reports

from upworkapi.utils import upwork_client

class UpworkGraphQLError(RuntimeError):
    pass


def _ymd(d: Union[str, date, datetime]) -> str:
    if isinstance(d, str):
        s = d.strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10].replace("-", "")
        return s
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    return d.strftime("%Y%m%d")


def fetch_fixed_price_transactions(
    *,
    token: Dict[str, Any],
    freelancer_reference: str,
    tenant_id: Optional[str] = None,
    start_date: Union[str, date, datetime],
    end_date: Union[str, date, datetime],
    debug: bool = False,
) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    client = upwork_client.get_client(token)
    if tenant_id:
        client.set_org_uid_header(tenant_id)
    router = reports.finance.billings.Gds(client)

    date_from = _ymd(start_date)
    date_to = _ymd(end_date)

    params_candidates = []
    base_params = [
        {"from": date_from, "to": date_to},
        {"from_date": date_from, "to_date": date_to},
        {"start_date": date_from, "end_date": date_to},
        {"begin_date": date_from, "end_date": date_to},
        {"date_from": date_from, "date_to": date_to},
        {},
    ]
    for params in base_params:
        with_format = dict(params)
        with_format["format"] = "json"
        params_candidates.append(with_format)
        params_candidates.append(params)

    payload = None
    last_error = None
    references = _candidate_references(
        token=token,
        tenant_id=tenant_id,
        freelancer_reference=freelancer_reference,
    )

    debug_info: Dict[str, Any] = {
        "references": references,
        "params_tried": [],
        "endpoint": "billings",
        "graphql_attempts": [],
        "ace_ids": [],
        "payload_top_keys": [],
        "row_count": 0,
        "sample_keys": [],
        "sample_row": {},
    }

    graphql_rows = _fetch_fixed_price_graphql(
        token=token,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        debug_info=debug_info if debug else None,
    )
    if graphql_rows is not None:
        nodes = graphql_rows
        payload = {"source": "graphql", "count": len(nodes)}
    else:
        payload = None
        for params in params_candidates:
            if debug:
                debug_info["params_tried"].append({"endpoint": "billings", **params})
            try:
                payload = router.get_by_freelancer(freelancer_reference, params)
            except Exception as exc:
                if isinstance(exc, ValueError):
                    payload = _fetch_finreports_raw(
                        token=token,
                        tenant_id=tenant_id,
                        freelancer_references=references,
                        params=params,
                        endpoint="billings",
                    )
                    if payload is not None and not _looks_like_error(payload):
                        break
                last_error = exc
                payload = None
            if payload is not None and not _looks_like_error(payload):
                break
            last_error = payload or last_error

    if debug and isinstance(payload, dict):
        debug_info["payload_top_keys"] = list(payload.keys())
        if "message" in payload:
            debug_info["payload_message"] = payload.get("message")
        if "error" in payload:
            debug_info["payload_error"] = payload.get("error")
        debug_info["payload"] = payload

    if payload is None or _looks_like_error(payload):
        err_text = None
        if isinstance(last_error, ValueError):
            err_text = (
                "Invalid JSON response from Upwork API. "
                "Check access token, tenant id, and reports permissions."
            )
        else:
            err_text = str(last_error or payload)
        if debug:
            debug_info["error"] = err_text
            return [], debug_info
        raise UpworkGraphQLError(err_text)

    nodes = nodes if graphql_rows is not None else _extract_rows(payload)
    if debug:
        debug_info["row_count"] = len(nodes)
        if nodes:
            debug_info["sample_keys"] = list(nodes[0].keys())
            debug_info["sample_row"] = nodes[0]

    out: List[Dict[str, Any]] = []
    for it in nodes:
        occurred_at = _normalize_date(
            it.get("dateTime")
            or it.get("createdDateTime")
            or it.get("date_time")
            or it.get("date")
            or it.get("timestamp")
            or ""
        )

        amt = 0.0
        cur = None
        amt_obj = it.get("amount") or it.get("amount_paid") or it.get("total") or {}
        try:
            if isinstance(amt_obj, dict) and "amount" in amt_obj:
                amt = float(amt_obj.get("amount") or 0)
                cur = amt_obj.get("currency")
            elif it.get("amountCents") is not None:
                amt = float(it.get("amountCents")) / 100.0
                cur = it.get("currency")
            elif isinstance(amt_obj, str):
                s = amt_obj.replace("$", "").replace(",", "").strip()
                amt = float(s or 0)
            elif isinstance(amt_obj, (int, float)):
                amt = float(amt_obj)
        except Exception:
            amt = 0.0

        if amt <= 0:
            continue

        client_name = _extract_client_name(it)

        if occurred_at and not _in_date_range(occurred_at, start_date, end_date):
            continue

        kind = it.get("type") or it.get("subtype") or it.get("category") or it.get("transaction_type")
        description = it.get("description") or it.get("memo") or it.get("note") or ""

        if _is_withdrawal(kind, description) or _is_hourly(kind, description):
            continue

        out.append({
            "occurred_at": occurred_at,
            "amount": amt,
            "currency": cur,
            "direction": it.get("direction"),
            "kind": kind,
            "description": description,
            "client_name": client_name,
            "contract_title": _get_nested(it, ("contract", "title")),
        })

    # filter fixed/bonus/milestone by keyword (boleh diubah nanti)
    KEYWORDS = ("fixed", "bonus", "milestone")
    filtered = []
    for r in out:
        text = f"{r.get('kind','')} {r.get('description','')}".lower()
        if any(k in text for k in KEYWORDS):
            filtered.append(r)

    result = out if (not filtered and out) else filtered
    if debug:
        return result, debug_info
    return result


def _looks_like_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("error") or payload.get("errors"):
        return True
    if payload.get("status") in {"error", "failed"}:
        return True
    if payload.get("code") and payload.get("message"):
        return True
    return False


def _fetch_finreports_raw(
    *,
    token: Dict[str, Any],
    tenant_id: Optional[str],
    freelancer_references: List[str],
    params: Dict[str, Any],
    endpoint: str,
) -> Optional[Dict[str, Any]]:
    access_token = token.get("access_token") or token.get("token")
    if not access_token:
        return None

    headers = {"Authorization": f"Bearer {access_token}"}
    if tenant_id:
        headers["X-Upwork-API-TenantId"] = str(tenant_id)

    bases = [
        "https://api.upwork.com/api",
        "https://api.upwork.com",
    ]

    last_error = None
    for base in bases:
        for ref in freelancer_references:
            url = f"{base}/finreports/v2/providers/{ref}/{endpoint}.json"
            req_headers = dict(headers)
            req_headers["Accept"] = "application/json"
            req_headers["User-Agent"] = "upwork-earning-graph/1.0"
            resp = requests.get(url, headers=req_headers, params=params, timeout=30)
            try:
                return resp.json()
            except Exception:
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"

    raise UpworkGraphQLError(f"Non-JSON response: {last_error}")


def _candidate_references(
    *,
    token: Dict[str, Any],
    tenant_id: Optional[str],
    freelancer_reference: str,
) -> List[str]:
    refs = [freelancer_reference]
    if freelancer_reference.startswith("~"):
        resolved = _resolve_provider_id(
            token=token,
            tenant_id=tenant_id,
            profile_key=freelancer_reference,
        )
        if resolved and resolved not in refs:
            refs.append(resolved)
    return refs


def _resolve_provider_id(
    *,
    token: Dict[str, Any],
    tenant_id: Optional[str],
    profile_key: str,
) -> Optional[str]:
    access_token = token.get("access_token") or token.get("token")
    if not access_token:
        return None

    url = f"https://api.upwork.com/api/profiles/v1/providers/{profile_key}.json"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if tenant_id:
        headers["X-Upwork-API-TenantId"] = str(tenant_id)

    resp = requests.get(url, headers=headers, timeout=30)
    try:
        payload = resp.json()
    except Exception:
        return None

    provider_id = _extract_numeric_id(payload)
    if provider_id:
        return str(provider_id)
    return None


def _extract_numeric_id(payload: Any) -> Optional[int]:
    if isinstance(payload, dict):
        for key in ("id", "profile_id", "profileId", "provider_id", "providerId"):
            val = payload.get(key)
            if isinstance(val, int):
                return val
            if isinstance(val, str) and val.isdigit():
                return int(val)
        for val in payload.values():
            found = _extract_numeric_id(val)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_numeric_id(item)
            if found is not None:
                return found
    return None


def _fetch_fixed_price_graphql(
    *,
    token: Dict[str, Any],
    tenant_id: Optional[str],
    start_date: Union[str, date, datetime],
    end_date: Union[str, date, datetime],
    debug_info: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    ace_ids = _graphql_accounting_entity_ids(token, tenant_id, debug_info)
    if not ace_ids:
        return None

    date_ranges = [
        {"rangeStart": _iso_start(start_date), "rangeEnd": _iso_end(end_date)},
    ]

    query = """
    query transactionHistory($transactionHistoryFilter: TransactionHistoryFilter) {
      transactionHistory(transactionHistoryFilter: $transactionHistoryFilter) {
        transactionDetail {
          transactionHistoryRow {
            transactionCreationDate
            description
            type
            accountingSubtype
            transactionAmount { rawValue currency displayValue }
            payment { rawValue currency displayValue }
            assignmentCompanyName
            assignmentAgencyName
            assignmentDeveloperName
          }
        }
      }
    }
    """

    for date_range in date_ranges:
        variables = {
            "transactionHistoryFilter": {
                "aceIds_any": ace_ids,
                "transactionDateTime_bt": date_range,
            }
        }
        payload = _graphql_execute(token, tenant_id, query, variables, debug_info, date_range)
        if payload is None:
            continue

        rows = (
            ((((payload.get("data") or {}).get("transactionHistory") or {}).get("transactionDetail") or {})
             .get("transactionHistoryRow") or [])
        )
        if not rows:
            continue

        out_rows: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            amt_obj = row.get("payment") or row.get("transactionAmount") or {}
            amt = 0.0
            cur = None
            try:
                if isinstance(amt_obj, dict):
                    amt = float(amt_obj.get("rawValue") or 0)
                    cur = amt_obj.get("currency")
            except Exception:
                amt = 0.0

            out_rows.append({
                "date": row.get("transactionCreationDate"),
                "occurred_at": row.get("transactionCreationDate"),
                "amount": amt,
                "currency": cur,
                "kind": row.get("type") or row.get("accountingSubtype"),
                "description": row.get("description") or "",
                "client_name": _assignment_name(row),
            })
        return out_rows

    return None


def _graphql_accounting_entity_ids(
    token: Dict[str, Any],
    tenant_id: Optional[str],
    debug_info: Optional[Dict[str, Any]],
) -> List[str]:
    query = """
    query accountingEntity {
      accountingEntity { id }
    }
    """
    payload = _graphql_execute(token, tenant_id, query, None, debug_info, None)
    if payload is None:
        return []
    entity = (payload.get("data") or {}).get("accountingEntity") or {}
    ace_id = entity.get("id") if isinstance(entity, dict) else None
    ace_ids = [str(ace_id)] if ace_id else []
    if debug_info is not None:
        debug_info["ace_ids"] = ace_ids
    return ace_ids


def _graphql_execute(
    token: Dict[str, Any],
    tenant_id: Optional[str],
    query: str,
    variables: Optional[Dict[str, Any]],
    debug_info: Optional[Dict[str, Any]],
    date_range: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    access_token = token.get("access_token") or token.get("token")
    if not access_token:
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "upwork-earning-graph/1.0",
    }
    if tenant_id:
        headers["X-Upwork-API-TenantId"] = str(tenant_id)

    resp = requests.post(
        "https://api.upwork.com/graphql",
        headers=headers,
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    try:
        payload = resp.json()
    except Exception:
        if debug_info is not None:
            debug_info.setdefault("graphql_attempts", []).append({
                "date_range": date_range,
                "variables": variables,
                "http_status": resp.status_code,
                "http_body": resp.text[:300],
            })
        return None
    if debug_info is not None:
        debug_info.setdefault("graphql_attempts", []).append({
            "date_range": date_range,
            "variables": variables,
            "http_status": resp.status_code,
            "errors": payload.get("errors"),
        })
    if payload.get("errors"):
        return None
    return payload


def _counterparty_name(inv: Dict[str, Any]) -> str:
    cp = (inv.get("counterpartyData") or {}).get("counterparty") or {}
    if isinstance(cp, dict) and cp.get("name"):
        return str(cp.get("name"))
    contractor = (inv.get("counterpartyData") or {}).get("contractor") or {}
    if isinstance(contractor, dict) and contractor.get("name"):
        return str(contractor.get("name"))
    return "Unknown"


def _assignment_name(row: Dict[str, Any]) -> str:
    for key in ("assignmentCompanyName", "assignmentAgencyName", "assignmentDeveloperName"):
        val = row.get(key)
        if val:
            return str(val)
    return "Unknown"


def _iso_start(value: Union[str, date, datetime]) -> str:
    d = _to_date(value)
    return d.strftime("%Y-%m-%dT00:00:00Z")


def _iso_end(value: Union[str, date, datetime]) -> str:
    d = _to_date(value)
    return d.strftime("%Y-%m-%dT23:59:59Z")


def _extract_rows(payload: Any) -> List[Dict[str, Any]]:
    direct_keys = ("rows", "items", "data", "transactions", "entries")
    if isinstance(payload, dict):
        for key in direct_keys:
            val = payload.get(key)
            if isinstance(val, list) and all(isinstance(x, dict) for x in val):
                return val
        table = payload.get("table")
        if isinstance(table, dict):
            for key in direct_keys:
                val = table.get(key)
                if isinstance(val, list) and all(isinstance(x, dict) for x in val):
                    return val

    candidates: List[List[Dict[str, Any]]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            if obj and all(isinstance(x, dict) for x in obj):
                candidates.append(obj)
            for x in obj:
                walk(x)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)

    walk(payload)

    if not candidates:
        return []

    expected = {"amount", "amount_paid", "total", "date", "description", "memo", "type", "subtype"}

    def score(rows: List[Dict[str, Any]]) -> int:
        keys: set[str] = set()
        for r in rows[:10]:
            keys.update(k for k in r.keys() if isinstance(k, str))
        return sum(1 for k in expected if k in keys)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def _get_nested(data: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _extract_client_name(item: Dict[str, Any]) -> str:
    for key in ("client_name", "client", "buyer", "organization", "company", "team"):
        val = item.get(key)
        if isinstance(val, dict):
            for sub in ("name", "team_name", "company_name"):
                subval = val.get(sub)
                if subval:
                    return str(subval).strip()
        elif val:
            return str(val).strip()

    for key in ("buyer_name", "client"):
        val = item.get(key)
        if val:
            return str(val).strip()

    desc = str(item.get("description") or item.get("memo") or "").strip()
    if not desc:
        return "Unknown"

    return desc.split("-")[0].strip() or "Unknown"


def _is_withdrawal(kind: Any, description: Any) -> bool:
    text = f"{kind or ''} {description or ''}".lower()
    return (
        "withdrawal" in text
        or "appayment" in text
        or "withdraw" in text
        or "payout" in text
        or "transfer" in text
        or "disbursement" in text
    )


def _is_hourly(kind: Any, description: Any) -> bool:
    text = f"{kind or ''} {description or ''}".lower()
    if "hourly" in text:
        return True
    if "hrs @" in text or "hr @" in text or "/hr" in text:
        return True
    return False


def _normalize_date(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    if len(s) >= 10 and s[4] == "/" and s[7] == "/":
        return s[:10].replace("/", "-")
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _in_date_range(value: str, start_date: Union[str, date, datetime], end_date: Union[str, date, datetime]) -> bool:
    try:
        d = datetime.strptime(_normalize_date(value), "%Y-%m-%d").date()
    except Exception:
        return True

    s = _to_date(start_date)
    e = _to_date(end_date)
    return s <= d <= e


def _to_date(value: Union[str, date, datetime]) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = _normalize_date(value)
    return datetime.strptime(s, "%Y-%m-%d").date()
