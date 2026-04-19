# Integration Deliverable Specification

**Document ID:** ID-TOPCV-JOBS-V1
**Version:** 1.0.0
**Status:** Draft for implementation
**Scope:** Integration outputs, mapping decisions, operational handoff, downstream contracts
**Related document:** `data_contract.md`

---

## 1. Objective

This document defines the integration-oriented deliverables required to operationalize the TopCV job-posting data contract across ingestion, processing, storage, and downstream consumption.

The document covers:

* canonical outputs per layer
* transformation mapping from sample raw record
* system integration targets
* downstream interfaces
* acceptance criteria
* operational handoff checklist

---

## 2. Deliverable Set

The following artifacts are required for implementation readiness.

## 2.1 Mandatory deliverables

1. Canonical raw envelope definition
2. Bronze normalized schema output
3. Silver canonical schema output
4. Gold aggregate table definitions
5. Field-level mapping matrix: raw -> bronze -> silver -> gold
6. Key-generation rules and validation examples
7. Batch/realtime naming alignment matrix
8. Quality flag policy
9. Storage target specification
10. Downstream consumer contract summary
11. Schema review checklist
12. Sample record expected outputs

## 2.2 Recommended implementation artifacts

1. `raw_jobs.schema.json`
2. `silver_jobs_schema.py`
3. `gold_tables.yaml`
4. `taxonomy/skills.yml`
5. `tests/test_job_id_generation.py`
6. `tests/test_company_name_resolution.py`
7. `tests/test_salary_parsing.py`
8. `tests/test_skill_filtering.py`
9. `tests/test_batch_realtime_alignment.py`

---

## 3. Integration Decisions for Sample Record

## 3.1 Canonical business identity

```yaml
source: "topcv"
normalized_source_url: "https://www.topcv.vn/viec-lam/tour-operator-dieu-hanh-tour-inbound-thu-nhap-tu-us-700-us-1500-thang/2111673.html"
job_id: "678bd9b075bde10570f67fefdef1f94c8ff169ee7732f95a533a5ca15e4b0d15"
hash_content: "7f4506c38669f1e9733bdc063a739160a3bdf39e0c232419e95d2be42c62fc9e"
record_version: 1
```

## 3.2 Canonical business resolution

```yaml
job_title: "Tour Operator/ Điều Hành Tour Inbound"
job_title_display: "Tour Operator/ Điều Hành Tour Inbound (Thu Nhập Từ $US 700 – $US 1500/Tháng)"
company_name: "Công ty TNHH Du Lịch Authentic Asia"
company_name_display: "HA TRAVEL"
employment_type: "FULL_TIME"
employment_type_vi: "Toàn thời gian"
salary_min: 700.0
salary_max: 1500.0
currency: "USD"
salary_period: "month"
posting_date: 2026-04-07
valid_through_ts: 2026-05-07T23:59:59+07:00
city: "Hà Nội"
district: "Hoàng Mai"
ward: "Phường Hoàng Mai"
openings: 1
```

## 3.3 Explicit exclusions from canonical layer

The following raw fields shall not be used directly as canonical business fields:

* `job_type` -> excluded due to crawler/UI noise
* top-level `skills` -> excluded as authoritative skill source; allowed only as filtered candidate input
* relative deadline string `(Còn 18 ngày)` -> excluded as canonical deadline source

---

## 4. Transformation Mapping Matrix

## 4.1 Raw -> Bronze

