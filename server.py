from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from http.cookies import SimpleCookie
from pathlib import Path
from datetime import datetime
import json, mimetypes, os, secrets, sqlite3, re, sys

# Windows terminals may default to a legacy code page that cannot print Vietnamese.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import connect, init_db, hash_password, now_iso, new_registration_code
from ai_engine import generate_notification, summarize_feedback, chatbot_answer
from ui import page, e, badge, stat_card, empty_state, STATUS_LABEL, ROLE_LABEL

# Render provides PORT and requires the service to listen publicly.
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SESSIONS = {}


def fv(data, key, default=""):
    return data.get(key, [default])[0]


def dt(value):
    return (value or "").replace("T", " ")


def valid_email(value):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value or ""))


def status_badge(status):
    kind = {"open":"success","completed":"neutral","closed":"warning","cancelled":"danger","draft":"info"}.get(status,"neutral")
    return badge(STATUS_LABEL.get(status,status), kind)


def redirect_with_msg(path, msg, kind="success"):
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}msg={quote(msg)}&kind={quote(kind)}"


class Handler(BaseHTTPRequestHandler):
    server_version = "EventAI/2.0"

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} - {fmt % args}")

    def current_user(self):
        cookie = SimpleCookie(self.headers.get("Cookie"))
        sid = cookie.get("sid")
        if not sid or sid.value not in SESSIONS:
            return None
        conn = connect()
        user = conn.execute("SELECT * FROM users WHERE id=? AND status='active'", (SESSIONS[sid.value],)).fetchone()
        conn.close()
        return user

    def post_data(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return parse_qs(raw, keep_blank_values=True)

    def send_html(self, title, body, user=None, active="", code=200, flash=None):
        data = page(title, body, user=user, active=active, flash=flash).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, code=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, path, cookie=None):
        self.send_response(303)
        self.send_header("Location", path)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def require(self, *roles):
        user = self.current_user()
        if not user:
            self.redirect("/login")
            return None
        if roles and user["role"] not in roles:
            self.send_html("Không có quyền", '<div class="panel"><h2>403 · Không có quyền truy cập</h2><p>Tài khoản hiện tại không được phép thực hiện chức năng này.</p><a class="btn" href="/">Quay lại</a></div>', user=user, code=403)
            return None
        return user

    def flash_from_query(self, q):
        msg = fv(q, "msg")
        return (fv(q, "kind", "success"), msg) if msg else None

    def serve_static(self, path):
        rel = path[len("/static/"):]
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in target.parents or not target.exists() or not target.is_file():
            self.send_error(404); return
        data = target.read_bytes()
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path, q = parsed.path, parse_qs(parsed.query)
        if path.startswith("/static/"):
            return self.serve_static(path)
        user = self.current_user()
        conn = connect()
        try:
            if path == "/":
                search = fv(q, "q").strip()
                status = fv(q, "status").strip()
                sql = "SELECT e.*, u.full_name creator FROM events e JOIN users u ON u.id=e.created_by WHERE 1=1"
                args=[]
                if search:
                    sql += " AND (e.name LIKE ? OR e.location LIKE ? OR e.description LIKE ?)"; args += [f"%{search}%"]*3
                if status:
                    sql += " AND e.status=?"; args.append(status)
                sql += " ORDER BY e.start_time DESC"
                events = conn.execute(sql,args).fetchall()
                cards=[]
                for ev in events:
                    counts = conn.execute("""SELECT
                        (SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='valid') regs,
                        (SELECT COUNT(*) FROM checkins c JOIN registrations r ON r.id=c.registration_id WHERE r.event_id=?) checkins
                    """,(ev['id'],ev['id'])).fetchone()
                    pct = round(counts['checkins']*100/counts['regs']) if counts['regs'] else 0
                    cards.append(f'''<article class="event-card"><div class="event-cover"><span class="event-date"><b>{e(ev['start_time'][8:10])}</b><small>TH{e(ev['start_time'][5:7])}</small></span><div class="event-status">{status_badge(ev['status'])}</div></div><div class="event-body"><div class="event-meta"><span>◷ {e(dt(ev['start_time']))}</span><span>⌖ {e(ev['location'])}</span></div><h3>{e(ev['name'])}</h3><p>{e((ev['description'] or '')[:145])}</p><div class="progress-row"><span>{counts['regs']}/{ev['capacity']} đăng ký</span><span>{pct}% đã check-in</span></div><div class="progress"><i style="width:{min(100, counts['regs']*100/max(ev['capacity'],1))}%"></i></div><div class="event-actions"><a class="btn btn-primary" href="/event?id={ev['id']}">Xem chi tiết</a>{'<a class="btn btn-ghost" href="/event-edit?id='+str(ev['id'])+'">Chỉnh sửa</a>' if user and user['role'] in ('admin','organizer') else ''}</div></div></article>''')
                create = '<a class="btn btn-primary" href="/event-new">＋ Tạo sự kiện</a>' if user and user['role'] in ('admin','organizer') else ''
                body=f'''<section class="hero"><div><span class="hero-tag">✦ Quản lý tập trung · AI hỗ trợ</span><h2>Tổ chức sự kiện thông minh,<br>vận hành <em>nhanh và chính xác</em>.</h2><p>Quản lý lịch trình, đăng ký, check-in, phản hồi và nội dung AI trong một hệ thống.</p><div class="hero-actions">{create}<a class="btn btn-soft" href="/dashboard">Xem dashboard</a></div></div><div class="hero-visual"><div class="orbit o1"></div><div class="orbit o2"></div><div class="ai-core">AI<small>EVENT</small></div></div></section>
                <div class="section-head"><div><small class="eyebrow">KHÁM PHÁ</small><h2>Sự kiện</h2></div><form class="filters"><input name="q" value="{e(search)}" placeholder="Tìm theo tên, địa điểm..."><select name="status"><option value="">Tất cả trạng thái</option>{''.join(f'<option value="{s}" {"selected" if status==s else ""}>{STATUS_LABEL[s]}</option>' for s in ['draft','open','closed','completed','cancelled'])}</select><button class="btn">Lọc</button></form></div><div class="event-grid">{''.join(cards) if cards else empty_state('Chưa có sự kiện','Không tìm thấy sự kiện phù hợp.')}</div>'''
                self.send_html("Sự kiện", body, user, "events", flash=self.flash_from_query(q))

            elif path == "/login":
                if user: return self.redirect("/")
                body='''<div class="auth-wrap"><div class="auth-art"><div class="brand-big">AI</div><h2>EventAI</h2><p>Quản lý sự kiện có tích hợp AI</p><ul><li>✓ Đăng ký & vé</li><li>✓ Check-in chống trùng</li><li>✓ Dashboard trực quan</li><li>✓ AI thông báo · tóm tắt · chatbot</li></ul></div><form class="auth-card" method="post"><span class="eyebrow">CHÀO MỪNG TRỞ LẠI</span><h2>Đăng nhập hệ thống</h2><label>Tài khoản<input name="username" required autocomplete="username" placeholder="Nhập tài khoản"></label><label>Mật khẩu<input type="password" name="password" required autocomplete="current-password" placeholder="••••••••"></label><button class="btn btn-primary btn-block">Đăng nhập</button><div class="demo-box"><b>Tài khoản demo</b><code>admin / admin123</code><code>organizer / organizer123</code><code>checkin / checkin123</code></div></form></div>'''
                self.send_html("Đăng nhập", body)

            elif path == "/logout":
                cookie = SimpleCookie(self.headers.get("Cookie")); sid = cookie.get("sid")
                if sid: SESSIONS.pop(sid.value, None)
                self.redirect("/", "sid=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/")

            elif path in ("/event-new","/event-edit"):
                u=self.require("admin","organizer")
                if not u:return
                ev=None
                if path=="/event-edit":
                    ev=conn.execute("SELECT * FROM events WHERE id=?",(int(fv(q,'id','0')),)).fetchone()
                    if not ev:return self.send_html("Không tìm thấy","<div class='panel'>Sự kiện không tồn tại.</div>",u,code=404)
                title="Chỉnh sửa sự kiện" if ev else "Tạo sự kiện"
                body=f'''<form class="panel form-grid" method="post"><input type="hidden" name="id" value="{e(ev['id'] if ev else '')}"><div class="field span-2"><label>Tên sự kiện *</label><input name="name" required value="{e(ev['name'] if ev else '')}" placeholder="Ví dụ: Ngày hội AI 2026"></div><div class="field"><label>Thời gian bắt đầu *</label><input type="datetime-local" name="start_time" required value="{e(ev['start_time'] if ev else '')}"></div><div class="field"><label>Thời gian kết thúc *</label><input type="datetime-local" name="end_time" required value="{e(ev['end_time'] if ev else '')}"></div><div class="field"><label>Địa điểm *</label><input name="location" required value="{e(ev['location'] if ev else '')}"></div><div class="field"><label>Sức chứa</label><input type="number" min="1" name="capacity" value="{e(ev['capacity'] if ev else 200)}"></div><div class="field"><label>Hạn đăng ký</label><input type="datetime-local" name="registration_deadline" value="{e(ev['registration_deadline'] if ev else '')}"></div><div class="field"><label>Trạng thái</label><select name="status">{''.join(f'<option value="{s}" {"selected" if ev and ev["status"]==s else ("selected" if not ev and s=="draft" else "")}>{STATUS_LABEL[s]}</option>' for s in ['draft','open','closed','completed','cancelled'])}</select></div><div class="field span-2"><label>Mô tả</label><textarea name="description" rows="6">{e(ev['description'] if ev else '')}</textarea></div><div class="form-actions span-2"><a class="btn btn-ghost" href="/">Hủy</a><button class="btn btn-primary">Lưu sự kiện</button></div></form>'''
                self.send_html(title,body,u,"manage")

            elif path == "/event":
                eid=int(fv(q,"id","0")); ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
                if not ev:return self.send_html("404","<div class='panel'>Không tìm thấy sự kiện.</div>",user,code=404)
                stats=conn.execute("""SELECT
                    (SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='valid') regs,
                    (SELECT COUNT(*) FROM checkins c JOIN registrations r ON r.id=c.registration_id WHERE r.event_id=?) checkins,
                    (SELECT COUNT(*) FROM feedbacks WHERE event_id=?) feedbacks,
                    (SELECT ROUND(AVG(rating),1) FROM feedbacks WHERE event_id=?) avg_rating
                """,(eid,eid,eid,eid)).fetchone()
                sessions=conn.execute("""SELECT s.*,sp.full_name speaker_name,sp.organization speaker_org FROM sessions s LEFT JOIN speakers sp ON sp.id=s.speaker_id WHERE s.event_id=? ORDER BY s.start_time""",(eid,)).fetchall()
                faqs=conn.execute("SELECT * FROM faqs WHERE event_id=? ORDER BY id",(eid,)).fetchall()
                pct=round(stats['checkins']*100/stats['regs'],1) if stats['regs'] else 0
                session_html=''.join(f'''<div class="timeline-item"><div class="timeline-time">{e(dt(s['start_time'])[11:16])}<small>{e(dt(s['end_time'])[11:16])}</small></div><div class="timeline-dot"></div><div class="timeline-card"><h4>{e(s['title'])}</h4><p>{e(s['description'])}</p><div class="chips"><span>⌖ {e(s['room'] or 'Chưa cập nhật')}</span><span>♙ {e(s['speaker_name'] or 'Chưa có diễn giả')}</span></div></div></div>''' for s in sessions)
                faq_html=''.join(f'<details><summary>{e(f["question"])}</summary><p>{e(f["answer"])}</p></details>' for f in faqs)
                admin_actions=''
                if user and user['role'] in ('admin','organizer'):
                    admin_actions=f'<a class="btn btn-ghost" href="/event-edit?id={eid}">✎ Chỉnh sửa</a><a class="btn btn-soft" href="/manage?event_id={eid}">⚙ Quản lý dữ liệu</a><a class="btn btn-ai" href="/ai?event_id={eid}">✦ AI hỗ trợ</a>'
                body=f'''<section class="event-hero"><div><div class="chips">{status_badge(ev['status'])}<span>⌖ {e(ev['location'])}</span></div><h2>{e(ev['name'])}</h2><p>{e(ev['description'])}</p><div class="event-info-grid"><div><small>Bắt đầu</small><b>{e(dt(ev['start_time']))}</b></div><div><small>Kết thúc</small><b>{e(dt(ev['end_time']))}</b></div><div><small>Sức chứa</small><b>{ev['capacity']} người</b></div></div><div class="hero-actions"><a class="btn btn-primary" href="/register?event_id={eid}">Đăng ký tham dự</a><a class="btn btn-soft" href="/feedback?event_id={eid}">Gửi phản hồi</a><a class="btn btn-ai" href="/chat?event_id={eid}">✦ Hỏi chatbot</a>{admin_actions}</div></div></section><div class="stats-grid four">{stat_card('◎','Đăng ký',stats['regs'],f"/{ev['capacity']} sức chứa",'blue')}{stat_card('✓','Check-in',stats['checkins'],f"{pct}% tham dự",'green')}{stat_card('★','Phản hồi',stats['feedbacks'],f"{stats['avg_rating'] or 0}/5 trung bình",'amber')}{stat_card('◷','Phiên nội dung',len(sessions),'lịch trình đã tạo','purple')}</div><div class="two-col"><section class="panel"><div class="panel-head"><div><small class="eyebrow">CHƯƠNG TRÌNH</small><h3>Lịch trình sự kiện</h3></div></div><div class="timeline">{session_html or empty_state('Chưa có lịch trình','Ban tổ chức chưa cập nhật phiên nội dung.')}</div></section><section class="panel"><div class="panel-head"><div><small class="eyebrow">FAQ</small><h3>Câu hỏi thường gặp</h3></div></div><div class="faq-list">{faq_html or empty_state('Chưa có FAQ','Chưa có câu hỏi thường gặp.')}</div></section></div>'''
                self.send_html(ev['name'],body,user,"events",flash=self.flash_from_query(q))

            elif path == "/register":
                eid=int(fv(q,"event_id","0")); ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
                if not ev:return self.send_html("Đăng ký","<div class='panel'>Không tìm thấy sự kiện.</div>",user,code=404)
                body=f'''<div class="split-card"><div class="info-pane"><span class="eyebrow">ĐĂNG KÝ / VÉ</span><h2>{e(ev['name'])}</h2><p>⌖ {e(ev['location'])}</p><p>◷ {e(dt(ev['start_time']))}</p><div class="notice">Sau khi đăng ký thành công, hệ thống sinh <b>mã đăng ký/QR ở mức demo</b> dùng cho check-in.</div></div><form class="panel form-stack" method="post"><input type="hidden" name="event_id" value="{eid}"><label>Họ và tên *<input name="full_name" required></label><label>Email *<input type="email" name="email" required></label><label>Số điện thoại<input name="phone"></label><label>Loại vé<select name="ticket_type"><option>Standard</option><option>VIP</option><option>Khách mời</option></select></label><button class="btn btn-primary btn-block">Hoàn tất đăng ký</button></form></div>'''
                self.send_html("Đăng ký tham dự",body,user,"events")

            elif path == "/ticket":
                code=fv(q,"code"); row=conn.execute("""SELECT r.*,a.full_name,a.email,e.name event_name,e.start_time,e.location FROM registrations r JOIN attendees a ON a.id=r.attendee_id JOIN events e ON e.id=r.event_id WHERE r.registration_code=?""",(code,)).fetchone()
                if not row:return self.send_html("Vé","<div class='panel'>Không tìm thấy mã đăng ký.</div>",user,code=404)
                qr = ''.join('<i></i>' if (ord(ch)+i)%3 else '<i class="dark"></i>' for i,ch in enumerate((code*12)[:144]))
                body=f'''<div class="ticket"><div class="ticket-main"><div class="ticket-brand"><b>EventAI</b>{badge(row['ticket_type'],'info')}</div><small>VÉ THAM DỰ / REGISTRATION TICKET</small><h2>{e(row['event_name'])}</h2><div class="ticket-grid"><div><small>Người tham dự</small><b>{e(row['full_name'])}</b></div><div><small>Thời gian</small><b>{e(dt(row['start_time']))}</b></div><div><small>Địa điểm</small><b>{e(row['location'])}</b></div><div><small>Trạng thái</small><b>{e(row['status'])}</b></div></div></div><div class="ticket-code"><div class="fake-qr">{qr}</div><small>MÃ ĐĂNG KÝ</small><strong>{e(row['registration_code'])}</strong><p>Trình mã này tại quầy check-in</p></div></div>'''
                self.send_html("Vé tham dự",body,user,"events")

            elif path == "/checkin":
                u=self.require("admin","organizer","checkin")
                if not u:return
                recent=conn.execute("""SELECT c.checked_in_at,a.full_name,e.name event_name,r.registration_code FROM checkins c JOIN registrations r ON r.id=c.registration_id JOIN attendees a ON a.id=r.attendee_id JOIN events e ON e.id=r.event_id ORDER BY c.id DESC LIMIT 8""").fetchall()
                rows=''.join(f'<tr><td>{e(x["full_name"])}</td><td><code>{e(x["registration_code"])}</code></td><td>{e(x["event_name"])}</td><td>{e(dt(x["checked_in_at"]))}</td></tr>' for x in recent)
                body=f'''<div class="checkin-layout"><section class="scan-card"><div class="scan-icon">⌁</div><span class="eyebrow">CHECK-IN NHANH</span><h2>Quét/nhập mã đăng ký</h2><p>Hệ thống kiểm tra mã hợp lệ và tự động ngăn check-in nhiều lần.</p><form method="post"><input class="code-input" name="code" autofocus required placeholder="VD: EV1-1A2B3C4D"><div class="segmented"><label><input type="radio" name="method" value="code" checked> Mã đăng ký</label><label><input type="radio" name="method" value="qr"> QR demo</label></div><button class="btn btn-primary btn-block">✓ Xác nhận check-in</button></form></section><section class="panel"><div class="panel-head"><h3>Check-in gần đây</h3><span class="live"><i></i> LIVE</span></div><div class="table-wrap"><table><thead><tr><th>Người tham dự</th><th>Mã</th><th>Sự kiện</th><th>Thời gian</th></tr></thead><tbody>{rows or '<tr><td colspan="4">Chưa có dữ liệu.</td></tr>'}</tbody></table></div></section></div>'''
                self.send_html("Check-in",body,u,"checkin",flash=self.flash_from_query(q))

            elif path == "/feedback":
                eid=int(fv(q,"event_id","0")); ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
                if not ev:return self.send_html("Phản hồi","<div class='panel'>Không tìm thấy sự kiện.</div>",user,code=404)
                body=f'''<div class="split-card"><div class="info-pane purple-pane"><span class="eyebrow">PHẢN HỒI SAU SỰ KIỆN</span><h2>Ý kiến của bạn giúp sự kiện tốt hơn</h2><p>Dữ liệu phản hồi được dùng cho dashboard và chức năng AI tóm tắt. Hệ thống chỉ gửi nội dung văn bản cần thiết cho tác vụ AI.</p></div><form class="panel form-stack" method="post"><input type="hidden" name="event_id" value="{eid}"><label>Mã đăng ký *<input name="code" required placeholder="Mã trên vé tham dự"></label><label>Đánh giá<select name="rating"><option value="5">★★★★★ · Rất tốt</option><option value="4">★★★★☆ · Tốt</option><option value="3">★★★☆☆ · Bình thường</option><option value="2">★★☆☆☆ · Chưa tốt</option><option value="1">★☆☆☆☆ · Kém</option></select></label><label>Nội dung phản hồi *<textarea name="content" rows="7" required placeholder="Điểm bạn hài lòng, vấn đề cần cải thiện, đề xuất..."></textarea></label><button class="btn btn-primary btn-block">Gửi phản hồi</button></form></div>'''
                self.send_html("Gửi phản hồi",body,user,"events")

            elif path == "/chat":
                eid=int(fv(q,"event_id","0")); ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
                if not ev:return self.send_html("Chatbot","<div class='panel'>Không tìm thấy sự kiện.</div>",user,code=404)
                body=f'''<div class="chat-shell"><div class="chat-head"><div class="bot-avatar">✦</div><div><h3>Trợ lý sự kiện</h3><span><i></i> Đang hoạt động · Chỉ trả lời theo dữ liệu sự kiện</span></div></div><div class="chat-window"><div class="message bot"><div class="bubble">Xin chào! Tôi có thể trả lời về <b>thời gian, địa điểm, lịch trình, diễn giả và FAQ</b> của “{e(ev['name'])}”.</div></div><div class="quick-questions"><button onclick="setQuestion('Sự kiện bắt đầu lúc mấy giờ?')">Mấy giờ bắt đầu?</button><button onclick="setQuestion('Sự kiện tổ chức ở đâu?')">Địa điểm ở đâu?</button><button onclick="setQuestion('Cho tôi xem lịch trình và diễn giả')">Lịch trình</button></div></div><form class="chat-input" method="post"><input type="hidden" name="event_id" value="{eid}"><input id="question" name="question" required placeholder="Nhập câu hỏi về sự kiện..."><button class="btn btn-ai">Gửi ✦</button></form></div>'''
                self.send_html("Chatbot hỏi đáp",body,user,"ai")

            elif path == "/dashboard":
                u=self.require("admin","organizer")
                if not u:return
                eid=int(fv(q,"event_id","0") or 0)
                events=conn.execute("SELECT * FROM events ORDER BY start_time DESC").fetchall()
                if not eid and events:eid=events[0]['id']
                ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone() if eid else None
                if not ev:return self.send_html("Dashboard",empty_state("Chưa có dữ liệu","Hãy tạo sự kiện trước."),u,"dashboard")
                stats=conn.execute("""SELECT
                (SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='valid') regs,
                (SELECT COUNT(*) FROM checkins c JOIN registrations r ON r.id=c.registration_id WHERE r.event_id=?) checkins,
                (SELECT COUNT(*) FROM feedbacks WHERE event_id=?) feedbacks,
                (SELECT ROUND(AVG(rating),1) FROM feedbacks WHERE event_id=?) avg_rating,
                (SELECT COUNT(*) FROM notifications WHERE event_id=? AND status='sent') sent_notices
                """,(eid,eid,eid,eid,eid)).fetchone()
                ratings=conn.execute("SELECT rating,COUNT(*) n FROM feedbacks WHERE event_id=? GROUP BY rating ORDER BY rating DESC",(eid,)).fetchall(); rating_map={r['rating']:r['n'] for r in ratings}
                pct=round(stats['checkins']*100/stats['regs'],1) if stats['regs'] else 0
                regpct=round(stats['regs']*100/max(ev['capacity'],1),1)
                opts=''.join(f'<option value="{x["id"]}" {"selected" if x["id"]==eid else ""}>{e(x["name"])}</option>' for x in events)
                bars=''.join(f'<div class="rating-row"><span>{i} ★</span><div><i style="width:{(rating_map.get(i,0)*100/max(stats["feedbacks"],1))}%"></i></div><b>{rating_map.get(i,0)}</b></div>' for i in range(5,0,-1))
                chart_data=json.dumps({"registrations":stats['regs'],"checkins":stats['checkins'],"feedbacks":stats['feedbacks']})
                body=f'''<div class="dashboard-toolbar"><form><label>Sự kiện<select name="event_id" onchange="this.form.submit()">{opts}</select></label></form><a class="btn btn-ai" href="/ai?event_id={eid}&task=summary">✦ AI tóm tắt phản hồi</a></div><div class="stats-grid four">{stat_card('♙','Đăng ký',stats['regs'],f'{regpct}% sức chứa','blue')}{stat_card('✓','Check-in',stats['checkins'],f'{pct}% tỷ lệ tham dự','green')}{stat_card('★','Điểm đánh giá',stats['avg_rating'] or 0,f'{stats["feedbacks"]} phản hồi','amber')}{stat_card('✉','Thông báo đã gửi',stats['sent_notices'],'chiến dịch','purple')}</div><div class="dashboard-grid"><section class="panel chart-panel"><div class="panel-head"><div><small class="eyebrow">TỔNG QUAN</small><h3>Đăng ký · Check-in · Phản hồi</h3></div></div><canvas id="overviewChart" data-values='{e(chart_data)}'></canvas></section><section class="panel"><div class="panel-head"><div><small class="eyebrow">ĐÁNH GIÁ</small><h3>Phân bố mức hài lòng</h3></div><strong class="rating-big">{stats['avg_rating'] or 0}<small>/5</small></strong></div><div class="rating-bars">{bars}</div></section><section class="panel span-2"><div class="panel-head"><div><small class="eyebrow">HIỆU SUẤT VẬN HÀNH</small><h3>Chỉ số mục tiêu</h3></div></div><div class="kpi-list"><div><span>Tỷ lệ lấp đầy</span><b>{regpct}%</b><div class="progress"><i style="width:{min(100,regpct)}%"></i></div></div><div><span>Tỷ lệ tham dự</span><b>{pct}%</b><div class="progress green"><i style="width:{min(100,pct)}%"></i></div></div><div><span>Tỷ lệ phản hồi / check-in</span><b>{round(stats['feedbacks']*100/max(stats['checkins'],1),1)}%</b><div class="progress purple"><i style="width:{min(100,stats['feedbacks']*100/max(stats['checkins'],1))}%"></i></div></div></div></section></div>'''
                self.send_html("Dashboard",body,u,"dashboard",flash=self.flash_from_query(q))

            elif path == "/manage":
                u=self.require("admin","organizer")
                if not u:return
                events=conn.execute("SELECT * FROM events ORDER BY start_time DESC").fetchall(); eid=int(fv(q,"event_id",str(events[0]['id'] if events else 0)))
                ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
                sessions=conn.execute("""SELECT s.*,sp.full_name speaker_name FROM sessions s LEFT JOIN speakers sp ON sp.id=s.speaker_id WHERE s.event_id=? ORDER BY s.start_time""",(eid,)).fetchall() if ev else []
                speakers=conn.execute("SELECT * FROM speakers ORDER BY full_name").fetchall()
                faqs=conn.execute("SELECT * FROM faqs WHERE event_id=? ORDER BY id",(eid,)).fetchall() if ev else []
                regs=conn.execute("""SELECT r.*,a.full_name,a.email,a.phone,(SELECT checked_in_at FROM checkins WHERE registration_id=r.id) checked_in_at FROM registrations r JOIN attendees a ON a.id=r.attendee_id WHERE r.event_id=? ORDER BY r.id DESC LIMIT 100""",(eid,)).fetchall() if ev else []
                notices=conn.execute("SELECT * FROM notifications WHERE event_id=? ORDER BY id DESC LIMIT 20",(eid,)).fetchall() if ev else []
                tabs=f'''<div class="tabs"><button class="tab active" data-tab="schedule">Lịch trình</button><button class="tab" data-tab="attendees">Người tham dự <span>{len(regs)}</span></button><button class="tab" data-tab="faq">FAQ</button><button class="tab" data-tab="notifications">Thông báo</button></div>'''
                sess_rows=''.join(f'<tr><td><b>{e(s["title"])}</b><small>{e(s["description"])}</small></td><td>{e(dt(s["start_time"]))}</td><td>{e(s["room"])}</td><td>{e(s["speaker_name"] or "—")}</td><td><form method="post" action="/session-delete" onsubmit="return confirm(\'Xóa phiên này?\')"><input type="hidden" name="id" value="{s["id"]}"><input type="hidden" name="event_id" value="{eid}"><button class="link-danger">Xóa</button></form></td></tr>' for s in sessions)
                sp_opts=''.join(f'<option value="{sp["id"]}">{e(sp["full_name"])} · {e(sp["organization"])}</option>' for sp in speakers)
                reg_rows=''.join(f'<tr><td><b>{e(r["full_name"])}</b><small>{e(r["email"])}</small></td><td><code>{e(r["registration_code"])}</code></td><td>{badge(r["ticket_type"],"info")}</td><td>{badge("Đã check-in","success") if r["checked_in_at"] else badge("Chưa check-in","warning")}</td><td>{e(dt(r["registered_at"]))}</td></tr>' for r in regs)
                faq_rows=''.join(f'<div class="faq-admin"><div><b>{e(f["question"])}</b><p>{e(f["answer"])}</p></div><form method="post" action="/faq-delete"><input type="hidden" name="id" value="{f["id"]}"><input type="hidden" name="event_id" value="{eid}"><button class="link-danger">Xóa</button></form></div>' for f in faqs)
                notice_rows=''.join(f'<tr><td><b>{e(n["subject"])}</b><small>{e(n["type"])} · {e(n["audience"])}</small></td><td>{badge("Đã gửi","success") if n["status"]=="sent" else badge("Bản nháp","warning")}</td><td>{n["recipient_count"]}</td><td>{e(dt(n["created_at"]))}</td><td>{f"<form method=\"post\" action=\"/notification-send\"><input type=\"hidden\" name=\"id\" value=\"{n['id']}\"><input type=\"hidden\" name=\"event_id\" value=\"{eid}\"><button class=\"link-primary\">Đánh dấu đã gửi</button></form>" if n['status']!='sent' else '—'}</td></tr>' for n in notices)
                event_opts=''.join(f'<option value="{x["id"]}" {"selected" if x["id"]==eid else ""}>{e(x["name"])}</option>' for x in events)
                body=f'''<div class="dashboard-toolbar"><form><label>Đang quản lý<select name="event_id" onchange="this.form.submit()">{event_opts}</select></label></form><div class="hero-actions"><a class="btn btn-ghost" href="/event-edit?id={eid}">Chỉnh sửa sự kiện</a><a class="btn btn-ai" href="/ai?event_id={eid}">✦ AI hỗ trợ</a></div></div>{tabs}<section class="tab-panel active" id="tab-schedule"><div class="manage-grid"><div class="panel"><div class="panel-head"><h3>Lịch trình & diễn giả</h3></div><div class="table-wrap"><table><thead><tr><th>Phiên</th><th>Thời gian</th><th>Phòng</th><th>Diễn giả</th><th></th></tr></thead><tbody>{sess_rows or '<tr><td colspan="5">Chưa có lịch trình.</td></tr>'}</tbody></table></div></div><form class="panel form-stack" method="post" action="/session-new"><h3>＋ Thêm phiên nội dung</h3><input type="hidden" name="event_id" value="{eid}"><label>Tiêu đề<input name="title" required></label><div class="form-grid compact"><label>Bắt đầu<input type="datetime-local" name="start_time" required></label><label>Kết thúc<input type="datetime-local" name="end_time" required></label></div><label>Phòng<input name="room"></label><label>Diễn giả<select name="speaker_id"><option value="">— Chưa chọn —</option>{sp_opts}</select></label><label>Mô tả<textarea name="description" rows="3"></textarea></label><button class="btn btn-primary">Thêm phiên</button><a class="link" href="/speakers">Quản lý danh sách diễn giả →</a></form></div></section><section class="tab-panel" id="tab-attendees"><div class="panel"><div class="panel-head"><div><h3>Danh sách đăng ký / vé</h3><p>Tối đa 100 bản ghi gần nhất.</p></div></div><div class="table-wrap"><table><thead><tr><th>Người tham dự</th><th>Mã đăng ký</th><th>Vé</th><th>Check-in</th><th>Đăng ký lúc</th></tr></thead><tbody>{reg_rows or '<tr><td colspan="5">Chưa có đăng ký.</td></tr>'}</tbody></table></div></div></section><section class="tab-panel" id="tab-faq"><div class="manage-grid"><div class="panel"><h3>Cơ sở tri thức FAQ</h3>{faq_rows or empty_state('Chưa có FAQ','Thêm câu hỏi để chatbot có thêm ngữ cảnh.')}</div><form class="panel form-stack" method="post" action="/faq-new"><h3>＋ Thêm FAQ</h3><input type="hidden" name="event_id" value="{eid}"><label>Câu hỏi<input name="question" required></label><label>Câu trả lời<textarea name="answer" rows="5" required></textarea></label><button class="btn btn-primary">Lưu FAQ</button></form></div></section><section class="tab-panel" id="tab-notifications"><div class="panel"><div class="panel-head"><div><h3>Thông báo cho người tham dự</h3><p>Gửi/thống kê thông báo ở mức demo; hệ thống không gửi email thật.</p></div><a class="btn btn-ai" href="/ai?event_id={eid}&task=notice">✦ Sinh bằng AI</a></div><div class="table-wrap"><table><thead><tr><th>Nội dung</th><th>Trạng thái</th><th>Số người nhận</th><th>Tạo lúc</th><th></th></tr></thead><tbody>{notice_rows or '<tr><td colspan="5">Chưa có thông báo.</td></tr>'}</tbody></table></div></div></section>'''
                self.send_html("Quản lý sự kiện",body,u,"manage",flash=self.flash_from_query(q))

            elif path == "/speakers":
                u=self.require("admin","organizer")
                if not u:return
                rows=conn.execute("SELECT * FROM speakers ORDER BY full_name").fetchall()
                cards=''.join(f'<div class="person-card"><div class="avatar large">{e(x["full_name"][0])}</div><div><h4>{e(x["full_name"])}</h4><span>{e(x["organization"] or "")}</span><p>{e(x["bio"] or "")}</p></div><form method="post" action="/speaker-delete" onsubmit="return confirm(\'Xóa diễn giả?\')"><input type="hidden" name="id" value="{x["id"]}"><button class="link-danger">Xóa</button></form></div>' for x in rows)
                body=f'''<div class="manage-grid"><section class="panel"><div class="panel-head"><h3>Danh sách diễn giả</h3></div><div class="person-list">{cards or empty_state('Chưa có diễn giả','Hãy thêm diễn giả mới.')}</div></section><form class="panel form-stack" method="post"><h3>＋ Thêm diễn giả</h3><label>Họ tên<input name="full_name" required></label><label>Đơn vị / tổ chức<input name="organization"></label><label>Tiểu sử ngắn<textarea name="bio" rows="5"></textarea></label><button class="btn btn-primary">Thêm diễn giả</button></form></div>'''
                self.send_html("Quản lý diễn giả",body,u,"manage",flash=self.flash_from_query(q))

            elif path in ("/ai","/ai-center"):
                u=self.require("admin","organizer")
                if not u:return
                events=conn.execute("SELECT * FROM events ORDER BY start_time DESC").fetchall(); eid=int(fv(q,"event_id",str(events[0]['id'] if events else 0))); task=fv(q,"task","notice")
                ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone() if eid else None
                event_opts=''.join(f'<option value="{x["id"]}" {"selected" if x["id"]==eid else ""}>{e(x["name"])}</option>' for x in events)
                logs=conn.execute("SELECT * FROM ai_logs WHERE event_id=? ORDER BY id DESC LIMIT 8",(eid,)).fetchall() if eid else []
                log_rows=''.join(f'<div class="ai-log"><span>{badge(x["task_type"],"info")}</span><div><b>{e(x["output_text"][:90])}{"…" if len(x["output_text"])>90 else ""}</b><small>{e(dt(x["created_at"]))} · {"Đã duyệt" if x["verified"] else "Chưa duyệt"}</small></div>{"" if x["verified"] else f"<form method=\"post\" action=\"/ai-verify\"><input type=\"hidden\" name=\"id\" value=\"{x['id']}\"><input type=\"hidden\" name=\"event_id\" value=\"{eid}\"><button class=\"link-primary\">Duyệt</button></form>"}</div>' for x in logs)
                body=f'''<div class="ai-banner"><div class="ai-orb">✦</div><div><small class="eyebrow">AI ENGINE · LOCAL DEMO</small><h2>Trợ lý AI cho vận hành sự kiện</h2><p>Ba chức năng theo báo cáo: sinh thông báo, tóm tắt phản hồi và chatbot hỏi đáp. Kết quả AI là nội dung hỗ trợ, cần người dùng kiểm tra trước khi sử dụng.</p></div></div><div class="dashboard-toolbar"><form><label>Sự kiện<select name="event_id" onchange="location='/ai?event_id='+this.value">{event_opts}</select></label></form></div><div class="ai-tools"><a class="ai-tool {('active' if task=='notice' else '')}" href="/ai?event_id={eid}&task=notice"><span>✉</span><div><b>Sinh thông báo</b><small>Mời · nhắc lịch · cảm ơn</small></div></a><a class="ai-tool {('active' if task=='summary' else '')}" href="/ai?event_id={eid}&task=summary"><span>≋</span><div><b>Tóm tắt phản hồi</b><small>Nhóm ý kiến chính</small></div></a><a class="ai-tool" href="/chat?event_id={eid}"><span>✦</span><div><b>Chatbot sự kiện</b><small>Hỏi đáp theo dữ liệu</small></div></a></div>'''
                if task=='summary':
                    body += f'''<form class="panel form-stack" method="post"><input type="hidden" name="event_id" value="{eid}"><input type="hidden" name="task" value="summary"><div class="panel-head"><div><h3>AI tóm tắt phản hồi</h3><p>Chỉ xử lý nội dung phản hồi; không gửi email/số điện thoại cho AI.</p></div></div><button class="btn btn-ai">✦ Tạo bản tóm tắt mới</button></form>'''
                else:
                    body += f'''<form class="panel form-grid" method="post"><input type="hidden" name="event_id" value="{eid}"><input type="hidden" name="task" value="notice"><div class="field"><label>Loại thông báo</label><select name="notice_type"><option value="invite">Mời tham dự</option><option value="reminder" selected>Nhắc lịch</option><option value="thanks">Cảm ơn sau sự kiện</option></select></div><div class="field"><label>Nhóm người nhận</label><input name="audience" value="Sinh viên đã đăng ký"></div><div class="field"><label>Giọng điệu</label><select name="tone"><option>Lịch sự</option><option>Thân thiện</option><option>Trang trọng</option></select></div><div class="field"><label>Ràng buộc</label><input value="Không tự thêm thời gian, địa điểm, diễn giả" disabled></div><div class="form-actions span-2"><button class="btn btn-ai">✦ Sinh nội dung</button></div></form>'''
                body += f'''<section class="panel"><div class="panel-head"><div><small class="eyebrow">AI LOGS</small><h3>Nhật ký sử dụng AI</h3></div></div><div class="ai-log-list">{log_rows or empty_state('Chưa có nhật ký AI','Thực hiện một tác vụ AI để tạo log.')}</div></section>'''
                self.send_html("AI Center",body,u,"ai",flash=self.flash_from_query(q))

            elif path == "/users":
                u=self.require("admin")
                if not u:return
                rows=conn.execute("SELECT * FROM users ORDER BY id").fetchall()
                tr=''.join(f'<tr><td><div class="user-cell"><div class="avatar">{e(x["full_name"][0])}</div><div><b>{e(x["full_name"])}</b><small>@{e(x["username"])}</small></div></div></td><td>{badge(ROLE_LABEL.get(x["role"],x["role"]),"info")}</td><td>{badge("Hoạt động","success") if x["status"]=="active" else badge("Đã khóa","danger")}</td><td>{e(dt(x["created_at"]))}</td><td>{'' if x['username']=='admin' else f'<form method="post"><input type="hidden" name="id" value="{x["id"]}"><button class="link-primary">{"Khóa" if x["status"]=="active" else "Mở khóa"}</button></form>'}</td></tr>' for x in rows)
                body=f'''<div class="panel"><div class="panel-head"><div><h3>Tài khoản & phân quyền</h3><p>Quản trị viên · Ban tổ chức · Nhân viên check-in</p></div></div><div class="table-wrap"><table><thead><tr><th>Tài khoản</th><th>Vai trò</th><th>Trạng thái</th><th>Ngày tạo</th><th></th></tr></thead><tbody>{tr}</tbody></table></div></div>'''
                self.send_html("Người dùng & phân quyền",body,u,"users",flash=self.flash_from_query(q))

            elif path == "/api/stats":
                eid=int(fv(q,"event_id","0")); row=conn.execute("""SELECT (SELECT COUNT(*) FROM registrations WHERE event_id=?) registrations,(SELECT COUNT(*) FROM checkins c JOIN registrations r ON r.id=c.registration_id WHERE r.event_id=?) checkins,(SELECT COUNT(*) FROM feedbacks WHERE event_id=?) feedbacks""",(eid,eid,eid)).fetchone(); self.send_json(dict(row))
            else:
                self.send_html("404",'<div class="panel"><h2>404 · Không tìm thấy trang</h2><a class="btn" href="/">Về trang chủ</a></div>',user,code=404)
        finally:
            conn.close()

    def do_POST(self):
        parsed=urlparse(self.path); path=parsed.path; data=self.post_data(); user=self.current_user(); conn=connect()
        try:
            if path=="/login":
                username=fv(data,"username").strip(); password=fv(data,"password")
                row=conn.execute("SELECT * FROM users WHERE username=? AND status='active'",(username,)).fetchone()
                if not row or row['password_hash']!=hash_password(password):
                    return self.send_html("Đăng nhập",'<div class="auth-wrap"><div class="auth-card"><h2>Đăng nhập thất bại</h2><div class="alert alert-error">! Sai tài khoản hoặc mật khẩu.</div><a class="btn btn-primary" href="/login">Thử lại</a></div></div>',code=400)
                sid=secrets.token_urlsafe(32); SESSIONS[sid]=row['id']; return self.redirect("/",f"sid={sid}; HttpOnly; SameSite=Lax; Path=/")

            if path in ("/event-new","/event-edit"):
                u=self.require("admin","organizer");
                if not u:return
                name=fv(data,"name").strip(); start=fv(data,"start_time"); end=fv(data,"end_time"); location=fv(data,"location").strip()
                try: capacity=max(1,int(fv(data,"capacity","200")))
                except: capacity=200
                if not name or not start or not end or not location or end<=start:
                    return self.redirect(redirect_with_msg("/","Dữ liệu sự kiện không hợp lệ.","error"))
                values=(name,start,end,location,fv(data,"description").strip(),fv(data,"status","draft"),capacity,fv(data,"registration_deadline") or None)
                event_id=fv(data,"id")
                if event_id:
                    conn.execute("UPDATE events SET name=?,start_time=?,end_time=?,location=?,description=?,status=?,capacity=?,registration_deadline=? WHERE id=?",values+(int(event_id),)); eid=int(event_id)
                else:
                    conn.execute("INSERT INTO events(created_by,name,start_time,end_time,location,description,status,capacity,registration_deadline,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(u['id'],)+values+(now_iso(),)); eid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.commit(); return self.redirect(redirect_with_msg(f"/event?id={eid}","Đã lưu thông tin sự kiện."))

            if path=="/register":
                eid=int(fv(data,"event_id","0")); ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
                if not ev:return self.send_html("Đăng ký","<div class='panel'>Sự kiện không tồn tại.</div>",user,code=404)
                if ev['status']!='open':return self.send_html("Đăng ký",'<div class="panel"><div class="alert alert-error">Sự kiện hiện không mở đăng ký.</div><a class="btn" href="/">Quay lại</a></div>',user,code=400)
                full_name=fv(data,"full_name").strip(); email=fv(data,"email").strip().lower(); phone=fv(data,"phone").strip()
                if not full_name or not valid_email(email):return self.send_html("Đăng ký",'<div class="panel"><div class="alert alert-error">Họ tên hoặc email không hợp lệ.</div></div>',user,code=400)
                count=conn.execute("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='valid'",(eid,)).fetchone()[0]
                if count>=ev['capacity']:return self.send_html("Đăng ký",'<div class="panel"><div class="alert alert-error">Sự kiện đã đủ số lượng người tham dự.</div></div>',user,code=400)
                attendee=conn.execute("SELECT * FROM attendees WHERE email=?",(email,)).fetchone()
                if attendee:
                    aid=attendee['id']; conn.execute("UPDATE attendees SET full_name=?,phone=? WHERE id=?",(full_name,phone,aid))
                else:
                    conn.execute("INSERT INTO attendees(full_name,email,phone) VALUES(?,?,?)",(full_name,email,phone)); aid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                try:
                    code=new_registration_code(eid); conn.execute("INSERT INTO registrations(event_id,attendee_id,registration_code,ticket_type,registered_at,status) VALUES(?,?,?,?,?,?)",(eid,aid,code,fv(data,"ticket_type","Standard"),now_iso(),"valid")); conn.commit(); return self.redirect(f"/ticket?code={quote(code)}")
                except sqlite3.IntegrityError:
                    return self.send_html("Đăng ký",f'<div class="panel"><div class="alert alert-error">Bạn đã đăng ký sự kiện này. Không tạo đăng ký trùng.</div><a class="btn" href="/event?id={eid}">Quay lại sự kiện</a></div>',user,code=400)

            if path=="/checkin":
                u=self.require("admin","organizer","checkin");
                if not u:return
                code=fv(data,"code").strip().upper(); reg=conn.execute("""SELECT r.*,a.full_name,e.name event_name FROM registrations r JOIN attendees a ON a.id=r.attendee_id JOIN events e ON e.id=r.event_id WHERE r.registration_code=? AND r.status='valid'""",(code,)).fetchone()
                if not reg:return self.redirect(redirect_with_msg("/checkin","Mã đăng ký không hợp lệ hoặc đã bị hủy.","error"))
                if conn.execute("SELECT 1 FROM checkins WHERE registration_id=?",(reg['id'],)).fetchone():return self.redirect(redirect_with_msg("/checkin",f"{reg['full_name']} đã check-in trước đó. Hệ thống không tạo check-in lần hai.","error"))
                conn.execute("INSERT INTO checkins(registration_id,checked_by,checked_in_at,method) VALUES(?,?,?,?)",(reg['id'],u['id'],now_iso(),fv(data,"method","code"))); conn.commit(); return self.redirect(redirect_with_msg("/checkin",f"Check-in thành công: {reg['full_name']} · {reg['event_name']}."))

            if path=="/feedback":
                eid=int(fv(data,"event_id","0")); code=fv(data,"code").strip().upper(); content=fv(data,"content").strip()
                reg=conn.execute("SELECT * FROM registrations WHERE event_id=? AND registration_code=? AND status='valid'",(eid,code)).fetchone()
                if not reg:return self.send_html("Phản hồi",'<div class="panel"><div class="alert alert-error">Không tìm thấy đăng ký hợp lệ.</div></div>',user,code=400)
                try:
                    rating=int(fv(data,"rating","5")); assert 1<=rating<=5
                except:return self.send_html("Phản hồi",'<div class="panel">Mức đánh giá không hợp lệ.</div>',user,code=400)
                if not content:return self.send_html("Phản hồi",'<div class="panel">Vui lòng nhập nội dung phản hồi.</div>',user,code=400)
                try:
                    conn.execute("INSERT INTO feedbacks(event_id,registration_id,rating,content,submitted_at) VALUES(?,?,?,?,?)",(eid,reg['id'],rating,content,now_iso())); conn.commit(); return self.redirect(redirect_with_msg(f"/event?id={eid}","Cảm ơn bạn đã gửi phản hồi."))
                except sqlite3.IntegrityError:return self.send_html("Phản hồi",'<div class="panel"><div class="alert alert-error">Đăng ký này đã gửi phản hồi trước đó.</div></div>',user,code=400)

            if path=="/chat":
                eid=int(fv(data,"event_id","0")); question=fv(data,"question").strip(); ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone(); sessions=conn.execute("SELECT s.*,sp.full_name speaker_name FROM sessions s LEFT JOIN speakers sp ON sp.id=s.speaker_id WHERE s.event_id=? ORDER BY s.start_time",(eid,)).fetchall(); faqs=conn.execute("SELECT * FROM faqs WHERE event_id=?",(eid,)).fetchall(); ans,source=chatbot_answer(ev,sessions,faqs,question); conn.execute("INSERT INTO ai_logs(event_id,user_id,task_type,input_summary,output_text,created_at,verified) VALUES(?,?,?,?,?,?,?)",(eid,user['id'] if user else None,'chatbot',question[:300],ans,now_iso(),0)); conn.commit(); body=f'''<div class="chat-shell"><div class="chat-head"><div class="bot-avatar">✦</div><div><h3>Trợ lý sự kiện</h3><span><i></i> Nguồn: {e(source)}</span></div></div><div class="chat-window"><div class="message user"><div class="bubble">{e(question)}</div></div><div class="message bot"><div class="bubble">{e(ans).replace(chr(10),'<br>')}</div></div><div class="source-note">Chatbot chỉ sử dụng mô tả, lịch trình và FAQ. Nếu thiếu dữ liệu sẽ không tự suy đoán.</div></div><form class="chat-input" method="post"><input type="hidden" name="event_id" value="{eid}"><input id="question" name="question" required placeholder="Hỏi tiếp..."><button class="btn btn-ai">Gửi ✦</button></form></div>'''; return self.send_html("Chatbot hỏi đáp",body,user,"ai")

            if path=="/session-new":
                u=self.require("admin","organizer");
                if not u:return
                eid=int(fv(data,"event_id")); conn.execute("INSERT INTO sessions(event_id,speaker_id,title,start_time,end_time,room,description) VALUES(?,?,?,?,?,?,?)",(eid,int(fv(data,"speaker_id")) if fv(data,"speaker_id") else None,fv(data,"title"),fv(data,"start_time"),fv(data,"end_time"),fv(data,"room"),fv(data,"description"))); conn.commit(); return self.redirect(redirect_with_msg(f"/manage?event_id={eid}","Đã thêm phiên nội dung."))
            if path=="/session-delete":
                u=self.require("admin","organizer");
                if not u:return
                eid=int(fv(data,"event_id")); conn.execute("DELETE FROM sessions WHERE id=?",(int(fv(data,"id")),)); conn.commit(); return self.redirect(redirect_with_msg(f"/manage?event_id={eid}","Đã xóa phiên nội dung."))
            if path=="/faq-new":
                u=self.require("admin","organizer");
                if not u:return
                eid=int(fv(data,"event_id")); conn.execute("INSERT INTO faqs(event_id,question,answer) VALUES(?,?,?)",(eid,fv(data,"question"),fv(data,"answer"))); conn.commit(); return self.redirect(redirect_with_msg(f"/manage?event_id={eid}","Đã thêm FAQ."))
            if path=="/faq-delete":
                u=self.require("admin","organizer");
                if not u:return
                eid=int(fv(data,"event_id")); conn.execute("DELETE FROM faqs WHERE id=?",(int(fv(data,"id")),)); conn.commit(); return self.redirect(redirect_with_msg(f"/manage?event_id={eid}","Đã xóa FAQ."))

            if path=="/speakers":
                u=self.require("admin","organizer");
                if not u:return
                conn.execute("INSERT INTO speakers(full_name,organization,bio) VALUES(?,?,?)",(fv(data,"full_name"),fv(data,"organization"),fv(data,"bio"))); conn.commit(); return self.redirect(redirect_with_msg("/speakers","Đã thêm diễn giả."))
            if path=="/speaker-delete":
                u=self.require("admin","organizer");
                if not u:return
                conn.execute("DELETE FROM speakers WHERE id=?",(int(fv(data,"id")),)); conn.commit(); return self.redirect(redirect_with_msg("/speakers","Đã xóa diễn giả."))

            if path=="/ai":
                u=self.require("admin","organizer");
                if not u:return
                eid=int(fv(data,"event_id")); ev=conn.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone(); task=fv(data,"task")
                if task=="summary":
                    rows=conn.execute("SELECT rating,content FROM feedbacks WHERE event_id=? ORDER BY id",(eid,)).fetchall(); result=summarize_feedback(rows); output=result['text']; conn.execute("INSERT INTO ai_logs(event_id,user_id,task_type,input_summary,output_text,created_at,verified) VALUES(?,?,?,?,?,?,0)",(eid,u['id'],'summarize_feedback',f"{len(rows)} phản hồi",output,now_iso())); conn.commit()
                    def section(label,items,cls): return f'<div class="summary-group {cls}"><h4>{label} <span>{len(items)}</span></h4>{"".join(f"<p>• {e(x)}</p>" for x in items) or "<p>Chưa xác định từ dữ liệu hiện có.</p>"}</div>'
                    body=f'''<div class="ai-result"><div class="ai-result-head"><div class="ai-orb">✦</div><div><span class="eyebrow">AI TÓM TẮT PHẢN HỒI</span><h2>{e(ev['name'])}</h2><p>{e(output)}</p></div></div><div class="summary-grid">{section('Ý kiến tích cực',result['positive'],'positive')}{section('Vấn đề cần cải thiện',result['improvement'],'improve')}{section('Đề xuất',result['suggestion'],'suggest')}</div><div class="notice">Kết quả tổng hợp từ <b>{result['count']}</b> phản hồi nguồn. Nội dung cần được ban tổ chức kiểm tra trước khi sử dụng.</div><a class="btn btn-ai" href="/ai?event_id={eid}&task=summary">Quay lại AI Center</a></div>'''; return self.send_html("Kết quả AI tóm tắt",body,u,"ai")
                subject,content=generate_notification(ev,fv(data,"audience"),fv(data,"notice_type","reminder"),fv(data,"tone","Lịch sự")); recipient_count=conn.execute("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='valid'",(eid,)).fetchone()[0]; conn.execute("INSERT INTO notifications(event_id,created_by,type,audience,subject,content,created_at,status,recipient_count) VALUES(?,?,?,?,?,?,?,?,?)",(eid,u['id'],fv(data,"notice_type"),fv(data,"audience"),subject,content,now_iso(),'draft',recipient_count)); conn.execute("INSERT INTO ai_logs(event_id,user_id,task_type,input_summary,output_text,created_at,verified) VALUES(?,?,?,?,?,?,0)",(eid,u['id'],'generate_notification',f"{fv(data,'notice_type')} · {fv(data,'audience')}",subject+"\n"+content,now_iso())); conn.commit(); body=f'''<div class="ai-result"><div class="ai-result-head"><div class="ai-orb">✦</div><div><span class="eyebrow">BẢN NHÁP AI</span><h2>{e(subject)}</h2><p>Đối tượng: {e(fv(data,'audience'))}</p></div></div><div class="email-preview"><div class="email-row"><small>Subject</small><b>{e(subject)}</b></div><div class="email-content">{e(content).replace(chr(10),'<br>')}</div></div><div class="notice">AI không tự thêm dữ kiện ngoài thông tin sự kiện. Hãy kiểm tra/chỉnh sửa trước khi gửi chính thức. Bản nháp đã được lưu vào mục Thông báo.</div><div class="hero-actions"><a class="btn btn-ai" href="/ai?event_id={eid}">Tạo nội dung khác</a><a class="btn btn-primary" href="/manage?event_id={eid}">Quản lý thông báo</a></div></div>'''; return self.send_html("Kết quả AI sinh thông báo",body,u,"ai")

            if path=="/notification-send":
                u=self.require("admin","organizer");
                if not u:return
                nid=int(fv(data,"id")); eid=int(fv(data,"event_id")); conn.execute("UPDATE notifications SET status='sent',sent_at=? WHERE id=?",(now_iso(),nid)); conn.commit(); return self.redirect(redirect_with_msg(f"/manage?event_id={eid}","Đã đánh dấu thông báo là đã gửi (demo)."))
            if path=="/ai-verify":
                u=self.require("admin","organizer");
                if not u:return
                eid=int(fv(data,"event_id")); conn.execute("UPDATE ai_logs SET verified=1 WHERE id=?",(int(fv(data,"id")),)); conn.commit(); return self.redirect(redirect_with_msg(f"/ai?event_id={eid}","Đã đánh dấu kết quả AI là đã kiểm tra."))
            if path=="/users":
                u=self.require("admin");
                if not u:return
                uid=int(fv(data,"id")); row=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone(); new='inactive' if row['status']=='active' else 'active'; conn.execute("UPDATE users SET status=? WHERE id=?",(new,uid)); conn.commit(); return self.redirect(redirect_with_msg("/users","Đã cập nhật trạng thái tài khoản."))

            self.send_html("404","<div class='panel'>Không tìm thấy tác vụ.</div>",user,code=404)
        except Exception as ex:
            conn.rollback()
            self.send_html("Lỗi hệ thống",f'<div class="panel"><div class="alert alert-error">Không thể hoàn tất thao tác: {e(str(ex))}</div><a class="btn" href="/">Quay lại</a></div>',user,code=500)
        finally:
            conn.close()


if __name__ == "__main__":
    os.chdir(BASE_DIR)
    init_db()
    print("="*64)
    print(f"EventAI PRO đang chạy tại: http://{HOST}:{PORT}")
    print("Tài khoản: admin/admin123 | organizer/organizer123 | checkin/checkin123")
    print("Dừng server: Ctrl+C")
    print("="*64)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
