"""
Configuration - Cấu hình cho toàn bộ dự án
"""
import os
from pathlib import Path

# Load environment variables từ .env file nếu có
try:
    from dotenv import load_dotenv
    # Load .env từ root directory của project
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        try:
            print(f"✅ Đã load environment variables từ: {env_path}")
        except UnicodeEncodeError:
            # Fallback cho Windows terminal không hỗ trợ emoji
            print(f"[OK] Da load environment variables tu: {env_path}")
except ImportError:
    # python-dotenv không được cài đặt, chỉ dùng system environment variables
    pass

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "gmail_farm")

# Telegram Configuration
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "gmail_farm_session")
GMAIL_FARMER_BOT_USERNAME = os.getenv("GMAIL_FARMER_BOT_USERNAME", "GmailFarmerBot")

# Orchestrator Configuration
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))
SCHEDULER_CHECK_INTERVAL = int(os.getenv("SCHEDULER_CHECK_INTERVAL", "10"))  # seconds

# GPM API Configuration
# Nếu chạy local GPM: http://127.0.0.1:19995 (không cần API key)
# Nếu chạy remote GPM: https://api.gpm.com (cần API key)
GPM_API_URL = os.getenv("GPM_API_URL", "http://127.0.0.1:19995")
GPM_API_KEY = os.getenv("GPM_API_KEY", "")  # Để trống nếu dùng local GPM

# ZingProxy API Configuration
ZINGPROXY_API_URL = os.getenv("ZINGPROXY_API_URL", "https://api.zingproxy.com")
ZINGPROXY_API_KEY = os.getenv("ZINGPROXY_API_KEY", "")  # Deprecated: giữ để tương thích

# ZingProxy Proxy Key - API Key của proxy cụ thể
# Lấy từ dashboard ZingProxy: Vào chi tiết proxy → Copy API Key của proxy
# Endpoint: https://api.zingproxy.com/get-proxy?key={API_KEY_CỦA_PROXY}
# Không cần Bearer token, chỉ cần query parameter
ZINGPROXY_PROXY_KEY = os.getenv("ZINGPROXY_PROXY_KEY", "")

# ZingProxy Change IP Link - Lấy từ dashboard ZingProxy (Link change IP)
# Format: https://api.zingproxy.com/getip/{api_key}
ZINGPROXY_CHANGE_IP_LINK = os.getenv("ZINGPROXY_CHANGE_IP_LINK", "")

# ZingProxy Default Port - Port mặc định của proxy
ZINGPROXY_DEFAULT_PORT = os.getenv("ZINGPROXY_DEFAULT_PORT", "8649")

# ZingProxy Default Proxy (đã thuê cố định)
# Lấy từ dashboard ZingProxy: HTTP IPv4 Proxy format "ip:port:username:password"
ZING_PROXY_HOST = os.getenv("ZING_PROXY_HOST", "")
ZING_PROXY_USER = os.getenv("ZING_PROXY_USER", "")
ZING_PROXY_PASS = os.getenv("ZING_PROXY_PASS", "")

# OTP Service API Configuration
OTP_API_URL = os.getenv("OTP_API_URL", "https://api.otp.com")
OTP_API_KEY = os.getenv("OTP_API_KEY", "")

# Paths
LOGS_DIR = Path("logs")
SCREENSHOTS_DIR = Path("screenshots")

# Tạo thư mục cần thiết
LOGS_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

