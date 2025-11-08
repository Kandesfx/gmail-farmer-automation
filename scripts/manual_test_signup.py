"""
Test script để test signup flow từ Gmail homepage
Attach to a running GPM profile debugPort và chạy signup với test mode (do_not_submit=True)
"""
import sys
import os
from pathlib import Path

# Thêm src vào path để import modules
root_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bson import ObjectId
from datetime import datetime

try:
    from src.gmail.gmail_register import signup_via_gmail_homepage
    from src.db.database_manager import DatabaseManager
    from src.core.otp_manager import OTPManager
    from src.utils.logger import get_logger
    from src.config import (
        MONGODB_URI, MONGODB_DB_NAME,
        OTP_API_URL, OTP_API_KEY,
        TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_NAME
    )
except ImportError:
    from gmail.gmail_register import signup_via_gmail_homepage
    from db.database_manager import DatabaseManager
    from core.otp_manager import OTPManager
    from utils.logger import get_logger
    from config import (
        MONGODB_URI, MONGODB_DB_NAME,
        OTP_API_URL, OTP_API_KEY,
        TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_NAME
    )

logger = get_logger(__name__)


def test_signup_flow(debug_port: int, test_email: str = "test@example.com"):
    """
    Test signup flow với một GPM profile đang chạy
    
    Args:
        debug_port: Remote debugging port từ GPM profile đang chạy
        test_email: Email test (không thực sự tạo account)
    """
    logger.info("=" * 60)
    logger.info("🧪 BẮT ĐẦU TEST SIGNUP FLOW")
    logger.info("=" * 60)
    
    # Setup Selenium với remote debugging
    try:
        chrome_options = Options()
        chrome_options.add_experimental_option("debuggerAddress", f"localhost:{debug_port}")
        
        # Sử dụng webdriver-manager để tự động download ChromeDriver
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        logger.info(f"✅ Đã attach Selenium với debugPort: {debug_port}")
    except Exception as e:
        logger.error(f"❌ Không thể setup Selenium: {e}")
        return False
    
    # Setup database manager
    try:
        db_manager = DatabaseManager(MONGODB_URI, MONGODB_DB_NAME)
        logger.info("✅ Đã khởi tạo DatabaseManager")
    except Exception as e:
        logger.error(f"❌ Không thể khởi tạo DatabaseManager: {e}")
        driver.quit()
        return False
    
    # Setup OTP manager (có thể mock nếu không có API key)
    otp_manager = None
    try:
        if OTP_API_URL and OTP_API_KEY:
            otp_manager = OTPManager(OTP_API_URL, OTP_API_KEY)
            logger.info("✅ Đã khởi tạo OTPManager")
        else:
            logger.warning("⚠️ Không có OTP_API_URL/OTP_API_KEY, bỏ qua OTP manager")
    except Exception as e:
        logger.warning(f"⚠️ Không thể khởi tạo OTPManager: {e}")
    
    # Setup Telegram client (có thể mock nếu không cần)
    telegram_client = None
    try:
        from telethon import TelegramClient
        session_path = root_dir / TELEGRAM_SESSION_NAME
        if session_path.exists():
            telegram_client = TelegramClient(str(session_path), TELEGRAM_API_ID, TELEGRAM_API_HASH)
            logger.info("✅ Đã khởi tạo TelegramClient")
        else:
            logger.warning("⚠️ Không có Telegram session, bỏ qua Telegram client")
    except Exception as e:
        logger.warning(f"⚠️ Không thể khởi tạo TelegramClient: {e}")
    
    # Tạo test account document
    test_account = {
        "_id": ObjectId(),
        "first_name": "Test",
        "last_name": "User",
        "email": test_email,
        "password": "TestPassword123!",
        "status": "creating",
        "message_chat_id": None,
        "message_id_input": None,
        "created_at": datetime.now()
    }
    
    # Lưu test account vào DB (tạm thời)
    try:
        db_manager.accounts.insert_one(test_account)
        logger.info(f"✅ Đã tạo test account: {test_account['_id']}")
    except Exception as e:
        logger.warning(f"⚠️ Không thể lưu test account vào DB: {e}")
    
    # Setup screenshots directory
    screenshots_dir = root_dir / "screenshots" / "test"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 Screenshots sẽ được lưu tại: {screenshots_dir}")
    
    try:
        # Gọi signup_via_gmail_homepage với test mode (do_not_submit=True)
        logger.info("🚀 Bắt đầu test signup flow...")
        result = signup_via_gmail_homepage(
            driver=driver,
            account_doc=test_account,
            db=db_manager,
            logger=logger,
            otp_manager=otp_manager,
            telegram_client=telegram_client,
            screenshots_dir=screenshots_dir,
            do_not_submit=True  # TEST MODE: Không click final submit
        )
        
        logger.info("=" * 60)
        logger.info("📊 KẾT QUẢ TEST")
        logger.info("=" * 60)
        logger.info(f"Success: {result.get('success', False)}")
        logger.info(f"Error: {result.get('error', 'None')}")
        logger.info(f"Phone Order: {result.get('phone_order', 'None')}")
        
        if result.get("success"):
            logger.info("✅ TEST THÀNH CÔNG: Flow đã điều hướng đến form và điền fields")
            logger.info("✅ Không click final submit (test mode)")
        else:
            logger.error(f"❌ TEST THẤT BẠI: {result.get('error', 'Unknown error')}")
        
        return result.get("success", False)
        
    except Exception as e:
        logger.error(f"❌ Lỗi trong test: {e}", exc_info=True)
        return False
        
    finally:
        # Cleanup
        logger.info("🧹 Đang cleanup...")
        
        # Xóa test account khỏi DB
        try:
            db_manager.accounts.delete_one({"_id": test_account["_id"]})
            logger.info("✅ Đã xóa test account khỏi DB")
        except Exception as e:
            logger.warning(f"⚠️ Không thể xóa test account: {e}")
        
        # Quit driver
        try:
            driver.quit()
            logger.info("✅ Đã quit Selenium driver")
        except Exception as e:
            logger.warning(f"⚠️ Lỗi quit driver: {e}")
        
        logger.info("=" * 60)
        logger.info("🏁 KẾT THÚC TEST")
        logger.info("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test signup flow từ Gmail homepage")
    parser.add_argument(
        "--debug-port",
        type=int,
        required=True,
        help="Remote debugging port từ GPM profile đang chạy (ví dụ: 9222)"
    )
    parser.add_argument(
        "--test-email",
        type=str,
        default="test@example.com",
        help="Email test (mặc định: test@example.com)"
    )
    
    args = parser.parse_args()
    
    success = test_signup_flow(args.debug_port, args.test_email)
    
    sys.exit(0 if success else 1)

