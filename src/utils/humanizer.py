"""
Humanizer - Nhân hóa hành vi người dùng
Typing delay ngẫu nhiên, DOM wait, mouse movement
"""
import random
import time
from typing import Optional
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

from .logger import get_logger

logger = get_logger(__name__)


class Humanizer:
    """Nhân hóa hành vi người dùng"""
    
    @staticmethod
    def type_like_human(element, text: str, min_delay: float = 0.05, max_delay: float = 0.3):
        """
        Gõ text với delay ngẫu nhiên từng ký tự (human-like)
        
        Args:
            element: Selenium WebElement
            text: Text cần gõ
            min_delay: Delay tối thiểu giữa các ký tự (giây)
            max_delay: Delay tối đa giữa các ký tự (giây)
        """
        try:
            element.clear()
            for char in text:
                element.send_keys(char)
                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)
            
            logger.debug(f"✅ Đã gõ text với human-like delay: {len(text)} ký tự")
        except Exception as e:
            logger.error(f"❌ Lỗi type_like_human: {e}", exc_info=True)
            raise
    
    @staticmethod
    def wait_for_element(
        driver,
        by: By,
        value: str,
        timeout: int = 10,
        raise_exception: bool = True
    ) -> Optional[object]:
        """
        Wait cho element xuất hiện (explicit wait - không dùng tọa độ cố định)
        
        Args:
            driver: Selenium WebDriver
            by: By strategy (By.ID, By.CSS_SELECTOR, ...)
            value: Giá trị selector
            timeout: Timeout (giây)
            raise_exception: Có raise exception nếu không tìm thấy không
            
        Returns:
            WebElement nếu tìm thấy, None nếu không tìm thấy và raise_exception=False
        """
        try:
            wait = WebDriverWait(driver, timeout)
            element = wait.until(EC.presence_of_element_located((by, value)))
            logger.debug(f"✅ Tìm thấy element: {by}={value}")
            return element
        except TimeoutException:
            logger.warning(f"⏱️ Timeout khi tìm element: {by}={value}")
            if raise_exception:
                raise
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi wait_for_element {by}={value}: {e}")
            if raise_exception:
                raise
            return None
    
    @staticmethod
    def wait_for_clickable(
        driver,
        by: By,
        value: str,
        timeout: int = 10,
        raise_exception: bool = True
    ) -> Optional[object]:
        """
        Wait cho element có thể click được
        
        Args:
            driver: Selenium WebDriver
            by: By strategy
            value: Giá trị selector
            timeout: Timeout (giây)
            raise_exception: Có raise exception không
            
        Returns:
            WebElement nếu tìm thấy, None nếu không
        """
        try:
            wait = WebDriverWait(driver, timeout)
            element = wait.until(EC.element_to_be_clickable((by, value)))
            logger.debug(f"✅ Element có thể click: {by}={value}")
            return element
        except TimeoutException:
            logger.warning(f"⏱️ Timeout khi đợi element clickable: {by}={value}")
            if raise_exception:
                raise
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi wait_for_clickable {by}={value}: {e}")
            if raise_exception:
                raise
            return None
    
    @staticmethod
    def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0):
        """
        Delay ngẫu nhiên
        
        Args:
            min_seconds: Delay tối thiểu (giây)
            max_seconds: Delay tối đa (giây)
        """
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)
        logger.debug(f"⏳ Random delay: {delay:.2f}s")
    
    @staticmethod
    def safe_click(driver, element, retry: int = 3):
        """
        Click element với retry
        
        Args:
            driver: Selenium WebDriver
            element: WebElement
            retry: Số lần retry
            
        Returns:
            True nếu thành công, False nếu thất bại
        """
        for attempt in range(retry):
            try:
                # Scroll vào view
                driver.execute_script("arguments[0].scrollIntoView(true);", element)
                Humanizer.random_delay(0.2, 0.5)
                
                # Click
                element.click()
                logger.debug(f"✅ Click thành công (attempt {attempt + 1})")
                return True
            except Exception as e:
                logger.warning(f"⚠️ Lỗi click attempt {attempt + 1}/{retry}: {e}")
                if attempt < retry - 1:
                    Humanizer.random_delay(0.5, 1.0)
                else:
                    logger.error(f"❌ Không thể click sau {retry} attempts")
                    return False
        return False

