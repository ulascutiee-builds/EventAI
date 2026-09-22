"""AI demo cục bộ, không dùng thư viện ngoài.

Mục đích: giữ đúng luồng nghiệp vụ trong báo cáo trên máy bị Device Guard chặn
các package nhị phân. Kết quả AI là nội dung hỗ trợ và luôn cần người dùng duyệt.
"""
from html import escape

POSITIVE = ("hay", "tốt", "hữu ích", "tuyệt", "ấn tượng", "dễ hiểu", "chuyên nghiệp", "thích")
IMPROVEMENT = ("chậm", "khó", "thiếu", "tệ", "ồn", "đông", "lỗi", "cải thiện", "bất tiện")
SUGGESTION = ("nên", "mong", "đề xuất", "thêm", "cần", "ước", "hy vọng")


def generate_notification(event, audience: str, notice_type: str, tone: str = "Lịch sự"):
    mapping = {
        "invite": ("Thư mời tham dự", "trân trọng mời bạn tham dự"),
        "reminder": ("Nhắc lịch tham dự", "xin nhắc bạn về lịch tham dự"),
        "thanks": ("Cảm ơn sau sự kiện", "xin cảm ơn bạn đã đồng hành cùng"),
    }
    subject_prefix, phrase = mapping.get(notice_type, mapping["reminder"])
    subject = f"{subject_prefix}: {event['name']}"
    lines = [
        f"Kính gửi {audience or 'người tham dự'},",
        "",
        f"Ban tổ chức {phrase} sự kiện “{event['name']}”.",
        f"Thời gian: {event['start_time'].replace('T', ' ')}.",
        f"Địa điểm: {event['location']}.",
    ]
    if event["description"]:
        lines += ["", f"Thông tin: {event['description']}"]
    lines += ["", "Trân trọng,", "Ban tổ chức"]
    return subject, "\n".join(lines)


def summarize_feedback(rows):
    if not rows:
        return {
            "count": 0,
            "average": None,
            "positive": [],
            "improvement": [],
            "suggestion": [],
            "other": [],
            "text": "Chưa đủ dữ liệu để tóm tắt phản hồi.",
        }
    result = {"positive": [], "improvement": [], "suggestion": [], "other": []}
    total = 0
    for row in rows:
        text = (row["content"] or "").strip()
        lower = text.lower()
        total += int(row["rating"])
        hit = False
        if any(k in lower for k in POSITIVE) or int(row["rating"]) >= 4:
            result["positive"].append(text); hit = True
        if any(k in lower for k in IMPROVEMENT) or int(row["rating"]) <= 3:
            result["improvement"].append(text); hit = True
        if any(k in lower for k in SUGGESTION):
            result["suggestion"].append(text); hit = True
        if not hit:
            result["other"].append(text)
    result["count"] = len(rows)
    result["average"] = round(total / len(rows), 1)
    result["text"] = (
        f"Tổng hợp từ {len(rows)} phản hồi, điểm trung bình {result['average']}/5. "
        f"Có {len(result['positive'])} phản hồi tích cực, "
        f"{len(result['improvement'])} phản hồi nêu vấn đề cần cải thiện và "
        f"{len(result['suggestion'])} phản hồi có đề xuất."
    )
    return result


def chatbot_answer(event, sessions, faqs, question: str):
    q = (question or "").strip().lower()
    if not q:
        return "Chưa có thông tin trong dữ liệu sự kiện.", "none"
    if any(k in q for k in ("thời gian", "mấy giờ", "bắt đầu", "kết thúc", "ngày nào")):
        return (
            f"Sự kiện {event['name']} diễn ra từ {event['start_time'].replace('T',' ')} "
            f"đến {event['end_time'].replace('T',' ')}.",
            "event_info",
        )
    if any(k in q for k in ("địa điểm", "ở đâu", "chỗ nào")):
        return f"Địa điểm sự kiện: {event['location']}.", "event_info"
    if any(k in q for k in ("lịch trình", "phiên", "chương trình", "diễn giả", "phòng")):
        if not sessions:
            return "Chưa có thông tin lịch trình trong dữ liệu sự kiện.", "sessions"
        items = []
        for s in sessions[:8]:
            speaker = s["speaker_name"] or "Chưa cập nhật diễn giả"
            items.append(f"{s['start_time'].replace('T',' ')} – {s['title']} – {speaker} – {s['room'] or 'Chưa cập nhật phòng'}")
        return "Lịch trình hiện có:\n" + "\n".join(items), "sessions"
    words = [w.strip(".,?!:;()[]\"") for w in q.split() if len(w.strip(".,?!:;()[]\"")) >= 3]
    best = None
    best_score = 0
    for faq in faqs:
        text = (faq["question"] + " " + faq["answer"]).lower()
        score = sum(1 for w in words if w in text)
        if score > best_score:
            best_score, best = score, faq
    if best and best_score > 0:
        return best["answer"], "faq"
    return "Chưa có thông tin trong dữ liệu sự kiện.", "none"
