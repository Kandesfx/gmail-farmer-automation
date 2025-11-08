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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import random
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
    from ..core.constants import (
        PROXY_ERROR_KEYWORDS,
        CAPTCHA_KEYWORDS,
        ELEMENT_WAIT_TIMEOUT,
        TYPING_DELAY_MIN,
        TYPING_DELAY_MAX,
        RANDOM_DELAY_MIN,
        RANDOM_DELAY_MAX
    )
except ImportError:
    from db.database_manager import DatabaseManager
    from core.gpm_manager import GPMManager
    from core.proxy_manager import ProxyManager
    from core.otp_manager import OTPManager
    from utils.humanizer import Humanizer
    from utils.logger import get_logger
    from config import GPM_CHROMEDRIVER_PATH
    from core.constants import (
        PROXY_ERROR_KEYWORDS,
        CAPTCHA_KEYWORDS,
        ELEMENT_WAIT_TIMEOUT,
        TYPING_DELAY_MIN,
        TYPING_DELAY_MAX,
        RANDOM_DELAY_MIN,
        RANDOM_DELAY_MAX
    )

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
            
            # Kiểm tra các lỗi proxy phổ biến (từ constants)
            for error_keyword in PROXY_ERROR_KEYWORDS:
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


def human_type(el, text: str, min_delay: float = 0.15, max_delay: float = 0.5, is_password: bool = False):
    """
    Gõ text với delay ngẫu nhiên từng ký tự (human-like)
    Cải thiện: Thêm backspace/corrections, variation trong typing, pauses tự nhiên hơn
    LƯU Ý: Với password field, KHÔNG có backspace/correction để tránh nhập sai
    
    Args:
        el: Selenium WebElement
        text: Text cần gõ
        min_delay: Delay tối thiểu giữa các ký tự (giây)
        max_delay: Delay tối đa giữa các ký tự (giây)
        is_password: True nếu là password field (sẽ tắt backspace/correction)
    """
    try:
        el.clear()
        # Thêm delay trước khi bắt đầu gõ (giống người dùng suy nghĩ và đọc field)
        if is_password:
            # Với password, delay ngắn hơn một chút (người thường nhập password nhanh hơn)
            time.sleep(random.uniform(0.5, 1.2))
        else:
            time.sleep(random.uniform(0.8, 2.0))  # Tăng delay
        
        # Variation: Đôi khi gõ nhanh hơn, đôi khi chậm hơn (giống người thật)
        typing_speed_variation = random.choice(["slow", "normal", "fast"])
        if typing_speed_variation == "slow":
            char_min, char_max = min_delay * 1.8, max_delay * 1.8  # Chậm hơn 80%
        elif typing_speed_variation == "fast":
            char_min, char_max = min_delay * 0.6, max_delay * 0.6  # Nhanh hơn 40%
        else:
            char_min, char_max = min_delay, max_delay
        
        typed_chars = []
        for i, char in enumerate(text):
            el.send_keys(char)
            typed_chars.append(char)
            
            # Đôi khi có pause dài hơn (giống người đang suy nghĩ hoặc sửa lỗi)
            # Với password, giảm pause dài (người thường nhập password liên tục)
            if is_password:
                if random.random() < 0.05:  # Chỉ 5% khả năng pause dài với password
                    time.sleep(random.uniform(0.5, 1.0))  # Pause ngắn hơn
            else:
                if random.random() < 0.12:  # Tăng lên 12% khả năng có pause dài
                    time.sleep(random.uniform(1.0, 2.5))  # Tăng pause dài hơn
            
            # Đôi khi "sửa lỗi" - backspace và gõ lại (giống người thật)
            # QUAN TRỌNG: KHÔNG áp dụng cho password field để tránh nhập sai
            if not is_password and random.random() < 0.05 and len(typed_chars) > 2:  # 5% khả năng sửa lỗi
                # Backspace 1-2 ký tự
                backspace_count = random.randint(1, 2)
                for _ in range(backspace_count):
                    el.send_keys(Keys.BACKSPACE)
                    time.sleep(random.uniform(0.2, 0.5))
                    if typed_chars:
                        typed_chars.pop()
                
                # Đợi một chút (suy nghĩ)
                time.sleep(random.uniform(0.5, 1.2))
                
                # Gõ lại
                for c in typed_chars[-backspace_count:]:
                    el.send_keys(c)
                    time.sleep(random.uniform(char_min, char_max))
            
            # Delay giữa các ký tự
            delay = random.uniform(char_min, char_max)
            # Thêm variation nhỏ trong delay (giống người gõ không đều)
            delay_variation = random.uniform(0.8, 1.2)
            time.sleep(delay * delay_variation)
            
            # Đôi khi có pause ngắn giữa các từ (sau khoảng trắng)
            # Với password, không có khoảng trắng nên bỏ qua
            if not is_password and char == " " and random.random() < 0.4:  # Tăng lên 40% khả năng pause sau khoảng trắng
                time.sleep(random.uniform(0.4, 0.8))
            
            # Đôi khi có pause sau dấu chấm/câu (giống người đọc lại)
            # Với password, không có dấu chấm nên bỏ qua
            if not is_password and char in [".", "!", "?"] and random.random() < 0.3:
                time.sleep(random.uniform(0.5, 1.0))
    except Exception as e:
        logger.error(f"❌ Lỗi human_type: {e}", exc_info=True)
        raise


def select_dropdown_by_keyboard(
    driver: webdriver.Chrome,
    element,
    target_value: int,
    total_options: int = 12,
    logger=None,
    field_name: str = "dropdown"
) -> bool:
    """
    Chọn dropdown bằng keyboard navigation: Tab + Enter + Arrow keys + Enter
    Phương pháp này tự nhiên hơn và ít bị phát hiện hơn so với click trực tiếp
    
    Args:
        driver: Selenium WebDriver
        element: WebElement của dropdown
        target_value: Giá trị cần chọn (1-12 cho tháng, 1-3 cho giới tính)
        total_options: Tổng số options (12 cho tháng, 3 cho giới tính)
        logger: Logger instance
        field_name: Tên field để log
        
    Returns:
        True nếu thành công, False nếu thất bại
    """
    try:
        if logger:
            logger.info(f"⌨️  Dùng keyboard navigation để chọn {field_name}: {target_value}")
        
        # Bước 1: Tab để focus vào element
        # Gửi Tab vào body để di chuyển focus đến element
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            # Có thể cần Tab nhiều lần để đến element, nhưng để đơn giản, focus trực tiếp
            driver.execute_script("arguments[0].focus();", element)
            Humanizer.random_delay(0.5, 1.0)
        except:
            pass
        
        # Bước 2: Enter để mở dropdown
        element.send_keys(Keys.ENTER)
        Humanizer.random_delay(0.8, 1.2)  # Đợi dropdown mở hoàn toàn
        
        # Bước 3: Dùng Arrow Down để di chuyển đến option cần chọn
        # Tính số lần nhấn Arrow Down (giả sử bắt đầu từ option đầu tiên)
        # Nếu target_value = 1, không cần nhấn (đã ở option đầu)
        # Nếu target_value = 2, nhấn 1 lần Down
        # Nếu target_value = 3, nhấn 2 lần Down
        arrow_presses = target_value - 1
        
        # Lấy active element (dropdown menu) để gửi Arrow keys
        # Sau khi mở dropdown, focus thường chuyển sang dropdown menu
        try:
            active_element = driver.switch_to.active_element
        except:
            active_element = element
        
        # Nhấn Arrow Down để di chuyển đến option cần chọn
        for i in range(arrow_presses):
            try:
                # Thử gửi vào active element trước
                active_element.send_keys(Keys.ARROW_DOWN)
            except:
                try:
                    # Fallback: gửi vào body
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.ARROW_DOWN)
                except:
                    # Fallback cuối: gửi vào element gốc
                    element.send_keys(Keys.ARROW_DOWN)
            
            Humanizer.random_delay(0.5, 1.0)  # Delay giữa các lần nhấn để tự nhiên hơn
        
        Humanizer.random_delay(0.4, 0.6)  # Đợi một chút trước khi confirm
        
        # Bước 4: Enter lần nữa để chọn option
        try:
            active_element.send_keys(Keys.ENTER)
        except:
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ENTER)
            except:
                element.send_keys(Keys.ENTER)
        
        Humanizer.random_delay(1.0, 1.5)  # Đợi dropdown đóng và value được set
        
        # Validation: Kiểm tra xem value đã được set chưa
        try:
            value = element.get_attribute("value")
            if value and value != "" and value != "0":
                # Chuyển value thành int để so sánh
                try:
                    value_int = int(value)
                    if value_int == target_value or str(value_int) == str(target_value):
                        if logger:
                            logger.info(f"✅ Đã chọn {field_name} bằng keyboard: {target_value} (value={value})")
                        return True
                except:
                    # Nếu value là string, kiểm tra xem có chứa target_value không
                    if str(target_value) in str(value):
                        if logger:
                            logger.info(f"✅ Đã chọn {field_name} bằng keyboard: {target_value} (value={value})")
                        return True
        except:
            pass
        
        # Nếu không validate được, vẫn return True (có thể value không có attribute hoặc không cập nhật ngay)
        # Nhưng log warning để biết
        if logger:
            logger.warning(f"⚠️ Keyboard navigation đã thực hiện nhưng không validate được value cho {field_name}")
        return True  # Return True vì đã thực hiện đúng các bước keyboard
        
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ Lỗi khi chọn {field_name} bằng keyboard: {e}")
        return False


def find_next_button(driver: webdriver.Chrome, timeout: int = 10) -> Optional[object]:
    """
    Tìm nút "Next" / "Tiếp theo" với nhiều selectors dựa trên cấu trúc thực tế từ DevTools
    
    Args:
        driver: Selenium WebDriver
        timeout: Timeout cho mỗi selector (giây)
        
    Returns:
        WebElement nếu tìm thấy, None nếu không tìm thấy
    """
    next_selectors = [
        # 1. Button với jsname="LgbsSe" (theo DevTools - ưu tiên cao nhất)
        (By.CSS_SELECTOR, "button[jsname='LgbsSe']"),
        (By.XPATH, "//button[@jsname='LgbsSe']"),
        # 2. Button chứa span với text "Tiếp theo" hoặc "Next"
        (By.XPATH, "//button[.//span[contains(text(), 'Tiếp theo')]]"),
        (By.XPATH, "//button[.//span[contains(text(), 'Next')]]"),
        (By.XPATH, "//button[.//span[normalize-space(text())='Tiếp theo']]"),
        (By.XPATH, "//button[.//span[normalize-space(text())='Next']]"),
        # 3. Span với jsname="V67aGc" (theo DevTools) → tìm parent button
        (By.XPATH, "//span[@jsname='V67aGc' and contains(text(), 'Tiếp theo')]/ancestor::button"),
        (By.XPATH, "//span[@jsname='V67aGc' and contains(text(), 'Next')]/ancestor::button"),
        # 4. Button với class chứa "VfPpkd-LgbsSe" (theo DevTools)
        (By.CSS_SELECTOR, "button.VfPpkd-LgbsSe"),
        (By.CSS_SELECTOR, "button[class*='VfPpkd-LgbsSe']"),
        # 5. Fallback: Button với text trực tiếp
        (By.XPATH, "//button[contains(text(), 'Next')]"),
        (By.XPATH, "//button[contains(text(), 'Tiếp theo')]"),
        # 6. Button với aria-label
        (By.CSS_SELECTOR, "button[aria-label*='Next']"),
        (By.CSS_SELECTOR, "button[aria-label*='Tiếp theo']"),
    ]
    
    for selector_type, selector_value in next_selectors:
        try:
            next_button = Humanizer.wait_for_clickable(
                driver, selector_type, selector_value, timeout=timeout, raise_exception=False
            )
            if next_button:
                logger.debug(f"✅ Tìm thấy nút Next với selector: {selector_type}={selector_value}")
                return next_button
        except Exception as e:
            logger.debug(f"   Selector {selector_type}={selector_value} không tìm thấy: {e}")
            continue
    
    return None


def human_move_mouse_randomly(driver: webdriver.Chrome, target_element=None):
    """
    Di chuyển chuột ngẫu nhiên để giống hành vi người dùng
    Cải thiện: Thêm nhiều chuyển động chuột hơn, bezier curves, scroll tự nhiên
    """
    try:
        actions = ActionChains(driver)
        viewport_width = driver.execute_script("return window.innerWidth")
        viewport_height = driver.execute_script("return window.innerHeight")
        
        # Nếu có target_element, di chuyển đến đó với đường cong tự nhiên
        if target_element:
            try:
                # Lấy vị trí của element
                element_location = target_element.location
                element_size = target_element.size
                target_x = element_location['x'] + element_size['width'] // 2
                target_y = element_location['y'] + element_size['height'] // 2
                
                # Di chuyển với nhiều điểm trung gian (bezier-like curve)
                num_steps = random.randint(3, 6)
                current_x = 0
                current_y = 0
                
                for step in range(num_steps):
                    # Tính toán vị trí trung gian
                    progress = (step + 1) / num_steps
                    # Thêm randomness để tạo đường cong
                    offset_x = random.randint(-50, 50)
                    offset_y = random.randint(-50, 50)
                    
                    intermediate_x = int(current_x + (target_x - current_x) * progress + offset_x)
                    intermediate_y = int(current_y + (target_y - current_y) * progress + offset_y)
                    
                    actions.move_by_offset(intermediate_x - current_x, intermediate_y - current_y)
                    time.sleep(random.uniform(0.05, 0.15))  # Delay nhỏ giữa các bước
                    
                    current_x = intermediate_x
                    current_y = intermediate_y
                
                actions.perform()
                Humanizer.random_delay(0.3, 0.8)
                return
            except:
                pass  # Fallback to random movement
        
        # Di chuyển chuột ngẫu nhiên với nhiều điểm dừng (giống người đang di chuyển chuột)
        num_movements = random.randint(2, 4)
        current_x = 0
        current_y = 0
        
        for _ in range(num_movements):
            x = random.randint(50, max(100, viewport_width - 50))
            y = random.randint(50, max(100, viewport_height - 50))
            
            # Di chuyển với tốc độ ngẫu nhiên
            actions.move_by_offset(x - current_x, y - current_y)
            time.sleep(random.uniform(0.1, 0.3))
            
            current_x = x
            current_y = y
        
        actions.perform()
        Humanizer.random_delay(0.5, 1.5)
        
        # Đôi khi scroll ngẫu nhiên (giống người đang xem trang)
        if random.random() < 0.4:  # Tăng lên 40% khả năng scroll
            scroll_amount = random.randint(-300, 300)
            # Scroll mượt mà hơn với nhiều bước nhỏ
            steps = random.randint(3, 8)
            step_size = scroll_amount // steps
            for _ in range(steps):
                driver.execute_script(f"window.scrollBy(0, {step_size});")
                time.sleep(random.uniform(0.05, 0.15))
            Humanizer.random_delay(0.5, 1.2)
    except Exception as e:
        logger.debug(f"⚠️ Không thể di chuyển chuột: {e}")


