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
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException

try:
    from .logger import get_logger
except ImportError:
    from utils.logger import get_logger

logger = get_logger(__name__)


class Humanizer:
    """Nhân hóa hành vi người dùng"""
    
    @staticmethod
    def type_like_human(element, text: str, min_delay: float = 0.15, max_delay: float = 0.5, is_password: bool = False):
        """
        Gõ text với delay ngẫu nhiên từng ký tự (human-like)
        Chậm hơn để giống người thật hơn
        LƯU Ý: Với password field, KHÔNG có pause dài để tránh nhập sai
        
        Args:
            element: Selenium WebElement
            text: Text cần gõ
            min_delay: Delay tối thiểu giữa các ký tự (giây) - mặc định 0.15s
            max_delay: Delay tối đa giữa các ký tự (giây) - mặc định 0.5s
            is_password: True nếu là password field (sẽ giảm pause)
        """
        try:
            element.clear()
            # Thêm delay trước khi bắt đầu gõ
            if is_password:
                time.sleep(random.uniform(0.3, 0.8))  # Delay ngắn hơn cho password
            else:
                time.sleep(random.uniform(0.5, 1.5))
            
            for char in text:
                element.send_keys(char)
                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)
                
                # Đôi khi có pause dài hơn (giống người đang suy nghĩ)
                # Với password, giảm pause để tránh nhập sai
                if is_password:
                    if random.random() < 0.03:  # Chỉ 3% khả năng pause dài với password
                        time.sleep(random.uniform(0.3, 0.6))  # Pause ngắn hơn
                else:
                    if random.random() < 0.1:  # 10% khả năng
                        time.sleep(random.uniform(0.8, 1.5))
            
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
    def random_delay(min_seconds: float = 1.0, max_seconds: float = 4.0):
        """
        Delay ngẫu nhiên - Tăng delay để giống người thật hơn
        
        Args:
            min_seconds: Delay tối thiểu (giây) - mặc định 1.0s
            max_seconds: Delay tối đa (giây) - mặc định 4.0s
        """
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)
        logger.debug(f"⏳ Random delay: {delay:.2f}s")
    
    @staticmethod
    def safe_click(driver, element, retry: int = 3):
        """
        Click element với retry - Cải thiện: Thêm mouse movement trước khi click, pause "đọc" lâu hơn
        
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
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                Humanizer.random_delay(0.8, 1.5)  # Tăng delay sau scroll
                
                # Di chuyển chuột đến element trước khi click (giống người thật)
                try:
                    actions = ActionChains(driver)
                    # Lấy vị trí element
                    element_location = element.location
                    element_size = element.size
                    target_x = element_location['x'] + element_size['width'] // 2
                    target_y = element_location['y'] + element_size['height'] // 2
                    
                    # Di chuyển với đường cong tự nhiên
                    num_steps = random.randint(2, 4)
                    current_x = 0
                    current_y = 0
                    
                    for step in range(num_steps):
                        progress = (step + 1) / num_steps
                        offset_x = random.randint(-30, 30)
                        offset_y = random.randint(-30, 30)
                        
                        intermediate_x = int(current_x + (target_x - current_x) * progress + offset_x)
                        intermediate_y = int(current_y + (target_y - current_y) * progress + offset_y)
                        
                        actions.move_by_offset(intermediate_x - current_x, intermediate_y - current_y)
                        time.sleep(random.uniform(0.05, 0.15))
                        
                        current_x = intermediate_x
                        current_y = intermediate_y
                    
                    actions.perform()
                    Humanizer.random_delay(0.3, 0.8)  # Đợi sau khi di chuyển chuột
                except:
                    pass  # Fallback nếu không di chuyển được chuột
                
                # Pause "đọc" trước khi click (giống người đang đọc button/link)
                Humanizer.random_delay(1.0, 2.5)  # Tăng pause lâu hơn
                
                # Đôi khi hover một chút trước khi click (giống người thật)
                if random.random() < 0.3:  # 30% khả năng hover
                    try:
                        ActionChains(driver).move_to_element(element).pause(random.uniform(0.2, 0.5)).perform()
                    except:
                        pass
                
                # Click
                element.click()
                logger.debug(f"✅ Click thành công (attempt {attempt + 1})")
                return True
            except Exception as e:
                logger.warning(f"⚠️ Lỗi click attempt {attempt + 1}/{retry}: {e}")
                if attempt < retry - 1:
                    Humanizer.random_delay(1.5, 3.0)  # Tăng delay giữa các retry
                else:
                    logger.error(f"❌ Không thể click sau {retry} attempts")
                    return False
        return False

