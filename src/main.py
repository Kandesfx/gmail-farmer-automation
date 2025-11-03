"""
Main Entry Point - Khởi động toàn bộ hệ thống Gmail Auto Farm
TeleMonitor + Orchestrator + Worker Pool
"""
import asyncio
import signal
import sys
from pathlib import Path

try:
    # Relative imports (khi chạy như module)
    from .config import (
        MONGO_URI,
        MONGO_DB_NAME,
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        TELEGRAM_SESSION_NAME,
        GMAIL_FARMER_BOT_USERNAME,
        MAX_WORKERS,
        SCHEDULER_CHECK_INTERVAL,
        GPM_API_URL,
        GPM_API_KEY,
        ZINGPROXY_API_URL,
        ZINGPROXY_API_KEY,
        OTP_API_URL,
        OTP_API_KEY,
        SCREENSHOTS_DIR
    )
    from .db.database_manager import DatabaseManager
    from .core.telegram_listener import TelegramListener
    from .core.orchestrator import Orchestrator
    from .core.gpm_manager import GPMManager
    from .core.proxy_manager import ProxyManager
    from .core.otp_manager import OTPManager
    from .utils.logger import get_logger
except ImportError:
    # Absolute imports (khi chạy trực tiếp từ src/)
    from config import (
        MONGO_URI,
        MONGO_DB_NAME,
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        TELEGRAM_SESSION_NAME,
        GMAIL_FARMER_BOT_USERNAME,
        MAX_WORKERS,
        SCHEDULER_CHECK_INTERVAL,
        GPM_API_URL,
        GPM_API_KEY,
        ZINGPROXY_API_URL,
        ZINGPROXY_API_KEY,
        OTP_API_URL,
        OTP_API_KEY,
        SCREENSHOTS_DIR
    )
    from db.database_manager import DatabaseManager
    from core.telegram_listener import TelegramListener
    from core.orchestrator import Orchestrator
    from core.gpm_manager import GPMManager
    from core.proxy_manager import ProxyManager
    from core.otp_manager import OTPManager
    from utils.logger import get_logger

logger = get_logger(__name__)


