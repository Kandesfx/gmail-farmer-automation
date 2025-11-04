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
                        
                        # Xử lý các lỗi đặc biệt
                        if error_msg == "PROFILE_IN_TRASH":
                            logger.error(f"   💡 Profile đang ở trong thùng rác (trash), không thể sử dụng")
                            logger.error(f"   💡 Vui lòng khôi phục profile từ GPM dashboard hoặc xóa profile khỏi MongoDB")
                        
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
    
    def delete_profile(self, profile_id: str) -> bool:
        """
        Xóa (delete) profile khỏi GPM - Dùng khi profile bị lỗi proxy hoặc lỗi nghiêm trọng
        
        Args:
            profile_id: ID của profile
            
        Returns:
            True nếu thành công, False nếu lỗi
        """
        try:
            # API: DELETE /api/v3/profiles/{id}?mode=2 (xóa vĩnh viễn)
            url = f"{self.api_url}/api/v3/profiles/{profile_id}?mode=2"
            
            logger.warning(f"🗑️ Đang XÓA profile: {profile_id} (do lỗi nghiêm trọng)")
            response = requests.delete(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                
                if isinstance(response_data, dict) and "success" in response_data:
                    if not response_data.get("success", False):
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"❌ API trả về lỗi khi xóa profile {profile_id}: {error_msg}")
                        return False
                
                logger.warning(f"✅ Profile {profile_id} đã bị XÓA vĩnh viễn")
                return True
            else:
                logger.error(f"❌ Lỗi xóa profile {profile_id}: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout khi xóa profile {profile_id}")
            return False
        except Exception as e:
            logger.error(f"❌ Lỗi xóa profile {profile_id}: {e}", exc_info=True)
            return False
    
    def create_profile(
        self,
        profile_name: str,
        proxy: Optional[Dict[str, str]] = None,
        group_name: str = "All",
        browser_core: str = "chromium",
        browser_name: str = "Chrome",
        browser_version: Optional[str] = None,
        is_random_browser_version: bool = False,
        startup_urls: str = "",
        is_masked_font: bool = True,
        is_noise_canvas: bool = False,
        is_noise_webgl: bool = False,
        is_noise_client_rect: bool = False,
        is_noise_audio_context: bool = True,
        is_random_screen: bool = False,
        is_masked_webgl_data: bool = True,
        is_masked_media_device: bool = True,
        is_random_os: bool = False,
        os: str = "Windows 11",
        webrtc_mode: int = 2,
        user_agent: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Tạo mới profile với proxy
        
        Args:
            profile_name: Tên của profile (bắt buộc)
            proxy: Dict chứa proxy config {"host": "...", "port": "...", "username": "...", "password": "..."}
            group_name: Tên group (mặc định: "All")
            browser_core: chromium hoặc firefox (mặc định: chromium)
            browser_name: Chrome hoặc Firefox (mặc định: Chrome)
            browser_version: Version của browser (tùy chọn)
            is_random_browser_version: Random browser version (mặc định: False)
            startup_urls: URLs khởi động, phân cách bằng dấu phẩy (tùy chọn)
            is_masked_font: Mask font (mặc định: True)
            is_noise_canvas: Noise canvas (mặc định: False)
            is_noise_webgl: Noise webgl (mặc định: False)
            is_noise_client_rect: Noise client rect (mặc định: False)
            is_noise_audio_context: Noise audio context (mặc định: True)
            is_random_screen: Random screen (mặc định: False)
            is_masked_webgl_data: Mask webgl data (mặc định: True)
            is_masked_media_device: Mask media device (mặc định: True)
            is_random_os: Random OS (mặc định: False)
            os: Tên hệ điều hành (mặc định: "Windows 11")
            webrtc_mode: 1 - Off, 2 - Base on IP (mặc định: 2)
            user_agent: User agent tùy chỉnh (tùy chọn)
            
        Returns:
            Dict chứa thông tin profile mới tạo, hoặc None nếu lỗi
            Format: {
                "id": str,
                "name": str,
                "raw_proxy": str,
                "profile_path": str,
                "browser_type": str,
                "browser_version": str,
                "note": str,
                "group_id": int,
                "created_at": str
            }
        """
        try:
            # API: POST /api/v3/profiles/create
            url = f"{self.api_url}/api/v3/profiles/create"
            
            # Build raw_proxy string từ proxy dict
            # Ưu tiên socks5Proxy, fallback sang httpProxy
            # Lấy nguyên vẹn chuỗi từ API và chỉ thêm prefix tương ứng
            raw_proxy = ""
            if proxy:
                socks5_raw = proxy.get("socks5_raw", "")
                http_raw = proxy.get("http_raw", "")
                
                if socks5_raw:
                    # Thêm prefix socks5:// vào đầu chuỗi từ API
                    # Ví dụ: "103.139.44.48:5555:xefzoorz:xeFZOOrZ" → "socks5://103.139.44.48:5555:xefzoorz:xeFZOOrZ"
                    raw_proxy = f"socks5://{socks5_raw}"
                    logger.debug(f"   Sử dụng SOCKS5 proxy: {socks5_raw[:50]}...")
                elif http_raw:
                    # Thêm prefix http:// vào đầu chuỗi từ API
                    # Ví dụ: "103.139.44.48:5677:xefzoorz:xeFZOOrZ" → "http://103.139.44.48:5677:xefzoorz:xeFZOOrZ"
                    raw_proxy = f"http://{http_raw}"
                    logger.debug(f"   Sử dụng HTTP proxy (fallback): {http_raw[:50]}...")
                else:
                    # Fallback: build từ các field riêng lẻ (nếu không có raw string)
                    host = proxy.get("host", "")
                    port = proxy.get("port", "")
                    username = proxy.get("username", "")
                    password = proxy.get("password", "")
                    proxy_type = proxy.get("proxy_type", "socks5")
                    
                    if host and port:
                        prefix = "socks5://" if proxy_type == "socks5" else "http://"
                        if username and password:
                            raw_proxy = f"{prefix}{host}:{port}:{username}:{password}"
                        else:
                            raw_proxy = f"{prefix}{host}:{port}"
            
            # Build request body
            payload = {
                "profile_name": profile_name,
                "group_name": group_name,
                "browser_core": browser_core,
                "browser_name": browser_name,
                "raw_proxy": raw_proxy,
                "startup_urls": startup_urls,
                "is_masked_font": is_masked_font,
                "is_noise_canvas": is_noise_canvas,
                "is_noise_webgl": is_noise_webgl,
                "is_noise_client_rect": is_noise_client_rect,
                "is_noise_audio_context": is_noise_audio_context,
                "is_random_screen": is_random_screen,
                "is_masked_webgl_data": is_masked_webgl_data,
                "is_masked_media_device": is_masked_media_device,
                "is_random_browser_version": is_random_browser_version,
                "is_random_os": is_random_os,
                "os": os,
                "webrtc_mode": webrtc_mode
            }
            
            # Thêm các field tùy chọn
            if browser_version:
                payload["browser_version"] = browser_version
            if user_agent:
                payload["user_agent"] = user_agent
            
            logger.info(f"📝 Đang tạo profile mới: {profile_name}")
            if raw_proxy:
                logger.debug(f"   Proxy: {proxy.get('host')}:{proxy.get('port')}")
            
            response = requests.post(url, json=payload, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                
                # GPM API trả về format {success: true, data: {...}}
                if isinstance(response_data, dict) and "success" in response_data:
                    if not response_data.get("success", False):
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"❌ API trả về lỗi khi tạo profile: {error_msg}")
                        return None
                    
                    # Lấy data từ field "data"
                    profile_data = response_data.get("data", {})
                    
                    profile_id = profile_data.get("id")
                    if not profile_id:
                        logger.error(f"❌ API không trả về profile_id")
                        logger.debug(f"Response data: {profile_data}")
                        return None
                    
                    logger.info(f"✅ Đã tạo profile thành công: {profile_id} ({profile_name})")
                    logger.debug(f"   Profile path: {profile_data.get('profile_path')}")
                    logger.debug(f"   Browser: {profile_data.get('browser_type')} {profile_data.get('browser_version')}")
                    
                    return profile_data
                else:
                    logger.error(f"❌ Response không đúng format: {response_data}")
                    return None
            else:
                logger.error(f"❌ Lỗi tạo profile: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout khi tạo profile")
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi tạo profile: {e}", exc_info=True)
            return None
    
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

