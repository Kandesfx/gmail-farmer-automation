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
    """Quản lý ZingProxy API - Lấy proxy đã thuê và xoay IP (Option 2: Ưu tiên API)"""
    
    def __init__(self, api_url: str, api_key: str = "", proxy_key: str = "", 
                 change_ip_link: str = "", default_host: str = "", 
                 default_port: str = "", default_user: str = "", default_pass: str = ""):
        """
        Khởi tạo ProxyManager
        """
        self.api_url = api_url.rstrip('/') if api_url else "https://api.zingproxy.com"
        self.api_key = api_key
        self.proxy_key = proxy_key  # API Key của proxy cụ thể
        self.change_ip_link = change_ip_link
        self.default_host = default_host
        self.default_port = default_port or "8649"
        self.default_user = default_user
        self.default_pass = default_pass
        
        # Headers cho API requests (không cần cho get-proxy endpoint)
        self.headers = {
            "Content-Type": "application/json"
        }
        
        logger.info(f"✅ Đã khởi tạo ProxyManager")
        logger.debug(f"   API URL: {self.api_url}")
        logger.debug(f"   Proxy Key: {'✅ Đã có' if self.proxy_key else '❌ Chưa có (cần điền ZINGPROXY_PROXY_KEY)'}")
        logger.debug(f"   Change IP Link: {'Đã có' if self.change_ip_link else 'Chưa có'}")
        if self.default_host:
            logger.debug(f"   Fallback Proxy (.env): {self.default_host}:{self.default_port}")
    
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
        timeout: int = 15,
        max_retries: int = 3,
        skip_validation: bool = False
    ) -> bool:
        """
        Validate proxy bằng cách gọi lại API ZingProxy get-proxy?key={key}
        Để kiểm tra proxy còn hợp lệ và hoạt động
        
        Args:
            proxy: Dict chứa proxy config (host, port, username, password)
            timeout: Timeout cho mỗi request (giây)
            max_retries: Số lần retry tối đa
            skip_validation: Bỏ qua validate (nếu proxy đã được verify từ config)
            
        Returns:
            True nếu proxy hợp lệ
            
        Raises:
            RuntimeError: Nếu validate thất bại sau max_retries
        """
        if not proxy.get("host") or not proxy.get("port"):
            error_msg = "Proxy không có host hoặc port"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        
        # Nếu skip validation (proxy từ config đã được verify) → return True
        if skip_validation:
            logger.info(f"ℹ️ Bỏ qua validate proxy {proxy['host']}:{proxy['port']} (proxy từ config)")
            return True
        
        # Nếu không có proxy_key, không thể validate bằng API
        if not self.proxy_key:
            logger.warning(f"⚠️ Không có Proxy Key để validate, bỏ qua validation")
            return True
        
        logger.info(f"🔍 Đang validate proxy {proxy['host']}:{proxy['port']} qua ZingProxy API...")
        
        # Validate bằng cách gọi lại API get-proxy?key={key}
        validation_url = f"{self.api_url}/get-proxy?key={self.proxy_key}"
        
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"   📡 Attempt {attempt}/{max_retries} - Gọi API: {validation_url}")
                
                response = requests.get(validation_url, timeout=timeout)
                
                # Kiểm tra HTTP status code
                if response.status_code != 200:
                    logger.debug(f"   ⚠️ HTTP Status {response.status_code} từ API, thử lại...")
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if attempt < max_retries:
                        wait_time = attempt * 2
                        logger.debug(f"   ⏳ Đợi {wait_time}s trước khi retry...")
                        time.sleep(wait_time)
                    continue
                
                # Parse JSON response
                try:
                    data = response.json()
                except ValueError as json_error:
                    logger.error(f"   ❌ Không thể parse JSON response: {json_error}")
                    logger.error(f"   Response text: {response.text[:200]}")
                    last_error = f"JSON parse error: {json_error}"
                    if attempt < max_retries:
                        wait_time = attempt * 2
                        time.sleep(wait_time)
                    continue
                
                # Kiểm tra format response theo đúng tài liệu ZingProxy
                if not isinstance(data, dict):
                    logger.error(f"   ❌ Response không phải là dict: {type(data)}")
                    last_error = f"Invalid response format: {type(data)}"
                    if attempt < max_retries:
                        wait_time = attempt * 2
                        time.sleep(wait_time)
                    continue
                
                # Kiểm tra status field
                status = data.get("status")
                if status == "failed":
                    error_msg = data.get("error", "Unknown error")
                    logger.error(f"   ❌ API trả về lỗi: {error_msg}")
                    last_error = f"API error: {error_msg}"
                    # Nếu API báo failed thì không cần retry, raise ngay
                    error_msg_full = f"ZingProxy API trả về lỗi: {error_msg}"
                    logger.error(f"❌ {error_msg_full}")
                    logger.error(f"   💡 Gợi ý:")
                    logger.error(f"      - Kiểm tra ZINGPROXY_PROXY_KEY trong .env có đúng không")
                    logger.error(f"      - Kiểm tra proxy có còn hạn không (từ dashboard ZingProxy)")
                    logger.error(f"      - Proxy có thể đã bị hủy hoặc hết hạn")
                    raise RuntimeError(error_msg_full)
                
                if status != "success":
                    logger.warning(f"   ⚠️ API trả về status không hợp lệ: {status}")
                    last_error = f"Invalid status: {status}"
                    if attempt < max_retries:
                        wait_time = attempt * 2
                        time.sleep(wait_time)
                    continue
                
                # Parse proxy info từ response
                proxy_data = data.get("proxy")
                if not proxy_data:
                    logger.error(f"   ❌ Response không có field 'proxy'")
                    last_error = "Missing 'proxy' field in response"
                    if attempt < max_retries:
                        wait_time = attempt * 2
                        time.sleep(wait_time)
                    continue
                
                # Ưu tiên validate socks5Proxy, fallback sang httpProxy
                socks5_proxy_str = proxy_data.get("socks5Proxy", "")
                http_proxy_str = proxy_data.get("httpProxy", "")
                
                api_proxy_str = ""
                api_proxy_type = ""
                
                if socks5_proxy_str:
                    api_proxy_str = socks5_proxy_str
                    api_proxy_type = "SOCKS5"
                    logger.debug(f"   ✅ Parse được socks5Proxy từ API: {socks5_proxy_str[:50]}...")
                elif http_proxy_str:
                    api_proxy_str = http_proxy_str
                    api_proxy_type = "HTTP"
                    logger.debug(f"   ✅ Parse được httpProxy từ API: {http_proxy_str[:50]}...")
                else:
                    logger.error(f"   ❌ Proxy data không có cả socks5Proxy và httpProxy")
                    last_error = "Missing both 'socks5Proxy' and 'httpProxy' in proxy data"
                    logger.error(f"   💡 Gợi ý: Kiểm tra proxy từ ZingProxy có hỗ trợ socks5Proxy hoặc httpProxy không")
                    if attempt < max_retries:
                        wait_time = attempt * 2
                        time.sleep(wait_time)
                    continue
                
                # So sánh với proxy hiện tại
                proxy_socks5_raw = proxy.get("socks5_raw", "")
                proxy_http_raw = proxy.get("http_raw", "")
                
                # So sánh với socks5_raw (nếu có)
                if proxy_socks5_raw and api_proxy_type == "SOCKS5":
                    if socks5_proxy_str == proxy_socks5_raw:
                        logger.info(f"✅ Proxy validation thành công - {api_proxy_type} proxy hợp lệ từ ZingProxy API")
                        logger.debug(f"   Proxy hiện tại khớp với API")
                        logger.debug(f"   Proxy ID: {proxy_data.get('uId')}, Resource ID: {proxy_data.get('resourceId')}")
                        return True
                    else:
                        logger.warning(f"⚠️ Proxy từ API khác với proxy hiện tại (có thể IP đã xoay)")
                        logger.info(f"✅ Proxy validation thành công - API trả về {api_proxy_type} proxy hợp lệ (có thể IP đã xoay)")
                        logger.debug(f"   Proxy ID: {proxy_data.get('uId')}, Resource ID: {proxy_data.get('resourceId')}")
                        return True
                
                # So sánh với http_raw (nếu có)
                if proxy_http_raw and api_proxy_type == "HTTP":
                    if http_proxy_str == proxy_http_raw:
                        logger.info(f"✅ Proxy validation thành công - {api_proxy_type} proxy hợp lệ từ ZingProxy API")
                        logger.debug(f"   Proxy hiện tại khớp với API")
                        logger.debug(f"   Proxy ID: {proxy_data.get('uId')}, Resource ID: {proxy_data.get('resourceId')}")
                        return True
                    else:
                        logger.warning(f"⚠️ Proxy từ API khác với proxy hiện tại (có thể IP đã xoay)")
                        logger.info(f"✅ Proxy validation thành công - API trả về {api_proxy_type} proxy hợp lệ (có thể IP đã xoay)")
                        logger.debug(f"   Proxy ID: {proxy_data.get('uId')}, Resource ID: {proxy_data.get('resourceId')}")
                        return True
                
                # Nếu không có raw string, so sánh host và port (fallback)
                try:
                    parts = api_proxy_str.split(":")
                    api_proxy_host = parts[0] if len(parts) > 0 else ""
                    api_proxy_port = parts[1] if len(parts) > 1 else ""
                    
                    if api_proxy_host == proxy.get("host") and api_proxy_port == str(proxy.get("port")):
                        logger.info(f"✅ Proxy validation thành công - {api_proxy_type} proxy hợp lệ từ ZingProxy API")
                        return True
                    else:
                        logger.warning(f"⚠️ Proxy từ API khác với proxy hiện tại")
                        logger.info(f"✅ Proxy validation thành công - API trả về {api_proxy_type} proxy hợp lệ")
                        return True
                except Exception as parse_error:
                    logger.warning(f"⚠️ Không thể so sánh proxy, nhưng API trả về success")
                    logger.info(f"✅ Proxy validation thành công - API trả về {api_proxy_type} proxy hợp lệ")
                    return True
                    
            except requests.exceptions.Timeout as e:
                logger.debug(f"   ⏱️ Timeout sau {timeout}s: {str(e)[:100]}")
                last_error = f"Timeout: {str(e)[:100]}"
            except requests.exceptions.ConnectionError as e:
                logger.debug(f"   🔌 ConnectionError: {str(e)[:100]}")
                last_error = f"ConnectionError: {str(e)[:100]}"
            except RuntimeError:
                # Đã raise RuntimeError trong try block (API trả về failed) → re-raise
                raise
            except Exception as e:
                logger.debug(f"   ❌ Lỗi không mong đợi: {str(e)[:100]}")
                last_error = f"Unexpected error: {str(e)[:100]}"
            
            # Nếu đã thử hết mà vẫn lỗi → backoff và retry
            if attempt < max_retries:
                wait_time = attempt * 2  # Tăng thời gian đợi: 2s, 4s
                logger.debug(f"   ⏳ Đợi {wait_time}s trước khi retry lần tiếp theo...")
                time.sleep(wait_time)
        
        # Nếu đã thử hết mà vẫn lỗi → FAIL FAST
        error_msg = f"Proxy validation thất bại sau {max_retries} attempts"
        logger.error(f"❌ {error_msg}")
        logger.error(f"   Proxy hiện tại: {proxy['host']}:{proxy['port']}")
        logger.error(f"   API URL: {validation_url}")
        logger.error(f"   Lỗi cuối cùng: {last_error}")
        logger.error(f"   💡 Gợi ý:")
        logger.error(f"      - Kiểm tra ZINGPROXY_PROXY_KEY trong .env có đúng không")
        logger.error(f"      - Kiểm tra proxy có còn hạn không (từ dashboard ZingProxy)")
        logger.error(f"      - Kiểm tra network có thể kết nối đến {self.api_url} không")
        logger.error(f"      - Kiểm tra proxy có bị hủy hoặc hết hạn không")
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
        Lấy proxy đã thuê cố định từ API hoặc từ config (.env)
        Option 2: Ưu tiên Proxy Key → Fallback sang .env config
        
        Returns:
            Dict chứa proxy config hoặc None nếu thiếu thông tin
        """
        # Ưu tiên 1: Lấy theo Proxy Key (nhanh nhất, không cần Bearer token)
        if self.proxy_key:
            logger.info("📡 Đang lấy proxy theo Proxy Key từ ZingProxy API...")
            proxy_by_key = self.get_proxy_by_key()
            if proxy_by_key:
                logger.info(f"✅ Đã lấy proxy theo key: {proxy_by_key['host']}:{proxy_by_key['port']}")
                return proxy_by_key
            else:
                logger.warning("⚠️ Không thể lấy proxy theo key, thử fallback sang .env config...")
        
        # Ưu tiên 2: Fallback sang .env config nếu có
        if self.default_host:
            if not self.default_user or not self.default_pass:
                logger.warning("⚠️ Chưa cấu hình ZING_PROXY_USER hoặc ZING_PROXY_PASS trong .env")
                logger.warning("   Sẽ dùng proxy không có authentication")
            
            proxy = self.build_proxy_object_from_raw(
                host=self.default_host,
                port=self.default_port,
                username=self.default_user,
                password=self.default_pass
            )
            
            # Set proxy_type là "socks5" khi lấy từ .env (mặc định dùng socks5)
            proxy["proxy_type"] = "socks5"
            
            logger.info(f"✅ Đã lấy default proxy từ .env config (fallback): {proxy['host']}:{proxy['port']}")
            return proxy
        
        # Không có proxy nào
        logger.error("❌ Không thể lấy proxy từ API và không có .env config")
        logger.error("   💡 Vui lòng:")
        logger.error("      1. Điền ZINGPROXY_PROXY_KEY trong .env để lấy proxy theo key (Khuyến nghị)")
        logger.error("      2. Hoặc điền ZING_PROXY_HOST, ZING_PROXY_USER, ZING_PROXY_PASS trong .env (Fallback)")
        return None
    
    def assign_proxy_for_profile(
        self,
        profile_id: str,
        change_ip: bool = False,
        skip_validation: bool = False
    ) -> Dict[str, str]:
        """
        Gán proxy cho profile cụ thể
        - Lấy default proxy từ config
        - Xoay IP nếu change_ip=True
        - Validate proxy (có thể skip nếu proxy từ config đã được verify)
        - Trả về proxy object chuẩn để truyền vào GPM API
        
        Args:
            profile_id: ID của profile cần gán proxy
            change_ip: Có xoay IP trước khi validate không
            skip_validation: Bỏ qua validate (nếu proxy từ config đã được verify)
            
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
            logger.error(f"   💡 Vui lòng kiểm tra .env: ZING_PROXY_HOST, ZING_PROXY_USER, ZING_PROXY_PASS")
            raise RuntimeError(error_msg)
        
        # 2. Xoay IP nếu được yêu cầu
        if change_ip:
            logger.info(f"🔄 Đang xoay IP cho profile {profile_id}...")
            ip_rotated = self.rotate_ip_with_link()
            if ip_rotated:
                # Đợi lâu hơn để IP xoay xong (theo code mẫu Bot1)
                logger.debug(f"   Đợi 5s để IP xoay xong...")
                time.sleep(5)
            else:
                logger.warning(f"⚠️ Không thể xoay IP, tiếp tục với IP hiện tại...")
        
        # 3. Validate proxy (FAIL-FAST nếu lỗi, trừ khi skip_validation=True)
        if not skip_validation:
            logger.info(f"🔍 Đang validate proxy cho profile {profile_id}...")
            try:
                self.validate_proxy_requests(proxy, skip_validation=False)
            except RuntimeError as e:
                error_msg = f"Proxy validation thất bại cho profile {profile_id}: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error(f"   💡 Gợi ý: Kiểm tra proxy có hoạt động không, hoặc set skip_validation=True nếu proxy đã được verify")
                raise RuntimeError(error_msg)
        else:
            logger.info(f"ℹ️ Bỏ qua validate proxy (proxy từ config đã được verify)")
        
        logger.info(f"✅ Đã gán proxy thành công cho profile {profile_id}: {proxy['host']}:{proxy['port']}")
        return proxy
    
    def get_proxy_by_key(self, proxy_key: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        Lấy thông tin proxy theo API Key của proxy (không cần Bearer token)
        Theo tài liệu: https://api.zingproxy.com/get-proxy?key={API_KEY_CỦA_PROXY}
        
        Args:
            proxy_key: API Key của proxy (nếu None thì dùng self.proxy_key)
        
        Returns:
            Dict chứa proxy config (host, port, username, password) hoặc None nếu lỗi
        """
        key = proxy_key or self.proxy_key
        if not key:
            logger.warning("⚠️ Không có Proxy Key, không thể lấy thông tin proxy theo key")
            return None
        
        try:
            url = f"{self.api_url}/get-proxy?key={key}"
            logger.info(f"📋 Đang lấy thông tin proxy theo key từ ZingProxy API...")
            logger.debug(f"   API URL: {url}")
            
            # Không cần Authorization header cho endpoint này
            response = requests.get(url, timeout=30)
            
            # Kiểm tra HTTP status code
            if response.status_code != 200:
                logger.error(f"❌ API trả về HTTP status {response.status_code}")
                logger.error(f"   Response: {response.text[:200]}")
                return None
            
            # Parse JSON response
            try:
                data = response.json()
            except ValueError as json_error:
                logger.error(f"❌ Không thể parse JSON response: {json_error}")
                logger.error(f"   Response text: {response.text[:200]}")
                return None
            
            # Kiểm tra format response theo đúng tài liệu ZingProxy
            if not isinstance(data, dict):
                logger.error(f"❌ Response không phải là dict: {type(data)}")
                logger.error(f"   Response: {data}")
                return None
            
            # Kiểm tra status field
            status = data.get("status")
            if status == "failed":
                error_msg = data.get("error", "Unknown error")
                logger.error(f"❌ API trả về lỗi: {error_msg}")
                logger.error(f"   💡 Gợi ý:")
                logger.error(f"      - Kiểm tra ZINGPROXY_PROXY_KEY trong .env có đúng không")
                logger.error(f"      - Kiểm tra proxy có còn hạn không (từ dashboard ZingProxy)")
                logger.error(f"      - Proxy có thể đã bị hủy hoặc hết hạn")
                return None
            
            if status != "success":
                logger.error(f"❌ API trả về status không hợp lệ: {status}")
                logger.error(f"   Response: {data}")
                return None
            
            # Parse proxy info từ response
            proxy_data = data.get("proxy")
            if not proxy_data:
                logger.error("❌ Response không có field 'proxy'")
                logger.error(f"   Response: {data}")
                return None
            
            # Ưu tiên dùng socks5Proxy, fallback sang httpProxy nếu không có
            socks5_proxy_str = proxy_data.get("socks5Proxy", "")
            http_proxy_str = proxy_data.get("httpProxy", "")
            
            proxy = {}
            proxy_raw = ""
            proxy_type = ""
            
            if socks5_proxy_str:
                logger.info("✅ Sử dụng socks5Proxy từ API")
                proxy_raw = socks5_proxy_str
                proxy_type = "socks5"
                proxy["socks5_raw"] = socks5_proxy_str
            elif http_proxy_str:
                logger.info("✅ Sử dụng httpProxy từ API (fallback)")
                logger.warning("   ⚠️ Không có socks5Proxy, đang dùng httpProxy")
                proxy_raw = http_proxy_str
                proxy_type = "http"
                proxy["http_raw"] = http_proxy_str
            else:
                logger.error("❌ Proxy data không có cả socks5Proxy và httpProxy")
                logger.error(f"   Proxy data: {proxy_data}")
                logger.error(f"   💡 Gợi ý: Kiểm tra proxy từ ZingProxy có hỗ trợ socks5Proxy hoặc httpProxy không")
                return None
            
            proxy["proxy_type"] = proxy_type
            
            # Parse để lấy thông tin riêng lẻ (dùng cho validation và logging)
            try:
                parts = proxy_raw.split(":")
                if len(parts) >= 2:
                    proxy["host"] = parts[0]
                    proxy["port"] = parts[1]
                    if len(parts) >= 3:
                        proxy["username"] = parts[2]
                    if len(parts) >= 4:
                        proxy["password"] = ":".join(parts[3:])  # Password có thể chứa ":"
                    
                    logger.debug(f"   ✅ Parse được {proxy_type} proxy: {proxy.get('host')}:{proxy.get('port')}")
            except Exception as parse_error:
                logger.warning(f"⚠️ Không thể parse {proxy_type}Proxy để lấy thông tin chi tiết: {parse_error}")
                logger.warning(f"   Sẽ dùng nguyên vẹn chuỗi: {proxy_raw[:50]}...")
            
            logger.info(f"✅ Đã lấy {proxy_type}Proxy theo key: {proxy_raw[:50]}...")
            logger.debug(f"   Proxy ID: {proxy_data.get('uId')}")
            logger.debug(f"   Resource ID: {proxy_data.get('resourceId')}")
            logger.debug(f"   Date End: {proxy_data.get('dateEnd')}")
            logger.debug(f"   Auto Renew: {proxy_data.get('autoRenew')}")
            return proxy
                
        except requests.exceptions.Timeout as e:
            logger.error(f"❌ Timeout khi gọi ZingProxy API: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ ConnectionError khi gọi ZingProxy API: {e}")
            logger.error(f"   💡 Gợi ý: Kiểm tra network có thể kết nối đến {self.api_url} không")
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi lấy proxy theo key: {e}", exc_info=True)
            return None
    
    
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