| Raw field             | Bronze field                  | Rule                     | Notes                                        |
| --------------------- | ----------------------------- | ------------------------ | -------------------------------------------- |
| `source_url`          | `source_url`                  | passthrough              | original URL preserved                       |
| `source_url`          | `normalized_source_url`       | normalize URL            | remove tracking params                       |
| `domain`              | `crawl_domain`                | passthrough              | source provenance                            |
| `crawled_at`          | `ingest_ts`                   | direct cast to timestamp | ingestion event time                         |
| `crawled_at`          | `event_ts`                    | fallback assignment      | event time unavailable from crawler envelope |
| `title`               | `job_title_raw`               | passthrough              | raw title                                    |
| `company_name`        | `company_name_raw`            | passthrough              | raw company label                            |
| `salary`              | `salary_raw`                  | passthrough              | raw salary text                              |
| `location`            | `location_raw`                | passthrough              | raw location                                 |
| `level`               | `level_raw`                   | passthrough              | raw level                                    |
| `experience`          | `experience_raw`              | passthrough              | raw experience                               |
| `deadline`            | `deadline_raw`                | passthrough              | raw relative deadline                        |
| `job_type`            | `job_type_raw`                | passthrough              | retained for audit only                      |
| `quantity`            | `quantity_raw`                | passthrough              | raw quantity                                 |
| `description`         | `description_raw`             | passthrough              | raw description                              |
| `requirements`        | `requirements_raw`            | passthrough              | raw requirements                             |
| `benefits`            | `benefits_raw`                | passthrough              | raw benefits                                 |
| `description_items`   | `description_items_raw_count` | count                    | summary metric                               |
| `requirement_items`   | `requirement_items_raw_count` | count                    | summary metric                               |
| `benefit_items`       | `benefit_items_raw_count`     | count                    | summary metric                               |
| `skills`              | `skills_raw_count`            | count                    | summary metric                               |
| `categories`          | `categories_raw_count`        | count                    | summary metric                               |
| `json_ld`             | `json_ld_present`             | boolean                  | structured evidence flag                     |
| `meta_tags`           | `meta_tags_present`           | boolean                  | metadata flag                                |
| `sections_by_heading` | `sections_by_heading_present` | boolean                  | parsing support flag                         |
| `page_text`           | `page_text_present`           | boolean                  | parsing support flag                         |

## 4.2 Bronze -> Silver

| Bronze field                                           | Silver field                                               | Rule                                | Priority            |
| ------------------------------------------------------ | ---------------------------------------------------------- | ----------------------------------- | ------------------- |
| `job_title_raw`                                        | `job_title_display`                                        | passthrough                         | direct              |
| `job_title_raw` + regex cleanup                        | `job_title`                                                | remove salary phrase in parentheses | canonical transform |
| `company_name_raw` + `json_ld.hiringOrganization.name` | `company_name`                                             | structured source priority          | priority 1          |
| `company_name_raw`                                     | `company_name_display`                                     | passthrough                         | display/audit       |
| raw + structured company names                         | `company_aliases`                                          | collect distinct values             | deterministic merge |
| `normalized_source_url`                                | `job_id`                                                   | hash generation                     | deterministic       |
| selected content fields                                | `hash_content`                                             | content hash                        | deterministic       |
| `json_ld.baseSalary.minValue`                          | `salary_min`                                               | parse structured                    | priority 1          |
| `json_ld.baseSalary.maxValue`                          | `salary_max`                                               | parse structured                    | priority 1          |
| `json_ld.baseSalary.currency`                          | `currency`                                                 | parse structured                    | priority 1          |
| `json_ld.baseSalary.value.unitText`                    | `salary_period`                                            | normalize to lowercase              | priority 1          |
| `json_ld.employmentType`                               | `employment_type`                                          | passthrough normalized enum         | priority 1          |
| `employment_type`                                      | `employment_type_vi`                                       | enum mapping                        | deterministic       |
| `json_ld.datePosted`                                   | `posting_date`                                             | cast date                           | priority 1          |
| `json_ld.validThrough`                                 | `valid_through_ts`                                         | cast timestamp                      | priority 1          |
| `json_ld.jobLocation.address.addressRegion`            | `city`                                                     | structured parse                    | priority 1          |
| section/location parse                                 | `district`                                                 | normalize district                  | combined            |
| `json_ld.jobLocation.address.addressLocality`          | `ward`                                                     | structured parse                    | priority 1          |
| parsed location pieces                                 | `location_display`                                         | render canonical string             | deterministic       |
| `json_ld.jobLocation.address.addressCountry`           | `country_code`                                             | passthrough                         | priority 1          |
| `json_ld.jobLocation.address.postalCode`               | `postal_code`                                              | cast string                         | priority 1          |
| `json_ld.occupationalCategory`                         | `level`                                                    | structured parse                    | priority 1          |
| `level`                                                | `level_normalized`                                         | mapping table                       | deterministic       |
| `json_ld.experienceRequirements.monthsOfExperience`    | `experience_months_min`                                    | direct parse                        | priority 1          |
| `experience_raw`                                       | `experience_text`                                          | passthrough                         | display             |
| requirement parsing                                    | `skills`                                                   | taxonomy filter                     | deterministic       |
| skill taxonomy                                         | `hard_skills`                                              | subset                              | deterministic       |
| soft-skill taxonomy                                    | `soft_skills`                                              | subset                              | deterministic       |
| benefit extraction                                     | `benefits_tags`                                            | taxonomy filter                     | deterministic       |
| schedule section                                       | `work_schedule_text`                                       | parse string                        | deterministic       |
| schedule parse                                         | `requires_weekend_rotation`                                | infer boolean                       | deterministic       |
| section texts                                          | `description_text` / `requirements_text` / `benefits_text` | cleaned text                        | canonical           |

