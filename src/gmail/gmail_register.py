"""
Gmail Register - Worker tạo tài khoản Gmail
Selenium + GPM remote debugging + OTP + Recovery handling
"""
import os
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from bson import ObjectId
from telethon import TelegramClient
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

try:
    from ..db.database_manager import DatabaseManager
    from ..core.gpm_manager import GPMManager
    from ..core.proxy_manager import ProxyManager
    from ..core.otp_manager import OTPManager
    from ..utils.humanizer import Humanizer
    from ..utils.logger import get_logger
    from ..config import GPM_CHROMEDRIVER_PATH
except ImportError:
    from db.database_manager import DatabaseManager
    from core.gpm_manager import GPMManager
    from core.proxy_manager import ProxyManager
    from core.otp_manager import OTPManager
    from utils.humanizer import Humanizer
    from utils.logger import get_logger
    from config import GPM_CHROMEDRIVER_PATH

logger = get_logger(__name__)


def _detect_proxy_errors(driver: webdriver.Chrome) -> Optional[str]:
    """
    Phát hiện lỗi proxy từ trang web (ERR_NO_SUPPORTED_PROXIES, etc.)
    
    Args:
        driver: Selenium WebDriver
        
    Returns:
        Error message nếu phát hiện lỗi proxy, None nếu không có lỗi
    """
    try:
        # Kiểm tra URL có chứa error code không
        current_url = driver.current_url
        if "error" in current_url.lower() or "err_" in current_url.lower():
            page_source = driver.page_source.lower()
            
            # Kiểm tra các lỗi proxy phổ biến
            proxy_errors = [
                "err_no_supported_proxies",
                "err_proxy_connection_failed",
                "err_tunnel_connection_failed",
                "proxy connection failed",
                "không thể truy cập trang web này",
                "cannot access this website"
            ]
            
            for error_keyword in proxy_errors:
                if error_keyword in page_source:
                    # Tìm error code trong page source
                    error_code = None
                    if "err_no_supported_proxies" in page_source:
                        error_code = "ERR_NO_SUPPORTED_PROXIES"
                    elif "err_proxy_connection_failed" in page_source:
                        error_code = "ERR_PROXY_CONNECTION_FAILED"
                    elif "err_tunnel_connection_failed" in page_source:
                        error_code = "ERR_TUNNEL_CONNECTION_FAILED"
                    
                    error_msg = f"Phát hiện lỗi proxy: {error_code or error_keyword}"
                    logger.error(f"❌ {error_msg}")
                    logger.error(f"   URL: {current_url}")
                    return error_msg
        
        # Kiểm tra page title có chứa error không
        try:
            page_title = driver.title.lower()
            if "error" in page_title or "không thể" in page_title or "cannot" in page_title:
                page_source = driver.page_source.lower()
                if any(keyword in page_source for keyword in ["proxy", "err_", "connection failed"]):
                    error_msg = "Phát hiện lỗi proxy từ page title và content"
                    logger.error(f"❌ {error_msg}")
                    return error_msg
        except Exception:
            pass
        
        return None
        
    except Exception as e:
        logger.warning(f"⚠️ Không thể kiểm tra proxy errors: {e}")
        return None


