# Gmail Auto Farm - Hệ Thống Tự Động Tạo Tài Khoản Gmail

Hệ thống tự động tạo tài khoản Gmail một cách an toàn, ổn định và có khả năng giám sát dựa trên:
- ✅ **GPM Profiles** - Fingerprint và remote debugging
- ✅ **Python Orchestrator** - Quản lý workflow và scheduling
- ✅ **Selenium** - Tự động hóa điền form Gmail
- ✅ **Telegram** - Monitor messages và callback
- ✅ **MongoDB** - Quản lý trạng thái accounts và profiles

---

## 📋 Mục Lục

- [Kiến Trúc Hệ Thống](#kiến-trúc-hệ-thống)
- [Yêu Cầu Hệ Thống](#yêu-cầu-hệ-thống)
- [Hướng Dẫn Cài Đặt](#hướng-dẫn-cài-đặt)
- [Cấu Hình](#cấu-hình)
- [Chạy Hệ Thống](#chạy-hệ-thống)
- [Checklist Kiểm Thử](#checklist-kiểm-thử)
- [Troubleshooting](#troubleshooting)
- [Gợi Ý Vận Hành](#gợi-ý-vận-hành)

---

## 🏗️ Kiến Trúc Hệ Thống

### Luồng Hoạt Động

```
┌─────────────────┐
│ GmailFarmerBot  │ ──► Parse Register Message
│   (Telegram)    │ ──► Lưu vào MongoDB (status="pending")
└─────────────────┘
         │
         ▼
┌─────────────────┐
│ Orchestrator     │ ──► Chọn pending account + idle profile
│  (Scheduler)     │ ──► Spawn worker tạo Gmail
└─────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────┐
│ GPM Manager     │ ──► │ Start Profile│ ──► Nhận debugPort
└─────────────────┘     └──────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────┐
│ Selenium        │ ──► │ Attach Chrome│ ──► Remote Debugging
│ (gmail_register)│     │  Debugger    │
└─────────────────┘     └──────────────┘
         │
         ├─► Điền form Gmail Signup
         ├─► Xử lý OTP (nếu yêu cầu)
         ├─► Xử lý Recovery Email (waiting-recovery)
         ├─► Detect Captcha/QR (fail-fast)
         └─► Logout → Click Complete → status="created"
```

### Cấu Trúc Module

```
src/
├─ core/
│  ├─ orchestrator.py      # Scheduler chọn pending + idle → spawn worker
│  ├─ telegram_listener.py # TeleMonitor parse Register & Recovery messages
│  ├─ gpm_manager.py       # Start/stop GPM profile, get debugPort
│  ├─ proxy_manager.py     # ZingProxy API integration
│  └─ otp_manager.py       # Phone rent + OTP code polling
│
├─ db/
│  └─ database_manager.py  # MongoDB CRUD cho Account + Profile
│
├─ gmail/
│  └─ gmail_register.py    # Worker: Selenium automate Gmail Signup
│
├─ utils/
│  ├─ logger.py            # Logging toàn hệ thống
│  └─ humanizer.py         # Human-like behavior (typing delay, DOM wait)
│
├─ config.py               # Cấu hình từ environment variables
└─ main.py                 # Entry point: khởi động TeleMonitor + Orchestrator
```

---

## 💻 Yêu Cầu Hệ Thống

### Phần Mềm Bắt Buộc

| Thành phần           | Phiên bản | Mô tả                         |
|----------------------|-----------|-------------------------------|
| **Python**           | 3.10+     | Ngôn ngữ lập trình            |
| **Chrome/Chromium**  | Latest    | Trình duyệt cho Selenium      |
| **MongoDB**          | 4.0+      | Database quản lý accounts     |
| **GPM Account**      |     -     | Tài khoản GPM với API access  |

### Dịch Vụ API Cần Thiết

- **GPM Profiles API** - Để start/stop profiles và lấy debugPort
- **ZingProxy API** - Để lấy proxy Việt Nam cho mỗi profile
- **OTP Service API** - Để rent phone number và nhận OTP codes
- **Telegram API** - Để monitor bot và callback buttons

---

## 🚀 Hướng Dẫn Cài Đặt

### Bước 1: Clone Repository

```bash
git clone <repository_url>
cd FarmGmailAuto
```

### Bước 2: Cài Đặt Python Dependencies

```bash
pip install -r requirements.txt
```

**Lưu ý:** Đảm bảo bạn đang dùng Python 3.10 hoặc cao hơn:
```bash
python --version  # Kiểm tra phiên bản Python
```

### Bước 3: Lấy Telegram API Credentials

1. Truy cập: https://my.telegram.org/apps
2. Đăng nhập bằng số điện thoại Telegram của bạn
3. Tạo ứng dụng mới (nếu chưa có)
4. Copy **api_id** và **api_hash**

**Lưu ý:** 
- api_id là số nguyên (integer)
- api_hash là chuỗi ký tự (string)
- Giữ bảo mật thông tin này, không chia sẻ công khai

### Bước 4: Setup MongoDB

#### Cài đặt MongoDB (nếu chưa có)

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install mongodb
sudo systemctl start mongodb
sudo systemctl enable mongodb
```

**Windows:**
- Tải MongoDB từ: https://www.mongodb.com/try/download/community
- Cài đặt và khởi động MongoDB service

#### Tạo Database

```bash
mongosh  # hoặc mongo (tùy phiên bản)
```

Trong MongoDB shell:
```javascript
use gmail_farm
db.accounts.insertOne({test: "init"})  // Tạo collection
db.profiles.insertOne({test: "init"})  // Tạo collection
```

**Hoặc** hệ thống sẽ tự động tạo database và collections khi chạy lần đầu.

### Bước 5: Cấu Hình Environment Variables

```bash
# Copy file mẫu
cp env.example .env

# Chỉnh sửa file .env với editor của bạn
nano .env
# hoặc
code .env
```

Điền đầy đủ các giá trị:

```bash
# MongoDB
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=gmail_farm

# Telegram (từ bước 3)
TELEGRAM_API_ID=your_telegram_api_id
TELEGRAM_API_HASH=your_telegram_api_hash
TELEGRAM_SESSION_NAME=gmail_farm_session
GMAIL_FARMER_BOT_USERNAME=GmailFarmerBot

# Orchestrator
MAX_WORKERS=3
SCHEDULER_CHECK_INTERVAL=10

# APIs (thay bằng API keys thực tế của bạn)
GPM_API_URL=https://api.gpm.com
GPM_API_KEY=your_gpm_api_key

ZINGPROXY_API_URL=https://api.zingproxy.com
ZINGPROXY_API_KEY=your_zingproxy_api_key

OTP_API_URL=https://api.otp.com
OTP_API_KEY=your_otp_api_key
```

**Lưu ý:** 
- File `.env` đã được thêm vào `.gitignore`, không commit vào Git
- Không chia sẻ file `.env` chứa API keys thực tế

### Bước 6: Kiểm Tra Chrome/ChromeDriver

Hệ thống sử dụng `webdriver-manager` để tự động quản lý ChromeDriver, nhưng bạn cần có Chrome/Chromium đã cài đặt.

**Kiểm tra:**
```bash
google-chrome --version  # Linux
# hoặc
chromium --version
```

**Windows:** Chrome thường tự động cài với ChromeDriver, nếu không có thì webdriver-manager sẽ tự download.

---

## ⚙️ Cấu Hình

### Trạng Thái Account trong MongoDB

| Trạng thái | Ý nghĩa |
|-----------|---------|
| `pending` | Chưa xử lý, đang đợi orchestrator |
| `creating` | Đang trong quá trình tạo Gmail |
| `waiting-recovery` | Chờ operator nhập recovery email |
| `recovery-received` | Đã nhận recovery, tiếp tục signup |
| `waiting-complete` | Gmail đã tạo xong, chờ click Complete |
| `waiting-observe` | Cần giám sát thủ công |
| `created` | ✅ Thành công |
| `failed-phone` | ❌ OTP thất bại sau 3 lần |
| `failed-captcha` | ❌ Phát hiện Captcha/QR |
| `failed` | ❌ Thất bại chung |
| `error` | ❌ Lỗi hệ thống |

### Cấu Hình Orchestrator

- **MAX_WORKERS**: Số tài khoản tạo đồng thời (khuyến nghị: 3-5)
- **SCHEDULER_CHECK_INTERVAL**: Thời gian kiểm tra DB (giây, khuyến nghị: 10-30)

---

## ▶️ Chạy Hệ Thống

### Chạy từ thư mục src/

```bash
cd src
python main.py
```

### Hoặc chạy như module

```bash
python -m src.main
```

### Kết quả mong đợi

```
============================================================
🚀 ĐANG KHỞI ĐỘNG HỆ THỐNG GMAIL AUTO FARM
============================================================
📦 Đang khởi tạo Database Manager...
✅ Database Manager đã sẵn sàng
🔧 Đang khởi tạo GPM Manager...
✅ GPM Manager đã sẵn sàng
...
✅ TẤT CẢ COMPONENTS ĐÃ ĐƯỢC KHỞI TẠO
============================================================
🚀 BẮT ĐẦU CHẠY HỆ THỐNG
============================================================
✅ Telegram Client đã kết nối
✅ Đã khởi động Telegram Listener task
✅ Đã khởi động Orchestrator task
🔄 HỆ THỐNG ĐANG CHẠY...
```

**Dừng hệ thống:** Nhấn `Ctrl+C` để graceful shutdown.

---

## ✅ Checklist Kiểm Thử

### Test 1: Telegram → MongoDB

**Mục tiêu:** Kiểm tra TeleMonitor nhận và lưu Register message vào DB.

**Các bước:**
1. Khởi động hệ thống: `python src/main.py`
2. Trong Telegram, gửi lệnh `➕ Register a new Gmail` cho @GmailFarmerBot
3. Bot sẽ trả về form với First Name, Last Name, Email, Password
4. Kiểm tra logs: Tìm dòng `✅ Đã lưu Register account: <email>`
5. Kiểm tra MongoDB:
```bash
mongosh
use gmail_farm
db.accounts.find({status: "pending"}).pretty()
```

**Kết quả mong đợi:**
- Document được tạo với `status="pending"`
- Có đầy đủ `message_id_input`, `message_chat_id`, `email`, `first_name`, `last_name`, `password`

### Test 2: GPM → Chrome Remote Debugging

**Mục tiêu:** Kiểm tra GPM start profile và Selenium attach thành công.

**Các bước:**
1. Đảm bảo có ít nhất 1 profile trong GPM với `status="idle"`
2. Đảm bảo có ít nhất 1 account `status="pending"` trong MongoDB
3. Orchestrator sẽ tự động:
   - Chọn pending account + idle profile
   - Start GPM profile → nhận debugPort
   - Khởi tạo Selenium với remote debugging
4. Kiểm tra logs:
```
🚀 Profile đã start, debugPort: 9222
✅ Đã khởi tạo Selenium với debugPort: 9222
```

**Kết quả mong đợi:**
- Profile chuyển sang `status="in_use"`
- Account chuyển sang `status="creating"`
- Chrome browser mở với profile GPM
- Selenium có thể điều khiển browser

### Test 3: Tạo Gmail Đầu Tiên

**Mục tiêu:** Kiểm tra toàn bộ workflow từ đầu đến cuối.

**Các bước:**
1. Chuẩn bị:
   - Có account pending
   - Có profile idle
   - GPM API hoạt động
   - Proxy VN sẵn sàng
   - OTP service sẵn sàng (nếu cần)
2. Khởi động hệ thống và theo dõi logs
3. Hệ thống sẽ tự động:
   - Parse Register message → lưu pending
   - Start profile → attach Selenium
   - Điền form Gmail Signup
   - Xử lý OTP (nếu yêu cầu)
   - Xử lý Recovery (nếu yêu cầu)
   - Click Complete → `status="created"`
4. Kiểm tra kết quả:
```bash
db.accounts.find({status: "created"}).pretty()
```

**Kết quả mong đợi:**
- Account có `status="created"`
- Profile quay về `status="idle"`
- Gmail đã được tạo thành công
- Complete button đã được click

---

## 🔧 Troubleshooting

### Lỗi: "Cannot connect to MongoDB"

**Nguyên nhân:** MongoDB chưa khởi động hoặc URI sai.

**Giải pháp:**
```bash
# Kiểm tra MongoDB đang chạy
sudo systemctl status mongodb  # Linux
# hoặc kiểm tra service trên Windows

# Kiểm tra kết nối
mongosh mongodb://localhost:27017

# Sửa MONGO_URI trong .env nếu cần
```

### Lỗi: "Telethon authentication failed"

**Nguyên nhân:** API ID/Hash sai hoặc chưa đăng nhập.

**Giải pháp:**
1. Kiểm tra lại `TELEGRAM_API_ID` và `TELEGRAM_API_HASH` trong `.env`
2. Xóa file session cũ: `rm *.session`
3. Chạy lại và đăng nhập khi được yêu cầu

### Lỗi: "ChromeDriver not found"

**Nguyên nhân:** ChromeDriver chưa được download hoặc Chrome chưa cài.

**Giải pháp:**
- Hệ thống tự động download qua `webdriver-manager`
- Đảm bảo Chrome/Chromium đã cài đặt
- Kiểm tra internet connection

### Lỗi: "GPM API không trả về debugPort"

**Nguyên nhân:** GPM API key sai hoặc profile không khả dụng.

**Giải pháp:**
1. Kiểm tra `GPM_API_KEY` trong `.env`
2. Test GPM API thủ công:
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
     https://api.gpm.com/api/v1/profiles
```
3. Đảm bảo có profile với `status="idle"`

### Lỗi: "Không tìm thấy profile idle"

**Nguyên nhân:** Chưa có profile hoặc tất cả đang `in_use`.

**Giải pháp:**
1. Tạo profile trong GPM dashboard
2. Đảm bảo profile có `status="idle"` trong MongoDB:
```bash
db.profiles.find({status: "idle"})
```
3. Hoặc chờ profile hiện tại hoàn thành → quay về `idle`

### Lỗi: "Recovery timeout" hoặc "waiting-recovery quá lâu"

**Nguyên nhân:** Operator chưa nhập recovery email hoặc TeleMonitor không parse được.

**Giải pháp:**
1. Kiểm tra TeleMonitor đang chạy: tìm log `📨 Nhận message từ...`
2. Kiểm tra message Recovery có đúng format không
3. Xem logs để tìm lỗi parse
4. Có thể set thủ công: `db.accounts.updateOne({email: "..."}, {$set: {status: "recovery-received", recovery_email: "..."}})`

### Lỗi: "Selenium không tìm thấy element"

**Nguyên nhân:** DOM thay đổi hoặc page chưa load xong.

**Giải pháp:**
1. Kiểm tra screenshot trong `screenshots/`
2. Xem log để biết element nào không tìm thấy
3. Có thể cần update selectors trong `gmail_register.py`

---

## 📌 Gợi Ý Vận Hành

### ⚠️ An Toàn

1. **Không chạy quá nhiều profiles khi test:**
   - Khuyến nghị: `MAX_WORKERS=1-3` khi test
   - Chỉ tăng lên 5+ khi đã test kỹ và hệ thống ổn định

2. **Giám sát logs thường xuyên:**
   - Theo dõi file `logs/app_YYYYMMDD.log`
   - Tìm các cảnh báo `⚠️` và lỗi `❌`

3. **Backup MongoDB định kỳ:**
```bash
mongodump --db gmail_farm --out /backup/$(date +%Y%m%d)
```

4. **Kiểm tra screenshots khi có lỗi:**
   - Thư mục `screenshots/` chứa ảnh chụp màn hình khi lỗi
   - Dùng để debug và cải thiện code

5. **Giới hạn số lượng pending accounts:**
   - Không nên để quá nhiều accounts pending cùng lúc
   - Xử lý từng batch để tránh quá tải

### 📊 Monitoring

- **MongoDB Stats:**
```bash
# Số lượng accounts theo status
db.accounts.aggregate([
  {$group: {_id: "$status", count: {$sum: 1}}}
])
```

- **Worker Performance:**
  - Theo dõi logs để xem thời gian tạo mỗi account
  - Điều chỉnh `SCHEDULER_CHECK_INTERVAL` nếu cần

### 🔄 Maintenance

1. **Dọn dẹp logs cũ:**
```bash
# Xóa logs cũ hơn 30 ngày
find logs/ -name "*.log" -mtime +30 -delete
```

2. **Dọn dẹp screenshots cũ:**
```bash
# Xóa screenshots cũ hơn 7 ngày
find screenshots/ -name "*.png" -mtime +7 -delete
```

3. **Kiểm tra profiles:**
   - Định kỳ kiểm tra profiles bị kẹt ở `in_use`
   - Có thể manual reset: `db.profiles.updateMany({status: "in_use"}, {$set: {status: "idle"}})`

---

## 📄 Quy Tắc Quan Trọng

**⚠️ TUYỆT ĐỐI KHÔNG thay đổi logic nghiệp vụ!**

Tất cả quy tắc chi tiết được định nghĩa trong: `.cursor/rules.md`

Các quy tắc cốt lõi:
- ✅ Chỉ dùng GPM cho fingerprint + remote debugging
- ✅ KHÔNG dùng GPM No-Code Automation cho form Gmail
- ✅ Mỗi profile = 1 account (không reuse)
- ✅ Proxy VN bắt buộc cho mỗi profile
- ✅ FAIL-FAST khi phát hiện Captcha/QR
- ✅ Logs + Screenshots bắt buộc mọi lỗi

---

## 👤 Tác Giả

Tool tự động hóa tạo Gmail với kiến trúc GPM Profiles + Python Orchestration + Selenium.

Dự án nội bộ - Không phân phối công khai.

---

## 📝 License

Dự án nội bộ - Không phân phối công khai.