## 4.3 Silver -> Gold

| Silver field(s)                                          | Gold dataset                       | Output field(s)                      | Rule                          |
| -------------------------------------------------------- | ---------------------------------- | ------------------------------------ | ----------------------------- |
| `posting_date`, `city`, `employment_type`, salary fields | `gold_job_facts_daily`             | `job_count`, salary aggregates       | grouped daily aggregate       |
| `skills`, `posting_date`, `city`                         | `gold_skill_counts_daily`          | `job_count`, rank, salary aggregates | explode skills then aggregate |
| `skills`, `posting_date`, salary fields                  | `gold_salary_stats_by_skill_month` | salary distribution metrics          | month + skill aggregate       |
| `company_name`, `posting_date`, city, salary fields      | `gold_company_hiring_by_month`     | hiring intensity metrics             | month + company aggregate     |
| `skills` pairs                                           | `gold_skill_cooccurrence_weekly`   | pair metrics                         | pairwise weekly aggregate     |

---

## 5. Expected Outputs by Layer

## 5.1 Raw expected output

* one append-only raw envelope record
* original source payload preserved
* source-normalized metadata attached

## 5.2 Bronze expected output

* one deterministic bronze record with keys and quality flags
* audit-safe raw business strings retained
* no irreversible business canonicalization applied

## 5.3 Silver expected output

* one canonical analytics-ready record
* typed salary, company, location, title, experience, and skills
* noise removed from crawler-specific artifacts

## 5.4 Gold expected output

The sample record contributes to the following aggregates:

* one row contribution to daily job facts for `2026-04-07`
* multiple exploded skill contributions for daily skill counts
* one row contribution to monthly salary-by-skill aggregate for `2026-04`
* one row contribution to monthly company hiring aggregate for `2026-04`
* multiple pair contributions to weekly skill co-occurrence aggregate for `2026-W15`

---

## 6. Gold Feature Delivery Plan

## 6.1 Primary features

These features are designated as implementation priority.

### Volume and demand

* `job_count`
* `distinct_company_count`
* `distinct_job_title_count`
* `new_job_count`
* `updated_job_count`
* `active_job_count`

### Salary

* `avg_salary_min`
* `avg_salary_max`
* `median_salary_min`
* `median_salary_max`
* `salary_disclosed_ratio`

### Skill demand

* `skill_job_count`
* `skill_distinct_company_count`
* `skill_rank_overall`
* `skill_rank_by_city`
* `skill_growth_7d`
* `skill_growth_30d`

### Company hiring

* `company_job_count`
* `company_distinct_roles`
* `company_avg_salary_min`
* `company_avg_salary_max`
* `company_hiring_intensity`

