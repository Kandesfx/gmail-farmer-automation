"""
OTP Manager - Quản lý phone rent và code polling
Retry tối đa 3 lần với delay ngẫu nhiên 2-6s
"""
import time
import random
import requests
from typing import Optional, Dict, Any
try:
    from ..utils.logger import get_logger
except ImportError:
    from utils.logger import get_logger

logger = get_logger(__name__)


class OTPManager:
    """Quản lý OTP phone rent và code polling"""
    
    def __init__(self, api_url: str, api_key: str):
        """
        Khởi tạo OTPManager
        
        Args:
            api_url: URL của OTP service API
            api_key: API key để authenticate
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"✅ Đã khởi tạo OTPManager: {api_url}")
    
    def rent_phone(self, country: str = "VN") -> Optional[Dict[str, Any]]:
        """
        Rent phone number cho OTP
        
        Args:
            country: Mã quốc gia (mặc định: VN)
            
        Returns:
            Dict chứa phone_number và order_id, hoặc None nếu lỗi
        """
        try:
            url = f"{self.api_url}/api/v1/phones/rent"
            
            payload = {
                "country": country,
                "service": "gmail"  # Service cụ thể
            }
            
            logger.info(f"📱 Đang rent phone number cho country: {country}")
            response = requests.post(url, json=payload, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                phone_number = data.get("phone_number")
                order_id = data.get("order_id")
                
                if not phone_number or not order_id:
                    logger.error("❌ API không trả về phone_number hoặc order_id")
                    return None
                
                logger.info(f"✅ Đã rent phone: {phone_number} (order_id: {order_id})")
                return {
                    "phone_number": phone_number,
                    "order_id": order_id
                }
            else:
                logger.error(f"❌ Lỗi rent phone: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout khi rent phone")
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi rent phone: {e}", exc_info=True)
            return None
    
    def get_code(
        self,
        order_id: str,
        max_attempts: int = 3,
        delay_min: int = 2,
        delay_max: int = 6,
        timeout: int = 120
    ) -> Optional[str]:
        """
        Poll OTP code với retry tối đa 3 lần
        
        Args:
            order_id: ID của order phone
            max_attempts: Số lần retry tối đa (mặc định: 3)
            delay_min: Delay tối thiểu giữa các attempts (giây, mặc định: 2)
            delay_max: Delay tối đa giữa các attempts (giây, mặc định: 6)
            timeout: Timeout tổng (giây, mặc định: 120)
            
        Returns:
            OTP code nếu nhận được, hoặc None nếu thất bại
        """
        try:
            url = f"{self.api_url}/api/v1/orders/{order_id}/code"
            
            start_time = time.time()
            attempt = 0
            
            while attempt < max_attempts:
                if time.time() - start_time > timeout:
                    logger.warning(f"⏱️ Timeout khi poll code cho order {order_id}")
                    break
                
                logger.info(f"🔄 Attempt {attempt + 1}/{max_attempts} - Đang poll code cho order {order_id}")
                
                response = requests.get(url, headers=self.headers, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    code = data.get("code")
                    status = data.get("status")
                    
                    if code:
                        logger.info(f"✅ Đã nhận OTP code: {code}")
                        return code
                    elif status == "waiting":
                        logger.debug(f"ℹ️ Chưa có code, đang đợi... (attempt {attempt + 1})")
                    else:
                        logger.warning(f"⚠️ Status không hợp lệ: {status}")
                else:
                    logger.warning(f"⚠️ Lỗi poll code: {response.status_code}")
                
                # Delay ngẫu nhiên giữa các attempts (trừ attempt cuối)
                if attempt < max_attempts - 1:
                    delay = random.uniform(delay_min, delay_max)
                    logger.debug(f"⏳ Đợi {delay:.1f}s trước attempt tiếp theo...")
                    time.sleep(delay)
                
                attempt += 1
            
            logger.error(f"❌ Không nhận được OTP code sau {max_attempts} attempts")
            return None
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout khi poll code cho order {order_id}")
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi poll code cho order {order_id}: {e}", exc_info=True)
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel order (nếu cần)
        
        Args:
            order_id: ID của order cần cancel
            
        Returns:
            True nếu thành công, False nếu lỗi
        """
        try:
            url = f"{self.api_url}/api/v1/orders/{order_id}/cancel"
            
            response = requests.post(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"✅ Đã cancel order: {order_id}")
                return True
            else:
                logger.warning(f"⚠️ Không thể cancel order {order_id}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ Lỗi cancel order: {e}")
            return False

