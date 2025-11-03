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
        print(f"✅ Đã load environment variables từ: {env_path}")
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
GPM_API_URL = os.getenv("GPM_API_URL", "https://api.gpm.com")
GPM_API_KEY = os.getenv("GPM_API_KEY", "")

# ZingProxy API Configuration
ZINGPROXY_API_URL = os.getenv("ZINGPROXY_API_URL", "https://api.zingproxy.com")
ZINGPROXY_API_KEY = os.getenv("ZINGPROXY_API_KEY", "")

# OTP Service API Configuration
OTP_API_URL = os.getenv("OTP_API_URL", "https://api.otp.com")
OTP_API_KEY = os.getenv("OTP_API_KEY", "")

# Paths
LOGS_DIR = Path("logs")
SCREENSHOTS_DIR = Path("screenshots")

# Tạo thư mục cần thiết
LOGS_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