def create_gmail_account(
    account: Dict[str, Any],
    db_manager: DatabaseManager,
    gpm_manager: GPMManager,
    proxy_manager: ProxyManager,
    otp_manager: OTPManager,
    telegram_client: TelegramClient,
    screenshots_dir: Path
) -> bool:
    """
    Worker function tạo tài khoản Gmail
    
    Args:
        account: Dict chứa thông tin account (từ DB)
        db_manager: DatabaseManager instance
        gpm_manager: GPMManager instance
        proxy_manager: ProxyManager instance
        otp_manager: OTPManager instance
        telegram_client: TelegramClient instance (cho callback)
        screenshots_dir: Thư mục lưu screenshots
        
    Returns:
        True nếu thành công, False nếu thất bại
    """
    account_id = ObjectId(account["_id"])
    profile_id = None
    driver = None
    phone_order = None
    
    try:
        logger.info(f"🚀 Bắt đầu tạo Gmail cho account: {account.get('email')}")
        
        # ============================================================
        # VALIDATION BẮT BUỘC - FAIL-FAST (theo rules.md)
        # ============================================================
        validation_errors = []
        
        # 1. Validate account fields (bắt buộc)
        if not account.get("email"):
            validation_errors.append("Thiếu email (bắt buộc)")
        if not account.get("first_name"):
            validation_errors.append("Thiếu first_name (bắt buộc)")
        if not account.get("password"):
            validation_errors.append("Thiếu password (bắt buộc)")
        
        # 3. Validate Telegram metadata (cần cho callback Complete)
        if not account.get("message_chat_id") and not account.get("source_chat_id"):
            validation_errors.append("Thiếu message_chat_id/source_chat_id (cần cho callback)")
        if not account.get("message_id_input"):
            validation_errors.append("Thiếu message_id_input (cần cho callback)")
        
        # Nếu có lỗi validation → FAIL-FAST
        if validation_errors:
            error_msg = "; ".join(validation_errors)
            logger.error(f"❌ VALIDATION FAILED - Dừng ngay: {error_msg}")
            db_manager.update_status(account_id, "failed", last_error=f"Validation failed: {error_msg}")
            return False
        
        logger.info("✅ Validation passed - Các trường bắt buộc đã đầy đủ")
        
        # ============================================================
        # 1. Lấy proxy (BẮT BUỘC theo rules.md)
        # ============================================================
        logger.info(f"🔗 Đang lấy proxy...")
        try:
            # Lấy proxy từ ProxyManager (không cần profile_id vì sẽ tạo profile mới)
            proxy = proxy_manager.get_default_rented_proxy()
            if not proxy:
                error_msg = "Không thể lấy proxy"
                logger.error(f"❌ {error_msg} - FAIL-FAST")
                db_manager.update_status(account_id, "failed", last_error=error_msg)
                return False
            
            # Validate proxy (FAIL-FAST nếu lỗi)
            proxy_manager.validate_proxy_requests(
                proxy=proxy,
                skip_validation=False
            )
            logger.info(f"✅ Đã lấy và validate proxy thành công: {proxy['host']}:{proxy.get('port', 'N/A')}")
        except RuntimeError as proxy_error:
            error_msg = f"Không thể lấy hoặc validate proxy: {str(proxy_error)}"
            logger.error(f"❌ {error_msg} - FAIL-FAST")
            db_manager.update_status(account_id, "failed", last_error=error_msg)
            return False
        except Exception as proxy_error:
            error_msg = f"Lỗi không xác định khi lấy proxy: {str(proxy_error)}"
            logger.error(f"❌ {error_msg} - FAIL-FAST")
            db_manager.update_status(account_id, "failed", last_error=error_msg)
            return False
        
        # ============================================================
        # 2. Tạo mới profile với proxy (BẮT BUỘC - theo rules.md)
        # ============================================================
        logger.info(f"📝 Đang tạo profile mới với proxy...")
        profile_name = f"Gmail_{account.get('email', 'unknown')}_{int(time.time())}"
        
        try:
            profile_data = gpm_manager.create_profile(
                profile_name=profile_name,
                proxy=proxy  # Đưa proxy vào khi tạo profile
            )
            
            if not profile_data or not profile_data.get("id"):
                error_msg = "Không thể tạo profile mới"
                logger.error(f"❌ {error_msg} - FAIL-FAST")
                db_manager.update_status(account_id, "failed", last_error=error_msg)
                return False
            
            profile_id = profile_data.get("id")
            logger.info(f"✅ Đã tạo profile thành công: {profile_id}")
            
            # Lưu profile_id vào account document
            try:
                db_manager.accounts.update_one(
                    {"_id": account_id},
                    {"$set": {"profile_id": profile_id}}
                )
                logger.debug(f"✅ Đã lưu profile_id vào account: {profile_id}")
            except Exception as save_error:
                logger.warning(f"⚠️ Không thể lưu profile_id vào account: {save_error}")
        
        except Exception as create_error:
            error_msg = f"Lỗi khi tạo profile: {str(create_error)}"
            logger.error(f"❌ {error_msg} - FAIL-FAST", exc_info=True)
            db_manager.update_status(account_id, "failed", last_error=error_msg)
            return False
        
        # ============================================================
        # 3. Start profile mới tạo (BẮT BUỘC - theo rules.md)
        # ============================================================
        logger.info(f"🚀 Đang start profile {profile_id}...")
        profile_result = gpm_manager.start_profile(profile_id)
        
        # Ưu tiên dùng remote_debugging_port (API v3), fallback về debugPort (backward compatibility)
        debug_port = profile_result.get("remote_debugging_port") if profile_result else None
        if not debug_port:
            debug_port = profile_result.get("debugPort") if profile_result else None
        
        # FAIL-FAST: Nếu không có debugPort → failed-start (theo rules.md)
        if not profile_result or not debug_port:
            error_msg = f"GPM không trả về remote_debugging_port cho profile {profile_id}"
            logger.error(f"❌ {error_msg} - FAIL-FAST")
            
            # Đánh dấu profile là error để không dùng nữa
            # Profile có thể bị PROFILE_IN_TRASH hoặc các lỗi khác
            try:
                logger.warning(f"⚠️ Profile {profile_id} không thể start, đánh dấu profile là error")
                db_manager.update_profile_status(profile_id, "error")
                logger.info(f"   💡 Profile đã được đánh dấu 'error', sẽ không được chọn lại")
                logger.info(f"   💡 Nếu profile bị PROFILE_IN_TRASH, vui lòng khôi phục từ GPM dashboard")
            except Exception as profile_update_error:
                logger.warning(f"⚠️ Không thể update profile status: {profile_update_error}")
            
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "start_profile_failed")
            db_manager.update_status(account_id, "failed-start", last_error=error_msg)
            
            # Profile chưa start thành công, không cần stop
            return False
        
        logger.info(f"✅ Profile đã start, remote_debugging_port: {debug_port}")
        
        # ============================================================
        # 4. Setup Selenium với remote debugging (BẮT BUỘC)
        # ============================================================
        logger.info(f"🔧 Đang setup Selenium với debug_port: {debug_port}...")
        driver = _setup_selenium(debug_port)
        if not driver:
            error_msg = "Không thể khởi tạo Selenium driver với remote debugging port"
            logger.error(f"❌ {error_msg} - FAIL-FAST")
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "selenium_init_failed")
            db_manager.update_status(account_id, "failed-start", last_error=error_msg)
            # Đã start profile nhưng không attach được → cần stop profile
            try:
                gpm_manager.stop_profile(profile_id)
                db_manager.update_profile_status(profile_id, "idle")
            except Exception as stop_error:
                logger.error(f"❌ Lỗi stop profile sau khi Selenium init failed: {stop_error}")
            return False
        
        logger.info("✅ Đã khởi tạo Selenium driver thành công")
        
        # ============================================================
        # 5. Điền form Gmail Signup
        # ============================================================
        if not _fill_gmail_signup_form(driver, account, screenshots_dir, account_id, db_manager):
            # _fill_gmail_signup_form đã set status và screenshot → return False
            return False
        
        # 6. Xử lý OTP nếu có
        phone_order = _handle_otp(driver, account, otp_manager, screenshots_dir, account_id, db_manager)
        if phone_order is False:  # False = failed, None = không cần OTP
            return False
        
        # 7. Xử lý Recovery Email (nếu yêu cầu)
        recovery_handled = _handle_recovery(
            driver, account, db_manager, account_id, screenshots_dir, max_wait=300
        )
        if not recovery_handled:
            return False
        
        # 8. Detect Captcha/QR và xử lý
        if _detect_captcha_qr(driver, screenshots_dir, account_id, db_manager):
            return False  # failed-captcha đã được set trong hàm
        
        # 9. Xử lý sau Signup (check bot message, logout, click Complete)
        success = _handle_post_signup(
            driver, account, db_manager, account_id, telegram_client, screenshots_dir
        )
        
        return success
        
    except RuntimeError as e:
        # RuntimeError thường là lỗi proxy hoặc lỗi nghiêm trọng
        error_msg = str(e)
        logger.error(f"❌ {error_msg} - FAIL-FAST", exc_info=True)
        
        # Kiểm tra nếu là lỗi proxy → set status failed-proxy
        if "proxy" in error_msg.lower() or "failed-proxy" in error_msg.lower():
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "proxy_error")
            # Status đã được set trong _fill_gmail_signup_form nếu là proxy error
            if account.get("status") != "failed-proxy":
                db_manager.update_status(account_id, "failed-proxy", last_error=error_msg)
        else:
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "error")
            db_manager.update_status(account_id, "error", last_error=error_msg)
        
        # Lưu flag để finally block biết cần kill profile
        should_kill_profile = "proxy" in error_msg.lower()
        return False
        
    except Exception as e:
        # FAIL-FAST: Bất kỳ exception nào → error status (theo rules.md)
        error_msg = f"Exception không mong đợi: {str(e)}"
        logger.error(f"❌ {error_msg} - FAIL-FAST", exc_info=True)
        _take_screenshot(driver, screenshots_dir, account_id, db_manager, "error")
        db_manager.update_status(account_id, "error", last_error=error_msg)
        should_kill_profile = False
        return False
        
    finally:
        # ============================================================
        # CLEANUP - Luôn thực hiện (theo rules.md)
        # ============================================================
        logger.info("🧹 Đang cleanup resources...")
        
        # Kiểm tra account status để quyết định có kill profile không
        should_kill_profile = False
        if account_id:
            try:
                account_obj = db_manager.accounts.find_one({"_id": account_id})
                if account_obj:
                    status = account_obj.get("status", "")
                    last_error = account_obj.get("last_error", "")
                    # Kill profile nếu là lỗi proxy hoặc failed-proxy
                    if status == "failed-proxy" or ("proxy" in last_error.lower() and "err_" in last_error.lower()):
                        should_kill_profile = True
                        logger.warning(f"⚠️ Account có lỗi proxy, sẽ KILL profile thay vì chỉ stop")
            except Exception as e:
                logger.debug(f"⚠️ Không thể kiểm tra account status để quyết định kill profile: {e}")
        
        # 1. Quit Selenium driver
        if driver:
            try:
                driver.quit()
                logger.debug("✅ Đã quit Selenium driver")
            except Exception as e:
                logger.warning(f"⚠️ Lỗi quit driver: {e}")
        
        # 2. Cancel phone order nếu có
        if phone_order:
            try:
                order_id = phone_order.get("order_id")
                if order_id:
                    otp_manager.cancel_order(order_id)
                    logger.debug(f"✅ Đã cancel phone order: {order_id}")
            except Exception as e:
                logger.warning(f"⚠️ Lỗi cancel phone order: {e}")
        
        # 3. Stop hoặc KILL profile (BẮT BUỘC theo rules.md - luôn cleanup trong finally)
        if profile_id:
            try:
                if should_kill_profile:
                    # Lỗi proxy nghiêm trọng → XÓA profile vĩnh viễn để không mở lại
                    logger.warning(f"🗑️ Đang KILL profile {profile_id} do lỗi proxy")
                    gpm_manager.delete_profile(profile_id)
                    logger.warning(f"✅ Đã KILL profile {profile_id} - Profile sẽ không được mở lại")
                else:
                    # Lỗi thông thường → chỉ stop profile
                    gpm_manager.stop_profile(profile_id)
                    logger.info(f"✅ Đã stop profile: {profile_id}")
            except Exception as e:
                logger.error(f"❌ Lỗi cleanup profile {profile_id}: {e}", exc_info=True)


