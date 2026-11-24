"""The monitoring kit stays in sync with what the platform and scripts emit."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
OBS = ROOT / "deploy" / "observability"
EMITTERS = [
    ROOT / "api" / "services" / "observability" / "business_metrics.py",
    ROOT / "api" / "services" / "observability" / "metrics.py",
    ROOT / "deploy" / "pbx" / "scripts" / "backup.sh",
    ROOT / "deploy" / "pbx" / "scripts" / "check_whitelabel.py",
    ROOT / "deploy" / "enterprise" / "scripts" / "backup.sh",
]
METRIC = re.compile(r"\bnimbora_[a-z_]+")


def emitted() -> set[str]:
    names: set[str] = set()
    for path in EMITTERS:
        names |= set(METRIC.findall(path.read_text()))
    return names


def test_alert_rules_use_metrics_that_exist():
    rules = yaml.safe_load((OBS / "prometheus" / "alerts.yml").read_text())
    exprs = [r["expr"] for g in rules["groups"] for r in g["rules"]]
    assert len(exprs) >= 10
    known = emitted()
    for expr in exprs:
        for name in METRIC.findall(str(expr)):
            assert name in known, (name, expr)


def test_dashboards_use_metrics_that_exist():
    known = emitted()
    for dashboard in (OBS / "grafana" / "dashboards").glob("*.json"):
        data = json.loads(dashboard.read_text())
        for panel in data["panels"]:
            for target in panel.get("targets", []):
                for name in METRIC.findall(target["expr"]):
                    # Histograms expose _bucket/_sum/_count series, and the
                    # OpenTelemetry exporter appends the unit (_seconds, _bytes).
                    base = re.sub(r"_(bucket|sum|count|total)$", "", name)
                    base = re.sub(r"_(seconds|bytes|By)$", "", base)
                    assert name in known or base in known, (dashboard.name, name)


def test_prometheus_scrapes_business_metrics_once_and_loads_rules():
    config = yaml.safe_load((OBS / "prometheus" / "prometheus.yml").read_text())
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    business = jobs["nimbora-business"]
    assert business["metrics_path"] == "/api/v1/metrics/business"
    assert business["scrape_interval"] == "60s"
    assert config["rule_files"] == ["/etc/prometheus/alerts.yml"]
    compose = yaml.safe_load((OBS / "docker-compose.yml").read_text())
    mounted = " ".join(compose["services"]["prometheus"]["volumes"])
    for name in (
        "alerts.yml",
        "business-targets.json",
        "node-targets.json",
        "targets.json",
    ):
        assert name in mounted


def test_devops_secret_instructions_are_readable_by_prometheus():
    """Seen on the lab: a 600 root-owned secret file is unreadable by Prometheus (nobody)."""
    readme = (
        (OBS / "README.md").read_text()
        if "OBS" in globals()
        else (
            Path(__file__).resolve().parents[2] / "observability" / "README.md"
        ).read_text()
    )
    compose = (
        Path(__file__).resolve().parents[2] / "observability" / "docker-compose.yml"
    ).read_text()
    assert (
        "chmod 644 devops_secret" in readme and "chmod 600 devops_secret" not in readme
    )
    assert "chmod 644 devops_secret" in compose
