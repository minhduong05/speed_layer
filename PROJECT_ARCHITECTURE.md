# PROJECT ARCHITECTURE — Big Data Job Market (TopCV)

> **Phân tích thị trường việc làm dựa trên dữ liệu từ TopCV**

Lambda Architecture: Historical JSON + Crawler → Batch/Speed Layer → Cassandra / Elasticsearch → FastAPI / Kibana / Grafana

---

## Repository Structure

```
bigdata-job-market/
│
├── apps/
│   ├── ingestion/              # TV2 — crawler, historical loader, Kafka producer
│   ├── batch/                  # TV3 — Spark batch ETL: raw → bronze → silver → gold
│   ├── stream/                 # TV4 — Spark Structured Streaming, DLQ handler
│   └── serving/                # TV5 — FastAPI endpoints
│
├── data_contracts/             # TV1 — schema definitions, data dictionary
│   └── data_contract_v1.md     #   Spec đầy đủ cho raw/bronze/silver/gold
│
├── infra/
│   ├── cassandra/              # K8ssandra manifests
│   ├── elastic/                # Elasticsearch + Kibana manifests
│   ├── kafka/                  # Strimzi Kafka manifests
│   ├── spark/                  # Spark RBAC, Dockerfile
│   ├── streaming/              # Streaming pipeline docs end-to-end
│   ├── kubernetes/             # Deployment manifests tổng hợp
│   └── compose/                # Docker Compose cho local dev
│
├── configs/                    # Spark, Kafka, serving configs (YAML)
├── shared/                     # Shared utils: schemas.py, logger.py, config_loader.py
├── scripts/                    # Setup, smoke test scripts
├── tests/                      # Unit & integration tests
├── docs/                       # Deployment guide, runbook, lineage
│
├── PROJECT_ARCHITECTURE.md     # File này
└── README.md
```

---

## HDFS Layout

```
/raw/jobs/source=topcv/ingest_date=YYYY-MM-DD/
/bronze/jobs/source=topcv/ingest_date=YYYY-MM-DD/
/silver/jobs/posting_date=YYYY-MM-DD/city=<city>/
/gold/job_facts_daily/date_key=YYYY-MM-DD/
/gold/skill_counts_daily/date_key=YYYY-MM-DD/
/gold/company_hiring_by_month/month_key=YYYY-MM/
```

---

## Team Ownership

| TV | Tên | Owns |
|----|-----|------|
| TV1 | KHÔI | `data_contracts/` — schema, dedup rules, review |
| TV2 | HOÀNG | `apps/ingestion/` — crawler, historical loader |
| TV3 | ĐỊNH | `apps/batch/` — Spark batch ETL |
| TV4 | MINH | `apps/stream/` — Structured Streaming, DLQ |
| TV5 | ANH | `apps/serving/`, `infra/` — Cassandra/ES, API, deploy |

> Chi tiết schema xem [`data_contracts/data_contract_v1.md`](data_contracts/data_contract_v1.md)