def _setup_selenium(debug_port: int) -> Optional[webdriver.Chrome]:
    """
    Setup Selenium với remote debugging port
    Ưu tiên dùng ChromeDriver từ GPM path, fallback về webdriver-manager
    
    Args:
        debug_port: Debug port từ GPM
        
    Returns:
        Chrome WebDriver instance hoặc None nếu lỗi
    """
    try:
        chrome_options = Options()
        chrome_options.add_experimental_option("debuggerAddress", f"localhost:{debug_port}")
        
        # Không cần thêm options khác vì GPM đã setup profile
        
        # Ưu tiên dùng ChromeDriver từ GPM path nếu có
        service = None
        if GPM_CHROMEDRIVER_PATH and Path(GPM_CHROMEDRIVER_PATH).exists():
            logger.debug(f"   Đang setup ChromeDriver từ GPM path: {GPM_CHROMEDRIVER_PATH}")
            # Selenium 4.x: truyền path trực tiếp vào Service constructor
            service = Service(GPM_CHROMEDRIVER_PATH)
        else:
            # Fallback: Sử dụng webdriver-manager để tự động download ChromeDriver phù hợp
            logger.debug(f"   Đang setup ChromeDriver (tự động download nếu cần)...")
            if GPM_CHROMEDRIVER_PATH:
                logger.warning(f"   ⚠️ GPM_CHROMEDRIVER_PATH được cấu hình nhưng file không tồn tại: {GPM_CHROMEDRIVER_PATH}")
                logger.warning(f"   💡 Đang fallback về webdriver-manager")
            service = Service(ChromeDriverManager().install())
        
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logger.info(f"✅ Đã khởi tạo Selenium với debugPort: {debug_port}")
        return driver
        
    except Exception as e:
        logger.error(f"❌ Lỗi setup Selenium: {e}", exc_info=True)
        logger.error(f"   💡 Gợi ý:")
        logger.error(f"      - Kiểm tra Chrome browser đã được cài đặt chưa")
        logger.error(f"      - Kiểm tra GPM_CHROMEDRIVER_PATH có đúng không (nếu có)")
        logger.error(f"      - Kiểm tra network có thể download ChromeDriver không (nếu dùng webdriver-manager)")
        logger.error(f"      - Thử update Chrome browser lên phiên bản mới nhất")
        return None


