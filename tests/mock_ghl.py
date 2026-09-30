"""In-memory imitation of the HighLevel Email API v3 for tests (httpx.MockTransport)."""
from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx

LOCATION = "loc_test"
TOKEN = "pit-test-token"

# 45 workflows so pagination (limit 20) needs three pages; each has 2 email steps.
WORKFLOWS = [
    {"id": f"wf{i:03d}", "name": f"Workflow {i}", "status": "published", "source": "workflow",
     "sourceId": f"src-{i:03d}", "deleted": False}
    for i in range(1, 46)
]
STEPS = {
    wf["id"]: [
        {"id": f"{wf['id']}-s1", "name": "Welcome email", "subject": f"Welcome from {wf['name']}",
         "fromName": "Clinic", "fromEmail": "hello@clinic.test"},
        {"id": f"{wf['id']}-s2", "name": "Follow-up after 3 days", "subject": "Quick follow-up",
         "fromName": "Clinic", "fromEmail": "hello@clinic.test"},
    ]
    for wf in WORKFLOWS
}
EMAIL_CAMPAIGNS = [
    {"id": "ec001", "name": "February Newsletter", "status": "sent", "sourceId": "bulkRequest_ec001"},
]


def stats_for(step_id: str) -> dict:
    n = sum(ord(c) for c in step_id) % 7  # deterministic variety
    delivered = 1000 + n * 10
    return {
        "sent": delivered + 20, "accepted": 5, "delivered": delivered, "opened": 300 + n, "clicked": 40 + n,
        "unsubscribed": 3, "complained": 1, "permanentFail": 15, "temporaryFail": 5, "rejected": 2,
        "failed": 1, "replied": 7,
        # rates intentionally omitted for some steps so the client computes them
        **({"openRate": round(100 * (300 + n) / delivered, 2)} if n % 2 else {}),
    }


def handler(request: httpx.Request) -> httpx.Response:
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        return httpx.Response(401, json={"message": "Unauthorized"})
    if request.headers.get("Version") != "v3":
        return httpx.Response(400, json={"message": "Version header must be v3"})
    path = request.url.path
    qs = parse_qs(request.url.query.decode())
    prefix = f"/emails/locations/{LOCATION}/campaigns"
    if not path.startswith(prefix):
        return httpx.Response(404, json={"message": "not found"})
    rest = path[len(prefix):]

    if rest == "/workflows":
        limit, offset = int(qs.get("limit", [10])[0]), int(qs.get("offset", [0])[0])
        items = [w for w in WORKFLOWS if w["status"] == qs.get("status", ["published"])[0]]
        return httpx.Response(200, json={"campaigns": items[offset:offset + limit], "total": len(items)})
    if rest.startswith("/workflows/"):
        wid = rest.split("/")[2]
        wf = next((w for w in WORKFLOWS if w["id"] == wid), None)
        if not wf:
            return httpx.Response(404, json={"message": "workflow not found"})
        return httpx.Response(200, json={**wf, "subSources": STEPS[wid]})
    if rest == "/emails":
        return httpx.Response(200, json={"campaigns": EMAIL_CAMPAIGNS, "total": len(EMAIL_CAMPAIGNS)})
    if rest.startswith("/stats/workflow-campaigns/"):
        sid = rest.split("/")[3]
        # the real API wants the workflow's sourceId, not the campaign id
        wf = next((w for w in WORKFLOWS if w["sourceId"] == sid), None)
        if not wf:
            return httpx.Response(422, json={"message": "unknown source id"})
        sub = qs.get("subSourceId", [None])[0]
        if sub not in {s["id"] for s in STEPS[wf["id"]]}:
            return httpx.Response(422, json={"message": "unknown subSourceId"})
        return httpx.Response(200, json={"locationId": LOCATION, "source": "workflow-campaigns",
                                         "sourceId": sid, "subSourceId": sub, "stats": stats_for(sub)})
    if rest.startswith("/stats/email-campaigns/"):
        sid = rest.split("/")[3]
        camp = next((c for c in EMAIL_CAMPAIGNS if c["id"] == sid), None)  # this one accepts the campaign id
        if not camp:
            return httpx.Response(422, json={"message": "unknown source id"})
        return httpx.Response(200, json={"stats": stats_for(sid)})
    return httpx.Response(404, json={"message": "no route", "path": path})


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)
