"""
Constants - Các hằng số dùng chung trong hệ thống
"""
from typing import List, Dict

# ============================================================
# BATCH CONFIGURATION
# ============================================================
BATCH_SIZE = 3  # Số lượng profiles chạy song song trong batch
BATCH_WAIT_FOR_ALL = True  # Đợi tất cả workers hoàn thành trước khi spawn batch mới

# ============================================================
# WINDOW CONFIGURATION (GPM Profile Window Position/Size)
# ============================================================
# Hàm để tự động tính toán window configs dựa trên screen resolution
def get_window_configs(screen_width: int = 1920, screen_height: int = 1080, batch_size: int = 3) -> List[Dict[str, str]]:
    """
    Tính toán window positions và sizes dựa trên screen resolution
    
    Args:
        screen_width: Chiều rộng màn hình (pixels)
        screen_height: Chiều cao màn hình (pixels)
        batch_size: Số lượng cửa sổ cần tạo
        
    Returns:
        List các dict chứa "pos" và "size" cho mỗi cửa sổ
    """
    # Tính toán window width: chia màn hình thành batch_size cột, trừ margin
    margin = 20  # Margin giữa các cửa sổ (pixels)
    total_margin = margin * (batch_size + 1)  # Margin ở 2 bên và giữa các cửa sổ
    available_width = screen_width - total_margin
    window_width = available_width // batch_size
    
    # Window height: 80% chiều cao màn hình, trừ margin
    window_height = int((screen_height - (margin * 2)) * 0.8)
    
    configs = []
    for i in range(batch_size):
        # Tính toán x position: margin + (i * window_width) + (i * margin)
        x_pos = margin + (i * window_width) + (i * margin)
        y_pos = margin  # Top margin
        
        configs.append({
            "pos": f"{x_pos},{y_pos}",
            "size": f"{window_width},{window_height}"
        })
    
    return configs

# Default window configs (sẽ được tính toán lại khi cần)
# Fallback cho màn hình 1920x1080
_DEFAULT_SCREEN_WIDTH = 1920
_DEFAULT_SCREEN_HEIGHT = 1080
_WINDOW_CONFIGS_CACHE = None

def get_cached_window_configs(batch_size: int = 3) -> List[Dict[str, str]]:
    """
    Lấy window configs với auto-detection screen resolution
    
    Returns:
        List các dict chứa "pos" và "size" cho mỗi cửa sổ
    """
    global _WINDOW_CONFIGS_CACHE
    
    if _WINDOW_CONFIGS_CACHE is not None:
        return _WINDOW_CONFIGS_CACHE
    
    # Thử auto-detect screen resolution
    screen_width = _DEFAULT_SCREEN_WIDTH
    screen_height = _DEFAULT_SCREEN_HEIGHT
    
    try:
        # Windows: sử dụng tkinter hoặc win32api
        try:
            import tkinter as tk
            root = tk.Tk()
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            root.destroy()
        except Exception:
            # Fallback: thử win32api nếu có
            try:
                import win32api
                screen_width = win32api.GetSystemMetrics(0)  # SM_CXSCREEN
                screen_height = win32api.GetSystemMetrics(1)  # SM_CYSCREEN
            except ImportError:
                # Không có win32api, dùng default
                pass
    except Exception as e:
        # Nếu lỗi, dùng default values
        pass
    
    _WINDOW_CONFIGS_CACHE = get_window_configs(screen_width, screen_height, batch_size)
    return _WINDOW_CONFIGS_CACHE

# WINDOW_CONFIGS - Sử dụng function để tính toán động
# Lưu ý: Không dùng trực tiếp, nên gọi get_cached_window_configs()
WINDOW_CONFIGS = get_window_configs(_DEFAULT_SCREEN_WIDTH, _DEFAULT_SCREEN_HEIGHT, BATCH_SIZE)

# ============================================================
# RETRY CONFIGURATION
# ============================================================
MAX_RETRIES = 3  # Số lần retry tối đa cho các thao tác
RETRY_DELAY_MIN = 2  # Delay tối thiểu giữa các lần retry (giây)
RETRY_DELAY_MAX = 6  # Delay tối đa giữa các lần retry (giây)

# ============================================================
# TIMEOUT CONFIGURATION
# ============================================================
ELEMENT_WAIT_TIMEOUT = 10  # Timeout cho việc đợi element (giây)
PAGE_LOAD_TIMEOUT = 30  # Timeout cho việc load page (giây)
API_TIMEOUT = 30  # Timeout cho API calls (giây)

# ============================================================
# HUMANIZER CONFIGURATION
# ============================================================
TYPING_DELAY_MIN = 0.03  # Delay tối thiểu giữa các ký tự khi typing (giây)
TYPING_DELAY_MAX = 0.12  # Delay tối đa giữa các ký tự khi typing (giây)
RANDOM_DELAY_MIN = 1.0  # Delay tối thiểu cho các thao tác ngẫu nhiên (giây)
RANDOM_DELAY_MAX = 2.5  # Delay tối đa cho các thao tác ngẫu nhiên (giây)

# ============================================================
# PROXY ERROR DETECTION
# ============================================================
PROXY_ERROR_KEYWORDS = [
    "err_no_supported_proxies",
    "err_proxy_connection_failed",
    "err_tunnel_connection_failed",
    "proxy connection failed",
    "không thể truy cập trang web này",
    "cannot access this website"
]

# ============================================================
# CAPTCHA/QR DETECTION
# ============================================================
CAPTCHA_KEYWORDS = [
    "captcha",
    "recaptcha",
    "verify you're human",
    "verify you are human",
    "i'm not a robot",
    "scan this qr",
    "qr code",
    "verify your identity",
    "xác minh bạn là người",
    "chứng minh bạn không phải robot"
]

# ============================================================
# ORCHESTRATOR CONFIGURATION
# ============================================================
MAX_CONSECUTIVE_PROXY_ERRORS = 3  # Dừng orchestrator sau N lỗi proxy liên tiếp
RATE_LIMIT_EXPIRY_SECONDS = 300  # 5 phút
MIN_REGISTER_INTERVAL_SECONDS = 30  # Khoảng thời gian tối thiểu giữa các lần gửi Register
PROFILE_SYNC_INTERVAL_SECONDS = 300  # Sync profiles từ GPM mỗi 5 phút
PENDING_CACHE_TTL_SECONDS = 5  # Cache TTL cho pending accounts query