def _fill_gmail_signup_form(
    driver: webdriver.Chrome,
    account: Dict[str, Any],
    screenshots_dir: Path,
    account_id: ObjectId,
    db_manager: DatabaseManager
) -> bool:
    """
    Điền form Gmail Signup
    
    Args:
        driver: Selenium WebDriver
        account: Dict chứa thông tin account
        screenshots_dir: Thư mục lưu screenshots
        account_id: ObjectId của account
        db_manager: DatabaseManager instance
        
    Returns:
        True nếu thành công, False nếu thất bại
    """
    try:
        # Navigate đến Gmail Signup
        logger.info("📝 Đang điều hướng đến Gmail Signup...")
        driver.get("https://accounts.google.com/signup/v2/webcreateaccount?flowName=GlifWebSignIn&flowEntry=SignUp")
        
        Humanizer.random_delay(2, 4)
        
        # Kiểm tra lỗi proxy NGAY sau khi navigate (FAIL-FAST)
        proxy_error = _detect_proxy_errors(driver)
        if proxy_error:
            # Lỗi proxy nghiêm trọng → kill profile và dừng ngay
            logger.error(f"❌ {proxy_error} - DỪNG NGAY và KILL PROFILE")
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "proxy_error")
            db_manager.update_status(account_id, "failed-proxy", last_error=proxy_error)
            # Raise exception để finally block có thể kill profile
            raise RuntimeError(f"Proxy error detected: {proxy_error}")
        
        # First Name
        first_name_elem = Humanizer.wait_for_element(
            driver, By.ID, "firstName", timeout=10, raise_exception=False
        )
        if not first_name_elem:
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "form_not_found")
            db_manager.update_status(account_id, "failed", last_error="Không tìm thấy form First Name")
            return False
        
        Humanizer.type_like_human(first_name_elem, account.get("first_name", ""))
        Humanizer.random_delay(0.5, 1.5)
        
        # Last Name
        last_name_elem = Humanizer.wait_for_element(
            driver, By.ID, "lastName", timeout=10, raise_exception=False
        )
        if not last_name_elem:
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "form_not_found")
            db_manager.update_status(account_id, "failed", last_error="Không tìm thấy form Last Name")
            return False
        
        # Logic Last Name: Nếu là "x" (không phân biệt hoa thường) → BỎ TRỐNG
        last_name = account.get("last_name", "")
        if last_name and last_name.lower() == "x":
            logger.info("ℹ️ Last name là 'x', bỏ trống không điền")
            # Không điền gì vào Last Name field
        else:
            # Điền Last Name nếu có giá trị
            if last_name:
                Humanizer.type_like_human(last_name_elem, last_name)
                Humanizer.random_delay(0.5, 1.5)
            else:
                logger.info("ℹ️ Không có Last name, bỏ trống")
        
        Humanizer.random_delay(0.5, 1.5)
        
        # Click Next
        next_button = Humanizer.wait_for_clickable(
            driver, By.XPATH, "//button[contains(text(), 'Next') or contains(text(), 'Tiếp theo')]", 
            timeout=10, raise_exception=False
        )
        if not next_button:
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "next_button_not_found")
            db_manager.update_status(account_id, "failed", last_error="Không tìm thấy nút Next")
            return False
        
        Humanizer.safe_click(driver, next_button)
        Humanizer.random_delay(2, 4)
        
        # Email (username)
        # Có thể cần chọn domain hoặc nhập username
        username_elem = Humanizer.wait_for_element(
            driver, By.ID, "username", timeout=10, raise_exception=False
        )
        if username_elem:
            email_local = account.get("email", "").split("@")[0]
            Humanizer.type_like_human(username_elem, email_local)
            Humanizer.random_delay(0.5, 1.5)
            
            # Click Next
            next_button = Humanizer.wait_for_clickable(
                driver, By.XPATH, "//button[contains(text(), 'Next') or contains(text(), 'Tiếp theo')]",
                timeout=10, raise_exception=False
            )
            if next_button:
                Humanizer.safe_click(driver, next_button)
                Humanizer.random_delay(2, 4)
        
        # Password
        password_elem = Humanizer.wait_for_element(
            driver, By.NAME, "Passwd", timeout=10, raise_exception=False
        )
        if not password_elem:
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "password_form_not_found")
            db_manager.update_status(account_id, "failed", last_error="Không tìm thấy form Password")
            return False
        
        Humanizer.type_like_human(password_elem, account.get("password", ""))
        Humanizer.random_delay(0.5, 1.5)
        
        # Confirm Password
        confirm_password_elem = Humanizer.wait_for_element(
            driver, By.NAME, "PasswdAgain", timeout=10, raise_exception=False
        )
        if confirm_password_elem:
            Humanizer.type_like_human(confirm_password_elem, account.get("password", ""))
            Humanizer.random_delay(0.5, 1.5)
        
        # Click Next
        next_button = Humanizer.wait_for_clickable(
            driver, By.XPATH, "//button[contains(text(), 'Next') or contains(text(), 'Tiếp theo')]",
            timeout=10, raise_exception=False
        )
        if not next_button:
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "next_button_not_found")
            db_manager.update_status(account_id, "failed", last_error="Không tìm thấy nút Next sau password")
            return False
        
        Humanizer.safe_click(driver, next_button)
        Humanizer.random_delay(2, 4)
        
        logger.info("✅ Đã điền form Gmail Signup")
        return True
        
    except Exception as e:
        logger.error(f"❌ Lỗi điền form Gmail Signup: {e}", exc_info=True)
        _take_screenshot(driver, screenshots_dir, account_id, db_manager, "form_error")
        db_manager.update_status(account_id, "failed", last_error=f"Lỗi điền form: {str(e)}")
        return False


