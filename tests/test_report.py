import csv
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import ghl_report as gr  # noqa: E402
import mock_ghl as mock  # noqa: E402


def client(token=mock.TOKEN, location=mock.LOCATION):
    return gr.GhlClient(token, location, transport=mock.transport(), sleep=lambda s: None)


def test_pagination_collects_all_45_workflows():
    assert len(client().workflows()) == 45


def test_report_has_one_row_per_email_step():
    report = gr.build_report(client())
    assert report.workflows == 45
    assert report.steps == 90
    assert len(report.rows) == 90
    assert report.errors == []


def test_stats_use_source_id_not_campaign_id():
    report = gr.build_report(client())
    assert {r.stats_source_id for r in report.rows} == {w["sourceId"] for w in mock.WORKFLOWS}


def test_email_campaign_fallback_to_campaign_id():
    report = gr.build_report(client(), include_email_campaigns=True)
    extra = [r for r in report.rows if r.workflow == "(one-time send)"]
    assert len(extra) == 1 and extra[0].stats_source_id == "ec001"


def test_rates_computed_when_api_omits_them():
    counts, rates = gr.normalize_stats({"delivered": 200, "opened": 50, "clicked": 10, "permanentFail": 4,
                                        "temporaryFail": 1, "accepted": 0})
    assert counts["sent"] == 205
    assert rates["openRate"] == 25.0
    assert rates["clickRate"] == 5.0
    assert rates["bounceRate"] == pytest.approx(2.44, abs=0.01)


def test_rates_from_api_are_kept():
    _, rates = gr.normalize_stats({"delivered": 200, "opened": 50, "openRate": 45.0})
    assert rates["openRate"] == 45.0


def test_wrong_token_is_reported_not_crashed():
    with pytest.raises(httpx.HTTPStatusError):
        client(token="bad").workflows()


def test_csv_has_header_and_rows(tmp_path):
    out = tmp_path / "r.csv"
    gr.write_csv(gr.build_report(client()), str(out))
    rows = list(csv.reader(open(out, encoding="utf-8")))
    assert rows[0] == list(gr.COLUMNS)
    assert len(rows) == 91
    assert rows[1][0] == "Workflow 1" and rows[1][1] == "Welcome email"


def test_cli_end_to_end(tmp_path, monkeypatch, capsys):
    out = tmp_path / "cli.csv"
    real = gr.GhlClient

    class MockedClient(real):
        def __init__(self, token, location, **kw):
            super().__init__(token, location, transport=mock.transport(), sleep=lambda s: None)

    monkeypatch.setattr(gr, "GhlClient", MockedClient)
    code = gr.main(["--token", mock.TOKEN, "--location", mock.LOCATION, "--out", str(out)])
    assert code == 0
    assert "rows: 90" in capsys.readouterr().out
