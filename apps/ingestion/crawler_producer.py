"""
apps/ingestion/crawler_producer.py
====================================
BƯỚC 1: PRODUCER
Crawler cào dữ liệu từ TopCV rồi gửi từng job vào Kafka topic "jobs_raw".

Kiến trúc pub-sub:
    [Crawler Producer] --> Kafka topic: jobs_raw --> [Spark Consumer]

Chạy thử (không cần Kafka thật, dùng --dry-run):
    python apps/ingestion/crawler_producer.py --dry-run

Chạy thật với Kafka:
    python apps/ingestion/crawler_producer.py --url https://www.topcv.vn/viec-lam/...
-
Chạy từ file JSON có sẵn (historical backfill):
    python apps/ingestion/crawler_producer.py --from-file data/jobs.json

Cài thư viện cần thiết:
    pip install requests beautifulsoup4 kafka-python
"""

import json
import time
import argparse
import hashlib
import logging
import sys
from datetime import datetime
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

import requests
from bs4 import BeautifulSoup

# ── Cấu hình logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("crawler_producer")

# ── Cấu hình Kafka ──────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP = "localhost:9092"          # override bằng env KAFKA_BOOTSTRAP
TOPIC_RAW       = "jobs_raw"               # topic nhận raw events

# ── HTTP headers giả lập browser ────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 1: CRAWL – lấy HTML và parse thành dict
# ════════════════════════════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    """
    Bỏ tracking params (ta_source, u_sr_id, utm_*...) khỏi URL.
    Giữ nguyên path để job_id ổn định qua các lần crawl.
    """
    parsed = urlparse(url.strip())
    TRACKING = {"ta_source", "u_sr_id", "ref", "source",
                "utm_source", "utm_medium", "utm_campaign",
                "utm_content", "utm_term", "fbclid", "gclid"}
    clean_params = {
        k: v for k, v in parse_qs(parsed.query).items()
        if k.lower() not in TRACKING
    }
    clean = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(clean_params, doseq=True),
        fragment="",
    )
    return urlunparse(clean)


def fetch_html(url: str) -> str:
    """Tải HTML trang job. Raise nếu HTTP error."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def _text(soup: BeautifulSoup, *selectors) -> str:
    """Thử từng CSS selector, trả về text đầu tiên tìm được."""
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return node.get_text(" ", strip=True)
    return ""


def _list_text(soup: BeautifulSoup, selector: str):
    """Lấy danh sách text từ nhiều nodes cùng selector."""
    return [n.get_text(" ", strip=True) for n in soup.select(selector) if n.get_text(strip=True)]


def parse_job_page(url: str, html: str) -> dict:
    """
    Parse HTML thành raw payload dict.
    Tất cả fields giữ nguyên dạng text (raw) – không biến đổi business logic.
    """
    soup = BeautifulSoup(html, "html.parser")
    parsed = urlparse(url)

    # Lấy JSON-LD structured data nếu có
    json_ld_blocks = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            json_ld_blocks.append(json.loads(script.string or ""))
        except Exception:
            pass

    payload = {
        "domain":       parsed.netloc,
        "fetch_method": "requests",
        # ── Fields visible trên trang ─────────────────────────────────────
        "title":        _text(soup, "h1.job-detail__info--title", "h1", ".title"),
        "company_name": _text(soup, ".company-name a", ".employer-name", ".job-company-name"),
        "salary":       _text(soup, ".job-detail__info--salary", ".salary", "[class*='salary']"),
        "location":     _text(soup, ".job-detail__info--location", ".location", "[class*='location']"),
        "experience":   _text(soup, "[class*='experience']", ".job-experience"),
        "deadline":     _text(soup, "[class*='deadline']", ".expired-date"),
        # job_type = field UI/payment của TopCV, KHÔNG phải employment_type thật
        "job_type":     _text(soup, "[class*='job-type']", "[class*='working-form']"),
        # ── Nội dung dài ──────────────────────────────────────────────────
        "description":  _text(soup, ".job-description", ".description"),
        "requirements": _text(soup, ".job-requirement",  ".requirements"),
        "benefits":     _text(soup, ".job-benefit",      ".benefits"),
        # ── Lists ─────────────────────────────────────────────────────────
        "requirement_items": _list_text(soup, ".job-requirement li"),
        "benefit_items":     _list_text(soup, ".job-benefit li"),
        # Skill chips – thường có nhiễu (breadcrumb, tên thành phố...)
        "skills":       list({
            n.get_text(strip=True)
            for n in soup.select(".skill, [class*='skill'] span, .job-tags a")
            if 2 < len(n.get_text(strip=True)) < 60
        }),
        "categories":   _list_text(soup, ".breadcrumb a"),
        # ── Structured data ───────────────────────────────────────────────
        "json_ld":               json_ld_blocks,
        "meta_tags":             {
            m.get("name") or m.get("property", ""): m.get("content", "")
            for m in soup.find_all("meta")
            if (m.get("name") or m.get("property")) and m.get("content")
        },
        "page_text": soup.get_text(" ", strip=True)[:3000],  # giới hạn để nhẹ message
    }
    return payload