def _handle_otp(
    driver: webdriver.Chrome,
    account: Dict[str, Any],
    otp_manager: OTPManager,
    screenshots_dir: Path,
    account_id: ObjectId,
    db_manager: DatabaseManager
) -> Optional[Dict[str, Any]]:
    """
    Xử lý OTP (nếu yêu cầu)
    
    Returns:
        Dict chứa phone_order nếu đã rent phone, False nếu thất bại, None nếu không cần OTP
    """
    try:
        # Kiểm tra có yêu cầu OTP không
        phone_input = Humanizer.wait_for_element(
            driver, By.ID, "phoneNumberId", timeout=5, raise_exception=False
        )
        
        if not phone_input:
            logger.info("ℹ️ Không yêu cầu OTP")
            return None
        
        logger.info("📱 Phát hiện yêu cầu OTP")
        
        # Rent phone
        phone_order = otp_manager.rent_phone("VN")
        if not phone_order:
            logger.error("❌ Không thể rent phone")
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "otp_rent_failed")
            db_manager.update_status(account_id, "failed-phone", last_error="Không thể rent phone")
            return False
        
        phone_number = phone_order.get("phone_number")
        logger.info(f"✅ Đã rent phone: {phone_number}")
        
        # Nhập phone number
        Humanizer.type_like_human(phone_input, phone_number)
        Humanizer.random_delay(0.5, 1.5)
        
        # Click Next
        next_button = Humanizer.wait_for_clickable(
            driver, By.XPATH, "//button[contains(text(), 'Next') or contains(text(), 'Tiếp theo')]",
            timeout=10, raise_exception=False
        )
        if next_button:
            Humanizer.safe_click(driver, next_button)
            Humanizer.random_delay(2, 4)
        
        # Đợi input OTP code
        code_input = Humanizer.wait_for_element(
            driver, By.ID, "code", timeout=30, raise_exception=False
        )
        if not code_input:
            logger.error("❌ Không tìm thấy input OTP code")
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "otp_input_not_found")
            db_manager.update_status(account_id, "failed-phone", last_error="Không tìm thấy input OTP")
            return False
        
        # Poll OTP code với retry 3 lần
        otp_code = otp_manager.get_code(phone_order.get("order_id"), max_attempts=3)
        
        if not otp_code:
            logger.error("❌ Không nhận được OTP code sau 3 attempts")
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "otp_timeout")
            db_manager.update_status(account_id, "failed-phone", last_error="Không nhận được OTP code")
            return False
        
        # Nhập OTP code
        Humanizer.type_like_human(code_input, otp_code)
        Humanizer.random_delay(0.5, 1.5)
        
        # Click Next/Verify
        verify_button = Humanizer.wait_for_clickable(
            driver, By.XPATH, 
            "//button[contains(text(), 'Next') or contains(text(), 'Verify') or contains(text(), 'Xác minh')]",
            timeout=10, raise_exception=False
        )
        if verify_button:
            Humanizer.safe_click(driver, verify_button)
            Humanizer.random_delay(2, 4)
        
        logger.info("✅ Đã xử lý OTP thành công")
        return phone_order
        
    except Exception as e:
        logger.error(f"❌ Lỗi xử lý OTP: {e}", exc_info=True)
        _take_screenshot(driver, screenshots_dir, account_id, db_manager, "otp_error")
        db_manager.update_status(account_id, "failed-phone", last_error=f"Lỗi OTP: {str(e)}")
        return False


