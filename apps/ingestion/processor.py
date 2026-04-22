import hashlib
from datetime import datetime
from typing import Dict, Any

def process_crawled_data(raw_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Xử lý dữ liệu thô từ crawler.py và map theo đúng schema định nghĩa trong apps.stream.schemas.RAW_EVENT_SCHEMA
    
    Args:
        raw_data (dict): Dữ liệu đầu ra từ hàm parse_job_posting của crawler.py
        
    Returns:
        dict: Dữ liệu đã được chuẩn hóa theo schema để đẩy vào Kafka / Spark
    """
    
    source_url = raw_data.get("source_url", "")
    
    # Tạo job_id bằng cách băm (hash) source_url để đảm bảo tính duy nhất
    job_id = hashlib.md5(source_url.encode("utf-8")).hexdigest() if source_url else ""
    
    # Lấy source từ domain, ví dụ "www.topcv.vn" -> "topcv.vn"
    domain = raw_data.get("domain", "")
    source = domain.replace("www.", "") if domain else ""
    
    # Xử lý skills: chuyển từ list sang string cách nhau bởi dấu phẩy
    skills = raw_data.get("skills", [])
    skills_text = ", ".join(skills) if isinstance(skills, list) else str(skills)
    
    # Gộp description, requirements, benefits lại để tạo thành description_text hoàn chỉnh (nếu muốn)
    # Vì Schema chỉ có description_text nên ta có thể kết hợp các phần lại với nhau để khỏi mất dữ liệu
    description = raw_data.get("description", "")
    requirements = raw_data.get("requirements", "")
    benefits = raw_data.get("benefits", "")
    
    full_description = description
    if requirements:
        full_description += f"\n\nYêu cầu công việc:\n{requirements}"
    if benefits:
        full_description += f"\n\nQuyền lợi:\n{benefits}"
    
    # Thời gian xảy ra event (lúc cào dữ liệu)
    event_ts = raw_data.get("crawled_at", datetime.utcnow().isoformat())
    # Thời gian đưa vào hệ thống
    ingest_ts = datetime.utcnow().isoformat()
    
    processed_data = {
        "job_id": job_id,
        "source": source,
        "source_url": source_url,
        "title": raw_data.get("title", ""),
        "company_name": raw_data.get("company_name", ""),
        "salary_text": raw_data.get("salary", ""),
        "location_text": raw_data.get("location", ""),
        "skills_text": skills_text,
        "description_text": full_description.strip(),
        "event_ts": event_ts,
        "ingest_ts": ingest_ts,
    }
    
    # Schema yêu cầu tất cả các trường đều là StringType()
    for key in processed_data:
        if processed_data[key] is None:
            processed_data[key] = ""
        else:
            processed_data[key] = str(processed_data[key])
            
    return processed_data

if __name__ == "__main__":
    # Test thử nghiệm trực tiếp
    import sys
    import json
    import os
    
    # Thêm đường dẫn project vào sys.path để có thể import từ apps.ingestion
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    if project_root not in sys.path:
        sys.path.append(project_root)
        
    try:
        from apps.ingestion.crawler import parse_job_posting
    except ImportError:
        print("Không thể import crawler. Vui lòng chạy file này từ thư mục gốc của project.")
        sys.exit(1)
    
    url = input("Nhập link bài đăng tuyển dụng để test: ").strip()
    if url:
        print("Đang cào dữ liệu...")
        raw_data, _ = parse_job_posting(url)
        print("Đã cào xong! Đang xử lý dữ liệu...")
        
        processed_data = process_crawled_data(raw_data)
        
        print("\nDữ liệu sau khi xử lý theo schema (Sẵn sàng đưa vào Kafka):")
        print(json.dumps(processed_data, ensure_ascii=False, indent=2))