def build_envelope(url: str, payload: dict) -> dict:
    """
    Đóng gói payload vào RawEnvelope – đây là schema message gửi lên Kafka.

        RawEnvelope = metadata (source, url, timestamp) + payload (nội dung crawl)

    Tất cả Spark consumer sẽ đọc đúng format này.
    """
    norm_url = normalize_url(url)
    now_iso  = datetime.utcnow().isoformat()
    return {
        "source":                 "topcv",
        "source_url":             url,
        "normalized_source_url":  norm_url,
        "crawl_version":          1,
        "ingest_ts":              now_iso,
        "event_ts":               now_iso,   # fallback khi không có datePosted
        "payload":                payload,
    }


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 2: PRODUCE – gửi envelope vào Kafka
# ════════════════════════════════════════════════════════════════════════════

def get_kafka_producer():
    """
    Tạo KafkaProducer.
    Raise ImportError nếu kafka-python chưa cài – caller xử lý.
    """
    from kafka import KafkaProducer                    # pip install kafka-python
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        # Serialise dict → JSON bytes trước khi gửi
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        # Đợi ít nhất leader xác nhận (cân bằng speed vs durability)
        acks=1,
        retries=3,
        retry_backoff_ms=500,
    )
    return producer


def send_to_kafka(producer, envelope: dict) -> None:
    """
    Gửi 1 envelope vào Kafka topic jobs_raw.
    Key = job_id (hash của source + url) để cùng job luôn vào cùng partition.
    """
    # job_id = sha256(source + "|" + normalized_url)  theo data_contract_v1.md
    raw_key = f"{envelope['source']}|{envelope['normalized_source_url']}"
    job_id  = hashlib.sha256(raw_key.encode()).hexdigest()

    future = producer.send(
        topic=TOPIC_RAW,
        key=job_id.encode("utf-8"),   # partition key
        value=envelope,
    )
    record_meta = future.get(timeout=10)   # block đợi xác nhận
    log.info(
        "✅ Sent job_id=%s... → %s [partition=%d offset=%d]",
        job_id[:12], TOPIC_RAW,
        record_meta.partition, record_meta.offset,
    )


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 3: ENTRY POINTS
# ════════════════════════════════════════════════════════════════════════════

def crawl_and_produce(url: str, producer=None, dry_run=False):
    """Crawl 1 URL rồi gửi vào Kafka (hoặc in ra nếu dry_run)."""
    log.info("Crawling: %s", url)
    html     = fetch_html(url)
    payload  = parse_job_page(url, html)
    envelope = build_envelope(url, payload)

    if dry_run:
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
        return

    send_to_kafka(producer, envelope)


def produce_from_file(json_path: str, producer=None, dry_run=False):
    """
    Đọc file JSON (list các raw payload đã crawl trước) và produce lên Kafka.
    Dùng cho historical backfill.
    """
    with open(json_path, encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        records = [records]

    for i, record in enumerate(records):
        url     = record.get("source_url", "")
        payload = record.get("payload", record)   # hỗ trợ cả format cũ và mới
        envelope = build_envelope(url, payload)

        if dry_run:
            print(json.dumps(envelope, ensure_ascii=False, indent=2))
        else:
            send_to_kafka(producer, envelope)
            time.sleep(0.1)   # throttle nhẹ

        log.info("Produced %d/%d", i + 1, len(records))


def main():
    global KAFKA_BOOTSTRAP
    ap = argparse.ArgumentParser(description="TopCV Crawler Producer")
    ap.add_argument("--url",       help="URL job cụ thể để crawl")
    ap.add_argument("--from-file", help="Path file JSON để backfill")
    ap.add_argument("--dry-run",   action="store_true",
                    help="In JSON ra stdout thay vì gửi Kafka (để test)")
    ap.add_argument("--kafka",     default=KAFKA_BOOTSTRAP,
                    help=f"Kafka bootstrap servers (default: {KAFKA_BOOTSTRAP})")
    args = ap.parse_args()

    KAFKA_BOOTSTRAP = args.kafka

    producer = None
    if not args.dry_run:
        producer = get_kafka_producer()
        log.info("Kafka producer kết nối tới: %s", KAFKA_BOOTSTRAP)

    try:
        if args.url:
            crawl_and_produce(args.url, producer, dry_run=args.dry_run)

        elif args.from_file:
            produce_from_file(args.from_file, producer, dry_run=args.dry_run)

        else:
            # Demo: tạo 1 envelope giả để test pipeline
            log.info("Không có --url hay --from-file → chạy demo message")
            fake_envelope = build_envelope(
                "https://www.topcv.vn/viec-lam/backend-developer/123456.html",
                {
                    "domain": "www.topcv.vn", "fetch_method": "demo",
                    "title": "Backend Developer", "company_name": "Demo Corp",
                    "salary": "20 - 35 triệu", "location": "Hà Nội",
                    "experience": "2 năm", "deadline": "Còn 30 ngày",
                    "job_type": "Toàn thời gian", "description": "Mô tả...",
                    "requirements": "Python, Docker, PostgreSQL",
                    "benefits": "Lương thưởng tốt",
                    "requirement_items": ["Python", "Docker", "PostgreSQL"],
                    "benefit_items": ["Thưởng tháng 13"],
                    "skills": ["Python", "Docker", "PostgreSQL", "FastAPI"],
                    "categories": ["IT / Software"], "json_ld": [], "meta_tags": {},
                    "page_text": "Backend Developer Demo Corp Hà Nội",
                }
            )
            if args.dry_run:
                print(json.dumps(fake_envelope, ensure_ascii=False, indent=2))
            else:
                send_to_kafka(producer, fake_envelope)
    finally:
        if producer:
            producer.flush()
            producer.close()


if __name__ == "__main__":
    main()