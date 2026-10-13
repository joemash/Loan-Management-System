# Observability

Local metrics stack:

- `prometheus-client` metrics exposed at `/actuator/prometheus` (public, so Prometheus can scrape it)
- Prometheus for scraping and querying
- Grafana with an auto-provisioned Prometheus datasource

## Files

- `docker-compose.yml` (services: `db`, `prometheus`, `grafana`, `kafka`, plus `app` under the `app` profile)
- `ops/observability/prometheus.yml` (scrapes `host.docker.internal:8080/actuator/prometheus`)
- `ops/observability/grafana/provisioning/datasources/prometheus-datasource.yml`

## Local setup

1. Start infrastructure: `docker compose up -d`
2. Start the backend on port 8080: `uv run uvicorn --factory src.main:app_factory --port 8080`
3. Check metrics: `curl -s http://localhost:8080/actuator/prometheus | head -n 20`
4. Open `http://localhost:9090/targets` and confirm `lms-backend` is `UP`.
5. Open Grafana at `http://localhost:3000` (`admin` / `admin`) → Explore → query
   `http_server_requests_seconds_count` or `process_resident_memory_bytes`.

## Health endpoints

| Endpoint | Purpose |
|----------|---------|
| `/actuator/health` | `UP`/`DOWN` with a database ping (503 when down) |
| `/actuator/health/liveness` | process is alive |
| `/actuator/health/readiness` | same check as `/actuator/health` |

## Metrics

| Metric | Type | Meaning |
|--------|------|---------|
| `http_server_requests_seconds` | histogram | latency by `method`, route template `uri`, `status` |
| `lms_notifications_outbox_published_total` | counter | outbox rows relayed to Kafka |
| `lms_notifications_outbox_failed_total` | counter | outbox publish failures |
| `lms_notifications_consumed_total` | counter | messages dispatched and marked `SENT` |
| `lms_notifications_consume_failed_total` | counter | dispatch failures |
| `lms_notifications_failed_count` | gauge | notifications with `delivery_status=FAILED` |
| `lms_notifications_unread_count` | gauge | notifications with `ui_status=UNREAD` |
| `lms_notifications_outbox_pending_count` | gauge | due outbox rows (capped at 100) |

Python process metrics (`process_*`, `python_gc_*`) replace the JVM metrics of the Java version.

## Generate sample traffic

```bash
for i in {1..20}; do
  curl -s "http://localhost:8080/admin/loans?page=0&size=10" -H "Authorization: Bearer ${ADMIN_JWT}" > /dev/null
done
```

## Troubleshooting

- Target down: make sure the backend listens on `localhost:8080` (Prometheus scrapes the host).
- No data in Grafana: query `up` in Prometheus first, then generate traffic.
- Grafana login fails after changing credentials: `docker compose down -v && docker compose up -d`.
