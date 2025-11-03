# DỰ ÁN: HỆ THỐNG TỰ ĐỘNG TẠO TÀI KHOẢN GMAIL
# KIẾN TRÚC: GPM Profiles + Python Orchestration + Selenium
# YÊU CẦU CỐ ĐỊNH - KHÔNG ĐƯỢC THAY ĐỔI LOGIC NGHIỆP VỤ

========================================================
I. QUY TẮC NGÔN NGỮ & GIAO TIẾP
========================================================
1. Toàn bộ trao đổi trong Cursor dùng **Tiếng Việt**.
2. Comment trong code bằng **Tiếng Việt**, ngắn gọn & rõ ràng.
3. Tên biến / hàm / file / thư mục giữ **Tiếng Anh** theo chuẩn kỹ thuật quốc tế.
4. Log terminal có thể dùng **Tiếng Việt hoặc song ngữ** để dễ hiểu lỗi.
5. Commit message bằng **Tiếng Việt**, theo chuẩn type:
   - feature: Thêm chức năng mới
   - fix: Sửa lỗi
   - chore: Công việc phụ (config, build…)
   - doc: Viết tài liệu
   - refactor: Cải tiến code không đổi nghiệp vụ
6. Tin/ nút gửi đến operator trên Telegram phải **bằng tiếng Việt**:
   - “Nhập Gmail Recovery cho tài khoản <email>”
   - “✅ Tài khoản <email> đã tạo xong, hệ thống sẽ bấm Complete tự động”
7. Tài liệu hướng dẫn nội bộ → **Viết bằng tiếng Việt**.

========================================================
II. LUỒNG NGHIỆP VỤ CHÍNH
========================================================
0. KHỞI ĐỘNG HỆ THỐNG & ĐẢM BẢO SỐ LƯỢNG ACCOUNTS:
   - Khi hệ thống khởi động, **tự động kiểm tra** số lượng accounts có `status="pending"` trong DB.
   - **Mỗi phiên làm việc yêu cầu 3 accounts** với `status="pending"` để tối ưu hóa việc sử dụng profiles.
   - Logic kiểm tra:
     • Đếm số accounts có `status="pending"` trong DB.
     • Nếu **< 3 accounts pending** → Hệ thống tự động gửi tin nhắn "➕ Register a new Gmail" cho @GmailFarmerBot.
     • Nếu **≥ 3 accounts pending** → Không cần gửi thêm, tiếp tục xử lý các accounts hiện có.
     • Gửi tiếp cho đến khi đạt **đủ 3 accounts pending** (hoặc bot không trả về thêm).
   - Việc gửi tin nhắn cho bot được thực hiện **tự động bởi hệ thống**, không cần operator can thiệp.

1. Khi hệ thống gửi "➕ Register a new Gmail" cho @GmailFarmerBot:
   - Bot trả về message với format:
     • **First name**: (ví dụ: "Georgeanna")
     • **Last name**: (có thể là "X" hoặc tên khác)
     • **Email**: (ví dụ: "ojegoxuzat420@gmail.com")
     • **Password**: (ví dụ: "X7SSQu1bWbtMUV")
     • Message cũng chứa các nút: "✓ Done", "🚫 Cancel registration", "❓ How to create account"
     • Timestamp và metadata của message
   - **Hệ thống parse** message và trích xuất các trường:
     • `first_name`: string
     • `last_name`: string (có thể rỗng hoặc "X")
     • `email`: string (chuẩn hoá lower-case)
     • `password`: string
   - Lưu document vào MongoDB với `status="pending"` cùng các meta (xem dưới).
   - **Lưu ý**: Message từ bot có format cố định, parse theo pattern để trích xuất chính xác các trường.

--- BEGIN: MESSAGE ID & BUTTON MAPPING (BẮT BUỘC) ---

Ngay khi parse message "Register a new Gmail" từ GmailFarmerBot, **bắt buộc** lưu các trường sau trong document MongoDB:

**Trường dữ liệu account:**
- first_name: string (ví dụ: "Georgeanna")
- last_name: string (có thể rỗng hoặc "X")
- email: string (chuẩn hoá lower-case) → **KHÓA CHÍNH**
- password: string

**Trường metadata Telegram:**
- message_id_input: integer (message_id của Telegram message chứa dữ liệu)
- message_chat_id / source_chat_id: id chat nơi message được gửi (dùng để callback)
- message_ts: timestamp của message

**Trường hỗ trợ:**
- operator_notified_at (nullable)
- last_error (nullable)
- screenshot_path (nullable)

Quy tắc thao tác:
1. Mọi thao tác UI (Done / Cancel / Complete) **phải** thực hiện dựa trên tuple (`message_chat_id`, `message_id_input`) — tuyệt đối không click theo vị trí UI.
2. Callback data khi thao tác phải chứa `account_id` (Mongo _id) và `message_id_input`. Ví dụ: `done|<account_id>|<message_id_input>`.
3. Khi TeleMonitor nhận message chứa **Recovery email**, hệ thống tìm document có `status="waiting-recovery"` (ưu tiên) và `email` khớp (nếu có). Thao tác map theo thứ tự:
   - Nếu có **chính xác 1 document** đang `waiting-recovery` → gán `recovery_email` và set `status="recovery-received"`.
   - Nếu không có document nào `waiting-recovery` → tìm document pending gần nhất có email giống message (nếu phù hợp) → else → set `status="waiting-observe"` và notify operator.
   - Nếu có >1 document cùng điều kiện → **không tự gán** → set `status="waiting-observe"` + notify operator.
4. FIFO (created_at ordering) chỉ dùng như fallback nếu không thể match bằng email hoặc message metadata.
5. Nếu Telegram callback API trả lỗi (message đã delete/edited hoặc bị rate limit):
   - Retry callback tối đa 3 lần trong 10 giây.
   - Nếu vẫn lỗi → lưu `last_error`, chụp screenshot, set `status="waiting-observe"`, notify operator.

