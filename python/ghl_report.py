"""GoHighLevel workflow email stats -> CSV.

Pulls per-step email statistics for every published workflow in a sub-account (location)
through the HighLevel Email API v3 and writes one row per email step.

Endpoints (Version: v3, base https://services.leadconnectorhq.com):
  GET /emails/locations/{locationId}/campaigns/workflows?limit=20&offset=N&status=published
  GET /emails/locations/{locationId}/campaigns/workflows/{campaignId}          -> subSources (email steps)
  GET /emails/locations/{locationId}/campaigns/stats/workflow-campaigns/{sourceId}?subSourceId={stepId}
  GET /emails/locations/{locationId}/campaigns/emails?limit=20&offset=N&status=sent   (optional, one-time sends)
  GET /emails/locations/{locationId}/campaigns/stats/email-campaigns/{sourceId}

Scopes on the Private Integration token: emails/campaigns.readonly, emails/stats.readonly.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

import httpx

BASE_URL = "https://services.leadconnectorhq.com"
PAGE_SIZE = 20
COUNT_FIELDS = ("sent", "accepted", "delivered", "opened", "clicked", "replied", "unsubscribed",
                "complained", "permanentFail", "temporaryFail", "rejected", "failed")
RATE_FIELDS = ("openRate", "clickRate", "replyRate", "unsubscribeRate", "complaintRate", "bounceRate")
COLUMNS = ("Workflow", "Step", "Subject", "From", "Sent", "Accepted", "Delivered", "Opened", "Clicked",
           "Replied", "Unsubscribed", "Complained", "Hard bounces", "Soft bounces", "Rejected", "Failed",
           "Open rate %", "Click rate %", "Reply rate %", "Unsubscribe rate %", "Complaint rate %",
           "Bounce rate %", "Stats source id")


@dataclass
class Row:
    workflow: str
    step: str
    subject: str
    sender: str
    counts: dict
    rates: dict
    stats_source_id: str

    def as_list(self) -> list:
        c, r = self.counts, self.rates
        return [self.workflow, self.step, self.subject, self.sender,
                c["sent"], c["accepted"], c["delivered"], c["opened"], c["clicked"], c["replied"],
                c["unsubscribed"], c["complained"], c["permanentFail"], c["temporaryFail"], c["rejected"],
                c["failed"], r["openRate"], r["clickRate"], r["replyRate"], r["unsubscribeRate"],
                r["complaintRate"], r["bounceRate"], self.stats_source_id]


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    workflows: int = 0
    steps: int = 0


def normalize_stats(stats: dict) -> tuple[dict, dict]:
    """Fill every count with an int and every rate with a float; compute rates when the API omits them."""
    counts = {k: int(stats.get(k) or 0) for k in COUNT_FIELDS}
    if not counts["sent"]:
        counts["sent"] = counts["delivered"] + counts["accepted"] + counts["permanentFail"] + counts["temporaryFail"]
    delivered = counts["delivered"] or 0
    sent = counts["sent"] or 0

    def pct(num: int, den: int) -> float:
        return round(100.0 * num / den, 2) if den else 0.0

    computed = {
        "openRate": pct(counts["opened"], delivered),
        "clickRate": pct(counts["clicked"], delivered),
        "replyRate": pct(counts["replied"], delivered),
        "unsubscribeRate": pct(counts["unsubscribed"], delivered),
        "complaintRate": pct(counts["complained"], delivered),
        "bounceRate": pct(counts["permanentFail"] + counts["temporaryFail"], sent),
    }
    rates = {k: (round(float(stats[k]), 2) if stats.get(k) is not None else computed[k]) for k in RATE_FIELDS}
    return counts, rates


class GhlClient:
    def __init__(self, token: str, location_id: str, base_url: str = BASE_URL,
                 transport: httpx.BaseTransport | None = None, pause: float = 0.12,
                 sleep: Callable[[float], None] = time.sleep):
        self.location_id = location_id
        self.pause = pause
        self.sleep = sleep
        self.http = httpx.Client(base_url=base_url, transport=transport, timeout=30.0, headers={
            "Authorization": f"Bearer {token}",
            "Version": "v3",
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        resp = self.http.get(path, params=params)
        self.sleep(self.pause)  # stay well under 100 requests / 10 s
        return resp

    def _paged(self, path: str, params: dict) -> Iterable[dict]:
        offset = 0
        while True:
            resp = self._get(path, {**params, "limit": PAGE_SIZE, "offset": offset})
            resp.raise_for_status()
            data = resp.json()
            items = data.get("campaigns") or []
            yield from items
            offset += PAGE_SIZE
            if len(items) < PAGE_SIZE or offset >= int(data.get("total") or 0):
                break

    def workflows(self) -> list[dict]:
        return list(self._paged(f"/emails/locations/{self.location_id}/campaigns/workflows",
                                {"status": "published"}))

    def workflow(self, campaign_id: str) -> dict:
        resp = self._get(f"/emails/locations/{self.location_id}/campaigns/workflows/{campaign_id}")
        resp.raise_for_status()
        return resp.json()

    def email_campaigns(self) -> list[dict]:
        return list(self._paged(f"/emails/locations/{self.location_id}/campaigns/emails", {"status": "sent"}))

    def stats(self, source: str, candidates: list[str], sub_source_id: str | None = None) -> tuple[dict, str]:
        """Try each candidate id in order (the spec is not explicit whether stats want `sourceId` or `id`)."""
        last = None
        for cid in [c for c in candidates if c]:
            params = {"subSourceId": sub_source_id} if sub_source_id else None
            resp = self._get(f"/emails/locations/{self.location_id}/campaigns/stats/{source}/{cid}", params)
            if resp.status_code == 200:
                return (resp.json().get("stats") or {}), cid
            last = f"{resp.status_code} for {source}/{cid}"
            if resp.status_code in (401, 403):
                break
        raise RuntimeError(last or "no candidate ids")


def build_report(client: GhlClient, include_email_campaigns: bool = False) -> Report:
    report = Report()
    for wf in client.workflows():
        report.workflows += 1
        try:
            detail = client.workflow(wf["id"])
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"workflow {wf.get('name')} ({wf['id']}): {exc}")
            continue
        candidates = [detail.get("sourceId") or wf.get("sourceId"), wf["id"]]
        for step in detail.get("subSources") or []:
            report.steps += 1
            try:
                stats, used = client.stats("workflow-campaigns", candidates, step["id"])
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"step {step.get('name')} in {wf.get('name')}: {exc}")
                continue
            counts, rates = normalize_stats(stats)
            sender = " ".join(x for x in (step.get("fromName"), step.get("fromEmail")) if x)
            report.rows.append(Row(wf.get("name") or wf["id"], step.get("name") or step["id"],
                                   step.get("subject") or "", sender, counts, rates, used))
    if include_email_campaigns:
        for camp in client.email_campaigns():
            try:
                stats, used = client.stats("email-campaigns", [camp.get("sourceId"), camp["id"]])
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"email campaign {camp.get('name')}: {exc}")
                continue
            counts, rates = normalize_stats(stats)
            report.rows.append(Row("(one-time send)", camp.get("name") or camp["id"], "", "", counts, rates, used))
    return report


def write_csv(report: Report, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for row in report.rows:
            w.writerow(row.as_list())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="GoHighLevel workflow email stats -> CSV")
    p.add_argument("--token", required=True, help="Private Integration token (emails/campaigns.readonly + emails/stats.readonly)")
    p.add_argument("--location", required=True, help="Sub-account (location) ID")
    p.add_argument("--out", default="ghl-email-report.csv")
    p.add_argument("--include-email-campaigns", action="store_true", help="also add one-time sends")
    p.add_argument("--base-url", default=BASE_URL)
    args = p.parse_args(argv)
    client = GhlClient(args.token, args.location, base_url=args.base_url)
    report = build_report(client, args.include_email_campaigns)
    write_csv(report, args.out)
    print(f"workflows: {report.workflows}, email steps: {report.steps}, rows: {len(report.rows)}, errors: {len(report.errors)}")
    for err in report.errors:
        print("  !", err)
    print(f"written: {args.out}")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