def detect_captcha_or_qr(driver: webdriver.Chrome) -> Optional[str]:
    """
    Phát hiện CAPTCHA hoặc QR code trên trang (chỉ khi thực sự hiển thị)
    
    Args:
        driver: Selenium WebDriver
        
    Returns:
        Error message nếu phát hiện CAPTCHA/QR thực sự, None nếu không có
    """
    try:
        # 1. Kiểm tra reCAPTCHA iframe (ưu tiên - chính xác nhất)
        try:
            captcha_frames = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha'], iframe[src*='google.com/recaptcha']")
            for frame in captcha_frames:
                try:
                    # Kiểm tra frame có visible và có kích thước hợp lý (không phải 0x0)
                    if frame.is_displayed():
                        frame_rect = frame.rect
                        if frame_rect['width'] > 0 and frame_rect['height'] > 0:
                            logger.warning("⚠️ Phát hiện reCAPTCHA iframe (visible và có kích thước)")
                            return "Phát hiện reCAPTCHA iframe"
                except:
                    continue
        except Exception as frame_error:
            logger.debug(f"   Không thể kiểm tra reCAPTCHA iframe: {frame_error}")
        
        # 2. Kiểm tra reCAPTCHA div/container (có class/id chứa recaptcha và visible)
        try:
            recaptcha_selectors = [
                "div[class*='recaptcha']",
                "div[id*='recaptcha']",
                "div[class*='g-recaptcha']",
                "div[id*='g-recaptcha']",
                "div[data-sitekey]",  # reCAPTCHA thường có data-sitekey
            ]
            for selector in recaptcha_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            elem_rect = elem.rect
                            # Kiểm tra element có kích thước hợp lý và không bị ẩn
                            if elem_rect['width'] > 50 and elem_rect['height'] > 50:
                                logger.warning(f"⚠️ Phát hiện reCAPTCHA element: {selector}")
                                return f"Phát hiện reCAPTCHA element: {selector}"
                except:
                    continue
        except Exception as elem_error:
            logger.debug(f"   Không thể kiểm tra reCAPTCHA elements: {elem_error}")
        
        # 3. Kiểm tra QR code canvas hoặc img (visible)
        try:
            qr_selectors = [
                "canvas[class*='qr']",
                "img[alt*='qr' i]",
                "img[src*='qr']",
                "canvas[id*='qr']",
                "div[class*='qr-code']",
                "div[id*='qr-code']"
            ]
            for selector in qr_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            elem_rect = elem.rect
                            if elem_rect['width'] > 50 and elem_rect['height'] > 50:
                                logger.warning(f"⚠️ Phát hiện QR code element: {selector}")
                                return f"Phát hiện QR code element: {selector}"
                except:
                    continue
        except Exception as qr_error:
            logger.debug(f"   Không thể kiểm tra QR code: {qr_error}")
        
        # 4. Kiểm tra trong URL (chỉ khi có "captcha" hoặc "challenge" trong URL)
        current_url = driver.current_url.lower()
        if "captcha" in current_url and ("challenge" in current_url or "verify" in current_url):
            logger.warning(f"⚠️ Phát hiện CAPTCHA từ URL: {current_url}")
            return f"Phát hiện CAPTCHA từ URL: {current_url}"
        
        # 5. Kiểm tra text visible trên trang (chỉ khi có text rõ ràng về CAPTCHA/QR)
        try:
            # Tìm các text node có chứa từ khóa CAPTCHA/QR và visible
            captcha_text_selectors = [
                "//*[contains(text(), 'verify you')][contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'human')]",
                "//*[contains(text(), 'i am not a robot')]",
                "//*[contains(text(), 'scan qr code')]",
                "//*[contains(text(), 'scan this qr')]",
            ]
            for selector in captcha_text_selectors:
                try:
                    elements = driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            logger.warning(f"⚠️ Phát hiện CAPTCHA/QR text: {elem.text[:50]}")
                            return f"Phát hiện CAPTCHA/QR text: {elem.text[:50]}"
                except:
                    continue
        except Exception as text_error:
            logger.debug(f"   Không thể kiểm tra CAPTCHA text: {text_error}")
        
        # Không phát hiện CAPTCHA/QR thực sự
        return None
        
    except Exception as e:
        logger.error(f"❌ Lỗi detect_captcha_or_qr: {e}", exc_info=True)
        return None


