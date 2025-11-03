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
        ZINGPROXY_CHANGE_IP_LINK,
        ZINGPROXY_DEFAULT_PORT,
        ZING_PROXY_HOST,
        ZING_PROXY_USER,
        ZING_PROXY_PASS,
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
        ZINGPROXY_CHANGE_IP_LINK,
        ZINGPROXY_DEFAULT_PORT,
        ZING_PROXY_HOST,
        ZING_PROXY_USER,
        ZING_PROXY_PASS,
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
        self._shutdown_event = None  # Sẽ được tạo trong start()
        
        logger.info("=" * 60)
        logger.info("🚀 ĐANG KHỞI ĐỘNG HỆ THỐNG GMAIL AUTO FARM")
        logger.info("=" * 60)
    
    def initialize(self):
        """Khởi tạo tất cả components"""
        import time
        try:
            # 1. Khởi tạo Database Manager
            logger.info("📦 Đang khởi tạo Database Manager...")
            self.db_manager = DatabaseManager(MONGO_URI, MONGO_DB_NAME)
            logger.info("✅ Database Manager đã sẵn sàng")
            time.sleep(0.5)
            
            # 1.5. Sync profiles từ GPM vào MongoDB ngay khi khởi động
            logger.info("🔄 Đang sync profiles từ GPM API vào MongoDB (lần đầu)...")
            # Tạm thời tạo GPMManager để sync profiles (sẽ được tạo lại ở bước 2)
            # GPMManager đã được import ở top level, sử dụng luôn
            gpm_api_key = GPM_API_KEY if GPM_API_KEY else None
            temp_gpm_manager = GPMManager(GPM_API_URL, gpm_api_key)
            gpm_profiles = temp_gpm_manager.get_profile_list()
            if gpm_profiles:
                synced = self.db_manager.sync_profiles_from_gpm(gpm_profiles)
                logger.info(f"✅ Đã sync {synced} profiles từ GPM vào MongoDB")
            else:
                logger.warning("⚠️ Không lấy được profiles từ GPM API. Hãy kiểm tra GPM API và đảm bảo có profiles.")
            time.sleep(0.5)  # Delay để dễ quan sát log
            
            # 2. Khởi tạo GPM Manager
            logger.info("🔧 Đang khởi tạo GPM Manager...")
            # API key chỉ cần khi dùng remote GPM, local GPM không cần
            gpm_api_key = GPM_API_KEY if GPM_API_KEY else None
            self.gpm_manager = GPMManager(GPM_API_URL, gpm_api_key)
            logger.info("✅ GPM Manager đã sẵn sàng")
            time.sleep(0.5)
            
            # 3. Khởi tạo Proxy Manager
            logger.info("🌐 Đang khởi tạo Proxy Manager...")
            self.proxy_manager = ProxyManager(
                api_url=ZINGPROXY_API_URL,
                api_key=ZINGPROXY_API_KEY,
                change_ip_link=ZINGPROXY_CHANGE_IP_LINK,
                default_host=ZING_PROXY_HOST,
                default_port=ZINGPROXY_DEFAULT_PORT,
                default_user=ZING_PROXY_USER,
                default_pass=ZING_PROXY_PASS
            )
            logger.info("✅ Proxy Manager đã sẵn sàng")
            time.sleep(0.5)
            
            # 4. Khởi tạo OTP Manager
            logger.info("📱 Đang khởi tạo OTP Manager...")
            self.otp_manager = OTPManager(OTP_API_URL, OTP_API_KEY)
            logger.info("✅ OTP Manager đã sẵn sàng")
            time.sleep(0.5)
            
            # 5. Khởi tạo Telegram Client (dùng chung cho listener và orchestrator)
            logger.info("💬 Đang khởi tạo Telegram Client...")
            from telethon import TelegramClient
            from pathlib import Path
            import os
            
            # Đảm bảo session file được lưu ở root directory (cùng cấp với src/)
            # Sử dụng absolute path để tránh tạo session ở thư mục hiện tại
            root_dir = Path(__file__).parent.parent.resolve()  # resolve() để có absolute path
            session_path = root_dir / TELEGRAM_SESSION_NAME
            session_path_absolute = str(session_path.absolute())  # Convert thành absolute string
            
            logger.info(f"📁 Session sẽ được lưu tại: {session_path_absolute}")
            self.telegram_client = TelegramClient(session_path_absolute, TELEGRAM_API_ID, TELEGRAM_API_HASH)
            logger.info("✅ Telegram Client đã sẵn sàng")
            time.sleep(0.5)
            
            # 6. Khởi tạo Telegram Listener (TeleMonitor) - dùng client riêng
            logger.info("👂 Đang khởi tạo Telegram Listener (TeleMonitor)...")
            # TelegramListener sẽ tạo client riêng của nó (cần để listen messages)
            # Đảm bảo session file được lưu ở root directory (cùng cấp với src/)
            root_dir = Path(__file__).parent.parent.resolve()  # resolve() để có absolute path
            listener_session_path = root_dir / f"{TELEGRAM_SESSION_NAME}_listener"
            listener_session_path_absolute = str(listener_session_path.absolute())  # Convert thành absolute string
            
            logger.info(f"📁 Listener session sẽ được lưu tại: {listener_session_path_absolute}")
            # Callback sẽ được set sau khi tạo orchestrator
            self.telegram_listener = TelegramListener(
                api_id=TELEGRAM_API_ID,
                api_hash=TELEGRAM_API_HASH,
                session_name=listener_session_path_absolute,  # Session riêng, absolute path ở root directory
                gmail_farmer_bot_username=GMAIL_FARMER_BOT_USERNAME,
                db_manager=self.db_manager,
                on_rate_limit_callback=None  # Sẽ được set sau khi tạo orchestrator
            )
            logger.info("✅ Telegram Listener đã sẵn sàng")
            time.sleep(0.5)
            
            # 7. Khởi tạo Orchestrator
            logger.info("🎯 Đang khởi tạo Orchestrator...")
            self.orchestrator = Orchestrator(
                db_manager=self.db_manager,
                gpm_manager=self.gpm_manager,
                proxy_manager=self.proxy_manager,
                otp_manager=self.otp_manager,
                telegram_client=self.telegram_client,
                screenshots_dir=SCREENSHOTS_DIR,
                telegram_listener=self.telegram_listener,  # Truyền listener để orchestrator có thể gửi tin nhắn
                max_workers=MAX_WORKERS,
                check_interval=SCHEDULER_CHECK_INTERVAL,
                min_pending_accounts=3  # Duy trì tối thiểu 3 accounts pending
            )
            logger.info(f"✅ Orchestrator đã sẵn sàng (max_workers={MAX_WORKERS}, interval={SCHEDULER_CHECK_INTERVAL}s, min_pending=3)")
            time.sleep(0.5)
            
            # Set callback cho telegram_listener để xử lý rate limit
            self.telegram_listener._on_rate_limit_detected = self.orchestrator._handle_rate_limit
            
            logger.info("=" * 60)
            logger.info("✅ TẤT CẢ COMPONENTS ĐÃ ĐƯỢC KHỞI TẠO")
            logger.info("=" * 60)
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"❌ Lỗi khởi tạo hệ thống: {e}", exc_info=True)
            raise
    
    async def ensure_pending_accounts(self, target_count: int = 3):
        """
        Đảm bảo có đủ số lượng accounts để xử lý (pending, failed, error, v.v.)
        Tự động gửi tin nhắn "➕ Register a new Gmail" cho bot nếu thiếu
        
        Args:
            target_count: Số lượng accounts cần có (mặc định: 3)
        """
        try:
            # Đếm số accounts có thể xử lý (pending, failed, error, v.v.)
            available_count = self.db_manager.count_available_accounts()
            logger.info(f"📊 Số lượng accounts có thể xử lý: {available_count}/{target_count}")
            
            if available_count >= target_count:
                logger.info(f"✅ Đã có đủ {available_count} accounts để xử lý, không cần gửi thêm")
                return
            
            # Tính số lượng cần gửi
            need_count = target_count - available_count
            logger.info(f"📤 Cần gửi {need_count} tin nhắn để đạt đủ {target_count} accounts")
            
            # Đảm bảo Telegram Listener client đã được start
            if not self.telegram_listener.client.is_connected():
                await self.telegram_listener.client.start()
                logger.info("✅ Đã kết nối Telegram Listener client")
            
            # Chỉ gửi 1 tin nhắn mỗi lần để đợi bot phản hồi trước khi gửi tiếp
            # Orchestrator sẽ tự động tiếp tục gửi khi cần thiết
            min_interval = 30  # Đợi 30 giây giữa các lần gửi để bot phản hồi
            
            logger.info(f"📤 Gửi 1 tin nhắn Register (đã có {available_count}/{target_count} accounts)...")
            logger.info(f"⏳ Orchestrator sẽ tự động gửi tiếp khi cần thiết (mỗi {min_interval}s)...")
            
            try:
                success, error_msg = await self.telegram_listener.send_register_message()
                if success:
                    logger.info(f"✅ Đã gửi tin nhắn Register. Đợi bot phản hồi...")
                else:
                    logger.warning(f"⚠️ Không thể gửi tin nhắn Register: {error_msg}")
                    
                    # Kiểm tra rate limit
                    if error_msg and ("too often" in error_msg.lower() or "rate limit" in error_msg.lower()):
                        logger.warning(f"⚠️ Phát hiện rate limit từ bot")
            except Exception as e:
                logger.error(f"❌ Lỗi khi gửi tin nhắn Register: {e}")
            
            logger.info(f"✅ Orchestrator sẽ tiếp tục kiểm tra và gửi tin nhắn khi cần...")
            
        except Exception as e:
            logger.error(f"❌ Lỗi trong ensure_pending_accounts: {e}", exc_info=True)
    
    async def start(self):
        """Bắt đầu chạy hệ thống"""
        try:
            self.is_running = True
            self._shutdown_event = asyncio.Event()  # Tạo event trong start() khi đã có event loop
            
            logger.info("=" * 60)
            logger.info("🚀 BẮT ĐẦU CHẠY HỆ THỐNG")
            logger.info("=" * 60)
            logger.info("💡 Để dừng hệ thống, nhấn Ctrl+C (hoặc Ctrl+Z trên một số terminal)")
            logger.info("=" * 60)
            
            # Khởi động Telegram Client
            # Kiểm tra xem đã có session chưa bằng cách thử connect trước
            # Nếu connect thành công và đã authorized thì không cần đăng nhập
            from pathlib import Path
            root_dir = Path(__file__).parent.parent.resolve()
            session_file = root_dir / f"{TELEGRAM_SESSION_NAME}.session"
            
            logger.info(f"🔄 Đang kiểm tra session Telegram tại: {session_file}")
            if session_file.exists():
                logger.info(f"📂 Tìm thấy session file, đang kết nối...")
            else:
                logger.info(f"📝 Chưa có session file, sẽ tạo mới sau khi đăng nhập...")
            
            if not self.telegram_client.is_connected():
                try:
                    await self.telegram_client.connect()
                    # Kiểm tra xem đã authorized chưa
                    if await self.telegram_client.is_user_authorized():
                        logger.info("✅ Đã kết nối với session hiện có (không cần đăng nhập)")
                    else:
                        logger.warning("⚠️ Session không hợp lệ hoặc chưa authorized, cần đăng nhập lại...")
                        await self.telegram_client.start()
                except Exception as connect_error:
                    logger.info(f"📝 Chưa có session hoặc session lỗi, tạo mới... ({connect_error})")
                    await self.telegram_client.start()
            else:
                # Đã connected, kiểm tra authorized
                if await self.telegram_client.is_user_authorized():
                    logger.info("✅ Client đã được kết nối và authorized")
                else:
                    logger.warning("⚠️ Client đã connect nhưng chưa authorized, cần đăng nhập...")
                    await self.telegram_client.start()
            
            logger.info("✅ Telegram Client đã sẵn sàng")
            
            # Đảm bảo có đủ 3 accounts pending khi khởi động
            logger.info("📋 Đang kiểm tra số lượng accounts pending...")
            await self.ensure_pending_accounts(target_count=3)
            
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
            logger.info("   - Nhấn Ctrl+C để dừng hệ thống")
            logger.info("=" * 60)
            
            # Đợi cho đến khi có signal dừng hoặc task bị lỗi
            # Sử dụng loop với kiểm tra flag thường xuyên để có thể dừng ngay khi nhận signal
            try:
                while self.is_running and any(not task.done() for task in self.tasks):
                    # Kiểm tra flag mỗi 0.5 giây để dừng nhanh
                    done, pending = await asyncio.wait(
                        self.tasks,
                        timeout=0.5,
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Nếu nhận signal dừng → cancel tất cả tasks ngay
                    if not self.is_running:
                        logger.info("⏹️ Nhận tín hiệu dừng, đang cancel tất cả tasks...")
                        for task in self.tasks:
                            if not task.done():
                                task.cancel()
                        # Đợi tasks cancel hoàn thành (timeout 5 giây)
                        try:
                            await asyncio.wait_for(
                                asyncio.gather(*self.tasks, return_exceptions=True),
                                timeout=5.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning("⚠️ Timeout khi đợi tasks cancel, tiếp tục shutdown...")
                        break
                    
                    # Kiểm tra nếu có task hoàn thành do lỗi
                    for task in done:
                        try:
                            await task
                        except asyncio.CancelledError:
                            logger.debug("ℹ️ Task đã bị cancel")
                        except Exception as e:
                            logger.error(f"❌ Task bị lỗi: {e}", exc_info=True)
                            # Nếu có lỗi nghiêm trọng, có thể dừng hệ thống
                            # (Tùy chọn: có thể set flag để dừng)
                    
                    # Nếu tất cả tasks đã hoàn thành, thoát loop
                    if all(task.done() for task in self.tasks):
                        break
                    
            except KeyboardInterrupt:
                logger.info("⚠️ Nhận KeyboardInterrupt, dừng hệ thống...")
                self.is_running = False
                # Cancel tất cả tasks
                for task in self.tasks:
                    if not task.done():
                        task.cancel()
            except asyncio.CancelledError:
                logger.info("⚠️ Tasks đã bị cancel")
            
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
    # Flag để tránh xử lý signal nhiều lần
    shutdown_in_progress = False
    
    def signal_handler(signum, frame):
        nonlocal shutdown_in_progress
        # Chỉ xử lý 1 lần
        if shutdown_in_progress:
            logger.warning("⚠️ Signal handler đã được gọi trước đó, bỏ qua...")
            return
        shutdown_in_progress = True
        
        logger.info(f"⚠️ Nhận signal {signum}, bắt đầu graceful shutdown...")
        logger.info("⏹️ Đang dừng hệ thống, vui lòng đợi...")
        system.is_running = False
        
        # Tạo một event để đánh thức main loop nếu đang đợi
        if hasattr(system, '_shutdown_event') and system._shutdown_event:
            system._shutdown_event.set()
        
        # Dừng orchestrator ngay (nếu có)
        if hasattr(system, 'orchestrator') and system.orchestrator:
            try:
                system.orchestrator.stop()
            except:
                pass
    
    # Thiết lập signal handlers
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except (ValueError, OSError) as e:
        # Windows có thể không hỗ trợ tất cả signals
        logger.warning(f"⚠️ Không thể thiết lập một số signal handlers: {e}")
        try:
            signal.signal(signal.SIGINT, signal_handler)
        except:
            pass


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

