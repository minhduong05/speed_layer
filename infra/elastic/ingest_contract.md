# Ingest contract for Elasticsearch

## Index
`jobs_historical`

## Mục tiêu
Index này dùng cho:
- Discover trong Kibana
- search / filter theo job
- dashboard historical jobs
- aggregate theo city / skill / salary

## Schema tối thiểu

| Field | Type | Required | Ghi chú |
|---|---|---:|---|
| `job_id` | keyword | yes | ID duy nhất cho job, nên ổn định |
| `job_url` | keyword | yes | URL chi tiết job |
| `content_hash` | keyword | yes | Hash nội dung để dedup/versioning |
| `job_title` | text + keyword | yes | Tên job |
| `company_name` | text + keyword | yes | Tên công ty |
| `city` | keyword | yes | Thành phố chuẩn hóa |
| `event_date` | date (`yyyy-MM-dd`) | yes | Ngày sự kiện/job date |
| `fetched_at` | date | yes | Thời điểm crawl/ingest |
| `salary_text` | keyword | no | Chuỗi lương gốc |
| `salary_min` | integer | no | Lương min nếu parse được |
| `salary_max` | integer | no | Lương max nếu parse được |
| `skills` | keyword[] | no | Danh sách skill |

## Quy tắc dữ liệu

### `job_id`
- phải duy nhất trong index
- nên ổn định theo job

### `event_date`
- format: `yyyy-MM-dd`
- ví dụ: `2026-04-02`

### `fetched_at`
- timestamp ISO-8601
- ví dụ: `2026-04-02T02:27:42.622Z`

### Salary
- nếu không parse được số thì vẫn có thể giữ `salary_text`
- không ép `salary_min = 0` hay `salary_max = 0`

### Skills
- là mảng string
- ví dụ: `["Python", "Docker", "Kubernetes"]`

## Ví dụ document

```json
{
  "job_id": "job_topcv_2084326",
  "job_url": "https://www.topcv.vn/viec-lam/back-end-developer/2084326.html",
  "content_hash": "5f75722a7104d05fb45fe1041670440845273330",
  "job_title": "Back-End Developer",
  "company_name": "CONG TY TNHH GIAI PHAP CONG NGHE TRIPLAYZ",
  "city": "Ha Noi",
  "event_date": "2026-04-02",
  "fetched_at": "2026-04-02T02:27:42.622Z",
  "salary_text": "15 - 20 trieu",
  "salary_min": 15,
  "salary_max": 20,
  "skills": ["Git", "Linux", "MySQL", "Python", "Docker", "AWS", "Kubernetes", "FastAPI"]
}
```