def _handle_recovery(
    driver: webdriver.Chrome,
    account: Dict[str, Any],
    db_manager: DatabaseManager,
    account_id: ObjectId,
    screenshots_dir: Path,
    max_wait: int = 300
) -> bool:
    """
    Xử lý Recovery Email (đợi và resume khi nhận được)
    
    Args:
        driver: Selenium WebDriver
        account: Dict chứa thông tin account
        db_manager: DatabaseManager instance
        account_id: ObjectId của account
        screenshots_dir: Thư mục lưu screenshots
        max_wait: Thời gian đợi tối đa (giây)
        
    Returns:
        True nếu thành công, False nếu thất bại
    """
    try:
        # Kiểm tra có yêu cầu Recovery Email không
        recovery_input = Humanizer.wait_for_element(
            driver, By.ID, "recoveryEmailId", timeout=5, raise_exception=False
        )
        
        if not recovery_input:
            logger.info("ℹ️ Không yêu cầu Recovery Email")
            return True
        
        logger.info("📧 Phát hiện yêu cầu Recovery Email")
        
        # Set status = "waiting-recovery"
        db_manager.update_status(account_id, "waiting-recovery")
        logger.info("⏳ Đang đợi recovery email từ operator...")
        
        # Đợi status chuyển thành "recovery-received" (từ telegram_listener)
        start_time = time.time()
        check_interval = 2  # Kiểm tra mỗi 2 giây
        
        while time.time() - start_time < max_wait:
            # Lấy account mới nhất từ DB
            from bson import ObjectId
            updated_account = db_manager.accounts.find_one({"_id": account_id})
            
            if updated_account and updated_account.get("status") == "recovery-received":
                recovery_email = updated_account.get("recovery_email")
                if recovery_email:
                    logger.info(f"✅ Đã nhận recovery email: {recovery_email}")
                    
                    # Nhập recovery email
                    Humanizer.type_like_human(recovery_input, recovery_email)
                    Humanizer.random_delay(0.5, 1.5)
                    
                    # Click Next
                    next_button = Humanizer.wait_for_clickable(
                        driver, By.XPATH, "//button[contains(text(), 'Next') or contains(text(), 'Tiếp theo')]",
                        timeout=10, raise_exception=False
                    )
                    if next_button:
                        Humanizer.safe_click(driver, next_button)
                        Humanizer.random_delay(2, 4)
                    
                    logger.info("✅ Đã nhập recovery email thành công")
                    return True
            
            # Kiểm tra có lỗi không
            if updated_account and updated_account.get("status") == "waiting-observe":
                logger.warning("⚠️ Account đã được set waiting-observe, dừng đợi recovery")
                return False
            
            time.sleep(check_interval)
        
        logger.error(f"❌ Timeout đợi recovery email sau {max_wait}s")
        _take_screenshot(driver, screenshots_dir, account_id, db_manager, "recovery_timeout")
        db_manager.update_status(account_id, "failed", last_error="Timeout đợi recovery email")
        return False
        
    except Exception as e:
        logger.error(f"❌ Lỗi xử lý Recovery: {e}", exc_info=True)
        _take_screenshot(driver, screenshots_dir, account_id, db_manager, "recovery_error")
        db_manager.update_status(account_id, "failed", last_error=f"Lỗi recovery: {str(e)}")
        return False