def signup_via_gmail_homepage(
    driver: webdriver.Chrome,
    account_doc: Dict[str, Any],
    db,
    logger,
    otp_manager: OTPManager,
    telegram_client: TelegramClient,
    screenshots_dir: Path,
    do_not_submit: bool = False
) -> Dict[str, Any]:
    """
    Signup flow từ Gmail homepage: Mở Gmail → "Tạo tài khoản" → "Dành cho cá nhân" → điền form → OTP/Recovery → hoàn tất
    
    Args:
        driver: Selenium WebDriver đã attach remote debugging port từ GPM
        account_doc: Dict chứa fields: first_name, last_name, email, password, _id, message_chat_id, message_id_input
        db: DatabaseManager để update status
        logger: Logger để log tiến trình
        otp_manager: OTPManager để rent phone và get code
        telegram_client: TelegramClient để callback Complete button
        screenshots_dir: Thư mục lưu screenshots
        do_not_submit: Flag test mode - không click final submit
        
    Returns:
        Dict với keys: success (bool), phone_order (Optional[Dict]), error (Optional[str])
    """
    account_id = ObjectId(account_doc["_id"])
    phone_order = None
    
    try:
        logger.info("🚀 Bắt đầu signup flow từ Gmail homepage")
        
        # ============================================================
        # Bước 1: Kiểm tra đã ở Gmail homepage chưa (đã được mở trong create_gmail_account)
        # ============================================================
        try:
            current_url = driver.current_url.lower()
            logger.debug(f"   Current URL: {current_url}")
            
            # Kiểm tra xem đã ở Gmail homepage chưa
            if "gmail" in current_url or "workspace.google.com" in current_url or "mail.google.com" in current_url:
                logger.info("✅ Đã ở Gmail homepage (đã được mở trước đó)")
            elif current_url == "about:blank" or not current_url or current_url.strip() == "":
                # Nếu vẫn là about:blank, mở Gmail homepage
                logger.warning("⚠️ Vẫn ở trang about:blank, đang mở Gmail homepage...")
                driver.get("https://workspace.google.com/intl/vi/gmail/")
                Humanizer.random_delay(1.0, 2.5)
                
                # Kiểm tra lỗi proxy
                proxy_error = _detect_proxy_errors(driver)
                if proxy_error:
                    logger.error(f"❌ {proxy_error} - DỪNG NGAY và KILL PROFILE")
                    _take_screenshot(driver, screenshots_dir, account_id, db, "proxy_error")
                    db.update_status(account_id, "failed-proxy", last_error=proxy_error)
                    raise RuntimeError(f"Proxy error detected: {proxy_error}")
                
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                Humanizer.random_delay(1.0, 2.5)
                logger.info("✅ Đã mở Gmail homepage")
            else:
                logger.info(f"ℹ️ Đang ở trang khác: {current_url}, tiếp tục với flow hiện tại")
        except RuntimeError:
            # Proxy error - đã được xử lý ở trên
            raise
        except Exception as check_error:
            logger.warning(f"⚠️ Không thể kiểm tra current_url: {check_error}, tiếp tục...")
        
        # ============================================================
        # Bước 2: Đợi trang load xong và kiểm tra đã ở trang signup chưa
        # ============================================================
        logger.info("⏳ Đang đợi trang load xong...")
        
        # Đợi page load hoàn toàn
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            Humanizer.random_delay(2, 3)  # Đợi thêm một chút để đảm bảo elements render xong
        except Exception as wait_error:
            logger.warning(f"⚠️ Lỗi khi đợi page load: {wait_error}, tiếp tục...")
        
        # Kiểm tra xem đã ở trang signup chưa (có thể đã navigate trước đó)
        current_url = driver.current_url.lower()
        is_on_signup_page = ("signup" in current_url or "webcreateaccount" in current_url or "createaccount" in current_url or "lifecycle/steps/signup" in current_url)
        
        if is_on_signup_page:
            logger.info("✅ Đã ở trang signup, bỏ qua bước tìm nút 'Tạo tài khoản'")
            logger.info(f"   Current URL: {current_url}")
        else:
            logger.warning(f"⚠️ Chưa ở trang signup (URL: {current_url}), navigate trực tiếp đến signup URL...")
            signup_urls = [
                "https://accounts.google.com/signup/v2/webcreateaccount?hl=vi&flowName=GlifWebSignIn&flowEntry=SignUp",
                "https://accounts.google.com/signup/v2/webcreateaccount?flowName=GlifWebSignIn&flowEntry=SignUp",
                "https://accounts.google.com/signup"
            ]
            
            navigate_success = False
            for signup_url in signup_urls:
                try:
                    logger.info(f"   Đang thử navigate đến: {signup_url}")
                    driver.get(signup_url)
                    
                    # Đợi page load HOÀN TOÀN
                    logger.info("   ⏳ Đang đợi page load xong...")
                    WebDriverWait(driver, 20).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    Humanizer.random_delay(3, 4)  # Đợi thêm để đảm bảo elements render xong
                    
                    # Kiểm tra URL đã chuyển đến signup chưa
                    current_url = driver.current_url.lower()
                    if "signup" in current_url or "webcreateaccount" in current_url or "createaccount" in current_url or "lifecycle/steps/signup" in current_url:
                        logger.info(f"✅ Đã navigate thành công đến signup URL: {signup_url}")
                        logger.info(f"   Current URL: {current_url}")
                        navigate_success = True
                        break
                    else:
                        logger.warning(f"   URL hiện tại không phải signup: {current_url}")
                        continue
                        
                except Exception as nav_error:
                    logger.warning(f"   Không thể navigate đến {signup_url}: {nav_error}")
                    continue
            
            if not navigate_success:
                logger.error("❌ Không thể navigate đến bất kỳ signup URL nào")
                _take_screenshot(driver, screenshots_dir, account_id, db, "signup_navigate_failed")
                db.update_status(account_id, "failed", last_error="Không thể navigate đến signup URL sau nhiều lần thử")
                return {"success": False, "error": "Không thể navigate đến signup URL"}
            
            # Kiểm tra lỗi proxy sau khi navigate
            proxy_error = _detect_proxy_errors(driver)
            if proxy_error:
                logger.error(f"❌ {proxy_error} - DỪNG NGAY và KILL PROFILE")
                _take_screenshot(driver, screenshots_dir, account_id, db, "proxy_error")
                db.update_status(account_id, "failed-proxy", last_error=proxy_error)
                raise RuntimeError(f"Proxy error detected: {proxy_error}")
        
        # Kiểm tra lỗi proxy (nếu chưa check ở trên)
        proxy_error = _detect_proxy_errors(driver)
        if proxy_error:
            logger.error(f"❌ {proxy_error} - DỪNG NGAY và KILL PROFILE")
            _take_screenshot(driver, screenshots_dir, account_id, db, "proxy_error")
            db.update_status(account_id, "failed-proxy", last_error=proxy_error)
            raise RuntimeError(f"Proxy error detected: {proxy_error}")
        
        # Bỏ qua toàn bộ logic tìm và click nút "Tạo tài khoản" vì đã ở trang signup rồi
        # Tiếp tục với bước "For myself" và điền form
        
        # ============================================================
        # Bước 3: Kiểm tra và điền form signup (bỏ qua "For myself" vì đã ở trang signup rồi)
        # ============================================================
        logger.info("✅ Đã ở trang signup form, bắt đầu điền thông tin...")
        
        # Đợi form load xong
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            Humanizer.random_delay(2, 3)  # Đợi thêm để đảm bảo form render xong
        except Exception as wait_error:
            logger.warning(f"⚠️ Lỗi khi đợi form load: {wait_error}, tiếp tục...")
        
        # ============================================================
        # Bước 4: Điền form signup
        # ============================================================
        logger.info("📝 Bắt đầu điền form signup...")
        
        # Detect CAPTCHA/QR trước khi điền form
        captcha_detected = detect_captcha_or_qr(driver)
        if captcha_detected:
            logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
            _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
            db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
            return {"success": False, "error": captcha_detected}
        
        # First Name
        first_name_elem = None
        for attempt in range(3):
            try:
                first_name_elem = Humanizer.wait_for_element(
                    driver, By.ID, "firstName", timeout=10, raise_exception=False
                )
                if first_name_elem:
                    break
            except:
                if attempt < 2:
                    Humanizer.random_delay(1, 2)
                    continue
        
        if not first_name_elem:
            _take_screenshot(driver, screenshots_dir, account_id, db, "form_not_found")
            db.update_status(account_id, "failed", last_error="Không tìm thấy form First Name sau 3 lần retry")
            return {"success": False, "error": "Không tìm thấy form First Name"}
        
        # Di chuyển chuột đến field trước khi gõ (giống người thật)
        human_move_mouse_randomly(driver, target_element=first_name_elem)
        Humanizer.random_delay(0.5, 1.5)  # Pause trước khi bắt đầu gõ
        
        human_type(first_name_elem, account_doc.get("first_name", ""))
        Humanizer.random_delay(2.5, 5.0)  # Tăng delay sau khi điền First Name (giống người đọc lại)
        logger.info("✅ Đã điền First Name")
        
        # Last Name - Logic đặc biệt: nếu là "x" (case-insensitive) → BỎ TRỐNG
        last_name_elem = Humanizer.wait_for_element(
            driver, By.ID, "lastName", timeout=10, raise_exception=False
        )
        
        if last_name_elem:
            last_name = account_doc.get("last_name", "").strip()
            if last_name.lower() == "x":
                logger.info("ℹ️ Last name là 'x', bỏ trống không điền")
                # Không điền gì vào Last Name field
            elif last_name:
                # Di chuyển chuột đến field trước khi gõ
                human_move_mouse_randomly(driver, target_element=last_name_elem)
                Humanizer.random_delay(0.5, 1.5)  # Pause trước khi bắt đầu gõ
                
                human_type(last_name_elem, last_name)
                Humanizer.random_delay(2.5, 5.0)  # Tăng delay sau khi điền Last Name
                logger.info("✅ Đã điền Last Name")
            else:
                logger.info("ℹ️ Không có Last name, bỏ trống")
        
        Humanizer.random_delay(1.0, 2.0)
        
        # Click Next - Sử dụng helper function
        next_button = find_next_button(driver, timeout=10)
        
        if not next_button:
            _take_screenshot(driver, screenshots_dir, account_id, db, "next_button_not_found")
            db.update_status(account_id, "failed", last_error="Không tìm thấy nút Next sau khi thử nhiều selectors")
            return {"success": False, "error": "Không tìm thấy nút Next"}
        
        # Detect CAPTCHA/QR trước khi click Next
        captcha_detected = detect_captcha_or_qr(driver)
        if captcha_detected:
            logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
            _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
            db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
            return {"success": False, "error": captcha_detected}
        
        human_move_mouse_randomly(driver)
        Humanizer.random_delay(0.5, 1.0)  # Đợi một chút trước khi click
        Humanizer.safe_click(driver, next_button)
        Humanizer.random_delay(3, 6)
        logger.info("✅ Đã click Next sau First/Last Name")
        
        # ============================================================
        # Kiểm tra và xử lý màn hình "Thông tin cơ bản" (ngày sinh, giới tính)
        # ============================================================
        logger.info("🔍 Kiểm tra màn hình ngày sinh/giới tính...")
        
        # Kiểm tra xem có phải màn hình ngày sinh/giới tính không
        date_of_birth_indicators = [
            "//input[@id='day']",
            "//input[@id='month']", 
            "//input[@id='year']",
            "//select[@id='day']",
            "//select[@id='month']",
            "//select[@id='year']",
            "//*[contains(text(), 'Nhập ngày sinh')]",
            "//*[contains(text(), 'Ngày sinh')]",
            "//*[contains(text(), 'Thông tin cơ bản')]",
            "//*[contains(@aria-label, 'Ngày')]",
            "//*[contains(@aria-label, 'Tháng')]",
            "//*[contains(@aria-label, 'Năm')]",
        ]
        
        has_date_of_birth = False
        for selector in date_of_birth_indicators:
            try:
                elem = driver.find_element(By.XPATH, selector)
                if elem and elem.is_displayed():
                    has_date_of_birth = True
                    logger.info(f"✅ Phát hiện màn hình ngày sinh/giới tính với selector: {selector}")
                    break
            except:
                continue
        
        if has_date_of_birth:
            logger.info("📅 Bắt đầu điền ngày sinh và giới tính...")
            
            # Luôn chọn random cho tháng và giới tính (không dùng account_doc)
            birth_day = account_doc.get("birth_day") or random.randint(1, 28)
            birth_month = random.randint(1, 12)  # Luôn random
            birth_year = account_doc.get("birth_year") or random.randint(1990, 2005)
            gender = random.choice(["Nam", "Nữ", "Khác"])  # Luôn random, Tiếng Việt
            logger.info(f"🎲 Đã random: Tháng={birth_month}, Giới tính={gender}")
            
            # Điền Ngày
            day_elem = None
            day_selectors = [
                (By.ID, "day"),
                (By.NAME, "day"),
                (By.XPATH, "//select[contains(@aria-label, 'Ngày')]"),
                (By.XPATH, "//input[contains(@aria-label, 'Ngày')]"),
                (By.XPATH, "//*[@id='day']"),
            ]
            for selector_type, selector_value in day_selectors:
                try:
                    day_elem = Humanizer.wait_for_element(
                        driver, selector_type, selector_value, timeout=5, raise_exception=False
                    )
                    if day_elem:
                        break
                except:
                    continue
            
            if day_elem:
                try:
                    if day_elem.tag_name == "select":
                        from selenium.webdriver.support.ui import Select
                        select = Select(day_elem)
                        select.select_by_value(str(birth_day))
                    else:
                        human_move_mouse_randomly(driver)
                        day_elem.clear()
                        human_type(day_elem, str(birth_day))
                    Humanizer.random_delay(0.5, 1.2)
                    logger.info(f"✅ Đã điền Ngày: {birth_day}")
                except Exception as e:
                    logger.warning(f"⚠️ Lỗi điền ngày: {e}")
            
            # Điền Tháng: Tìm combobox -> Tab -> Enter -> Tìm listbox -> Arrow Down -> Enter
            try:
                # Tìm combobox tháng bằng role và aria-label
                month_combobox = None
                month_combobox_selectors = [
                    (By.XPATH, "//div[@role='combobox' and contains(@aria-labelledby, 'i10')]"),  # Tháng thường có i10 trong aria-labelledby
                    (By.XPATH, "//div[@role='combobox' and .//text()[contains(., 'Tháng')]]"),
                    (By.XPATH, "//*[@role='combobox' and @aria-haspopup='listbox']"),
                ]
                
                for selector_type, selector_value in month_combobox_selectors:
                    try:
                        month_combobox = Humanizer.wait_for_element(
                            driver, selector_type, selector_value, timeout=3, raise_exception=False
                        )
                        if month_combobox:
                            logger.debug(f"   Tìm thấy combobox tháng: {selector_value}")
                            break
                    except:
                        continue
                
                if not month_combobox:
                    # Fallback: Tab từ field ngày để đến combobox tháng
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.TAB)
                    Humanizer.random_delay(0.8, 1.5)
                    month_combobox = driver.switch_to.active_element
                
                # Tab để focus vào combobox (nếu chưa focus)
                if month_combobox:
                    try:
                        driver.execute_script("arguments[0].focus();", month_combobox)
                        Humanizer.random_delay(0.5, 1.0)
                    except:
                        pass
                
                # Enter để mở dropdown
                if month_combobox:
                    month_combobox.send_keys(Keys.ENTER)
                else:
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.ENTER)
                
                Humanizer.random_delay(1.5, 2.5)  # Đợi dropdown mở (tăng delay)
                
                # Tìm listbox thực sự: <ul jsname="rymPhb" role="listbox">
                # KHÔNG phải span id="i13" (chỉ là placeholder)
                listbox = None
                try:
                    # Tìm listbox bằng jsname (ổn định nhất)
                    listbox = driver.find_element(By.CSS_SELECTOR, "ul[jsname='rymPhb'][role='listbox']")
                    if listbox and listbox.is_displayed():
                        logger.debug("   Tìm thấy listbox bằng jsname='rymPhb'")
                except:
                    try:
                        # Fallback: tìm listbox bằng role và visible
                        listbox = driver.find_element(By.XPATH, "//ul[@role='listbox' and not(ancestor::*[contains(@style, 'display: none')])]")
                        if listbox and listbox.is_displayed():
                            logger.debug("   Tìm thấy listbox bằng role='listbox'")
                    except:
                        pass
                
                # Tìm và click trực tiếp vào option bằng data-value (chính xác nhất)
                # Không cần Arrow Down nữa, click trực tiếp vào option
                option_clicked = False
                try:
                    # Tìm option bằng data-value (ổn định nhất, không phụ thuộc text)
                    option_elem = driver.find_element(By.XPATH, f"//li[@role='option' and @data-value='{birth_month}']")
                    if option_elem:
                        # Đợi option visible
                        WebDriverWait(driver, 2).until(EC.visibility_of(option_elem))
                        # Scroll vào view
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", option_elem)
                        Humanizer.random_delay(0.5, 1.0)
                        
                        # Thử nhiều cách click
                        try:
                            # Cách 1: Click trực tiếp
                            option_elem.click()
                            option_clicked = True
                            logger.debug(f"   Đã click option tháng bằng click(): data-value={birth_month}")
                        except:
                            try:
                                # Cách 2: JavaScript click (trigger jsaction)
                                driver.execute_script("arguments[0].click();", option_elem)
                                option_clicked = True
                                logger.debug(f"   Đã click option tháng bằng JS: data-value={birth_month}")
                            except:
                                try:
                                    # Cách 3: Trigger jsaction trực tiếp
                                    driver.execute_script("""
                                        var event = new MouseEvent('click', {
                                            bubbles: true,
                                            cancelable: true,
                                            view: window
                                        });
                                        arguments[0].dispatchEvent(event);
                                    """, option_elem)
                                    option_clicked = True
                                    logger.debug(f"   Đã trigger click event cho option: data-value={birth_month}")
                                except:
                                    pass
                except Exception as e:
                    logger.debug(f"   Không tìm thấy option bằng data-value: {e}")
                
                # Nếu không click được bằng data-value, thử tìm bằng text
                if not option_clicked:
                    try:
                        option_selectors = [
                            f"//li[@role='option' and contains(text(), 'Tháng {birth_month}')]",
                            f"//li[@role='option' and .//span[contains(text(), 'Tháng {birth_month}')]]",
                        ]
                        for option_selector in option_selectors:
                            try:
                                option_elem = driver.find_element(By.XPATH, option_selector)
                                if option_elem and option_elem.is_displayed():
                                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", option_elem)
                                    Humanizer.random_delay(0.5, 1.0)
                                    option_elem.click()
                                    option_clicked = True
                                    logger.debug(f"   Đã click option tháng bằng text: Tháng {birth_month}")
                                    break
                            except:
                                continue
                    except:
                        pass
                
                # Nếu vẫn không click được, thử Arrow Down + Enter (fallback)
                if not option_clicked:
                    logger.warning("   Không click được option, thử Arrow Down + Enter")
                    target_element = listbox if listbox else driver.find_element(By.TAG_NAME, "body")
                    arrow_presses = birth_month - 1
                    for i in range(arrow_presses):
                        target_element.send_keys(Keys.ARROW_DOWN)
                        Humanizer.random_delay(0.5, 1.0)
                    Humanizer.random_delay(1.0, 2.0)
                    target_element.send_keys(Keys.ENTER)
                
                Humanizer.random_delay(2.0, 3.5)  # Đợi dropdown đóng (tăng delay)
                
                logger.info(f"✅ Đã chọn Tháng: {birth_month} bằng keyboard (Tab+Enter+Arrow+Enter)")
            except Exception as e:
                logger.warning(f"⚠️ Lỗi chọn tháng bằng keyboard: {e}")
            
            # Điền Năm
            year_elem = None
            year_selectors = [
                (By.ID, "year"),
                (By.NAME, "year"),
                (By.XPATH, "//select[contains(@aria-label, 'Năm')]"),
                (By.XPATH, "//input[contains(@aria-label, 'Năm')]"),
                (By.XPATH, "//*[@id='year']"),
            ]
            for selector_type, selector_value in year_selectors:
                try:
                    year_elem = Humanizer.wait_for_element(
                        driver, selector_type, selector_value, timeout=5, raise_exception=False
                    )
                    if year_elem:
                        break
                except:
                    continue
            
            if year_elem:
                try:
                    if year_elem.tag_name == "select":
                        from selenium.webdriver.support.ui import Select
                        select = Select(year_elem)
                        select.select_by_value(str(birth_year))
                    else:
                        human_move_mouse_randomly(driver)
                        year_elem.clear()
                        human_type(year_elem, str(birth_year))
                    Humanizer.random_delay(0.5, 1.2)
                    logger.info(f"✅ Đã điền Năm: {birth_year}")
                except Exception as e:
                    logger.warning(f"⚠️ Lỗi điền năm: {e}")
            
            # Điền Giới tính: Tìm combobox -> Tab -> Enter -> Tìm listbox -> Arrow Down -> Enter
            try:
                # Tìm combobox giới tính bằng role và aria-label
                gender_combobox = None
                gender_combobox_selectors = [
                    (By.XPATH, "//div[@role='combobox' and contains(@aria-labelledby, 'i11')]"),  # Giới tính thường có i11 trong aria-labelledby
                    (By.XPATH, "//div[@role='combobox' and .//text()[contains(., 'Giới tính')]]"),
                    (By.XPATH, "//*[@role='combobox' and @aria-haspopup='listbox']"),
                ]
                
                for selector_type, selector_value in gender_combobox_selectors:
                    try:
                        gender_combobox = Humanizer.wait_for_element(
                            driver, selector_type, selector_value, timeout=3, raise_exception=False
                        )
                        if gender_combobox:
                            logger.debug(f"   Tìm thấy combobox giới tính: {selector_value}")
                            break
                    except:
                        continue
                
                if not gender_combobox:
                    # Fallback: Tab từ field năm để đến combobox giới tính
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.TAB)
                    Humanizer.random_delay(0.8, 1.5)
                    gender_combobox = driver.switch_to.active_element
                
                # Tab để focus vào combobox (nếu chưa focus)
                if gender_combobox:
                    try:
                        driver.execute_script("arguments[0].focus();", gender_combobox)
                        Humanizer.random_delay(0.5, 1.0)
                    except:
                        pass
                
                # Enter để mở dropdown
                if gender_combobox:
                    gender_combobox.send_keys(Keys.ENTER)
                else:
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.ENTER)
                
                Humanizer.random_delay(1.5, 2.5)  # Đợi dropdown mở (tăng delay)
                
                # Tìm listbox thực sự: <ul jsname="rymPhb" role="listbox">
                # Đợi listbox xuất hiện và sẵn sàng
                listbox = None
                try:
                    # Đợi listbox xuất hiện với explicit wait
                    listbox = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "ul[jsname='rymPhb'][role='listbox']"))
                    )
                    # Đợi listbox visible
                    WebDriverWait(driver, 2).until(EC.visibility_of(listbox))
                    if listbox and listbox.is_displayed():
                        logger.debug("   Tìm thấy listbox giới tính bằng jsname='rymPhb'")
                except:
                    try:
                        # Fallback: tìm listbox bằng role và visible
                        listbox = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, "//ul[@role='listbox' and @aria-label='Giới tính']"))
                        )
                        WebDriverWait(driver, 2).until(EC.visibility_of(listbox))
                        if listbox and listbox.is_displayed():
                            logger.debug("   Tìm thấy listbox giới tính bằng role='listbox' và aria-label")
                    except:
                        try:
                            # Fallback cuối: tìm listbox bằng role
                            listbox = driver.find_element(By.XPATH, "//ul[@role='listbox' and not(ancestor::*[contains(@style, 'display: none')])]")
                            if listbox and listbox.is_displayed():
                                logger.debug("   Tìm thấy listbox giới tính bằng role='listbox'")
                        except:
                            pass
                
                # Map gender thành data-value: Nữ=2, Nam=1, Khác=3 (theo HTML thực tế)
                gender_data_value_map = {
                    "Nữ": "2", "Female": "2",
                    "Nam": "1", "Male": "1",
                    "Khác": "3", "Other": "3"
                }
                gender_data_value = gender_data_value_map.get(gender, "1")
                
                # Tìm và click trực tiếp vào option bằng data-value (chính xác nhất)
                option_clicked = False
                option_selected = False
                max_click_attempts = 3
                
                for click_attempt in range(max_click_attempts):
                    try:
                        # Tìm option trong listbox (nếu có) hoặc toàn bộ page
                        option_elem = None
                        if listbox:
                            # Tìm option trong listbox cụ thể
                            try:
                                option_elem = listbox.find_element(By.XPATH, f".//li[@role='option' and @data-value='{gender_data_value}']")
                                logger.debug(f"   Tìm thấy option trong listbox: {gender} (data-value={gender_data_value})")
                            except:
                                # Fallback: tìm trong toàn bộ page
                                option_elem = driver.find_element(By.XPATH, f"//li[@role='option' and @data-value='{gender_data_value}']")
                        else:
                            # Tìm option trong toàn bộ page
                            option_elem = driver.find_element(By.XPATH, f"//li[@role='option' and @data-value='{gender_data_value}']")
                        
                        if option_elem:
                            # Đợi option visible và clickable
                            try:
                                WebDriverWait(driver, 2).until(EC.visibility_of(option_elem))
                                WebDriverWait(driver, 2).until(EC.element_to_be_clickable(option_elem))
                            except:
                                logger.debug(f"   Attempt {click_attempt + 1}: Option chưa clickable, thử tiếp...")
                            
                            # Scroll vào view
                            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", option_elem)
                            Humanizer.random_delay(0.8, 1.5)
                            
                            # Thử nhiều cách click - ưu tiên click vào span con (thường click được hơn)
                            try:
                                # Cách 1: Click vào span con bên trong (có thể click được hơn)
                                span_elem = option_elem.find_element(By.XPATH, ".//span[@jsname='K4r5Ff']")
                                if span_elem and span_elem.is_displayed():
                                    span_elem.click()
                                    option_clicked = True
                                    logger.debug(f"   Attempt {click_attempt + 1}: Đã click span con trong option giới tính: {gender} (data-value={gender_data_value})")
                            except:
                                try:
                                    # Cách 2: Click trực tiếp vào option (nếu span không click được)
                                    if option_elem.is_displayed() and option_elem.is_enabled():
                                        option_elem.click()
                                        option_clicked = True
                                        logger.debug(f"   Attempt {click_attempt + 1}: Đã click option giới tính bằng click(): {gender} (data-value={gender_data_value})")
                                except:
                                    try:
                                        # Cách 3: ActionChains click (move to element rồi click)
                                        from selenium.webdriver.common.action_chains import ActionChains
                                        actions = ActionChains(driver)
                                        actions.move_to_element(option_elem).pause(0.2).click().perform()
                                        option_clicked = True
                                        logger.debug(f"   Attempt {click_attempt + 1}: Đã click option giới tính bằng ActionChains: {gender} (data-value={gender_data_value})")
                                    except:
                                        try:
                                            # Cách 4: Click vào phần tử con khác
                                            try:
                                                # Thử click vào div con
                                                div_elem = option_elem.find_element(By.XPATH, ".//div[contains(@class, 'VfPpkd-rymPhb-Gtdoyb')]")
                                                div_elem.click()
                                                option_clicked = True
                                                logger.debug(f"   Attempt {click_attempt + 1}: Đã click div con trong option giới tính: {gender} (data-value={gender_data_value})")
                                            except:
                                                # Fallback: JavaScript click (chỉ khi các cách trên đều thất bại)
                                                driver.execute_script("arguments[0].click();", option_elem)
                                                option_clicked = True
                                                logger.debug(f"   Attempt {click_attempt + 1}: Đã click option giới tính bằng JS (fallback): {gender} (data-value={gender_data_value})")
                                        except:
                                            pass
                            
                            # Đợi một chút sau khi click để dropdown đóng và giá trị được set
                            if option_clicked:
                                Humanizer.random_delay(0.8, 1.2)
                                
                                # Kiểm tra xem option đã được chọn chưa bằng cách check span id="i17" (hoặc id động)
                                try:
                                    # Tìm span chứa giá trị giới tính (có thể là i17, c10, hoặc id động)
                                    value_span_selectors = [
                                        f"//span[@id='i17' and contains(@aria-label, '{gender}')]",
                                        f"//span[@jsname='Fb0Bif' and contains(@aria-label, '{gender}')]",
                                        f"//span[contains(@aria-label, '{gender}') and ancestor::div[@id='gender']]",
                                    ]
                                    
                                    for value_span_selector in value_span_selectors:
                                        try:
                                            value_span = driver.find_element(By.XPATH, value_span_selector)
                                            value_text = value_span.get_attribute("aria-label") or value_span.text
                                            if value_text and gender in value_text:
                                                option_selected = True
                                                logger.info(f"✅ Đã chọn giới tính thành công (attempt {click_attempt + 1}): {gender} (value={value_text})")
                                                break
                                        except:
                                            continue
                                    
                                    # Nếu chưa tìm thấy, kiểm tra aria-selected="true" trên option
                                    if not option_selected:
                                        try:
                                            selected_option = driver.find_element(By.XPATH, f"//li[@role='option' and @data-value='{gender_data_value}' and @aria-selected='true']")
                                            if selected_option:
                                                option_selected = True
                                                logger.info(f"✅ Option đã được chọn (aria-selected=true) (attempt {click_attempt + 1}): {gender}")
                                        except:
                                            pass
                                    
                                    # Kiểm tra aria-expanded="false" để xác nhận dropdown đã đóng
                                    if not option_selected:
                                        try:
                                            aria_expanded = gender_combobox.get_attribute("aria-expanded")
                                            if aria_expanded == "false":
                                                # Dropdown đã đóng, có thể đã chọn thành công
                                                option_selected = True
                                                logger.info(f"✅ Dropdown đã đóng, coi như đã chọn (attempt {click_attempt + 1}): {gender}")
                                        except:
                                            pass
                                    
                                except:
                                    pass
                                
                                if option_selected:
                                    break
                                else:
                                    logger.warning(f"   Attempt {click_attempt + 1}: Click thành công nhưng chưa thấy giá trị được set, thử lại...")
                                    if click_attempt < max_click_attempts - 1:
                                        Humanizer.random_delay(0.5, 1.0)
                                        continue
                    except Exception as e:
                        logger.debug(f"   Attempt {click_attempt + 1}: Không tìm thấy option bằng data-value: {e}")
                        if click_attempt < max_click_attempts - 1:
                            Humanizer.random_delay(0.5, 1.0)
                            continue
                
                # Nếu không click được bằng data-value, thử tìm bằng text
                if not option_clicked:
                    try:
                        option_selectors = [
                            f"//li[@role='option' and .//span[contains(text(), '{gender}')]]",
                            f"//li[@role='option' and contains(text(), '{gender}')]",
                        ]
                        for option_selector in option_selectors:
                            try:
                                option_elem = driver.find_element(By.XPATH, option_selector)
                                if option_elem and option_elem.is_displayed():
                                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", option_elem)
                                    Humanizer.random_delay(0.5, 1.0)
                                    option_elem.click()
                                    option_clicked = True
                                    logger.debug(f"   Đã click option giới tính bằng text: {gender}")
                                    break
                            except:
                                continue
                    except:
                        pass
                
                # Nếu vẫn không click được, thử Arrow Down + Enter (fallback)
                if not option_clicked:
                    logger.warning("   Không click được option giới tính, thử Arrow Down + Enter")
                    gender_arrow_map = {"Nữ": 0, "Nam": 1, "Khác": 2, "Female": 0, "Male": 1, "Other": 2}
                    arrow_presses = gender_arrow_map.get(gender, 0)
                    target_element = listbox if listbox else driver.find_element(By.TAG_NAME, "body")
                    for i in range(arrow_presses):
                        target_element.send_keys(Keys.ARROW_DOWN)
                        Humanizer.random_delay(0.5, 1.0)
                    Humanizer.random_delay(1.0, 2.0)
                    target_element.send_keys(Keys.ENTER)
                
                Humanizer.random_delay(2.0, 3.5)  # Đợi dropdown đóng (tăng delay)
                
                # Validation: Kiểm tra xem giới tính đã được chọn chưa và dropdown đã đóng chưa
                # Tìm combobox giới tính để check value
                dropdown_closed = False
                try:
                    gender_combobox_check = None
                    gender_combobox_selectors_check = [
                        (By.XPATH, "//div[@role='combobox' and contains(@aria-labelledby, 'c9')]"),
                        (By.XPATH, "//div[@role='combobox' and .//text()[contains(., 'Giới tính')]]"),
                        (By.XPATH, "//*[@role='combobox' and @aria-haspopup='listbox']"),
                    ]
                    for selector_type, selector_value in gender_combobox_selectors_check:
                        try:
                            gender_combobox_check = driver.find_element(selector_type, selector_value)
                            if gender_combobox_check:
                                break
                        except:
                            continue
                    
                    if gender_combobox_check:
                        # Kiểm tra aria-expanded để xem dropdown đã đóng chưa
                        max_wait_attempts = 5
                        for attempt in range(max_wait_attempts):
                            try:
                                aria_expanded = gender_combobox_check.get_attribute("aria-expanded")
                                if aria_expanded == "false":
                                    dropdown_closed = True
                                    logger.info(f"✅ Dropdown giới tính đã đóng (attempt {attempt + 1})")
                                    break
                                else:
                                    logger.debug(f"   Dropdown vẫn mở (aria-expanded={aria_expanded}), đợi thêm...")
                                    Humanizer.random_delay(0.5, 1.0)
                            except:
                                pass
                        
                        # Nếu dropdown vẫn mở, thử đóng bằng cách click vào body hoặc ESC
                        if not dropdown_closed:
                            logger.warning("⚠️ Dropdown giới tính vẫn mở, thử đóng bằng ESC hoặc click body")
                            try:
                                body = driver.find_element(By.TAG_NAME, "body")
                                body.send_keys(Keys.ESCAPE)
                                Humanizer.random_delay(0.5, 1.0)
                                # Kiểm tra lại
                                aria_expanded = gender_combobox_check.get_attribute("aria-expanded")
                                if aria_expanded == "false":
                                    dropdown_closed = True
                                    logger.info("✅ Đã đóng dropdown bằng ESC")
                            except:
                                pass
                        
                        # Kiểm tra span id="c10" có chứa giá trị giới tính không
                        try:
                            value_span = driver.find_element(By.ID, "c10")
                            value_text = value_span.get_attribute("aria-label") or value_span.text
                            if value_text and gender in value_text:
                                logger.info(f"✅ Đã chọn Giới tính thành công: {gender} (value={value_text})")
                            else:
                                logger.warning(f"⚠️ Giới tính chưa được set đúng: expected={gender}, actual={value_text}")
                        except:
                            pass
                except:
                    pass
                
                # Đảm bảo dropdown đã đóng trước khi tiếp tục
                if not dropdown_closed:
                    logger.warning("⚠️ Dropdown giới tính có thể vẫn mở, thử đóng lại...")
                    try:
                        body = driver.find_element(By.TAG_NAME, "body")
                        body.send_keys(Keys.ESCAPE)
                        Humanizer.random_delay(0.5, 1.0)
                    except:
                        pass
                
                logger.info(f"✅ Đã xử lý Giới tính: {gender}")
            except Exception as e:
                logger.warning(f"⚠️ Lỗi chọn giới tính: {e}")
            
            Humanizer.random_delay(2.0, 4.0)  # Tăng delay sau khi điền form
            
            # Click Next sau khi điền ngày sinh/giới tính
            # Đảm bảo dropdown đã đóng trước khi click Next
            Humanizer.random_delay(2.0, 4.0)  # Tăng delay để đảm bảo dropdown đóng
            
            next_button_dob = find_next_button(driver, timeout=10)
            if next_button_dob:
                # Detect CAPTCHA/QR trước khi click
                captcha_detected = detect_captcha_or_qr(driver)
                if captcha_detected:
                    logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
                    _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
                    db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
                    return {"success": False, "error": captcha_detected}
                
                # Kiểm tra xem có element nào che button không (như dropdown)
                try:
                    # Thử scroll button vào view và đợi nó clickable
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", next_button_dob)
                    Humanizer.random_delay(0.5, 1.0)
                    
                    # Đợi button clickable
                    WebDriverWait(driver, 3).until(EC.element_to_be_clickable(next_button_dob))
                except:
                    logger.warning("⚠️ Button Next có thể bị che, thử đóng dropdown...")
                    try:
                        body = driver.find_element(By.TAG_NAME, "body")
                        body.send_keys(Keys.ESCAPE)
                        Humanizer.random_delay(0.5, 1.0)
                    except:
                        pass
                
                human_move_mouse_randomly(driver)
                Humanizer.random_delay(1.0, 2.5)  # Tăng delay trước khi click (đọc button)
                Humanizer.safe_click(driver, next_button_dob)
                Humanizer.random_delay(4, 8)  # Tăng delay sau click (đợi page load)
                logger.info("✅ Đã click Next sau ngày sinh/giới tính")
            else:
                logger.warning("⚠️ Không tìm thấy nút Next sau ngày sinh/giới tính, tiếp tục...")
        else:
            logger.info("ℹ️ Không phát hiện màn hình ngày sinh/giới tính, tiếp tục tìm username...")
        
        # Username (Email) - Xử lý 2 trường hợp
        # Trường hợp 1: Google cho chọn giữa các Gmail có sẵn hoặc tạo mới
        # Trường hợp 2: Chỉ có form nhập Gmail
        
        # Kiểm tra trường hợp 1: Có radio buttons với các Gmail có sẵn
        has_gmail_options = False
        try:
            # Tìm text "Chọn địa chỉ Gmail của bạn" hoặc radio buttons
            gmail_choice_indicators = [
                "//*[contains(text(), 'Chọn địa chỉ Gmail')]",
                "//*[contains(text(), 'Choose your Gmail address')]",
                "//input[@type='radio' and contains(@value, '@gmail.com')]",
                "//label[contains(text(), '@gmail.com')]",
                "//*[contains(text(), 'w') and contains(text(), '@gmail.com')]",  # Pattern: w123456@gmail.com
            ]
            
            for indicator in gmail_choice_indicators:
                try:
                    elems = driver.find_elements(By.XPATH, indicator)
                    for elem in elems:
                        if elem and elem.is_displayed():
                            has_gmail_options = True
                            logger.info(f"📧 Phát hiện trường hợp 1: Google cho chọn Gmail có sẵn (indicator: {indicator})")
                            break
                    if has_gmail_options:
                        break
                except:
                    continue
        except:
            pass
        
        # Xử lý trường hợp 1: Click vào "Tạo địa chỉ Gmail của riêng bạn"
        if has_gmail_options:
            try:
                option_clicked = False
                option_selected = False
                
                # Cách 0: Tìm và click trực tiếp vào div cha có thể click được (ưu tiên cao nhất - theo HTML structure)
                try:
                    # Tìm trực tiếp div cha có thể click được theo nhiều cách
                    # Theo HTML: 
                    # - Khi chưa tích: <div data-value="custom" jscontroller="SU9Rsf" jsaction="click:cOuCgd...">
                    # - Khi đã tích: <div class="sfqPrd rBUW7e" jsaction="click:va5fqd..." data-option-jsname="UgJMid">
                    parent_div_selectors = [
                        # Tìm div có data-option-jsname="UgJMid" (khi đã tích)
                        "//div[@data-option-jsname='UgJMid']",
                        # Tìm div có jsaction="click:va5fqd" và chứa input value="custom"
                        "//div[@jsaction and contains(@jsaction, 'click:va5fqd') and .//input[@value='custom']]",
                        # Tìm div có data-value="custom" và jsaction (khi chưa tích)
                        "//div[@data-value='custom' and @jsaction]",
                        # Tìm div có class "sfqPrd" và chứa input value="custom"
                        "//div[contains(@class, 'sfqPrd') and .//input[@value='custom']]",
                        # Tìm div chứa text "Tạo địa chỉ Gmail của riêng bạn" và có jsaction
                        "//div[contains(text(), 'Tạo địa chỉ Gmail của riêng bạn')]/ancestor::div[@jsaction][1]",
                    ]
                    
                    for parent_selector in parent_div_selectors:
                        try:
                            parent_div = driver.find_element(By.XPATH, parent_selector)
                            if parent_div and parent_div.is_displayed():
                                # Scroll vào view
                                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", parent_div)
                                Humanizer.random_delay(0.8, 1.5)
                                
                                # Thử nhiều cách click vào div cha
                                click_success = False
                                click_methods = [
                                    (lambda: parent_div.click(), "click trực tiếp"),
                                    (lambda: driver.execute_script("arguments[0].click();", parent_div), "JavaScript click"),
                                    (lambda: ActionChains(driver).move_to_element(parent_div).pause(0.2).click().perform(), "ActionChains click"),
                                    # Trigger jsaction trực tiếp
                                    (lambda: driver.execute_script("""
                                        var event = new MouseEvent('click', {
                                            view: window,
                                            bubbles: true,
                                            cancelable: true
                                        });
                                        arguments[0].dispatchEvent(event);
                                    """, parent_div), "trigger click event"),
                                ]
                                
                                for click_method, method_name in click_methods:
                                    try:
                                        click_method()
                                        option_clicked = True
                                        click_success = True
                                        logger.info(f"✅ Đã click div cha bằng {method_name} (selector: {parent_selector})")
                                        break
                                    except Exception as click_err:
                                        logger.debug(f"   Không click được bằng {method_name}: {click_err}")
                                        continue
                                
                                if click_success:
                                    # Tìm radio button để kiểm tra
                                    try:
                                        custom_radio = parent_div.find_element(By.XPATH, ".//input[@value='custom']")
                                        if custom_radio:
                                            # Kiểm tra is_selected với retry
                                            for check_attempt in range(5):  # Tăng retry lên 5 lần
                                                Humanizer.random_delay(0.5, 1.0)
                                                try:
                                                    if custom_radio.is_selected():
                                                        option_selected = True
                                                        logger.info(f"✅ Radio button custom đã được chọn (is_selected=true, attempt {check_attempt + 1})")
                                                        break
                                                    else:
                                                        logger.debug(f"   Radio button chưa được chọn (attempt {check_attempt + 1}), đợi thêm...")
                                                except:
                                                    pass
                                            
                                            # Nếu vẫn chưa được chọn, thử click lại
                                            if not option_selected:
                                                logger.warning("⚠️ Radio button chưa được chọn sau 5 lần kiểm tra, thử click lại...")
                                                try:
                                                    driver.execute_script("arguments[0].click();", parent_div)
                                                    Humanizer.random_delay(1.0, 2.0)
                                                    if custom_radio.is_selected():
                                                        option_selected = True
                                                        logger.info("✅ Radio button đã được chọn sau khi click lại")
                                                except:
                                                    pass
                                            
                                            if option_selected:
                                                break
                                    except:
                                        pass
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"   Không tìm thấy div cha có thể click được: {e}")
                
                # Cách 0.5: Tìm radio button và click vào div cha của nó
                if not option_selected:
                    try:
                        # Tìm bằng value="custom" và jsname="YPqjbf" (theo HTML thực tế)
                        custom_radio_selectors = [
                            "//input[@type='radio' and @value='custom' and @jsname='YPqjbf']",
                            "//input[@type='radio' and @value='custom']",
                            "//input[@type='radio' and @name='usernameRadio' and @value='custom']",
                            "//input[@type='radio' and @jsname='YPqjbf']",
                        ]
                        
                        for selector in custom_radio_selectors:
                            try:
                                custom_radio = driver.find_element(By.XPATH, selector)
                            except:
                                continue
                            
                            try:
                                if custom_radio and custom_radio.is_displayed():
                                    # Scroll vào view
                                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", custom_radio)
                                    Humanizer.random_delay(0.8, 1.5)
                                    
                                    # Tìm các element có thể click được (theo HTML structure)
                                    clickable_elements = []
                                    
                                    # 1. Tìm div cha có jsaction="click:va5fqd" (theo HTML khi đã tích)
                                    try:
                                        parent_div = custom_radio.find_element(By.XPATH, "./ancestor::div[@jsaction and contains(@jsaction, 'click:va5fqd')]")
                                        if parent_div:
                                            clickable_elements.append((parent_div, "div cha có jsaction"))
                                    except:
                                        pass
                                    
                                    # 2. Tìm div có data-value="custom" và jsaction
                                    try:
                                        data_value_div = custom_radio.find_element(By.XPATH, "./ancestor::div[@data-value='custom' and @jsaction]")
                                        if data_value_div:
                                            clickable_elements.append((data_value_div, "div có data-value='custom'"))
                                    except:
                                        pass
                                    
                                    # 3. Tìm label qua aria-labelledby
                                    try:
                                        aria_labelledby = custom_radio.get_attribute("aria-labelledby")
                                        if aria_labelledby:
                                            label = driver.find_element(By.ID, aria_labelledby)
                                            if label:
                                                clickable_elements.append((label, "label qua aria-labelledby"))
                                    except:
                                        pass
                                    
                                    # 4. Tìm div chứa text "Tạo địa chỉ Gmail của riêng bạn"
                                    try:
                                        text_div = driver.find_element(By.XPATH, "//div[contains(text(), 'Tạo địa chỉ Gmail của riêng bạn') and ancestor::div[@data-value='custom']]")
                                        if text_div:
                                            clickable_elements.append((text_div, "div chứa text"))
                                    except:
                                        pass
                                    
                                    # Thử click vào các element có thể click được
                                    click_attempts = [
                                        # Ưu tiên: Click vào div cha có jsaction
                                        *[(lambda elem=elem: elem.click(), f"{name}") for elem, name in clickable_elements],
                                        # Fallback: Click trực tiếp vào radio button
                                        (lambda: custom_radio.click(), "click trực tiếp vào input"),
                                        # JavaScript click
                                        (lambda: driver.execute_script("arguments[0].click();", custom_radio), "JavaScript click"),
                                        # ActionChains click
                                        (lambda: ActionChains(driver).move_to_element(custom_radio).pause(0.2).click().perform(), "ActionChains click"),
                                    ]
                                    
                                    for click_method, method_name in click_attempts:
                                        try:
                                            click_method()
                                            option_clicked = True
                                            logger.info(f"✅ Đã click radio button custom bằng {method_name} (selector: {selector})")
                                            break
                                        except:
                                            continue
                                    
                                    # Kiểm tra xem radio button đã được chọn chưa (với retry)
                                    if option_clicked:
                                        # Retry kiểm tra is_selected() nhiều lần vì có thể cần thời gian để update
                                        for check_attempt in range(3):
                                            Humanizer.random_delay(0.5, 1.0)
                                            try:
                                                if custom_radio.is_selected():
                                                    option_selected = True
                                                    logger.info(f"✅ Radio button custom đã được chọn (is_selected=true, attempt {check_attempt + 1})")
                                                    break
                                                else:
                                                    logger.debug(f"   Radio button chưa được chọn (attempt {check_attempt + 1}), đợi thêm...")
                                            except:
                                                pass
                                        
                                        # Nếu vẫn chưa được chọn, thử click lại và kiểm tra bằng nhiều cách
                                        if not option_selected:
                                            logger.warning("⚠️ Radio button chưa được chọn sau khi click, thử click lại...")
                                            try:
                                                # Thử click lại bằng JavaScript
                                                driver.execute_script("arguments[0].click();", custom_radio)
                                                Humanizer.random_delay(0.5, 1.0)
                                                
                                                # Kiểm tra bằng nhiều cách
                                                if custom_radio.is_selected():
                                                    option_selected = True
                                                    logger.info("✅ Radio button đã được chọn sau khi click lại (is_selected)")
                                                elif custom_radio.get_attribute("checked") == "true":
                                                    option_selected = True
                                                    logger.info("✅ Radio button đã được chọn sau khi click lại (checked attribute)")
                                                elif custom_radio.get_attribute("aria-checked") == "true":
                                                    option_selected = True
                                                    logger.info("✅ Radio button đã được chọn sau khi click lại (aria-checked)")
                                            except:
                                                pass
                                        
                                        # Kiểm tra cuối cùng: Tìm lại radio button và check
                                        if not option_selected:
                                            try:
                                                # Tìm lại radio button và check
                                                recheck_radio = driver.find_element(By.XPATH, selector)
                                                if recheck_radio.is_selected() or recheck_radio.get_attribute("checked") == "true":
                                                    option_selected = True
                                                    logger.info("✅ Radio button đã được chọn (recheck)")
                                            except:
                                                pass
                                        
                                        if option_selected:
                                            break
                            except:
                                continue
                    except Exception as e:
                        logger.debug(f"   Không tìm thấy radio button custom: {e}")
                
                # Cách 1: Tìm radio button cuối cùng (thường là option tạo mới) - cách này đơn giản và hiệu quả nhất
                try:
                    radios = driver.find_elements(By.XPATH, "//input[@type='radio']")
                    if radios and len(radios) >= 3:  # Có ít nhất 3 radio buttons (2 Gmail có sẵn + 1 tạo mới)
                        last_radio = radios[-1]  # Radio button cuối cùng
                        if last_radio and last_radio.is_displayed():
                            # Scroll vào view
                            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", last_radio)
                            Humanizer.random_delay(0.8, 1.5)
                            
                            # Thử click radio button
                            try:
                                last_radio.click()
                                option_clicked = True
                                logger.info("✅ Đã click radio button cuối cùng (option tạo mới)")
                            except:
                                # Thử click label liên quan
                                try:
                                    # Tìm label liên quan với radio button
                                    radio_id = last_radio.get_attribute("id")
                                    if radio_id:
                                        label = driver.find_element(By.XPATH, f"//label[@for='{radio_id}']")
                                        label.click()
                                        option_clicked = True
                                        logger.info("✅ Đã click label của radio button cuối cùng")
                                except:
                                    pass
                            
                            # Kiểm tra xem radio button đã được chọn chưa (với retry)
                            if option_clicked:
                                # Retry kiểm tra is_selected() nhiều lần
                                for check_attempt in range(3):
                                    Humanizer.random_delay(0.5, 1.0)
                                    try:
                                        if last_radio.is_selected():
                                            option_selected = True
                                            logger.info(f"✅ Radio button đã được chọn (is_selected=true, attempt {check_attempt + 1})")
                                            break
                                    except:
                                        pass
                                
                                # Nếu vẫn chưa được chọn, thử click lại
                                if not option_selected:
                                    logger.warning("⚠️ Radio button cuối cùng chưa được chọn, thử click lại...")
                                    try:
                                        driver.execute_script("arguments[0].click();", last_radio)
                                        Humanizer.random_delay(0.5, 1.0)
                                        if last_radio.is_selected():
                                            option_selected = True
                                            logger.info("✅ Radio button đã được chọn sau khi click lại")
                                    except:
                                        pass
                except Exception as e:
                    logger.debug(f"   Không tìm thấy radio button cuối cùng: {e}")
                
                # Cách 2: Tìm label "Tạo địa chỉ Gmail của riêng bạn" và click
                if not option_selected:
                    create_own_options = [
                        "//label[contains(text(), 'Tạo địa chỉ Gmail của riêng bạn')]",
                        "//label[contains(text(), 'Create your own Gmail address')]",
                        "//*[contains(text(), 'Tạo địa chỉ Gmail của riêng bạn') and (self::label or ancestor::label)]",
                        "//*[contains(text(), 'Create your own Gmail address') and (self::label or ancestor::label)]",
                    ]
                    
                    for option_selector in create_own_options:
                        try:
                            option_elem = driver.find_element(By.XPATH, option_selector)
                            if option_elem and option_elem.is_displayed():
                                # Scroll vào view
                                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", option_elem)
                                Humanizer.random_delay(0.8, 1.5)
                                
                                # Thử click trực tiếp vào label
                                try:
                                    option_elem.click()
                                    option_clicked = True
                                    logger.info("✅ Đã click label 'Tạo địa chỉ Gmail của riêng bạn'")
                                    
                                    # Kiểm tra xem radio button đã được chọn chưa
                                    Humanizer.random_delay(0.5, 1.0)
                                    try:
                                        # Tìm radio button liên quan
                                        radio = option_elem.find_element(By.XPATH, "./preceding-sibling::input[@type='radio'] | ./following-sibling::input[@type='radio'] | ./ancestor::label/input[@type='radio'] | ./input[@type='radio'] | //input[@type='radio'][following-sibling::label[contains(text(), 'Tạo địa chỉ Gmail')]]")
                                        if radio and radio.is_selected():
                                            option_selected = True
                                            logger.info("✅ Radio button đã được chọn sau khi click label")
                                    except:
                                        pass
                                    
                                    if option_selected:
                                        break
                                except:
                                    # Thử tìm và click radio button trực tiếp
                                    try:
                                        radio = option_elem.find_element(By.XPATH, "./preceding-sibling::input[@type='radio'] | ./following-sibling::input[@type='radio'] | ./ancestor::label/input[@type='radio'] | ./input[@type='radio']")
                                        if radio:
                                            radio.click()
                                            option_clicked = True
                                            logger.info("✅ Đã click radio button 'Tạo địa chỉ Gmail của riêng bạn'")
                                            
                                            Humanizer.random_delay(0.5, 1.0)
                                            if radio.is_selected():
                                                option_selected = True
                                                logger.info("✅ Radio button đã được chọn")
                                            break
                                    except:
                                        continue
                        except:
                            continue
                
                # Cách 3: Tìm tất cả radio buttons và click cái cuối cùng (fallback)
                if not option_selected:
                    try:
                        radios = driver.find_elements(By.XPATH, "//input[@type='radio']")
                        if radios:
                            last_radio = radios[-1]
                            if last_radio and last_radio.is_displayed():
                                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", last_radio)
                                Humanizer.random_delay(0.8, 1.5)
                                last_radio.click()
                                option_clicked = True
                                logger.info("✅ Đã click radio button cuối cùng (fallback)")
                                
                                Humanizer.random_delay(0.5, 1.0)
                                if last_radio.is_selected():
                                    option_selected = True
                                    logger.info("✅ Radio button cuối cùng đã được chọn")
                    except:
                        pass
                
                # Chỉ đợi form xuất hiện nếu radio button đã được chọn thành công
                if option_selected:
                    logger.info("✅ Radio button đã được chọn, đợi form nhập Gmail xuất hiện...")
                    # Đợi input field xuất hiện với explicit wait (tăng timeout)
                    try:
                        WebDriverWait(driver, 10).until(
                            lambda d: d.find_elements(By.XPATH, "//input[contains(@aria-label, 'Tạo một địa chỉ Gmail') or contains(@aria-label, 'Create a Gmail address') or contains(@aria-label, 'Tên người dùng') or contains(@aria-label, 'Username')]")
                        )
                        logger.info("✅ Input field đã xuất hiện")
                    except:
                        logger.warning("⚠️ Timeout đợi input field xuất hiện, tiếp tục tìm...")
                    Humanizer.random_delay(2.0, 3.0)  # Tăng delay để đảm bảo field sẵn sàng
                elif option_clicked:
                    logger.warning("⚠️ Đã click radio button nhưng chưa xác nhận được chọn, đợi thêm...")
                    Humanizer.random_delay(2.0, 4.0)  # Đợi lâu hơn nếu chưa chắc chắn
                else:
                    logger.warning("⚠️ Không click được radio button 'Tạo địa chỉ Gmail của riêng bạn', có thể đang ở trường hợp 2 (form nhập trực tiếp)")
            except Exception as e:
                logger.warning(f"⚠️ Lỗi khi xử lý trường hợp chọn Gmail: {e}")
        
        # Username (Email) - Điền Gmail
        # Tăng timeout và retry vì có thể cần đợi form xuất hiện sau khi click option
        username_elem = None
        for attempt in range(8):  # Tăng retry lên 8 lần
            try:
                # Thử nhiều selector để tìm username field
                # Chỉ giữ lại các selector đã thành công trong thực tế
                username_selectors = [
                    # Selector đã thành công: "Tên người dùng" (trường hợp 2)
                    (By.XPATH, "//input[contains(@aria-label, 'Tên người dùng')]"),
                    (By.XPATH, "//input[contains(@aria-label, 'Username')]"),
                    # Selector đã thành công: jsname (Google thường dùng)
                    (By.XPATH, "//input[@jsname='YPqjbf']"),
                    # Selector cho trường hợp 1: "Tạo một địa chỉ Gmail" (sau khi click option)
                    (By.XPATH, "//input[contains(@aria-label, 'Tạo một địa chỉ Gmail')]"),
                    (By.XPATH, "//input[contains(@aria-label, 'Create a Gmail address')]"),
                    # Selector chung (fallback)
                    (By.ID, "username"),
                    (By.NAME, "username"),
                ]
                
                for selector_type, selector_value in username_selectors:
                    try:
                        username_elem = Humanizer.wait_for_element(
                            driver, selector_type, selector_value, timeout=3, raise_exception=False
                        )
                        if username_elem and username_elem.is_displayed() and username_elem.is_enabled():
                            logger.info(f"✅ Tìm thấy username field: {selector_type}={selector_value}")
                            break
                    except:
                        continue
                
                if username_elem:
                    break
                    
            except:
                pass
            
            if attempt < 7:
                Humanizer.random_delay(1, 2)
                logger.debug(f"   Retry {attempt + 1}/8: Đang tìm username field...")
                continue
        
        if username_elem:
            try:
                # Đảm bảo input field sẵn sàng: scroll vào view, focus, clear
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", username_elem)
                Humanizer.random_delay(0.3, 0.5)
                
                # Focus vào input
                try:
                    username_elem.click()  # Click để focus
                    Humanizer.random_delay(0.5, 1.0)
                except:
                    try:
                        driver.execute_script("arguments[0].focus();", username_elem)
                        Humanizer.random_delay(0.5, 1.0)
                    except:
                        pass
                
                # Clear input nếu có giá trị cũ
                try:
                    username_elem.clear()
                    Humanizer.random_delay(0.5, 1.0)
                except:
                    pass
                
                # Điền email
                email_local = account_doc.get("email", "").split("@")[0]
                human_move_mouse_randomly(driver)
                human_type(username_elem, email_local)
                Humanizer.random_delay(2.0, 4.0)  # Tăng delay sau khi điền (đọc lại input)
                
                # Validation: Kiểm tra xem đã điền thành công chưa
                try:
                    current_value = username_elem.get_attribute("value")
                    if current_value and email_local in current_value:
                        logger.info(f"✅ Đã điền Username thành công: {current_value}")
                    else:
                        logger.warning(f"⚠️ Username có thể chưa được điền đúng: expected={email_local}, actual={current_value}")
                except:
                    logger.info("✅ Đã điền Username")
            except Exception as e:
                logger.error(f"❌ Lỗi khi điền Username: {e}")
                _take_screenshot(driver, screenshots_dir, account_id, db, "username_fill_error")
            
            # Click Next - Sử dụng helper function
            next_button = find_next_button(driver, timeout=10)
            if next_button:
                # Detect CAPTCHA/QR trước khi click
                captcha_detected = detect_captcha_or_qr(driver)
                if captcha_detected:
                    logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
                    _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
                    db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
                    return {"success": False, "error": captcha_detected}
                
                human_move_mouse_randomly(driver)
                Humanizer.random_delay(1.0, 2.5)  # Tăng delay trước khi click (đọc button)
                Humanizer.safe_click(driver, next_button)
                Humanizer.random_delay(4, 8)  # Tăng delay sau click (đợi page load)
                logger.info("✅ Đã click Next sau Username")
                
                # Kiểm tra QR code ngay sau khi click Next (trước khi điền password)
                captcha_detected = detect_captcha_or_qr(driver)
                if captcha_detected:
                    logger.error(f"❌ {captcha_detected} - DỪNG NGAY (sau khi click Next từ Username)")
                    _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected_after_username")
                    db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
                    return {"success": False, "error": captcha_detected}
        
        # Password
        password_elem = None
        for attempt in range(3):
            try:
                password_elem = Humanizer.wait_for_element(
                    driver, By.NAME, "Passwd", timeout=10, raise_exception=False
                )
                if password_elem:
                    break
            except:
                if attempt < 2:
                    Humanizer.random_delay(1, 2)
                    continue
        
        if not password_elem:
            _take_screenshot(driver, screenshots_dir, account_id, db, "password_form_not_found")
            db.update_status(account_id, "failed", last_error="Không tìm thấy form Password sau 3 lần retry")
            return {"success": False, "error": "Không tìm thấy form Password"}
        
        password = account_doc.get("password", "")
        # Di chuyển chuột đến password field trước khi gõ
        human_move_mouse_randomly(driver, target_element=password_elem)
        Humanizer.random_delay(0.5, 1.0)  # Pause trước khi bắt đầu gõ password
        
        # Nhập password KHÔNG có backspace/correction để đảm bảo chính xác
        human_type(password_elem, password, is_password=True)
        Humanizer.random_delay(1.5, 3.0)  # Delay sau khi điền password (ngắn hơn vì password thường nhập nhanh)
        logger.info("✅ Đã điền Password")
        
        # Confirm Password
        confirm_password_elem = Humanizer.wait_for_element(
            driver, By.NAME, "PasswdAgain", timeout=10, raise_exception=False
        )
        if confirm_password_elem:
            # Di chuyển chuột đến confirm password field
            human_move_mouse_randomly(driver, target_element=confirm_password_elem)
            Humanizer.random_delay(0.5, 1.0)  # Pause trước khi bắt đầu gõ
            
            # Nhập lại password CHÍNH XÁC, KHÔNG có backspace/correction
            human_type(confirm_password_elem, password, is_password=True)
            Humanizer.random_delay(1.5, 3.0)  # Delay sau khi điền confirm password
            logger.info("✅ Đã điền Confirm Password")
        
        # Click Next (final submit nếu không phải test mode) - Sử dụng helper function
        next_button = find_next_button(driver, timeout=10)
        if not next_button:
            _take_screenshot(driver, screenshots_dir, account_id, db, "next_button_not_found")
            db.update_status(account_id, "failed", last_error="Không tìm thấy nút Next sau password")
            return {"success": False, "error": "Không tìm thấy nút Next sau password"}
        
        # Detect CAPTCHA/QR trước khi submit cuối cùng
        captcha_detected = detect_captcha_or_qr(driver)
        if captcha_detected:
            logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
            _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
            db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
            return {"success": False, "error": captcha_detected}
        
        if not do_not_submit:
            human_move_mouse_randomly(driver)
            Humanizer.random_delay(0.5, 1.0)  # Đợi một chút trước khi click
            Humanizer.safe_click(driver, next_button)
            Humanizer.random_delay(3, 6)
            logger.info("✅ Đã click Next (submit form)")
        else:
            logger.info("ℹ️ Test mode: Không click final submit")
        
        # ============================================================
        # Bước 5: Xử lý OTP (nếu yêu cầu)
        # ============================================================
        logger.info("📱 Kiểm tra yêu cầu OTP...")
        
        phone_input = Humanizer.wait_for_element(
            driver, By.ID, "phoneNumberId", timeout=5, raise_exception=False
        )
        
        if phone_input:
            logger.info("📱 Phát hiện yêu cầu OTP")
            
            # Rent phone
            phone_order = otp_manager.rent_phone("VN")
            if not phone_order:
                logger.error("❌ Không thể rent phone")
                _take_screenshot(driver, screenshots_dir, account_id, db, "otp_rent_failed")
                db.update_status(account_id, "failed-phone", last_error="Không thể rent phone")
                return {"success": False, "phone_order": None, "error": "Không thể rent phone"}
            
            phone_number = phone_order.get("phone_number")
            logger.info(f"✅ Đã rent phone: {phone_number}")
            
            # Nhập phone number
            human_move_mouse_randomly(driver)
            human_type(phone_input, phone_number)
            Humanizer.random_delay(2.0, 4.0)  # Tăng delay sau khi điền số điện thoại
            
            # Click Next - Sử dụng helper function
            next_button = find_next_button(driver, timeout=10)
            if next_button:
                human_move_mouse_randomly(driver)
                Humanizer.random_delay(1.0, 2.5)  # Tăng delay trước khi click (đọc button)
                Humanizer.safe_click(driver, next_button)
                Humanizer.random_delay(4, 8)  # Tăng delay sau click (đợi page load)
            
            # Đợi input OTP code
            code_input = Humanizer.wait_for_element(
                driver, By.ID, "code", timeout=30, raise_exception=False
            )
            if not code_input:
                logger.error("❌ Không tìm thấy input OTP code")
                _take_screenshot(driver, screenshots_dir, account_id, db, "otp_input_not_found")
                db.update_status(account_id, "failed-phone", last_error="Không tìm thấy input OTP")
                return {"success": False, "phone_order": phone_order, "error": "Không tìm thấy input OTP"}
            
            # Poll OTP code với retry 3 lần (delay random 2-6s giữa mỗi poll)
            otp_code = None
            max_polls = 3
            for poll_attempt in range(max_polls):
                logger.info(f"🔄 Poll OTP attempt {poll_attempt + 1}/{max_polls}...")
                otp_code = otp_manager.get_code(phone_order.get("order_id"), max_attempts=1)
                
                if otp_code:
                    logger.info(f"✅ Đã nhận OTP code: {otp_code}")
                    break
                
                if poll_attempt < max_polls - 1:
                    delay = random.uniform(2, 6)
                    logger.info(f"⏳ Chưa nhận OTP, đợi {delay:.1f}s trước khi poll tiếp...")
                    time.sleep(delay)
            
            if not otp_code:
                logger.error("❌ Không nhận được OTP code sau 3 lần poll")
                _take_screenshot(driver, screenshots_dir, account_id, db, "otp_timeout")
                db.update_status(account_id, "failed-phone", last_error="Không nhận được OTP code sau 3 lần poll")
                return {"success": False, "phone_order": phone_order, "error": "Không nhận được OTP code"}
            
            # Nhập OTP code
            human_move_mouse_randomly(driver)
            human_type(code_input, otp_code)
            Humanizer.random_delay(2.0, 4.0)  # Tăng delay sau khi điền OTP
            
            # Click Next/Verify - Thử nhiều selectors
            verify_button = None
            verify_selectors = [
                # Ưu tiên Next button
                (By.CSS_SELECTOR, "button[jsname='LgbsSe']"),
                (By.XPATH, "//button[@jsname='LgbsSe']"),
                (By.XPATH, "//button[.//span[contains(text(), 'Next') or contains(text(), 'Tiếp theo') or contains(text(), 'Verify') or contains(text(), 'Xác minh')]]"),
                # Verify button
                (By.XPATH, "//button[.//span[contains(text(), 'Verify')]]"),
                (By.XPATH, "//button[.//span[contains(text(), 'Xác minh')]]"),
                (By.XPATH, "//button[contains(text(), 'Verify')]"),
                (By.XPATH, "//button[contains(text(), 'Xác minh')]"),
            ]
            
            for selector_type, selector_value in verify_selectors:
                try:
                    verify_button = Humanizer.wait_for_clickable(
                        driver, selector_type, selector_value, timeout=3, raise_exception=False
                    )
                    if verify_button:
                        logger.debug(f"✅ Tìm thấy nút Verify với selector: {selector_type}={selector_value}")
                        break
                except:
                    continue
            
            # Fallback: Thử Next button nếu không tìm thấy Verify
            if not verify_button:
                verify_button = find_next_button(driver, timeout=5)
            if verify_button:
                # Detect CAPTCHA/QR trước khi verify
                captcha_detected = detect_captcha_or_qr(driver)
                if captcha_detected:
                    logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
                    _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
                    db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
                    return {"success": False, "phone_order": phone_order, "error": captcha_detected}
                
                human_move_mouse_randomly(driver)
                Humanizer.random_delay(0.5, 1.0)  # Đợi một chút trước khi click
                Humanizer.safe_click(driver, verify_button)
                Humanizer.random_delay(3, 6)
            
            logger.info("✅ Đã xử lý OTP thành công")
        else:
            logger.info("ℹ️ Không yêu cầu OTP")
        
        # ============================================================
        # Bước 6: Xử lý Recovery Email (nếu yêu cầu)
        # ============================================================
        logger.info("📧 Kiểm tra yêu cầu Recovery Email...")
        
        recovery_input = Humanizer.wait_for_element(
            driver, By.ID, "recoveryEmailId", timeout=5, raise_exception=False
        )
        
        if recovery_input:
            logger.info("📧 Phát hiện yêu cầu Recovery Email")
            db.update_status(account_id, "waiting-recovery")
            logger.info("⏳ Đã set status=waiting-recovery, đợi recovery email từ operator...")
            
            # Đợi status chuyển thành "recovery-received" (từ telegram_listener)
            start_time = time.time()
            max_wait = 300  # 5 phút
            check_interval = 2  # Kiểm tra mỗi 2 giây
            
            while time.time() - start_time < max_wait:
                updated_account = db.accounts.find_one({"_id": account_id})
                
                if updated_account and updated_account.get("status") == "recovery-received":
                    recovery_email = updated_account.get("recovery_email")
                    if recovery_email:
                        logger.info(f"✅ Đã nhận recovery email: {recovery_email}")
                        
                        # Nhập recovery email
                        human_move_mouse_randomly(driver)
                        human_type(recovery_input, recovery_email)
                        Humanizer.random_delay(2.0, 4.0)  # Tăng delay sau khi điền recovery email
                        
                        # Click Next - Sử dụng helper function
                        next_button = find_next_button(driver, timeout=10)
                        if next_button:
                            # Detect CAPTCHA/QR trước khi click
                            captcha_detected = detect_captcha_or_qr(driver)
                            if captcha_detected:
                                logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
                                _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
                                db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
                                return {"success": False, "phone_order": phone_order, "error": captcha_detected}
                            
                            human_move_mouse_randomly(driver)
                            Humanizer.random_delay(0.5, 1.0)  # Đợi một chút trước khi click
                            Humanizer.safe_click(driver, next_button)
                            Humanizer.random_delay(3, 6)
                        
                        logger.info("✅ Đã nhập recovery email thành công")
                        break
                
                # Kiểm tra có lỗi không
                if updated_account and updated_account.get("status") == "waiting-observe":
                    logger.warning("⚠️ Account đã được set waiting-observe, dừng đợi recovery")
                    return {"success": False, "phone_order": phone_order, "error": "Account được set waiting-observe"}
                
                time.sleep(check_interval)
            
            if time.time() - start_time >= max_wait:
                logger.error(f"❌ Timeout đợi recovery email sau {max_wait}s")
                _take_screenshot(driver, screenshots_dir, account_id, db, "recovery_timeout")
                db.update_status(account_id, "failed", last_error="Timeout đợi recovery email")
                return {"success": False, "phone_order": phone_order, "error": "Timeout đợi recovery email"}
        else:
            logger.info("ℹ️ Không yêu cầu Recovery Email")
        
        # ============================================================
        # Bước 7: Detect CAPTCHA/QR trước khi hoàn tất
        # ============================================================
        captcha_detected = detect_captcha_or_qr(driver)
        if captcha_detected:
            logger.error(f"❌ {captcha_detected} - DỪNG NGAY")
            _take_screenshot(driver, screenshots_dir, account_id, db, "captcha_detected")
            db.update_status(account_id, "failed-captcha", last_error=captcha_detected)
            return {"success": False, "phone_order": phone_order, "error": captcha_detected}
        
        # ============================================================
        # Bước 8: Post-signup (logout, click Complete)
        # ============================================================
        logger.info("🚪 Bắt đầu xử lý post-signup...")
        
        # Đợi một chút để bot có thời gian gửi message (nếu có)
        Humanizer.random_delay(3, 5)
        
        # Logout Gmail
        logger.info("🚪 Đang logout Gmail...")
        try:
            driver.get("https://accounts.google.com/Logout")
            Humanizer.random_delay(2, 4)
        except:
            logger.warning("⚠️ Không thể logout, tiếp tục...")
        
        # Update DB: status="waiting-complete"
        db.update_status(account_id, "waiting-complete")
        logger.info("✅ Đã set status=waiting-complete")
        
        # Tự động nhấn nút Complete trên Telegram
        success = _click_complete_button(
            telegram_client,
            account_doc,
            db,
            account_id,
            screenshots_dir
        )
        
        if success:
            db.update_status(account_id, "created")
            logger.info("✅ Account đã được tạo thành công (status=created)")
            return {"success": True, "phone_order": phone_order}
        else:
            logger.error("❌ Không thể click Complete button")
            return {"success": False, "phone_order": phone_order, "error": "Không thể click Complete button"}
        
    except RuntimeError as e:
        # RuntimeError thường là lỗi proxy hoặc lỗi nghiêm trọng
        error_msg = str(e)
        logger.error(f"❌ {error_msg} - FAIL-FAST", exc_info=True)
        
        # Kiểm tra nếu là lỗi proxy → set status failed-proxy
        if "proxy" in error_msg.lower() or "failed-proxy" in error_msg.lower():
            _take_screenshot(driver, screenshots_dir, account_id, db, "proxy_error")
            db.update_status(account_id, "failed-proxy", last_error=error_msg)
            return {"success": False, "phone_order": phone_order, "error": error_msg}
        else:
            _take_screenshot(driver, screenshots_dir, account_id, db, "error")
            db.update_status(account_id, "error", last_error=error_msg)
            return {"success": False, "phone_order": phone_order, "error": error_msg}
        
    except Exception as e:
        # Bất kỳ exception nào → error status
        error_msg = f"Exception không mong đợi: {str(e)}"
        logger.error(f"❌ {error_msg} - FAIL-FAST", exc_info=True)
        _take_screenshot(driver, screenshots_dir, account_id, db, "error")
        db.update_status(account_id, "error", last_error=error_msg)
        return {"success": False, "phone_order": phone_order, "error": error_msg}


