import sqlite3
import os
import hashlib
import secrets
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "event_ai_system.db"


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def hash_password(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','organizer','checkin')),
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_by INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','open','closed','completed','cancelled')),
            capacity INTEGER NOT NULL DEFAULT 200,
            registration_deadline TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS speakers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            organization TEXT,
            bio TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            speaker_id INTEGER REFERENCES speakers(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            room TEXT,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS attendees(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT
        );

        CREATE TABLE IF NOT EXISTS registrations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            attendee_id INTEGER NOT NULL REFERENCES attendees(id) ON DELETE CASCADE,
            registration_code TEXT NOT NULL UNIQUE,
            ticket_type TEXT NOT NULL DEFAULT 'Standard',
            registered_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'valid' CHECK(status IN ('valid','cancelled')),
            UNIQUE(event_id, attendee_id)
        );

        CREATE TABLE IF NOT EXISTS checkins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(id) ON DELETE CASCADE,
            checked_by INTEGER NOT NULL REFERENCES users(id),
            checked_in_at TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT 'code'
        );

        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            created_by INTEGER NOT NULL REFERENCES users(id),
            type TEXT NOT NULL,
            audience TEXT NOT NULL,
            subject TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','sent')),
            recipient_count INTEGER NOT NULL DEFAULT 0,
            sent_at TEXT
        );

        CREATE TABLE IF NOT EXISTS feedbacks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            registration_id INTEGER NOT NULL REFERENCES registrations(id) ON DELETE CASCADE,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            content TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            UNIQUE(event_id, registration_id)
        );

        CREATE TABLE IF NOT EXISTS faqs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            task_type TEXT NOT NULL,
            input_summary TEXT,
            output_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0
        );
        """
    )

    users = [
        ("admin", "admin123", "Quản trị viên", "admin"),
        ("organizer", "organizer123", "Ban tổ chức", "organizer"),
        ("checkin", "checkin123", "Nhân viên check-in", "checkin"),
    ]
    for username, password, full_name, role in users:
        cur.execute(
            "INSERT OR IGNORE INTO users(username,password_hash,full_name,role,status,created_at) VALUES(?,?,?,?,?,?)",
            (username, hash_password(password), full_name, role, "active", now_iso()),
        )

    if not cur.execute("SELECT 1 FROM events LIMIT 1").fetchone():
        admin_id = cur.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        cur.execute(
            """INSERT INTO events(created_by,name,start_time,end_time,location,description,status,capacity,registration_deadline,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                admin_id,
                "Ngày hội AI 2026",
                "2026-09-20T08:00",
                "2026-09-20T17:00",
                "Hội trường Đại học CNTT & Truyền thông",
                "Ngày hội chia sẻ kiến thức và ứng dụng trí tuệ nhân tạo, gồm nhiều phiên nội dung, hỏi đáp và hoạt động trải nghiệm.",
                "open",
                200,
                "2026-09-19T23:59",
                now_iso(),
            ),
        )
        event_id = cur.lastrowid
        speakers = [
            ("TS. Nguyễn Minh Anh", "ICTU", "Diễn giả về AI ứng dụng và giáo dục."),
            ("Trần Thu Hà", "AI Lab", "Kỹ sư AI, chuyên về mô hình ngôn ngữ và RAG."),
        ]
        sp_ids = []
        for item in speakers:
            cur.execute("INSERT INTO speakers(full_name,organization,bio) VALUES(?,?,?)", item)
            sp_ids.append(cur.lastrowid)
        session_rows = [
            (event_id, sp_ids[0], "Khai mạc & AI trong giáo dục", "2026-09-20T08:30", "2026-09-20T10:00", "Hội trường A", "Tổng quan AI và các ứng dụng trong đào tạo."),
            (event_id, sp_ids[1], "RAG và chatbot hỏi đáp", "2026-09-20T10:15", "2026-09-20T11:30", "Hội trường A", "Thiết kế chatbot bám dữ liệu sự kiện."),
            (event_id, sp_ids[0], "Workshop AI thực hành", "2026-09-20T13:30", "2026-09-20T15:00", "Phòng Lab 1", "Thực hành xây dựng tác vụ AI đơn giản."),
            (event_id, sp_ids[1], "Hỏi đáp & tổng kết", "2026-09-20T15:15", "2026-09-20T16:30", "Hội trường A", "Trao đổi và tổng kết chương trình."),
        ]
        cur.executemany(
            "INSERT INTO sessions(event_id,speaker_id,title,start_time,end_time,room,description) VALUES(?,?,?,?,?,?,?)",
            session_rows,
        )
        faqs = [
            (event_id, "Sự kiện tổ chức ở đâu?", "Sự kiện tổ chức tại Hội trường Đại học CNTT & Truyền thông."),
            (event_id, "Tôi cần mang theo gì để check-in?", "Bạn chỉ cần mã đăng ký được cấp sau khi đăng ký thành công."),
            (event_id, "Sự kiện bắt đầu lúc mấy giờ?", "Sự kiện bắt đầu lúc 08:00 ngày 20/09/2026."),
        ]
        cur.executemany("INSERT INTO faqs(event_id,question,answer) VALUES(?,?,?)", faqs)

        demo_attendees = [
            ("Nguyễn Văn An", "an.demo@example.com", "0900000001"),
            ("Trần Thị Bình", "binh.demo@example.com", "0900000002"),
            ("Lê Minh Châu", "chau.demo@example.com", "0900000003"),
        ]
        registration_ids = []
        for idx, attendee in enumerate(demo_attendees, start=1):
            cur.execute("INSERT INTO attendees(full_name,email,phone) VALUES(?,?,?)", attendee)
            aid = cur.lastrowid
            code = f"AI2026-DEMO{idx}"
            cur.execute(
                "INSERT INTO registrations(event_id,attendee_id,registration_code,ticket_type,registered_at,status) VALUES(?,?,?,?,?,?)",
                (event_id, aid, code, "Standard", now_iso(), "valid"),
            )
            registration_ids.append(cur.lastrowid)
        checkin_user = cur.execute("SELECT id FROM users WHERE username='checkin'").fetchone()[0]
        cur.execute(
            "INSERT INTO checkins(registration_id,checked_by,checked_in_at,method) VALUES(?,?,?,?)",
            (registration_ids[0], checkin_user, now_iso(), "code/qr"),
        )
        feedback_samples = [
            (event_id, registration_ids[0], 5, "Nội dung rất hữu ích, diễn giả trình bày dễ hiểu.", now_iso()),
            (event_id, registration_ids[1], 3, "Nội dung hay nhưng phần check-in hơi chậm, nên bố trí thêm bàn check-in.", now_iso()),
        ]
        cur.executemany(
            "INSERT INTO feedbacks(event_id,registration_id,rating,content,submitted_at) VALUES(?,?,?,?,?)",
            feedback_samples,
        )

    conn.commit()
    conn.close()


def new_registration_code(event_id: int) -> str:
    return f"EV{event_id}-{secrets.token_hex(4).upper()}"
