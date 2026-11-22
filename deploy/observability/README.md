# Monitoring NIMBORA (Prometheus + Grafana)

Optional stack: Prometheus with the NIMBORA alert rules, and Grafana with two
dashboards (runtime and operations).

| Job | Endpoint | What |
| --- | --- | --- |
| `nimbora` | `/api/v1/metrics` on **each** API worker (5 s) | calls in progress, AI and response latencies, TTS cache |
| `nimbora-business` | `/api/v1/metrics/business` on **one** API (60 s) | PBX of each company (reachable, last check, events, supervision alerts, human-minutes catch-up), subscriptions by plan/status, AI and human minutes of the month |
| `node` | `:9100` on the platform server and each PBX | host metrics + backup freshness (`nimbora_*_backup_last_success_timestamp_seconds`) |

## Start

1. In the API environment: `ENABLE_PROMETHEUS_METRICS=true` and a random
   `NIMBORA_DEVOPS_SECRET`.
2. Here: `echo -n "<NIMBORA_DEVOPS_SECRET>" > devops_secret && chmod 600 devops_secret`.
3. Targets: workers in `prometheus/targets.json`, one API in
   `prometheus/business-targets.json`, hosts in `prometheus/node-targets.json`.
4. On each PBX: `install.sh … --metrics-from <Prometheus IP>` (installs the
   node exporter, opens 9100 to that address only). On the platform server:
   `apt install prometheus-node-exporter` (the backup script writes its metric
   in `/var/lib/prometheus/node-exporter`).
5. `docker compose up -d` → Grafana on http://localhost:3001 (folder NIMBORA),
   Prometheus on http://localhost:9090/alerts.

## Alerts (`prometheus/alerts.yml`)

PBX unreachable (5 min), PBX not checked (30 min), call events disconnected
(1 h), human minutes not read for 3 h (invoices would miss calls), supervision
alert open 30 min, no backup for 26 h or last backup failed (PBX and
platform), business metrics stale, disk under 10 %. Route them with
Alertmanager to e-mail, Slack, Teams…