--- END: MESSAGE ID & BUTTON MAPPING ---

2. Orchestrator chọn:
   - 01 account với `status="pending"`
   - 01 profile với `status="idle"`

3. Gọi API GPM → start profile → nhận `debugPort` → lưu `profile_id` vào document account & profile status → "in_use"

4. Selenium attach debugger → điền form Gmail Signup theo dữ liệu account

5. Nếu yêu cầu OTP:
   - Retry tối đa 3 lần (khoảng delay ngẫu nhiên 2–6s giữa attempts)
   - Nếu vẫn thất bại → set `status="failed-phone"` → STOP profile

6. Khi Gmail yêu cầu Recovery Email:
   - Worker set `status="waiting-recovery"` → notify operator (nếu cần) yêu cầu ấn **Done** trên GmailFarmerBot
   - TeleMonitor sẽ parse message Recovery (chứa recovery email)
   - Hệ thống map Recovery theo quy tắc trong MESSAGE ID block (ở trên)
   - Nếu map thành công → `status="recovery-received"` → Worker resume
   - Nếu không map được → `status="waiting-observe"` → giữ profile mở để operator can thiệp

7. Nếu phát hiện Captcha / QR hoặc trang review bắt buộc tương tác:
   - Chụp screenshot
   - `status="failed-captcha"` (hoặc "failed" nếu không rõ)
   - Stop profile ngay — **KHÔNG** retry (FAIL-FAST)

8. XỬ LÝ SAU KHI SIGNUP (gộp các bước liên quan)
   - Sau khi Worker submit form, kiểm tra phản hồi Bot:
     • Nếu Bot gửi: “⚠️ It seems you haven't added recovery email <recovery_email>”:
         → Worker quay lại Selenium → add `recovery_email` vào account → verify done → tiếp tục.
     • Nếu Bot gửi **video hướng dẫn Settings** hoặc tin nhắn chỉ dẫn thao tác → coi là **tạo thất bại**:
         → chụp screenshot + save log → `status="failed"` → Stop profile.
     • Nếu Bot **không** gửi thêm gì → coi là **thành công**.
   - Khi xác định **thành công**:
       • Worker logout Gmail
       • Update DB: `status="waiting-complete"`
       • Hệ thống **tự động** nhấn nút “❤️ Complete (0.12$)” trên message đã lưu (`message_chat_id`, `message_id_input`)
           - Retry callback tối đa 3 lần trong 10 giây.
           - Nếu callback lỗi → set `status="waiting-observe"` + notify operator
       • Nếu nhấn Complete thành công → `status="created"` → Stop profile → giải phóng tài nguyên

9. Stop profile → Giải phóng tài nguyên

========================================================
III. QUY TẮC BẮT BUỘC (HARD RULES)
========================================================
- KHÔNG dùng GPM No-Code Automation để điền form Gmail.
- Chỉ dùng GPM cho fingerprint + remote-debugger attach.
- Mỗi profile = 01 account (không reuse profile cho nhiều account đồng thời).
- Không warm-up Gmail sau khi tạo.
- Proxy VN bắt buộc cho mỗi profile (ZingProxy API).
- Logs + Screenshots bắt buộc cho mọi lỗi.

========================================================
IV. XỬ LÝ LỖI & AN TOÀN (MANDATORY)
========================================================
MỌI THAO TÁC Selenium / API / DB phải:
✅ Bọc trong try/except  
✅ Log nguyên nhân lỗi (cùng selector nếu liên quan)  
✅ Update trạng thái DB chính xác  
✅ Screenshot nếu trình duyệt đang mở  
✅ Luôn stop_profile trong finally  
✅ Không nuốt lỗi trong im lặng  

Lỗi cụ thể:
- OTP lỗi 3 lần → failed-phone
- Captcha/QR detect → failed-captcha → DỪNG NGAY
- Không tìm thấy DOM → retry ≤3 → nếu vẫn lỗi → failed
- DebugPort không trả về → failed-start
- Chrome crash/debugger mất kết nối → error
- Exception bất kỳ → error

TẤT CẢ LỖI → FAIL FAST để bảo vệ fingerprint & proxy

========================================================
V. TRẠNG THÁI DB (BẮT BUỘC)
========================================================
- pending
- creating
- waiting-recovery
- recovery-received
- waiting-complete
- waiting-observe
- created
- failed-phone
- failed-captcha
- failed
- error

========================================================
VI. NHÂN HÓA HÀNH VI NGƯỜI DÙNG
========================================================
- Typing delay ngẫu nhiên từng ký tự (human-like)
- Wait theo điều kiện DOM (explicit waits) — KHÔNG dùng tọa độ cố định
- Chuyển hướng chuột tự nhiên nếu cần

========================================================
VII. YÊU CẦU KỸ THUẬT
========================================================
- Python 3.10+
- Selenium attach remote debugging port (GPM API)
- MongoDB cho accounts & profiles
- Telethon để monitor GmailFarmerBot + Bot API cho operator callback
- ProcessPoolExecutor (default max_workers=3)
- ZingProxy integration để cấp proxy VN cho profile

========================================================
VIII. QUY TẮC CHO CURSOR KHI CODE
========================================================
✅ Chia module rõ ràng, có thể test từng phần  
✅ Viết log tiến trình chi tiết từng step  
✅ Code phải có điểm dừng rõ cho mọi nhánh logic  
✅ TUYỆT ĐỐI KHÔNG thay đổi nghiệp vụ trong RULE  
✅ Nếu cần thay đổi lớn, hỏi user trước

========================================================
KẾT THÚC QUY TẮC
========================================================
