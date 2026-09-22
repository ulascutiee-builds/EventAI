EVENTAI PRO - HỆ THỐNG QUẢN LÝ SỰ KIỆN CÓ TÍCH HỢP AI
=======================================================
Bản tương thích Python 3.14, không cần pip install và không dùng package ngoài.
Thiết kế cho máy Windows có Device Guard/Application Control chặn Pydantic Core.

1. CHẠY HỆ THỐNG
-----------------
Mở CMD hoặc PowerShell tại thư mục này và chạy:

    python -X utf8 server.py

Nếu máy chưa nhận lệnh `python`, cài Python 3.10+ từ python.org rồi chọn
"Add Python to PATH" trong trình cài đặt. Với Python Launcher, có thể dùng:

    py -X utf8 server.py

Sau đó mở trình duyệt:

    http://127.0.0.1:8000

Dừng server: Ctrl + C

2. TÀI KHOẢN DEMO
-----------------
Quản trị viên:       admin / admin123
Ban tổ chức:         organizer / organizer123
Nhân viên check-in:  checkin / checkin123

3. CHỨC NĂNG ĐÃ XÂY DỰNG THEO BÁO CÁO
--------------------------------------
- Đăng nhập và phân quyền 3 vai trò.
- Quản lý sự kiện: tạo, sửa, trạng thái, sức chứa, thời gian, địa điểm, mô tả.
- Quản lý lịch trình, phiên nội dung, phòng và diễn giả.
- Quản lý diễn giả.
- Đăng ký/vé, chống đăng ký trùng, sinh mã đăng ký/QR demo.
- Danh sách người tham dự.
- Check-in bằng mã/QR demo, chống check-in nhiều lần.
- Thu thập phản hồi, giới hạn một phản hồi chính cho mỗi đăng ký/sự kiện.
- Dashboard: đăng ký, check-in, tỷ lệ tham dự, phản hồi, điểm đánh giá, thông báo.
- Quản lý FAQ làm cơ sở tri thức chatbot.
- Thông báo: tạo bản nháp, thống kê số người nhận, trạng thái gửi ở mức demo.
- AI sinh nội dung thông báo mời/nhắc lịch/cảm ơn.
- AI tóm tắt phản hồi theo nhóm: tích cực, cần cải thiện, đề xuất.
- Chatbot hỏi đáp dựa trên mô tả, lịch trình và FAQ; thiếu dữ liệu thì không suy đoán.
- Nhật ký sử dụng AI và trạng thái người dùng đã kiểm tra kết quả.
- Quản lý tài khoản/trạng thái tài khoản cho admin.

4. LƯU Ý AI
-----------
Bản này dùng AI DEMO CỤC BỘ bằng Python chuẩn để chạy được trên máy bị chặn
các thư viện nhị phân. Nó mô phỏng đúng luồng AI trong báo cáo và không gửi dữ liệu
ra Internet. Kết quả AI là nội dung hỗ trợ và cần người dùng duyệt.

Nếu sau này máy cho phép dùng API/SDK AI thật, có thể thay file ai_engine.py bằng
OpenAI/Gemini/Claude mà không cần thay đổi luồng nghiệp vụ chính.

5. DỮ LIỆU
-----------
SQLite tự tạo file event_ai_system.db trong cùng thư mục khi chạy lần đầu.
Để reset dữ liệu demo: dừng server, xóa event_ai_system.db, chạy lại server.py.

6. TEST
-------
Chạy:
    python -m unittest discover -s tests -v

7. DEPLOY RENDER
----------------
File `render.yaml` đã cấu hình Web Service, health check và persistent disk
cho SQLite. Sau khi đẩy lên GitHub, tạo Blueprint trên Render và chọn repo.
Render tự chạy `python server.py`; không cần cài thêm package ngoài.
