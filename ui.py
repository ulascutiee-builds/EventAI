from html import escape


# ============================================================
# LABEL / TÊN HIỂN THỊ
# ============================================================

ROLE_LABEL = {
    "admin": "Quản trị viên",
    "organizer": "Ban tổ chức",
    "checkin": "Nhân viên check-in",
}

STATUS_LABEL = {
    "draft": "Nháp",
    "open": "Mở đăng ký",
    "closed": "Đóng đăng ký",
    "completed": "Đã kết thúc",
    "cancelled": "Đã hủy",
    "valid": "Hợp lệ",
}


# ============================================================
# HÀM HỖ TRỢ
# ============================================================

def e(value):
    return escape(str(value or ""))


def badge(text, kind="neutral"):
    return (
        f'<span class="badge badge-{kind}">'
        f'{e(text)}'
        f'</span>'
    )


# ============================================================
# GIAO DIỆN CHÍNH
# ============================================================

def page(title, body, user=None, active="", flash=None):

    # --------------------------------------------------------
    # 1. THÔNG TIN NGƯỜI DÙNG
    # --------------------------------------------------------

    if user:
        userbox = f'''
        <div class="user-menu">

            <div class="avatar">
                {e(user['full_name'][:1].upper())}
            </div>

            <div>
                <strong>
                    {e(user['full_name'])}
                </strong>

                <small>
                    {e(ROLE_LABEL.get(user['role'], user['role']))}
                </small>
            </div>

            <a
                class="icon-btn"
                href="/logout"
                title="Đăng xuất"
            >
                ↪
            </a>

        </div>
        '''
    else:
        userbox = '''
        <a class="btn btn-primary" href="/login">
            Đăng nhập
        </a>
        '''


    # --------------------------------------------------------
    # 2. MENU ĐIỀU HƯỚNG
    # --------------------------------------------------------

    nav_items = [
        ("/", "⌂", "Sự kiện", "events"),
        ("/dashboard", "▦", "Dashboard", "dashboard"),
        ("/checkin", "⌁", "Check-in", "checkin"),
    ]


    # Menu dành cho Admin và Ban tổ chức
    if user and user["role"] in ("admin", "organizer"):
        nav_items += [
            ("/manage", "⚙", "Quản lý", "manage"),
            ("/ai-center", "✦", "AI Center", "ai"),
        ]


    # Menu chỉ dành cho Admin
    if user and user["role"] == "admin":
        nav_items += [
            ("/users", "♟", "Người dùng", "users"),
        ]


    # Tạo HTML cho menu
    nav = "".join(
        f'''
        <a
            class="nav-link {"active" if active == key else ""}"
            href="{href}"
        >
            <span>{icon}</span>
            {label}
        </a>
        '''
        for href, icon, label, key in nav_items
    )


    # --------------------------------------------------------
    # 3. THÔNG BÁO FLASH
    # --------------------------------------------------------

    flash_html = ""

    if flash:
        kind, msg = flash

        flash_icon = "✓" if kind == "success" else "!"

        flash_html = f'''
        <div class="alert alert-{e(kind)}">

            <span>
                {flash_icon}
            </span>

            <div>
                {e(msg)}
            </div>

        </div>
        '''


    # --------------------------------------------------------
    # 4. TRẢ VỀ TOÀN BỘ TRANG HTML
    # --------------------------------------------------------

    return f'''
<!doctype html>

<html lang="vi">

<head>

    <meta charset="utf-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>
        {e(title)} · Hệ thống quản lý sự kiện AI
    </title>

    <link
        rel="stylesheet"
        href="/static/style.css"
    >

    <script
        defer
        src="/static/app.js"
    ></script>

</head>


<body>

    <div class="app-shell">


        <!-- ================================================
             SIDEBAR
        ================================================= -->

        <aside class="sidebar">


            <!-- LOGO / TÊN HỆ THỐNG -->

            <a class="brand" href="/">

                <div class="brand-mark">
                    AI
                </div>

                <div>

                    <b>
                        Event Management AI
                    </b>

                    <small>
                        Hệ thống quản lý sự kiện
                    </small>

                </div>

            </a>


            <!-- MENU -->

            <nav>
                {nav}
            </nav>


            <!-- THÔNG TIN AI LOCAL -->

            <div class="sidebar-foot">

                <div class="ai-chip">

                    <span class="pulse"></span>

                    <div>

                        <strong>
                            AI Service
                        </strong>

                        <small>
                            UlasCutiee
                        </small>

                    </div>

                </div>

            </div>

        </aside>


        <!-- ================================================
             KHU VỰC NỘI DUNG
        ================================================= -->

        <section class="workspace">


            <!-- HEADER -->

            <header class="topbar">

                <button
                    class="mobile-menu"
                    onclick="toggleSidebar()"
                >
                    ☰
                </button>


                <div>

                    <small class="eyebrow">
                        HỆ THỐNG QUẢN LÝ SỰ KIỆN CÓ TÍCH HỢP AI
                    </small>

                    <h1>
                        {e(title)}
                    </h1>

                </div>


                <!-- THÔNG TIN USER -->

                {userbox}

            </header>


            <!-- NỘI DUNG CHÍNH -->

            <main class="content">

                {flash_html}

                {body}

            </main>


            <!-- FOOTER -->

            <footer>
                Nhóm 21 · Hệ thống quản lý sự kiện có tích hợp AI · ICTU 2026
            </footer>


        </section>

    </div>

</body>

</html>
'''


# ============================================================
# THẺ THỐNG KÊ
# ============================================================

def stat_card(
    icon,
    label,
    value,
    note="",
    tone="blue"
):
    return f'''
    <div class="stat-card tone-{tone}">

        <div class="stat-icon">
            {icon}
        </div>

        <div>

            <small>
                {e(label)}
            </small>

            <strong>
                {e(value)}
            </strong>

            <span>
                {e(note)}
            </span>

        </div>

    </div>
    '''


# ============================================================
# TRẠNG THÁI KHÔNG CÓ DỮ LIỆU
# ============================================================

def empty_state(
    title,
    text,
    action=""
):
    return f'''
    <div class="empty">

        <div class="empty-icon">
            ◇
        </div>

        <h3>
            {e(title)}
        </h3>

        <p>
            {e(text)}
        </p>

        {action}

    </div>
    '''