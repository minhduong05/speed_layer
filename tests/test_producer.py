"""
tests/test_producer.py
=======================
Unit tests cho crawler_producer.py - KHÔNG cần Kafka hay Network.

Chạy:
    pytest tests/test_producer.py -v
"""

import pytest
import json
from datetime import datetime
from urllib.parse import urlparse

# Import functions cần test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from apps.ingestion.crawler_producer import (
    normalize_url,
    build_envelope,
)


class TestNormalizeUrl:
    """Test URL normalization - bỏ tracking params, lowercase, bỏ fragment."""

    def test_tracking_params_removed(self):
        """Bỏ ta_source, u_sr_id, utm_*, fbclid, gclid."""
        url = "https://www.topcv.vn/job/123.html?ta_source=x&u_sr_id=y&utm_source=google"
        result = normalize_url(url)
        assert "ta_source" not in result
        assert "u_sr_id" not in result
        assert "utm_source" not in result

    def test_fragment_removed(self):
        """Bỏ fragment (#section)."""
        url = "https://www.topcv.vn/job/123.html#details"
        result = normalize_url(url)
        assert "#details" not in result
        assert result == "https://www.topcv.vn/job/123.html"

    def test_lowercase_scheme_host(self):
        """Scheme + host lowercase."""
        url = "HTTPS://WWW.TOPCV.VN/Job/123.html"
        result = normalize_url(url)
        assert result.startswith("https://www.topcv.vn")
        assert "/Job/" in result  # Path giữ nguyên casing

    def test_preserves_path(self):
        """Path để nguyên để job_id ổn định."""
        url = "https://www.topcv.vn/viec-lam/backend-dev-123.html"
        result = normalize_url(url)
        assert "/viec-lam/backend-dev-123.html" in result

    def test_whitespace_stripped(self):
        """Bỏ whitespace ở đầu/cuối."""
        url = "  https://www.topcv.vn/job/123.html  "
        result = normalize_url(url)
        assert result == "https://www.topcv.vn/job/123.html"


class TestBuildEnvelope:
    """Test RawEnvelope construction."""

    def test_envelope_structure(self):
        """Envelope có đúng fields."""
        url = "https://www.topcv.vn/job/123.html"
        payload = {"title": "Dev", "company_name": "Corp"}
        env = build_envelope(url, payload)

        assert env["source"] == "topcv"
        assert env["source_url"] == url
        assert "normalized_source_url" in env
        assert env["crawl_version"] == 1
        assert "ingest_ts" in env
        assert "event_ts" in env
        assert env["payload"] == payload

    def test_ingest_ts_iso_format(self):
        """ingest_ts là ISO format."""
        env = build_envelope("https://www.topcv.vn/job/123.html", {})
        ts = datetime.fromisoformat(env["ingest_ts"])  # Không raise nếu ISO
        assert isinstance(ts, datetime)

    def test_normalized_url_in_envelope(self):
        """normalized_source_url bỏ tracking."""
        url_with_tracking = "https://www.topcv.vn/job/123.html?ta_source=x"
        env = build_envelope(url_with_tracking, {})
        assert "ta_source" not in env["normalized_source_url"]

    def test_payload_included(self):
        """payload được include vào envelope."""
        payload = {
            "title": "Backend Dev",
            "company_name": "Tech Corp",
            "salary": "20 triệu",
        }
        env = build_envelope("https://www.topcv.vn/job/123.html", payload)
        assert env["payload"]["title"] == "Backend Dev"
        assert env["payload"]["company_name"] == "Tech Corp"


class TestProducerIntegration:
    """Integration test - verify demo message generation."""

    def test_demo_envelope_valid_json(self):
        """Demo envelope phải valid JSON."""
        from apps.ingestion.crawler_producer import build_envelope
        env = build_envelope(
            "https://www.topcv.vn/viec-lam/dev/123.html",
            {
                "title": "Backend Dev",
                "company_name": "Demo Corp",
                "salary": "20 triệu",
            }
        )
        # Phải serialize được thành JSON
        json_str = json.dumps(env, ensure_ascii=False)
        assert json_str
        # Phải parse lại được
        parsed = json.loads(json_str)
        assert parsed["source"] == "topcv"

    def test_envelope_serializable(self):
        """Tất cả fields phải JSON serializable."""
        env = build_envelope(
            "https://www.topcv.vn/job/123.html",
            {"title": "Dev", "skills": ["Python", "Docker"]}
        )
        # Nếu không serializable sẽ raise exception
        json.dumps(env, ensure_ascii=False)  # Should not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])