### Experience and language

* `experience_bucket_job_count`
* `english_required_ratio`
* `junior_ratio`
* `mid_ratio`
* `senior_ratio`

### Benefits

* `social_insurance_ratio`
* `training_ratio`
* `team_building_ratio`
* `travel_benefit_ratio`
* `bonus_13th_month_ratio`
* `benefit_coverage_ratio`

### Data quality

* `structured_salary_coverage`
* `structured_company_coverage`
* `skill_parse_confidence_avg`
* `record_quality_score_avg`

## 6.2 Optional features

The following features are optional and may be deferred.

### Currency normalization

* `salary_min_vnd_snapshot`
* `salary_max_vnd_snapshot`
* `exchange_rate_snapshot_date`

### Text richness

* `description_length`
* `requirements_length`
* `benefits_length`
* `keyword_density`

### Quality heuristics

* `has_salary`
* `has_deadline`
* `has_schedule`
* `quality_score_bucket`
* `is_suspected_low_quality_post`

### Graph/network

* `skill_centrality_score`
* `community_id`
* `bridge_skill_score`

### Time-series

* `rolling_7d_job_count`
* `rolling_30d_job_count`
* `mom_growth_rate`
* `wow_growth_rate`
* `seasonality_index`

### Search/recommendation

* `normalized_title_tokens`
* `skill_vector`
* `content_embedding_id`
* `search_boost_score`

### Governance

* `schema_version`
* `pipeline_run_id`
* `canonicalization_rule_id`
* `quality_rule_fail_count`

---

## 7. Storage Target Specification

## 7.1 HDFS targets

```text
/raw/jobs/source=topcv/ingest_date=2026-04-19/
/bronze/jobs/source=topcv/ingest_date=2026-04-19/
/silver/jobs/posting_date=2026-04-07/city=ha_noi/
/gold/job_facts_daily/date_key=2026-04-07/
/gold/skill_counts_daily/date_key=2026-04-07/
/gold/salary_stats_by_skill_month/month_key=2026-04/
/gold/company_hiring_by_month/month_key=2026-04/
/gold/skill_cooccurrence_weekly/week_key=2026-W15/
```

## 7.2 Kafka targets

```text
topic.jobs_raw
topic.jobs_clean
topic.jobs_dead_letter
```

Message key:

```text
job_id
```

## 7.3 Cassandra targets

```text
jobs_by_day
jobs_by_skill
salary_stats_by_skill_month
company_stats_by_month
realtime_skill_counts
realtime_job_counts_10m
```

## 7.4 Elasticsearch targets

```text
jobs_silver_v1
gold_skill_counts_daily_v1
gold_company_hiring_by_month_v1
jobs_realtime_v1
```

---

## 8. Downstream Consumer Contract

## 8.1 Dashboard contract

Dashboards may assume the following stable business fields where applicable:

* `time_bucket`
* `city`
* `skill`
* `company_name`
* `job_count`
* `avg_salary_min`
* `avg_salary_max`
* `median_salary_min`
* `median_salary_max`

## 8.2 API contract

Serving/API layer may depend on:

* canonical `company_name`
* canonical `job_title`
* normalized location fields
* typed salary fields
* stable aggregate field names across batch and realtime

## 8.3 Search contract

Elasticsearch indexing may depend on:

* `job_title_display`
* `company_name`
* `location_display`
* `skills`
* `category_level_1/2/3`
* `benefits_tags`
* `status`

---

## 9. Acceptance Criteria

## 9.1 Record-level acceptance

The sample record is accepted only if all of the following conditions are met:

* `job_id` equals `678bd9b075bde10570f67fefdef1f94c8ff169ee7732f95a533a5ca15e4b0d15`
* `normalized_source_url` removes tracking parameters
* `company_name` resolves to `Công ty TNHH Du Lịch Authentic Asia`
* `company_name_display` retains `HA TRAVEL`
* `employment_type` resolves to `FULL_TIME`
* `job_type_raw` is excluded from canonical employment mapping
* `salary_min = 700.0`
* `salary_max = 1500.0`
* `currency = USD`
* `salary_period = month`
* `posting_date = 2026-04-07`
* `valid_through_ts = 2026-05-07T23:59:59+07:00`
* noisy UI tokens are absent from silver `skills`

## 9.2 Gold-level acceptance

* sample contributes exactly one count to `gold_job_facts_daily` for `2026-04-07`
* sample contributes one count per accepted canonical skill to `gold_skill_counts_daily`
* sample contributes one count to `gold_company_hiring_by_month` for `2026-04`
* sample contributes all accepted unique skill pairs to `gold_skill_cooccurrence_weekly`

## 9.3 Alignment acceptance

* batch and realtime outputs reuse stable field names for equivalent concepts
* no dashboard/API-level semantic remapping required for shared fields

---

## 10. Required Validation Tests

## 10.1 Key and URL tests

* normalize tracking URL to canonical URL
* generate stable `job_id` from canonical URL
* generate stable `hash_content` from canonical content inputs

## 10.2 Canonical field resolution tests

* company conflict resolution prefers structured source
* salary parsing prefers JSON-LD `baseSalary`
* employment type ignores noisy `job_type_raw`
* deadline parsing prefers structured `validThrough`

## 10.3 Taxonomy tests

* remove noisy skill tokens such as `Xem thêm`, `Nổi bật`, `Quyền lợi:`
* keep valid skill concepts such as `mice`, `tour guide`, `tiếng anh`, `điều hành tour`
* separate `soft_skills` from `hard_skills`

## 10.4 Aggregate tests

* skill explosion count is deterministic
* company aggregate count is deterministic
* weekly co-occurrence pairs are unique and reproducible
* batch/realtime aligned field names are unchanged

---

## 11. Operational Handoff Checklist

## 11.1 Engineering handoff

* [ ] canonical URL normalization function implemented
* [ ] `job_id` generation function implemented
* [ ] `hash_content` generation function implemented
* [ ] structured-source priority resolver implemented
* [ ] salary parser implemented
* [ ] company-name conflict resolver implemented
* [ ] skill taxonomy filter implemented
* [ ] gold aggregates implemented

## 11.2 Data governance handoff

* [ ] field dictionary reviewed
* [ ] compatibility policy reviewed
* [ ] schema version recorded
* [ ] breaking-change procedure documented
* [ ] PR checklist published

## 11.3 Platform handoff

* [ ] Kafka topics created
* [ ] HDFS partition layout created
* [ ] Cassandra tables created
* [ ] Elasticsearch indexes created
* [ ] batch and streaming sinks aligned

## 11.4 QA handoff

* [ ] sample record output snapshot approved
* [ ] automated schema tests added
* [ ] aggregate tests added
* [ ] regression test set created for noisy crawler cases

---

## 12. Implementation Boundary

## In scope

* deterministic transformation of the sample TopCV record
* technical contract for layer outputs
* integration targets for batch, streaming, serving, and search
* gold feature prioritization
* consumer-facing naming alignment

## Out of scope for initial delivery

* currency conversion based on external FX service
* embedding generation
* advanced graph scoring
* ML-based quality scoring
* realtime salary analytics

---

## 13. Final Integration Output Summary

### Mandatory layer outputs for this record

```yaml
raw_output: 1 event
bronze_output: 1 normalized record
silver_output: 1 canonical record
gold_daily_job_facts_contribution: 1
gold_skill_daily_contributions: N canonical skills
gold_company_monthly_contribution: 1
gold_skill_pair_weekly_contributions: M canonical skill pairs
```

### Final integration status target

```yaml
identity_stable: true
canonical_company_resolved: true
salary_structured: true
employment_type_resolved: true
location_structured: true
skill_noise_filtered: true
batch_realtime_names_aligned: true
gold_ready: true
```