def _detect_captcha_qr(
    driver: webdriver.Chrome,
    screenshots_dir: Path,
    account_id: ObjectId,
    db_manager: DatabaseManager
) -> bool:
    """
    Detect Captcha/QR Code
    
    Returns:
        True nếu phát hiện Captcha/QR (đã set failed-captcha), False nếu không
    """
    try:
        # Kiểm tra các indicator của Captcha/QR
        captcha_indicators = [
            "captcha",
            "recaptcha",
            "verify you're human",
            "scan this qr",
            "qr code"
        ]
        
        page_source_lower = driver.page_source.lower()
        
        for indicator in captcha_indicators:
            if indicator in page_source_lower:
                logger.warning(f"⚠️ Phát hiện {indicator}")
                _take_screenshot(driver, screenshots_dir, account_id, db_manager, "captcha_detected")
                db_manager.update_status(account_id, "failed-captcha", last_error=f"Phát hiện {indicator}")
                return True
        
        # Kiểm tra element captcha (nếu có)
        captcha_frame = Humanizer.wait_for_element(
            driver, By.CSS_SELECTOR, "iframe[src*='recaptcha']", timeout=2, raise_exception=False
        )
        if captcha_frame:
            logger.warning("⚠️ Phát hiện reCAPTCHA iframe")
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "captcha_detected")
            db_manager.update_status(account_id, "failed-captcha", last_error="Phát hiện reCAPTCHA")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"❌ Lỗi detect captcha: {e}")
        return False


def _handle_post_signup(
    driver: webdriver.Chrome,
    account: Dict[str, Any],
    db_manager: DatabaseManager,
    account_id: ObjectId,
    telegram_client: TelegramClient,
    screenshots_dir: Path
) -> bool:
    """
    Xử lý sau Signup: check bot message, logout, click Complete
    
    Returns:
        True nếu thành công, False nếu thất bại
    """
    try:
        # Đợi một chút để bot có thời gian gửi message (nếu có)
        Humanizer.random_delay(3, 5)
        
        # TODO: Kiểm tra bot message (cần tích hợp với telegram_listener hoặc query messages)
        # Tạm thời coi như thành công nếu không có error
        
        # Logout Gmail
        logger.info("🚪 Đang logout Gmail...")
        try:
            # Có thể cần navigate đến account settings hoặc dùng URL logout
            driver.get("https://accounts.google.com/Logout")
            Humanizer.random_delay(2, 4)
        except:
            logger.warning("⚠️ Không thể logout, tiếp tục...")
        
        # Update DB: status="waiting-complete"
        db_manager.update_status(account_id, "waiting-complete")
        logger.info("✅ Đã set status=waiting-complete")
        
        # Tự động nhấn nút Complete trên Telegram
        success = _click_complete_button(
            telegram_client,
            account,
            db_manager,
            account_id,
            screenshots_dir
        )
        
        if success:
            db_manager.update_status(account_id, "created")
            logger.info("✅ Account đã được tạo thành công (status=created)")
            return True
        else:
            logger.error("❌ Không thể click Complete button")
            return False
        
    except Exception as e:
        logger.error(f"❌ Lỗi xử lý post-signup: {e}", exc_info=True)
        _take_screenshot(driver, screenshots_dir, account_id, db_manager, "post_signup_error")
        db_manager.update_status(account_id, "failed", last_error=f"Lỗi post-signup: {str(e)}")
        return False


