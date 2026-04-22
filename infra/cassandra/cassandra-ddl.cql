-- infra/cassandra/cassandra-ddl.cql
-- ===================================
-- Khởi tạo keyspace + tables cho Speed Layer.
--
-- Chạy:
--   cqlsh < infra/cassandra/cassandra-ddl.cql
--   hoặc: bash infra/cassandra/cassandra-init.sh

-- Keyspace cho tất cả tables
CREATE KEYSPACE IF NOT EXISTS demo_jobs
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE demo_jobs;

-- ════════════════════════════════════════════════════════════════════════════
-- TABLE 1: jobs_streaming
-- ════════════════════════════════════════════════════════════════════════════
-- Purpose: Lưu trữ individual job records từ Consumer 1
-- 
-- Write pattern: INSERT (upsert by primary key) từ spark_consumer.py
-- Read pattern: Query by job_id, or scan tất cả
--
-- Primary key: job_id (partition key)
-- - Partition key = job_id đảm bảo 1 job luôn vào cùng partition
-- - Các job khác nhau không xung đột writes
--
-- Indexes:
-- - city: hỗ trợ query tất cả jobs ở 1 thành phố (secondary index)

CREATE TABLE IF NOT EXISTS jobs_streaming (
    job_id          text PRIMARY KEY,
    ingested_at     timestamp,
    job_title       text,
    company_name    text,
    city            text,
    salary_min      double,
    salary_max      double,
    employment_type text,
    skills          set<text>,
    event_date      text,
) WITH
    default_time_to_live = 2592000  -- TTL 30 days
    AND compression = {'class': 'org.apache.cassandra.io.compress.LZ4Compressor'}
    AND gc_grace_seconds = 600;

CREATE INDEX IF NOT EXISTS jobs_streaming_city ON jobs_streaming(city);
CREATE INDEX IF NOT EXISTS jobs_streaming_company ON jobs_streaming(company_name);

-- ════════════════════════════════════════════════════════════════════════════
-- TABLE 2: realtime_job_counts_10m
-- ════════════════════════════════════════════════════════════════════════════
-- Purpose: Aggregated job counts per 10-min window, grouped by city + employment_type
--
-- Write pattern: Batch insert từ realtime_aggregator.py mỗi 10 phút
-- Read pattern: Query latest counts, scatter-gather across time_buckets
--
-- Primary key: (time_bucket, city, employment_type)
-- - Partition key = time_bucket: đảm bảo tất cả city/employment_type ở cùng partition
-- - Clustering keys = city, employment_type: quick range scan
--
-- Time bucket format: "2025-04-22T14:30:00Z" (10-min granule)

CREATE TABLE IF NOT EXISTS realtime_job_counts_10m (
    time_bucket             text,
    city                    text,
    employment_type        text,
    job_count               bigint,
    distinct_company_count  bigint,
    updated_at              timestamp,
    PRIMARY KEY ((time_bucket), city, employment_type)
) WITH
    default_time_to_live = 604800  -- TTL 7 days (hết hạn sau 1 tuần)
    AND compression = {'class': 'org.apache.cassandra.io.compress.LZ4Compressor'}
    AND clustering_order_by (city ASC, employment_type ASC);

-- ════════════════════════════════════════════════════════════════════════════
-- TABLE 3: realtime_skill_counts
-- ════════════════════════════════════════════════════════════════════════════
-- Purpose: Aggregated skill counts per 10-min window, grouped by skill + city
--
-- Write pattern: Batch insert từ realtime_aggregator.py sau khi EXPLODE(skills)
-- Read pattern: Query top skills, filter by city/time_bucket
--
-- Primary key: (time_bucket, city, skill)
-- - Partition key = time_bucket: distribute data across nodes
-- - Clustering key = city, skill: support range scan "all skills in city X"
--
-- Statistics:
-- - job_count: bao nhiêu jobs mention skill này
-- - distinct_company_count: bao nhiêu công ty đang tuyển dùng skill này
-- - avg_salary_min, avg_salary_max: đơn giá trung bình cho skill

CREATE TABLE IF NOT EXISTS realtime_skill_counts (
    time_bucket             text,
    city                    text,
    skill                   text,
    job_count               bigint,
    distinct_company_count  bigint,
    avg_salary_min          double,
    avg_salary_max          double,
    updated_at              timestamp,
    PRIMARY KEY ((time_bucket, city), skill)
) WITH
    default_time_to_live = 604800  -- TTL 7 days
    AND compression = {'class': 'org.apache.cassandra.io.compress.LZ4Compressor'}
    AND clustering_order_by (skill ASC);

-- ════════════════════════════════════════════════════════════════════════════
-- Verify tables
-- ════════════════════════════════════════════════════════════════════════════
DESC KEYSPACE demo_jobs;
SELECT COUNT(*) FROM jobs_streaming;
SELECT COUNT(*) FROM realtime_job_counts_10m;
SELECT COUNT(*) FROM realtime_skill_counts;
