"""
GPM Manager - Quản lý GPM Profiles API v3
Start/Stop profile, get remote_debugging_port để kết nối Selenium
"""
import time
import requests
from typing import Optional, Dict, Any

try:
    from ..utils.logger import get_logger
except ImportError:
    from utils.logger import get_logger

logger = get_logger(__name__)


class GPMManager:
    """Quản lý GPM Profiles API"""
    
    def __init__(self, api_url: str, api_key: Optional[str] = None):
        """
        Khởi tạo GPMManager
        
        Args:
            api_url: URL của GPM API (ví dụ: "http://127.0.0.1:19995" cho local hoặc "https://api.gpm.com" cho remote)
            api_key: API key để authenticate (None nếu dùng local GPM)
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.is_local = api_url.startswith(('http://127.0.0.1', 'http://localhost', 'http://0.0.0.0'))
        
        # Chỉ thêm Authorization header nếu có API key (remote GPM)
        self.headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        
        mode = "local" if self.is_local else "remote"
        logger.info(f"✅ Đã khởi tạo GPMManager ({mode}): {api_url}")
    
    def start_profile(
        self,
        profile_id: str,
        proxy: Optional[Dict[str, str]] = None,
        win_scale: Optional[float] = None,
        win_pos: Optional[str] = None,
        win_size: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Start profile và nhận remote_debugging_port
        
        Args:
            profile_id: ID của profile
            proxy: Dict chứa proxy config (nếu có) - format: {"host": "...", "port": "...", "username": "...", "password": "..."}
            win_scale: Giá trị từ 0 tới 1.0 (tùy chọn)
            win_pos: Tọa độ trình duyệt theo dạng "x,y" (tùy chọn)
            win_size: Kích thước trình duyệt theo dạng "width,height" (tùy chọn)
            
        Returns:
            Dict chứa remote_debugging_port và thông tin profile, hoặc None nếu lỗi
            Format: {
                "remote_debugging_port": int,
                "remote_debugging_address": str,  # IP:PORT
                "debugPort": int (alias cho backward compatibility),
                "profile_id": str,
                "browser_location": str,
                "driver_path": str
            }
        """
        try:
            # API: GET /api/v3/profiles/start/{id}
            url = f"{self.api_url}/api/v3/profiles/start/{profile_id}"
            
            # Build query params
            params = {}
            if proxy:
                # Proxy có thể cần format khác, tạm thời bỏ qua vì không thấy trong tài liệu
                pass
            if win_scale is not None:
                params["win_scale"] = win_scale
            if win_pos:
                params["win_pos"] = win_pos
            if win_size:
                params["win_size"] = win_size
            
            logger.info(f"🚀 Đang start profile: {profile_id}")
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                
                # GPM API trả về format {success: true, data: {...}}
                if isinstance(response_data, dict) and "success" in response_data:
                    if not response_data.get("success", False):
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"❌ API trả về lỗi khi start profile {profile_id}: {error_msg}")
                        return None
                    # Lấy data từ field "data"
                    data = response_data.get("data", {})
                    
                    # Kiểm tra nested success trong data (theo tài liệu)
                    if isinstance(data, dict) and "success" in data:
                        if not data.get("success", False):
                            logger.error(f"❌ Profile {profile_id} không thể start (nested success: false)")
                            return None
                else:
                    data = response_data
                
                # API trả về remote_debugging_address dạng "127.0.0.1:53378"
                remote_debugging_address = data.get("remote_debugging_address")
                
                if not remote_debugging_address:
                    logger.error(f"❌ API không trả về remote_debugging_address cho profile {profile_id}")
                    logger.debug(f"Response data: {data}")
                    return None
                
                # Parse IP:PORT để lấy port number
                try:
                    if ":" in remote_debugging_address:
                        _, port_str = remote_debugging_address.rsplit(":", 1)
                        remote_debugging_port = int(port_str)
                    else:
                        # Nếu chỉ có port number
                        remote_debugging_port = int(remote_debugging_address)
                except (ValueError, AttributeError) as e:
                    logger.error(f"❌ Không thể parse remote_debugging_address '{remote_debugging_address}': {e}")
                    return None
                
                logger.info(f"✅ Profile {profile_id} đã start, remote_debugging_address: {remote_debugging_address}, port: {remote_debugging_port}")
                
                # Trả về đầy đủ thông tin từ API
                result = {
                    "remote_debugging_port": remote_debugging_port,
                    "remote_debugging_address": remote_debugging_address,
                    "debugPort": remote_debugging_port,  # Alias cho backward compatibility
                    "profile_id": data.get("profile_id", profile_id),
                    "browser_location": data.get("browser_location"),
                    "driver_path": data.get("driver_path")
                }
                
                return result
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
        Đóng (close) profile
        
        Args:
            profile_id: ID của profile
            
        Returns:
            True nếu thành công, False nếu lỗi
        """
        try:
            # API: GET /api/v3/profiles/close/{id}
            url = f"{self.api_url}/api/v3/profiles/close/{profile_id}"
            
            logger.info(f"🛑 Đang đóng profile: {profile_id}")
            response = requests.get(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                
                # GPM API trả về format {success: true, message: "Đóng thành công"}
                if isinstance(response_data, dict) and "success" in response_data:
                    if not response_data.get("success", False):
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"❌ API trả về lỗi khi đóng profile {profile_id}: {error_msg}")
                        return False
                
                logger.info(f"✅ Profile {profile_id} đã đóng thành công")
                return True
            else:
                logger.error(f"❌ Lỗi đóng profile {profile_id}: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout khi đóng profile {profile_id}")
            return False
        except Exception as e:
            logger.error(f"❌ Lỗi đóng profile {profile_id}: {e}", exc_info=True)
            return False
    
    def get_profile_list(
        self,
        group_id: Optional[str] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        sort: Optional[int] = None,
        search: Optional[str] = None
    ) -> Optional[list]:
        """
        Lấy danh sách profiles
        
        Args:
            group_id: ID group cần lọc (lấy tại api Danh sách nhóm) (tùy chọn)
            page: Số trang (mặc định 1) (tùy chọn)
            per_page: Số profile mỗi trang (mặc định 50) (tùy chọn)
            sort: 0 - Mới nhất, 1 - Cũ tới mới, 2 - Tên A-Z, 3 - Tên Z-A (tùy chọn)
            search: Từ khóa profile name (tùy chọn)
        
        Returns:
            List các profiles, hoặc None nếu lỗi
        """
        try:
            # API: GET /api/v3/profiles
            url = f"{self.api_url}/api/v3/profiles"
            
            # Build query params
            params = {}
            if group_id:
                params["group_id"] = group_id
            if page is not None:
                params["page"] = page
            if per_page is not None:
                params["per_page"] = per_page
            if sort is not None:
                params["sort"] = sort
            if search:
                params["search"] = search
            
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                
                # GPM API trả về format {success: true, data: [...], pagination: {...}}
                if isinstance(response_data, dict) and "success" in response_data:
                    if not response_data.get("success", False):
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"❌ API trả về lỗi khi get profile list: {error_msg}")
                        return None
                    # Lấy data từ field "data"
                    profiles = response_data.get("data", [])
                else:
                    # Fallback nếu response không đúng format
                    if isinstance(response_data, list):
                        profiles = response_data
                    else:
                        profiles = response_data.get("profiles", response_data.get("data", []))
                
                logger.info(f"✅ Lấy được {len(profiles)} profiles")
                return profiles
            else:
                logger.error(f"❌ Lỗi get profile list: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Lỗi get profile list: {e}", exc_info=True)
            return None