def create_gmail_account(
    account: Dict[str, Any],
    db_manager: DatabaseManager,
    gpm_manager: GPMManager,
    proxy_manager: ProxyManager,
    otp_manager: OTPManager,
    telegram_client: TelegramClient,
    screenshots_dir: Path,
    shared_proxy: Optional[Dict[str, Any]] = None,
    win_pos: Optional[str] = None,
    win_size: Optional[str] = None
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
        if shared_proxy:
            # BATCH MODE: Dùng proxy dùng chung
            logger.info(f"🔗 BATCH MODE: Đang dùng shared proxy...")
            proxy = shared_proxy
            logger.info(f"   📦 Proxy đã được cung cấp từ batch orchestrator")
        else:
            # SINGLE MODE: Lấy proxy riêng
            logger.info(f"🔗 Đang lấy proxy...")
            try:
                # Lấy proxy từ ProxyManager (không cần profile_id vì sẽ tạo profile mới)
                proxy = proxy_manager.get_default_rented_proxy()
                if not proxy:
                    error_msg = "Không thể lấy proxy"
                    logger.error(f"❌ {error_msg} - FAIL-FAST")
                    db_manager.update_status(account_id, "failed", last_error=error_msg)
                    return False
            except RuntimeError as proxy_error:
                error_msg = f"Không thể lấy proxy: {str(proxy_error)}"
                logger.error(f"❌ {error_msg} - FAIL-FAST")
                db_manager.update_status(account_id, "failed", last_error=error_msg)
                return False
        
        # Log để confirm proxy dict có gì
        logger.debug(f"   📦 Proxy dict keys: {list(proxy.keys())}")
        if proxy.get("socks5_raw"):
            logger.debug(f"   ✅ socks5_raw đã được lưu: {proxy.get('socks5_raw')[:50]}...")
        if proxy.get("http_raw"):
            logger.debug(f"   ✅ http_raw đã được lưu: {proxy.get('http_raw')[:50]}...")
        logger.info(f"   🔗 Proxy type: {proxy.get('proxy_type', 'unknown')}")
        
        # Validate proxy (FAIL-FAST nếu lỗi) - chỉ validate nếu không phải shared_proxy (đã validate rồi)
        if not shared_proxy:
            try:
                proxy_manager.validate_proxy_requests(
                    proxy=proxy,
                    skip_validation=False
                )
                logger.info(f"✅ Đã lấy và validate proxy thành công: {proxy['host']}:{proxy.get('port', 'N/A')}")
            except RuntimeError as proxy_error:
                error_msg = f"Không thể validate proxy: {str(proxy_error)}"
                logger.error(f"❌ {error_msg} - FAIL-FAST")
                db_manager.update_status(account_id, "failed", last_error=error_msg)
                return False
        else:
            logger.info(f"✅ Đang dùng shared proxy (đã được validate): {proxy['host']}:{proxy.get('port', 'N/A')}")
        
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
        if win_pos and win_size:
            logger.info(f"   📐 Window position: {win_pos}, size: {win_size}")
        profile_result = gpm_manager.start_profile(
            profile_id,
            win_pos=win_pos,
            win_size=win_size
        )
        
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
        
        # Đợi một chút để browser trong profile sẵn sàng (tránh navigate quá nhanh)
        logger.info("⏳ Đang đợi browser trong profile sẵn sàng (3-5s)...")
        Humanizer.random_delay(3, 5)
        
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
        # 4.5. Đợi browser sẵn sàng và kiểm tra driver hoạt động
        # ============================================================
        logger.info("⏳ Đang đợi browser sẵn sàng và kiểm tra driver...")
        
        # Đợi browser sẵn sàng - retry nhiều lần cho đến khi current_url không còn "about:blank"
        max_retries = 10
        browser_ready = False
        
        for retry_count in range(max_retries):
            try:
                # Thử truy cập current_url để kiểm tra driver hoạt động
                current_url = driver.current_url
                logger.debug(f"   Retry {retry_count + 1}/{max_retries}: current_url = {current_url}")
                
                # Nếu không còn "about:blank" → browser đã sẵn sàng
                if current_url and current_url.strip() != "" and current_url != "about:blank":
                    logger.info(f"✅ Browser đã sẵn sàng, current_url: {current_url}")
                    browser_ready = True
                    break
                
                # Thử một thao tác nhỏ để "đánh thức" browser
                try:
                    driver.execute_script("return document.readyState")
                except Exception as script_error:
                    logger.debug(f"   Browser chưa sẵn sàng: {script_error}")
                
                # Đợi một chút trước khi retry
                Humanizer.random_delay(1, 2)
                
            except Exception as check_error:
                logger.debug(f"   Lỗi khi kiểm tra browser (retry {retry_count + 1}/{max_retries}): {check_error}")
                Humanizer.random_delay(1, 2)
                continue
        
        if not browser_ready:
            logger.warning("⚠️ Browser vẫn chưa sẵn sàng sau nhiều lần retry, tiếp tục với navigate...")
            # Không fail ngay, thử navigate xem sao
        
        # ============================================================
        # 4.6. Switch về main window và chuyển hướng về trang Gmail homepage
        # ============================================================
        logger.info("📧 Đang chuyển hướng về trang Gmail homepage...")
        
        # QUAN TRỌNG: Switch về main window (không phải extension window)
        try:
            logger.info("🔍 Đang kiểm tra và switch về main window...")
            all_windows = driver.window_handles
            logger.debug(f"   Tổng số windows: {len(all_windows)}")
            
            # Tìm main window (không phải chrome-extension)
            main_window = None
            current_window = driver.current_window_handle
            
            for window_handle in all_windows:
                try:
                    driver.switch_to.window(window_handle)
                    current_url = driver.current_url
                    logger.debug(f"   Window handle: {window_handle}, URL: {current_url}")
                    
                    # Nếu không phải extension URL → đây là main window
                    if not current_url.startswith("chrome-extension://"):
                        main_window = window_handle
                        logger.info(f"✅ Tìm thấy main window: {current_url}")
                        break
                    elif "chrome-extension://" in current_url:
                        logger.debug(f"   Bỏ qua extension window: {current_url}")
                except Exception as switch_error:
                    logger.debug(f"   Không thể switch đến window {window_handle}: {switch_error}")
                    continue
            
            # Nếu không tìm thấy main window, tạo window mới hoặc dùng window đầu tiên
            if not main_window:
                logger.warning("⚠️ Không tìm thấy main window, tạo window mới...")
                try:
                    # Tạo window mới
                    driver.execute_script("window.open('about:blank', '_blank');")
                    all_windows = driver.window_handles
                    if all_windows:
                        main_window = all_windows[-1]  # Lấy window mới nhất
                        driver.switch_to.window(main_window)
                        logger.info("✅ Đã tạo và switch sang window mới")
                except Exception as new_window_error:
                    logger.warning(f"⚠️ Không thể tạo window mới: {new_window_error}, dùng window đầu tiên")
                    if all_windows:
                        main_window = all_windows[0]
                        driver.switch_to.window(main_window)
            else:
                # Switch về main window
                driver.switch_to.window(main_window)
                logger.info("✅ Đã switch về main window")
            
            # Đợi một chút để window sẵn sàng
            Humanizer.random_delay(1, 2)
            
            # Kiểm tra current_url sau khi switch
            current_url_before = driver.current_url
            logger.info(f"   Current URL sau khi switch: {current_url_before}")
            
            # Nếu vẫn là extension URL, thử cách khác
            if current_url_before and current_url_before.startswith("chrome-extension://"):
                logger.warning("⚠️ Vẫn ở extension window, thử cách khác...")
                # Thử navigate đến about:blank trước
                try:
                    driver.get("about:blank")
                    Humanizer.random_delay(1, 2)
                    logger.info("✅ Đã navigate đến about:blank")
                except:
                    pass
            
            # Nếu đã ở trang signup, bỏ qua navigate
            if current_url_before and ("signup" in current_url_before.lower() or "webcreateaccount" in current_url_before.lower() or "createaccount" in current_url_before.lower()):
                logger.info("✅ Đã ở trang signup, bỏ qua navigate")
                # Vẫn validate để đảm bảo page load xong
                try:
                    WebDriverWait(driver, 10).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    Humanizer.random_delay(2, 3)
                    logger.info("✅ Trang signup đã load xong")
                except:
                    pass
            else:
                # Navigate trực tiếp đến trang signup (không cần qua Gmail homepage)
                signup_urls = [
                    "https://accounts.google.com/signup/v2/webcreateaccount?hl=vi&flowName=GlifWebSignIn&flowEntry=SignUp",
                    "https://accounts.google.com/signup/v2/webcreateaccount?flowName=GlifWebSignIn&flowEntry=SignUp",
                    "https://accounts.google.com/signup"
                ]
                
                navigate_success = False
                last_error = None
                
                for attempt in range(5):  # Tăng retry lên 5 lần
                    for signup_url in signup_urls:
                        try:
                            logger.info(f"   Attempt {attempt + 1}/5: Đang navigate đến {signup_url}...")
                            
                            # Thử navigate với timeout dài hơn
                            driver.set_page_load_timeout(30)  # 30s timeout cho page load
                            driver.get(signup_url)
                            
                            # Đợi page load HOÀN TOÀN với timeout dài hơn
                            logger.info("   ⏳ Đang đợi page load xong...")
                            try:
                                WebDriverWait(driver, 25).until(
                                    lambda d: d.execute_script("return document.readyState") == "complete"
                                )
                            except TimeoutException:
                                logger.warning("   ⚠️ Timeout khi đợi readyState, tiếp tục validate...")
                            
                            Humanizer.random_delay(4, 5)  # Đợi thêm để đảm bảo elements render
                            
                            # Kiểm tra lỗi proxy NGAY sau khi navigate
                            proxy_error = _detect_proxy_errors(driver)
                            if proxy_error:
                                logger.error(f"❌ {proxy_error} - DỪNG NGAY và KILL PROFILE")
                                _take_screenshot(driver, screenshots_dir, account_id, db_manager, "proxy_error")
                                db_manager.update_status(account_id, "failed-proxy", last_error=proxy_error)
                                raise RuntimeError(f"Proxy error detected: {proxy_error}")
                            
                            # Validate page đã load thành công: kiểm tra URL, title, và elements
                            current_url = driver.current_url.lower()
                            page_title = driver.title.lower()
                            
                            logger.debug(f"   Current URL: {current_url}")
                            logger.debug(f"   Page title: {page_title}")
                            
                            # Kiểm tra URL có chứa signup không
                            url_valid = ("signup" in current_url or "webcreateaccount" in current_url or "createaccount" in current_url)
                            
                            # Kiểm tra title có chứa signup/create account không
                            title_valid = ("signup" in page_title.lower() or "create account" in page_title.lower() or "tạo tài khoản" in page_title.lower())
                            
                            # Kiểm tra xem có error indicator không (chrome error page)
                            try:
                                page_source_lower = driver.page_source.lower()
                                has_error = any(keyword in page_source_lower for keyword in [
                                    "this site can't be reached",
                                    "không thể truy cập trang web này",
                                    "err_",
                                    "chrome-error://",
                                    "dns_probe_finished",
                                    "network_error",
                                    "this page isn't working",
                                    "trang này không hoạt động"
                                ])
                            except:
                                has_error = False
                            
                            # Kiểm tra xem có elements signup form không (firstName field hoặc signup form)
                            has_signup_elements = False
                            try:
                                # Thử tìm signup form elements
                                signup_selectors = [
                                    "//input[@id='firstName']",
                                    "//input[@name='firstName']",
                                    "//input[@id='lastName']",
                                    "//form[contains(@action, 'signup')]",
                                    "//form[contains(@action, 'createaccount')]",
                                    "//*[contains(@class, 'signup')]",
                                    "//*[contains(@id, 'signup')]"
                                ]
                                for selector in signup_selectors:
                                    try:
                                        elem = driver.find_element(By.XPATH, selector)
                                        if elem and elem.is_displayed():
                                            has_signup_elements = True
                                            logger.debug(f"   ✅ Tìm thấy signup element: {selector}")
                                            break
                                    except:
                                        continue
                            except:
                                pass
                            
                            if has_error:
                                logger.warning(f"   ⚠️ Phát hiện error indicator trên page, thử URL khác...")
                                last_error = "Page có error indicator"
                                continue
                            
                            if url_valid and (title_valid or has_signup_elements):
                                logger.info(f"✅ Đã navigate thành công đến trang signup: {signup_url}")
                                logger.info(f"   Current URL: {current_url}")
                                logger.info(f"   Page title: {page_title}")
                                logger.info(f"   Has signup elements: {has_signup_elements}")
                                navigate_success = True
                                break
                            else:
                                logger.warning(f"   ⚠️ Page không hợp lệ: URL={url_valid}, Title={title_valid}, Elements={has_signup_elements}")
                                logger.warning(f"   Current URL: {current_url}")
                                logger.warning(f"   Page title: {page_title}")
                                last_error = f"Page không hợp lệ sau khi navigate"
                                continue
                                
                        except RuntimeError:
                            # Proxy error - đã được xử lý ở trên
                            raise
                        except TimeoutException as timeout_error:
                            logger.warning(f"   ⚠️ Timeout khi navigate đến {signup_url}: {timeout_error}")
                            last_error = f"Timeout: {str(timeout_error)}"
                            continue
                        except Exception as nav_error:
                            logger.warning(f"   ⚠️ Lỗi navigate đến {signup_url}: {nav_error}")
                            last_error = str(nav_error)
                            continue
                    
                    if navigate_success:
                        break
                    
                    # Nếu chưa thành công, đợi một chút rồi retry
                    if attempt < 4:
                        wait_time = (attempt + 1) * 2  # 2s, 4s, 6s, 8s
                        logger.warning(f"   ⚠️ Navigate thất bại (attempt {attempt + 1}/5), đợi {wait_time}s rồi retry...")
                        Humanizer.random_delay(wait_time, wait_time + 1)
                
                if not navigate_success:
                    logger.error(f"❌ Không thể navigate đến trang signup sau 5 attempts: {last_error}")
                    _take_screenshot(driver, screenshots_dir, account_id, db_manager, "signup_navigate_failed")
                    db_manager.update_status(account_id, "failed", last_error=f"Không thể navigate đến trang signup sau 5 attempts: {last_error}")
                    return False
                
                logger.info("✅ Đã chuyển hướng đến trang signup thành công và validated")
        except RuntimeError:
            # Proxy error - đã được xử lý ở trên
            raise
        except Exception as nav_error:
            logger.error(f"❌ Lỗi trong quá trình navigate: {nav_error}", exc_info=True)
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "gmail_navigate_error")
            db_manager.update_status(account_id, "failed", last_error=f"Lỗi navigate: {str(nav_error)}")
            return False
        
        # ============================================================
        # 5. Signup flow từ Gmail homepage (Tạo tài khoản → For myself)
        # ============================================================
        signup_result = signup_via_gmail_homepage(
            driver=driver,
            account_doc=account,
            db=db_manager,
            logger=logger,
            otp_manager=otp_manager,
            telegram_client=telegram_client,
            screenshots_dir=screenshots_dir
        )
        
        # signup_via_gmail_homepage trả về dict với phone_order nếu có
        if isinstance(signup_result, dict):
            phone_order = signup_result.get("phone_order")
            success = signup_result.get("success", False)
            return success
        else:
            # Trả về False nếu signup thất bại
            return False
        
    except RuntimeError as e:
        # RuntimeError thường là lỗi proxy hoặc lỗi nghiêm trọng
        error_msg = str(e)
        logger.error(f"❌ {error_msg} - FAIL-FAST", exc_info=True)
        
        # Kiểm tra nếu là lỗi proxy → set status failed-proxy
        if "proxy" in error_msg.lower() or "failed-proxy" in error_msg.lower():
            _take_screenshot(driver, screenshots_dir, account_id, db_manager, "proxy_error")
            # Status đã được set trong signup_via_gmail_homepage nếu là proxy error
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
        
        # LƯU Ý: Khi attach vào browser đã chạy (remote debugging), 
        # KHÔNG THỂ set các Chrome options như excludeSwitches, useAutomationExtension
        # Vì browser đã được khởi động rồi. Chỉ có thể dùng CDP commands để ẩn automation.
        
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
        
        # ============================================================
        # ẨN AUTOMATION DETECTION - QUAN TRỌNG ĐỂ TRÁNH BỊ PHÁT HIỆN
        # ============================================================
        try:
            # Inject script tổng hợp để ẩn tất cả dấu hiệu automation
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    // 1. Ẩn navigator.webdriver (dấu hiệu rõ ràng nhất của automation)
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => false,
                    });
                    
                    // 2. Thêm window.chrome để giống browser thật
                    window.chrome = {
                        runtime: {},
                    };
                    
                    // 3. Thêm navigator.chrome để giống browser thật
                    Object.defineProperty(navigator, 'chrome', {
                        get: () => ({
                            runtime: {},
                        }),
                    });
                    
                    // 4. Thêm plugins để giống browser thật (nếu chưa có)
                    if (!navigator.plugins || navigator.plugins.length === 0) {
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => [1, 2, 3, 4, 5],
                        });
                    }
                    
                    // 5. Đảm bảo languages có giá trị hợp lý
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['vi-VN', 'vi', 'en-US', 'en'],
                    });
                    
                    // 6. Ẩn automation trong permissions
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                '''
            })
            
            logger.info("✅ Đã inject scripts để ẩn automation detection")
        except Exception as cdp_error:
            logger.warning(f"⚠️ Không thể inject CDP scripts (có thể không ảnh hưởng): {cdp_error}")
            # Không fail, tiếp tục vì GPM có thể đã xử lý một phần
        
        # Kiểm tra driver.current_url sau khi attach
        # Nếu vẫn "about:blank" → retry tối đa 1 lần
        try:
            current_url = driver.current_url
            logger.debug(f"   Current URL sau khi attach: {current_url}")
            
            if current_url == "about:blank" or not current_url or current_url.strip() == "":
                logger.warning("⚠️ Driver vẫn ở trang about:blank sau khi attach, đợi và retry...")
                time.sleep(2)  # Đợi 2 giây
                
                # Retry 1 lần: kiểm tra lại current_url
                current_url = driver.current_url
                logger.debug(f"   Current URL sau retry: {current_url}")
                
                if current_url == "about:blank" or not current_url or current_url.strip() == "":
                    logger.warning("⚠️ Driver vẫn ở trang about:blank sau retry")
                    # Không return None ở đây, để caller xử lý
                    # Caller sẽ kiểm tra và quyết định có fail hay không
        except Exception as check_error:
            logger.warning(f"⚠️ Không thể kiểm tra current_url: {check_error}")
            # Tiếp tục, không fail ngay
        
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
        
        # Click Next - Sử dụng helper function
        next_button = find_next_button(driver, timeout=10)
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
            
            # Click Next - Sử dụng helper function
            next_button = find_next_button(driver, timeout=10)
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
        
        # Nhập password KHÔNG có pause dài để đảm bảo chính xác
        Humanizer.type_like_human(password_elem, account.get("password", ""), is_password=True)
        Humanizer.random_delay(1.0, 2.0)  # Delay sau khi điền password
        
        # Confirm Password
        confirm_password_elem = Humanizer.wait_for_element(
            driver, By.NAME, "PasswdAgain", timeout=10, raise_exception=False
        )
        if confirm_password_elem:
            # Nhập lại password CHÍNH XÁC, KHÔNG có pause dài
            Humanizer.type_like_human(confirm_password_elem, account.get("password", ""), is_password=True)
            Humanizer.random_delay(1.0, 2.0)  # Delay sau khi điền confirm password
        
        # Click Next - Sử dụng helper function
        next_button = find_next_button(driver, timeout=10)
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
        
        # Click Next - Sử dụng helper function
        next_button = find_next_button(driver, timeout=10)
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
        
        # Click Next/Verify - Thử nhiều selectors
        verify_button = None
        verify_selectors = [
            # Ưu tiên Next button
            (By.CSS_SELECTOR, "button[jsname='LgbsSe']"),
            (By.XPATH, "//button[@jsname='LgbsSe']"),
            (By.XPATH, "//button[.//span[contains(text(), 'Next') or contains(text(), 'Tiếp theo') or contains(text(), 'Verify') or contains(text(), 'Xác minh')]]"),
            # Verify button
            (By.XPATH, "//button[.//span[contains(text(), 'Verify')]]"),
            (By.XPATH, "//button[.//span[contains(text(), 'Xác minh')]]"),
            (By.XPATH, "//button[contains(text(), 'Verify')]"),
            (By.XPATH, "//button[contains(text(), 'Xác minh')]"),
        ]
        
        for selector_type, selector_value in verify_selectors:
            try:
                verify_button = Humanizer.wait_for_clickable(
                    driver, selector_type, selector_value, timeout=3, raise_exception=False
                )
                if verify_button:
                    logger.debug(f"✅ Tìm thấy nút Verify với selector: {selector_type}={selector_value}")
                    break
            except:
                continue
        
        # Fallback: Thử Next button nếu không tìm thấy Verify
        if not verify_button:
            verify_button = find_next_button(driver, timeout=5)
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
                    
                    # Click Next - Sử dụng helper function
                    next_button = find_next_button(driver, timeout=10)
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

