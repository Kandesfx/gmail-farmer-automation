"""
GPM Manager - Quản lý GPM Profiles API
Start/Stop profile, get debugPort
"""
import time
import requests
from typing import Optional, Dict, Any
from ..utils.logger import get_logger

logger = get_logger(__name__)


class GPMManager:
    """Quản lý GPM Profiles API"""
    
    def __init__(self, api_url: str, api_key: str):
        """
        Khởi tạo GPMManager
        
        Args:
            api_url: URL của GPM API (ví dụ: "https://api.gpm.com")
            api_key: API key để authenticate
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"✅ Đã khởi tạo GPMManager: {api_url}")
    
    def start_profile(
        self,
        profile_id: str,
        proxy: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Start profile và nhận debugPort
        
        Args:
            profile_id: ID của profile
            proxy: Dict chứa proxy config (nếu có) - format: {"host": "...", "port": "...", "username": "...", "password": "..."}
            
        Returns:
            Dict chứa debugPort và thông tin profile, hoặc None nếu lỗi
        """
        try:
            url = f"{self.api_url}/api/v1/profiles/{profile_id}/start"
            
            payload = {}
            if proxy:
                payload["proxy"] = proxy
            
            logger.info(f"🚀 Đang start profile: {profile_id}")
            response = requests.post(url, json=payload, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                debug_port = data.get("debugPort")
                
                if not debug_port:
                    logger.error(f"❌ API không trả về debugPort cho profile {profile_id}")
                    return None
                
                logger.info(f"✅ Profile {profile_id} đã start, debugPort: {debug_port}")
                return {
                    "debugPort": debug_port,
                    "profile_id": profile_id,
                    "status": data.get("status", "running")
                }
            else:
                logger.error(f"❌ Lỗi start profile {profile_id}: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout khi start profile {profile_id}")
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi start profile {profile_id}: {e}", exc_info=True)
            return None
    
    def stop_profile(self, profile_id: str) -> bool:
        """
        Stop profile
        
        Args:
            profile_id: ID của profile
            
        Returns:
            True nếu thành công, False nếu lỗi
        """
        try:
            url = f"{self.api_url}/api/v1/profiles/{profile_id}/stop"
            
            logger.info(f"🛑 Đang stop profile: {profile_id}")
            response = requests.post(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"✅ Profile {profile_id} đã stop")
                return True
            else:
                logger.error(f"❌ Lỗi stop profile {profile_id}: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout khi stop profile {profile_id}")
            return False
        except Exception as e:
            logger.error(f"❌ Lỗi stop profile {profile_id}: {e}", exc_info=True)
            return False
    
    def get_profile_list(self) -> Optional[list]:
        """
        Lấy danh sách profiles
        
        Returns:
            List các profiles, hoặc None nếu lỗi
        """
        try:
            url = f"{self.api_url}/api/v1/profiles"
            
            response = requests.get(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                profiles = data.get("profiles", [])
                logger.info(f"✅ Lấy được {len(profiles)} profiles")
                return profiles
            else:
                logger.error(f"❌ Lỗi get profile list: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Lỗi get profile list: {e}", exc_info=True)
            return None

