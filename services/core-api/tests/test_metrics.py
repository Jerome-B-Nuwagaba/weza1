"""Operational metrics (TSD §64-65): /metrics is closed by default, token-protected, and carries no personal data."""

import uuid

from weza.config import get_settings
from weza.platform import metrics


def test_metrics_do_not_exist_until_a_token_is_configured(client):
    assert client.get("/metrics").status_code == 404


def test_a_wrong_or_missing_token_is_refused(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "scrape-token-for-tests")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_the_scrape_carries_health_queues_and_business_telemetry(client, as_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "scrape-token-for-tests")
    manager = as_user("manager@lakeside.demo")
    unknown = uuid.uuid4()
    client.get(f"/api/v1/inst/opportunities/{unknown}", headers=manager)  # a 404 on a route that has an ID in its path
    body = client.get("/metrics", headers={"Authorization": "Bearer scrape-token-for-tests"})
    assert body.status_code == 200 and body.headers["content-type"].startswith("text/plain")
    text = body.text
    for expected in ("weza_http_request_seconds_count", "weza_http_request_seconds_bucket", "weza_outbox_deliveries",
                     'weza_outbox_deliveries{status="PENDING"}', "weza_outbox_oldest_pending_seconds",
                     "weza_whatsapp_inbox_pending", "weza_journeys_overdue", "weza_notifications_24h",
                     "weza_ai_calls_1h", "weza_opportunities_24h", "weza_consents_granted_24h",
                     'weza_dependency_up{dependency="database"} 1'):
        assert expected in text, expected
    assert 'status="4xx"' in text  # errors are visible by class
    # labels are route TEMPLATES: the raw ID in the URL never appears, nor does anything personal
    assert str(unknown) not in text and "{opp_id}" in text
    assert "+256" not in text and "@" not in text


def test_timers_and_counters_accumulate_and_render():
    metrics.reset()

    @metrics.timed("weza_matching_seconds")
    def work():
        return 7

    assert work() == 7 and work() == 7
    metrics.count("consent", "granted")
    out = metrics.render(None)
    assert "weza_matching_seconds_count 2" in out and 'weza_events_total{name="consent",outcome="granted"} 1' in out
    assert "# database gauges" not in out  # no database was given, so no database gauges are claimed