def _click_complete_button(
    telegram_client: TelegramClient,
    account: Dict[str, Any],
    db_manager: DatabaseManager,
    account_id: ObjectId,
    screenshots_dir: Path
) -> bool:
    """
    Tự động nhấn nút Complete trên Telegram với retry 3 lần
    
    Returns:
        True nếu thành công, False nếu thất bại
    """
    try:
        message_chat_id = account.get("message_chat_id") or account.get("source_chat_id")
        message_id_input = account.get("message_id_input")
        
        if not message_chat_id or not message_id_input:
            logger.error("❌ Thiếu message_chat_id hoặc message_id_input")
            db_manager.update_status(
                account_id, "waiting-observe",
                last_error="Thiếu metadata để click Complete button"
            )
            return False
        
        # Retry tối đa 3 lần trong 10 giây
        max_retries = 3
        retry_delay = 10 / max_retries  # Chia đều trong 10 giây
        
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 Attempt {attempt + 1}/{max_retries} - Đang click Complete button...")
                
                # Lấy message để tìm button
                message = asyncio.run_coroutine_threadsafe(
                    telegram_client.get_messages(message_chat_id, ids=message_id_input),
                    telegram_client.loop
                ).result()
                
                if not message:
                    logger.warning(f"⚠️ Không tìm thấy message {message_id_input}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        db_manager.update_status(
                            account_id, "waiting-observe",
                            last_error=f"Không tìm thấy message {message_id_input}"
                        )
                        return False
                
                # Tìm button "Complete" hoặc "❤️ Complete" trong reply_markup
                button_data = None
                if message.reply_markup:
                    for row in message.reply_markup.rows:
                        for button in row.buttons:
                            button_text = getattr(button, 'text', '') or ''
                            if 'complete' in button_text.lower() or '❤️' in button_text:
                                button_data = getattr(button, 'data', None)
                                if button_data:
                                    logger.info(f"✅ Tìm thấy Complete button với data: {button_data}")
                                    break
                        if button_data:
                            break
                
                if not button_data:
                    logger.warning("⚠️ Không tìm thấy Complete button trong message")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        db_manager.update_status(
                            account_id, "waiting-observe",
                            last_error="Không tìm thấy Complete button trong message"
                        )
                        return False
                
                # Click button bằng GetBotCallbackAnswerRequest
                result = asyncio.run_coroutine_threadsafe(
                    telegram_client(GetBotCallbackAnswerRequest(
                        peer=message_chat_id,
                        msg_id=message_id_input,
                        data=button_data
                    )),
                    telegram_client.loop
                ).result()
                
                if result:
                    logger.info("✅ Đã click Complete button thành công")
                    return True
                    
            except Exception as e:
                logger.warning(f"⚠️ Lỗi click Complete attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    logger.error("❌ Không thể click Complete sau 3 attempts")
                    db_manager.update_status(
                        account_id, "waiting-observe",
                        last_error=f"Không thể click Complete: {str(e)}"
                    )
                    return False
        
        return False
        
    except Exception as e:
        logger.error(f"❌ Lỗi click_complete_button: {e}", exc_info=True)
        db_manager.update_status(
            account_id, "waiting-observe",
            last_error=f"Lỗi click Complete: {str(e)}"
        )
        return False


def _take_screenshot(
    driver: Optional[webdriver.Chrome],
    screenshots_dir: Path,
    account_id: ObjectId,
    db_manager: DatabaseManager,
    suffix: str = ""
):
    """
    Chụp screenshot và lưu vào DB
    
    Args:
        driver: Selenium WebDriver
        screenshots_dir: Thư mục lưu screenshots
        account_id: ObjectId của account
        db_manager: DatabaseManager instance
        suffix: Suffix cho tên file
    """
    try:
        if not driver:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"account_{account_id}_{suffix}_{timestamp}.png"
        filepath = screenshots_dir / filename
        
        driver.save_screenshot(str(filepath))
        
        # Update DB với screenshot_path
        db_manager.update_status(account_id, None, screenshot_path=str(filepath))
        
        logger.info(f"📸 Đã chụp screenshot: {filepath}")
        
    except Exception as e:
        logger.error(f"❌ Lỗi chụp screenshot: {e}")

