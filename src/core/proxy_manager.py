"""
Proxy Manager - Quản lý ZingProxy API để lấy proxy VN
"""
import requests
from typing import Optional, Dict, Any
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ProxyManager:
    """Quản lý ZingProxy API"""
    
    def __init__(self, api_url: str, api_key: str):
        """
        Khởi tạo ProxyManager
        
        Args:
            api_url: URL của ZingProxy API
            api_key: API key để authenticate
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"✅ Đã khởi tạo ProxyManager: {api_url}")
    
    def get_vn_proxy(self) -> Optional[Dict[str, str]]:
        """
        Lấy proxy VN từ ZingProxy API
        
        Returns:
            Dict chứa proxy config: {"host": "...", "port": "...", "username": "...", "password": "..."}
            hoặc None nếu lỗi
        """
        try:
            url = f"{self.api_url}/api/v1/proxies/vietnam"
            
            logger.info("🌐 Đang lấy proxy VN từ ZingProxy...")
            response = requests.get(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                proxy = {
                    "host": data.get("host"),
                    "port": str(data.get("port", "")),
                    "username": data.get("username", ""),
                    "password": data.get("password", "")
                }
                
                if not proxy["host"]:
                    logger.error("❌ API không trả về host proxy")
                    return None
                
                logger.info(f"✅ Đã lấy proxy VN: {proxy['host']}:{proxy['port']}")
                return proxy
            else:
                logger.error(f"❌ Lỗi lấy proxy VN: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout khi lấy proxy VN")
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi lấy proxy VN: {e}", exc_info=True)
            return None
    
    def release_proxy(self, proxy_id: Optional[str] = None) -> bool:
        """
        Release proxy (nếu API hỗ trợ)
        
        Args:
            proxy_id: ID của proxy cần release (nếu có)
            
        Returns:
            True nếu thành công, False nếu lỗi
        """
        try:
            if not proxy_id:
                logger.debug("ℹ️ Không có proxy_id để release")
                return True
            
            url = f"{self.api_url}/api/v1/proxies/{proxy_id}/release"
            
            response = requests.post(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"✅ Đã release proxy: {proxy_id}")
                return True
            else:
                logger.warning(f"⚠️ Không thể release proxy {proxy_id}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ Lỗi release proxy: {e}")
            return False