class GmailFarmSystem:
    """Hệ thống chính quản lý TeleMonitor và Orchestrator"""
    
    def __init__(self):
        """Khởi tạo toàn bộ hệ thống"""
        self.db_manager = None
        self.telegram_client = None
        self.telegram_listener = None
        self.orchestrator = None
        self.gpm_manager = None
        self.proxy_manager = None
        self.otp_manager = None
        self.is_running = False
        self.tasks = []
        
        logger.info("=" * 60)
        logger.info("🚀 ĐANG KHỞI ĐỘNG HỆ THỐNG GMAIL AUTO FARM")
        logger.info("=" * 60)
    
    def initialize(self):
        """Khởi tạo tất cả components"""
        try:
            # 1. Khởi tạo Database Manager
            logger.info("📦 Đang khởi tạo Database Manager...")
            self.db_manager = DatabaseManager(MONGO_URI, MONGO_DB_NAME)
            logger.info("✅ Database Manager đã sẵn sàng")
            
            # 2. Khởi tạo GPM Manager
            logger.info("🔧 Đang khởi tạo GPM Manager...")
            self.gpm_manager = GPMManager(GPM_API_URL, GPM_API_KEY)
            logger.info("✅ GPM Manager đã sẵn sàng")
            
            # 3. Khởi tạo Proxy Manager
            logger.info("🌐 Đang khởi tạo Proxy Manager...")
            self.proxy_manager = ProxyManager(ZINGPROXY_API_URL, ZINGPROXY_API_KEY)
            logger.info("✅ Proxy Manager đã sẵn sàng")
            
            # 4. Khởi tạo OTP Manager
            logger.info("📱 Đang khởi tạo OTP Manager...")
            self.otp_manager = OTPManager(OTP_API_URL, OTP_API_KEY)
            logger.info("✅ OTP Manager đã sẵn sàng")
            
            # 5. Khởi tạo Telegram Client (dùng chung cho listener và orchestrator)
            logger.info("💬 Đang khởi tạo Telegram Client...")
            from telethon import TelegramClient
            self.telegram_client = TelegramClient(TELEGRAM_SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
            logger.info("✅ Telegram Client đã sẵn sàng")
            
            # 6. Khởi tạo Telegram Listener (TeleMonitor) - dùng client riêng
            logger.info("👂 Đang khởi tạo Telegram Listener (TeleMonitor)...")
            # TelegramListener sẽ tạo client riêng của nó (cần để listen messages)
            self.telegram_listener = TelegramListener(
                api_id=TELEGRAM_API_ID,
                api_hash=TELEGRAM_API_HASH,
                session_name=f"{TELEGRAM_SESSION_NAME}_listener",  # Session riêng để tránh conflict
                gmail_farmer_bot_username=GMAIL_FARMER_BOT_USERNAME,
                db_manager=self.db_manager
            )
            logger.info("✅ Telegram Listener đã sẵn sàng")
            
            # 7. Khởi tạo Orchestrator
            logger.info("🎯 Đang khởi tạo Orchestrator...")
            self.orchestrator = Orchestrator(
                db_manager=self.db_manager,
                gpm_manager=self.gpm_manager,
                proxy_manager=self.proxy_manager,
                otp_manager=self.otp_manager,
                telegram_client=self.telegram_client,
                screenshots_dir=SCREENSHOTS_DIR,
                max_workers=MAX_WORKERS,
                check_interval=SCHEDULER_CHECK_INTERVAL
            )
            logger.info(f"✅ Orchestrator đã sẵn sàng (max_workers={MAX_WORKERS}, interval={SCHEDULER_CHECK_INTERVAL}s)")
            
            logger.info("=" * 60)
            logger.info("✅ TẤT CẢ COMPONENTS ĐÃ ĐƯỢC KHỞI TẠO")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"❌ Lỗi khởi tạo hệ thống: {e}", exc_info=True)
            raise
    
    async def start(self):
        """Bắt đầu chạy hệ thống"""
        try:
            self.is_running = True
            
            logger.info("=" * 60)
            logger.info("🚀 BẮT ĐẦU CHẠY HỆ THỐNG")
            logger.info("=" * 60)
            
            # Khởi động Telegram Client
            await self.telegram_client.start()
            logger.info("✅ Telegram Client đã kết nối")
            
            # Tạo tasks chạy song song
            # Task 1: Telegram Listener (TeleMonitor)
            listener_task = asyncio.create_task(self._run_telegram_listener())
            self.tasks.append(listener_task)
            logger.info("✅ Đã khởi động Telegram Listener task")
            
            # Task 2: Orchestrator Scheduler
            orchestrator_task = asyncio.create_task(self._run_orchestrator())
            self.tasks.append(orchestrator_task)
            logger.info("✅ Đã khởi động Orchestrator task")
            
            # Đợi tất cả tasks chạy (hoặc bị interrupt)
            logger.info("=" * 60)
            logger.info("🔄 HỆ THỐNG ĐANG CHẠY...")
            logger.info(f"   - TeleMonitor: Đang lắng nghe bot {GMAIL_FARMER_BOT_USERNAME}")
            logger.info(f"   - Orchestrator: Kiểm tra mỗi {SCHEDULER_CHECK_INTERVAL}s, max_workers={MAX_WORKERS}")
            logger.info("=" * 60)
            
            # Đợi cho đến khi có signal dừng
            await asyncio.gather(*self.tasks, return_exceptions=True)
            
        except KeyboardInterrupt:
            logger.info("⚠️ Nhận tín hiệu dừng (Ctrl+C)")
        except Exception as e:
            logger.error(f"❌ Lỗi trong main loop: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def _run_telegram_listener(self):
        """Chạy Telegram Listener trong async task"""
        try:
            await self.telegram_listener.start()
        except Exception as e:
            logger.error(f"❌ Lỗi trong Telegram Listener: {e}", exc_info=True)
            raise
    
    async def _run_orchestrator(self):
        """Chạy Orchestrator trong async task"""
        try:
            await self.orchestrator.start()
        except Exception as e:
            logger.error(f"❌ Lỗi trong Orchestrator: {e}", exc_info=True)
            raise
    
    async def stop(self):
        """Dừng hệ thống một cách graceful"""
        if not self.is_running:
            return
        
        logger.info("=" * 60)
        logger.info("⏹️ ĐANG DỪNG HỆ THỐNG...")
        logger.info("=" * 60)
        
        self.is_running = False
        
        try:
            # 1. Dừng Orchestrator
            if self.orchestrator:
                logger.info("⏹️ Đang dừng Orchestrator...")
                self.orchestrator.stop()
                logger.info("✅ Orchestrator đã dừng")
            
            # 2. Dừng Telegram Listener
            if self.telegram_listener:
                logger.info("⏹️ Đang dừng Telegram Listener...")
                await self.telegram_listener.stop()
                logger.info("✅ Telegram Listener đã dừng")
            
            # 3. Cancel tất cả tasks
            if self.tasks:
                logger.info("⏹️ Đang cancel các tasks...")
                for task in self.tasks:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                logger.info("✅ Đã cancel tất cả tasks")
            
            # 4. Đóng Telegram Client
            if self.telegram_client:
                logger.info("⏹️ Đang đóng Telegram Client...")
                await self.telegram_client.disconnect()
                logger.info("✅ Telegram Client đã đóng")
            
            # 5. Đóng Database Connection
            if self.db_manager:
                logger.info("⏹️ Đang đóng Database connection...")
                self.db_manager.close()
                logger.info("✅ Database connection đã đóng")
            
            logger.info("=" * 60)
            logger.info("✅ HỆ THỐNG ĐÃ DỪNG THÀNH CÔNG")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"❌ Lỗi khi dừng hệ thống: {e}", exc_info=True)


def setup_signal_handlers(system: GmailFarmSystem):
    """Thiết lập signal handlers cho graceful shutdown"""
    def signal_handler(signum, frame):
        logger.info(f"⚠️ Nhận signal {signum}, bắt đầu graceful shutdown...")
        system.is_running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Hàm main async"""
    system = GmailFarmSystem()
    
    try:
        # Setup signal handlers
        setup_signal_handlers(system)
        
        # Khởi tạo hệ thống
        system.initialize()
        
        # Bắt đầu chạy
        await system.start()
        
    except Exception as e:
        logger.error(f"❌ Lỗi nghiêm trọng: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Đảm bảo cleanup
        await system.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Nhận KeyboardInterrupt, dừng hệ thống...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Lỗi không mong đợi: {e}", exc_info=True)
        sys.exit(1)

