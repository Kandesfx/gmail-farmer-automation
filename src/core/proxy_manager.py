"""
Proxy Manager - Quản lý ZingProxy API để lấy proxy VN
Theo rules.md: Proxy VN bắt buộc cho mỗi profile
"""
import requests
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

try:
    from ..utils.logger import get_logger
except ImportError:
    try:
        from utils.logger import get_logger
    except ImportError:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from utils.logger import get_logger

logger = get_logger(__name__)


class ProxyManager:
    """Quản lý ZingProxy API - Lấy proxy đã thuê và xoay IP"""
    
    def __init__(self, api_url: str, api_key: str, change_ip_link: str = "", 
                 default_host: str = "", default_port: str = "", 
                 default_user: str = "", default_pass: str = ""):
        """
        Khởi tạo ProxyManager
        
        Args:
            api_url: URL của ZingProxy API (không dùng)
            api_key: API key (không dùng, giữ để tương thích)
            change_ip_link: Link change IP từ ZingProxy dashboard (ví dụ: https://api.zingproxy.com/getip/{key})
            default_host: IP proxy mặc định từ .env
            default_port: Port proxy mặc định từ .env
            default_user: Username proxy mặc định từ .env
            default_pass: Password proxy mặc định từ .env
        """
        self.api_url = api_url.rstrip('/') if api_url else ""
        self.api_key = api_key
        self.change_ip_link = change_ip_link
        self.default_host = default_host
        self.default_port = default_port or "8649"
        self.default_user = default_user
        self.default_pass = default_pass
        
        logger.info(f"✅ Đã khởi tạo ProxyManager")
        logger.debug(f"   Change IP Link: {'Đã có' if self.change_ip_link else 'Chưa có'}")
        logger.debug(f"   Default Proxy: {self.default_host}:{self.default_port}")
    
    def build_proxy_object_from_raw(
        self,
        host: str,
        port: str,
        username: str,
        password: str
    ) -> Dict[str, str]:
        """
        Build proxy object từ raw data (host, port, username, password)
        Format chuẩn để truyền vào GPM API
        
        Args:
            host: IP proxy
            port: Port proxy
            username: Username proxy
            password: Password proxy
            
        Returns:
            Dict chứa proxy config theo format GPM API:
            {
                "host": "...",
                "port": "...",
                "username": "...",
                "password": "..."
            }
        """
        proxy = {
            "host": host.strip() if host else "",
            "port": str(port).strip() if port else "",
            "username": username.strip() if username else "",
            "password": password.strip() if password else ""
        }
        
        logger.debug(f"📦 Đã build proxy object: {proxy['host']}:{proxy['port']}")
        return proxy
    
    def validate_proxy_requests(
        self,
        proxy: Dict[str, str],
        timeout: int = 10,
        max_retries: int = 3
    ) -> bool:
        """
        Validate proxy bằng cách gọi httpbin.org/ip qua proxy
        
        Args:
            proxy: Dict chứa proxy config (host, port, username, password)
            timeout: Timeout cho mỗi request (giây)
            max_retries: Số lần retry tối đa
            
        Returns:
            True nếu proxy hoạt động, False nếu lỗi
            
        Raises:
            RuntimeError: Nếu validate thất bại sau max_retries
        """
        if not proxy.get("host") or not proxy.get("port"):
            error_msg = "Proxy không có host hoặc port"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        
        # Build proxy URL cho requests
        proxy_url = self._build_proxy_url(proxy)
        
        logger.info(f"🔍 Đang validate proxy {proxy['host']}:{proxy['port']} qua httpbin.org/ip...")
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"   Attempt {attempt}/{max_retries}...")
                
                # Gọi httpbin.org/ip qua proxy
                response = requests.get(
                    "https://httpbin.org/ip",
                    proxies={"http": proxy_url, "https": proxy_url},
                    timeout=timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    detected_ip = data.get("origin", "")
                    logger.info(f"✅ Proxy validation thành công - IP: {detected_ip}")
                    logger.debug(f"   Response: {data}")
                    return True
                else:
                    logger.warning(f"⚠️ Proxy validation attempt {attempt} trả về status {response.status_code}")
                    
            except requests.exceptions.ProxyError as e:
                logger.warning(f"⚠️ Proxy validation attempt {attempt} - ProxyError: {e}")
            except requests.exceptions.Timeout as e:
                logger.warning(f"⚠️ Proxy validation attempt {attempt} - Timeout: {e}")
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"⚠️ Proxy validation attempt {attempt} - ConnectionError: {e}")
            except Exception as e:
                logger.warning(f"⚠️ Proxy validation attempt {attempt} - Error: {e}")
            
            # Backoff: đợi tăng dần (1s, 2s, 3s)
            if attempt < max_retries:
                wait_time = attempt
                logger.debug(f"   Đợi {wait_time}s trước khi retry...")
                time.sleep(wait_time)
        
        # Nếu đã thử hết mà vẫn lỗi → FAIL FAST
        error_msg = f"Proxy validation thất bại sau {max_retries} attempts"
        logger.error(f"❌ {error_msg}")
        logger.error(f"   Proxy: {proxy['host']}:{proxy['port']}")
        raise RuntimeError(error_msg)
    
    def _build_proxy_url(self, proxy: Dict[str, str]) -> str:
        """
        Build proxy URL từ proxy object
        Format: http://username:password@host:port
        
        Args:
            proxy: Dict chứa proxy config
            
        Returns:
            Proxy URL string
        """
        host = proxy.get("host", "")
        port = proxy.get("port", "")
        username = proxy.get("username", "")
        password = proxy.get("password", "")
        
        if username and password:
            return f"http://{username}:{password}@{host}:{port}"
        else:
            return f"http://{host}:{port}"
    
    def rotate_ip_with_link(
        self,
        change_ip_link: Optional[str] = None,
        max_retries: int = 3
    ) -> bool:
        """
        Xoay IP bằng cách gọi ChangeIP link của ZingProxy API (HTTP GET)
        
        Args:
            change_ip_link: Link change IP (nếu None thì dùng self.change_ip_link)
            max_retries: Số lần retry tối đa
            
        Returns:
            True nếu thành công, False nếu thất bại
        """
        link = change_ip_link or self.change_ip_link
        
        if not link:
            logger.warning("⚠️ Không có Change IP Link, bỏ qua rotate IP")
            return False
        
        logger.info(f"🔄 Đang xoay IP bằng Change IP Link: {link[:50]}...")
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"   Attempt {attempt}/{max_retries}...")
                
                response = requests.get(link, timeout=10)
                
                if response.status_code == 200:
                    logger.info(f"✅ Đã xoay IP thành công")
                    logger.debug(f"   Response: {response.text[:100]}")
                    return True
                else:
                    logger.warning(f"⚠️ Change IP attempt {attempt} trả về status {response.status_code}: {response.text[:100]}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ Change IP attempt {attempt} - Timeout")
            except Exception as e:
                logger.warning(f"⚠️ Change IP attempt {attempt} - Error: {e}")
            
            # Backoff: đợi tăng dần
            if attempt < max_retries:
                wait_time = attempt
                logger.debug(f"   Đợi {wait_time}s trước khi retry...")
                time.sleep(wait_time)
        
        logger.warning(f"⚠️ Không thể xoay IP sau {max_retries} attempts")
        return False
    
    def get_default_rented_proxy(self) -> Optional[Dict[str, str]]:
        """
        Lấy proxy đã thuê cố định từ config (.env)
        Đây là proxy mặc định đã được cấu hình sẵn
        
        Returns:
            Dict chứa proxy config hoặc None nếu thiếu thông tin
        """
        if not self.default_host:
            logger.error("❌ Chưa cấu hình ZING_PROXY_HOST trong .env")
            return None
        
        if not self.default_user or not self.default_pass:
            logger.warning("⚠️ Chưa cấu hình ZING_PROXY_USER hoặc ZING_PROXY_PASS trong .env")
            logger.warning("   Sẽ dùng proxy không có authentication")
        
        proxy = self.build_proxy_object_from_raw(
            host=self.default_host,
            port=self.default_port,
            username=self.default_user,
            password=self.default_pass
        )
        
        logger.info(f"✅ Đã lấy default proxy từ config: {proxy['host']}:{proxy['port']}")
        return proxy
    
    def assign_proxy_for_profile(
        self,
        profile_id: str,
        change_ip: bool = False
    ) -> Dict[str, str]:
        """
        Gán proxy cho profile cụ thể
        - Lấy default proxy từ config
        - Xoay IP nếu change_ip=True
        - Validate proxy
        - Trả về proxy object chuẩn để truyền vào GPM API
        
        Args:
            profile_id: ID của profile cần gán proxy
            change_ip: Có xoay IP trước khi validate không
            
        Returns:
            Dict chứa proxy config chuẩn để truyền vào GPM API
            
        Raises:
            RuntimeError: Nếu không lấy được proxy hoặc validate thất bại
        """
        logger.info(f"🔗 Đang gán proxy cho profile: {profile_id}")
        
        # 1. Lấy default proxy từ config
        proxy = self.get_default_rented_proxy()
        if not proxy:
            error_msg = "Không thể lấy default proxy từ config"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        
        # 2. Xoay IP nếu được yêu cầu
        if change_ip:
            logger.info(f"🔄 Đang xoay IP cho profile {profile_id}...")
            self.rotate_ip_with_link()
            # Đợi một chút để IP xoay xong
            time.sleep(2)
        
        # 3. Validate proxy (FAIL-FAST nếu lỗi)
        logger.info(f"🔍 Đang validate proxy cho profile {profile_id}...")
        try:
            self.validate_proxy_requests(proxy)
        except RuntimeError as e:
            error_msg = f"Proxy validation thất bại cho profile {profile_id}: {str(e)}"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        
        logger.info(f"✅ Đã gán proxy thành công cho profile {profile_id}: {proxy['host']}:{proxy['port']}")
        return proxy
    
    def release_proxy(self, proxy_id: Optional[str] = None) -> bool:
        """
        Release proxy (nếu API hỗ trợ)
        ZingProxy không cần release, hàm này giữ để tương thích
        
        Args:
            proxy_id: ID của proxy (không dùng)
            
        Returns:
            True (luôn thành công vì không cần release)
        """
        logger.debug("ℹ️ ZingProxy không cần release proxy")
        return True
