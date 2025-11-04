"""
Orchestrator - Scheduler quản lý workflow tạo Gmail
Chọn pending account + idle profile → spawn worker
"""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any

try:
    from ..db.database_manager import DatabaseManager
    from ..utils.logger import get_logger
    from ..gmail.gmail_register import create_gmail_account
except ImportError:
    from db.database_manager import DatabaseManager
    from utils.logger import get_logger
    from gmail.gmail_register import create_gmail_account

logger = get_logger(__name__)


class Orchestrator:
    """Quản lý workflow tạo Gmail account"""
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        gpm_manager,
        proxy_manager,
        otp_manager,
        telegram_client,
        screenshots_dir,
        telegram_listener=None,  # Thêm telegram_listener để có thể gửi tin nhắn
        max_workers: int = 3,
        check_interval: int = 10,
        min_pending_accounts: int = 3  # Số lượng accounts pending tối thiểu cần duy trì
    ):
        """
        Khởi tạo Orchestrator
        
        Args:
            db_manager: DatabaseManager instance
            gpm_manager: GPMManager instance
            proxy_manager: ProxyManager instance
            otp_manager: OTPManager instance
            telegram_client: TelegramClient instance
            screenshots_dir: Path đến thư mục screenshots
            telegram_listener: TelegramListener instance (để gửi tin nhắn Register)
            max_workers: Số worker tối đa (mặc định: 3)
            check_interval: Khoảng thời gian kiểm tra DB (giây, mặc định: 10)
            min_pending_accounts: Số lượng accounts pending tối thiểu cần duy trì (mặc định: 3)
        """
        self.db_manager = db_manager
        self.gpm_manager = gpm_manager
        self.proxy_manager = proxy_manager
        self.otp_manager = otp_manager
        self.telegram_client = telegram_client
        self.telegram_listener = telegram_listener
        self.screenshots_dir = screenshots_dir
        self.max_workers = max_workers
        self.check_interval = check_interval
        self.min_pending_accounts = min_pending_accounts
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.running_workers = {}  # account_id -> future
        self.is_running = False
        self._last_register_check = 0  # Timestamp của lần kiểm tra cuối
        self._rate_limit_detected = False  # Flag để track rate limit từ bot
        self._rate_limit_expiry = 0  # Timestamp khi rate limit hết hạn (mặc định 0 = không bị rate limit)
        self._last_pending_query = 0  # Timestamp của lần query pending account cuối
        self._last_pending_result = None  # Cache kết quả query pending account
        self._pending_cache_ttl = 5  # Cache TTL (giây) - giảm số lần query DB
        self._last_idle_profile_query = 0  # Timestamp của lần query idle profile cuối
        self._last_idle_profile_result = None  # Cache kết quả query idle profile
        self._last_register_sent_time = 0  # Timestamp của lần gửi Register message cuối
        self._min_register_interval = 30  # Khoảng thời gian tối thiểu giữa các lần gửi (giây) - để đợi bot phản hồi
        self._last_profile_sync = 0  # Timestamp của lần sync profiles cuối
        self._profile_sync_interval = 300  # Sync profiles từ GPM mỗi 5 phút
        self._consecutive_proxy_errors = 0  # Đếm số lỗi proxy liên tiếp
        self._max_consecutive_proxy_errors = 3  # Dừng nếu có 3 lỗi proxy liên tiếp
        
        logger.info(f"✅ Đã khởi tạo Orchestrator (max_workers={max_workers}, interval={check_interval}s)")
    
    async def start(self):
        """Bắt đầu scheduler"""
        self.is_running = True
        logger.info("🚀 Orchestrator đã bắt đầu")
        
        try:
            while self.is_running:
                # Kiểm tra flag dừng trước mỗi vòng lặp
                if not self.is_running:
                    break
                
                await self._scheduler_loop()
                
                # Kiểm tra flag dừng và sleep với khả năng bị interrupt
                if not self.is_running:
                    break
                
                # Sử dụng asyncio.sleep với timeout ngắn để kiểm tra flag thường xuyên hơn
                for _ in range(self.check_interval):
                    if not self.is_running:
                        break
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            logger.info("⏹️ Orchestrator đã bị cancel")
        except KeyboardInterrupt:
            logger.info("⚠️ Orchestrator nhận KeyboardInterrupt")
        except Exception as e:
            logger.error(f"❌ Lỗi trong scheduler loop: {e}", exc_info=True)
        finally:
            logger.info("⏹️ Orchestrator đã dừng")
    
    async def _ensure_pending_accounts(self):
        """
        Đảm bảo có đủ số lượng accounts để xử lý
        Tính cả pending + creating (vì creating cũng đang được xử lý)
        Tự động gửi tin nhắn "➕ Register a new Gmail" cho bot nếu thiếu
        """
        if not self.telegram_listener:
            logger.debug("ℹ️ Không có telegram_listener, bỏ qua kiểm tra pending accounts")
            return
        
        try:
            # Đếm cả pending và creating (vì creating cũng đang được xử lý)
            available_count = self.db_manager.count_available_accounts()
            pending_count = self.db_manager.count_pending_accounts()
            creating_count = self.db_manager.count_creating_accounts()
            
            logger.debug(f"📊 Thống kê accounts: pending={pending_count}, creating={creating_count}, tổng={available_count}")
            
            # Nếu đã có đủ accounts (pending + creating) → không cần gửi thêm
            if available_count >= self.min_pending_accounts:
                logger.debug(f"ℹ️ Đã có đủ {available_count} accounts sẵn sàng (pending={pending_count} + creating={creating_count} >= {self.min_pending_accounts})")
                return
            
            # Tính số lượng cần gửi (dựa trên tổng available, không chỉ pending)
            need_count = self.min_pending_accounts - available_count
            logger.info(f"📤 Cần gửi {need_count} tin nhắn để đạt đủ {self.min_pending_accounts} accounts sẵn sàng (hiện có: {available_count} = {pending_count} pending + {creating_count} creating)")
            
            # Đảm bảo Telegram Listener client đã được start
            if not self.telegram_listener.client.is_connected():
                await self.telegram_listener.client.start()
            
            # Kiểm tra xem có đang bị rate limit không
            import time
            current_time = time.time()
            if current_time < self._rate_limit_expiry:
                wait_time = self._rate_limit_expiry - current_time
                logger.info(f"⏳ Đang chờ rate limit hết hạn ({wait_time:.0f} giây còn lại), bỏ qua lần gửi này")
                return
            
            # Kiểm tra xem có vừa gửi tin nhắn gần đây không (để đợi bot phản hồi)
            time_since_last_send = current_time - self._last_register_sent_time
            if time_since_last_send < self._min_register_interval:
                wait_time = self._min_register_interval - time_since_last_send
                logger.info(f"⏳ Vừa gửi tin nhắn cách đây {time_since_last_send:.0f}s, đợi thêm {wait_time:.0f}s để bot phản hồi...")
                return
            
            # Chỉ gửi 1 tin nhắn mỗi lần để đợi bot phản hồi trước khi gửi tiếp
            # Không gửi hàng loạt nữa
            logger.info(f"📤 Gửi 1 tin nhắn Register (đã có {available_count}/{self.min_pending_accounts} accounts sẵn sàng: {pending_count} pending + {creating_count} creating)...")
            try:
                success, error_msg = await self.telegram_listener.send_register_message()
                if success:
                    self._last_register_sent_time = time.time()
                    logger.info(f"✅ Đã gửi tin nhắn Register. Đợi bot phản hồi ({self._min_register_interval}s) trước khi gửi tiếp...")
                    # Reset rate limit flag nếu gửi thành công
                    self._rate_limit_detected = False
                else:
                    logger.warning(f"⚠️ Không thể gửi tin nhắn Register: {error_msg}")
                    # Nếu lỗi, vẫn cập nhật thời gian để tránh spam
                    self._last_register_sent_time = time.time()
            except Exception as e:
                logger.error(f"❌ Lỗi khi gửi tin nhắn Register: {e}")
                # Nếu lỗi, vẫn cập nhật thời gian để tránh spam
                self._last_register_sent_time = time.time()
            
            # Lưu ý: Rate limit từ bot sẽ được xử lý trong telegram_listener khi nhận message "too often"
            
        except Exception as e:
            logger.error(f"❌ Lỗi trong _ensure_pending_accounts: {e}", exc_info=True)
    
    async def _sync_profiles_from_gpm(self):
        """
        Đồng bộ profiles từ GPM API vào MongoDB
        Gọi định kỳ để đảm bảo có profiles sẵn sàng
        """
        try:
            logger.info("🔄 Đang sync profiles từ GPM API vào MongoDB...")
            
            # Lấy danh sách profiles từ GPM API
            gpm_profiles = self.gpm_manager.get_profile_list()
            
            if not gpm_profiles:
                logger.warning("⚠️ Không lấy được profiles từ GPM API")
                return
            
            # Sync vào MongoDB
            synced_count = self.db_manager.sync_profiles_from_gpm(gpm_profiles)
            
            if synced_count > 0:
                logger.info(f"✅ Đã sync {synced_count} profiles từ GPM vào MongoDB")
            else:
                logger.debug("ℹ️ Không có profiles mới cần sync")
                
        except Exception as e:
            logger.error(f"❌ Lỗi sync profiles từ GPM: {e}", exc_info=True)
    
    async def _handle_rate_limit(self):
        """
        Xử lý khi phát hiện rate limit từ bot
        Set expiry time là 5 phút (300 giây) từ bây giờ
        """
        import time
        self._rate_limit_expiry = time.time() + 300  # 5 phút
        self._rate_limit_detected = True
        logger.warning(f"⚠️ Đã set rate limit expiry: sẽ hết hạn sau 5 phút")
    
    async def _scheduler_loop(self):
        """
        Vòng lặp scheduler chính
        Chọn pending account + idle profile → spawn worker
        """
        try:
            import time
            current_time = time.time()
            
            # Sync profiles từ GPM API vào MongoDB (mỗi 5 phút)
            if current_time - self._last_profile_sync > self._profile_sync_interval:
                await self._sync_profiles_from_gpm()
                self._last_profile_sync = current_time
            
            # Kiểm tra và duy trì số lượng accounts pending (mỗi 30 giây, hoặc lâu hơn nếu bị rate limit)
            # Nếu đang bị rate limit, đợi lâu hơn (60 giây) trước khi kiểm tra lại
            check_interval = 60 if (current_time < self._rate_limit_expiry) else 30
            
            if current_time - self._last_register_check > check_interval:
                await self._ensure_pending_accounts()
                self._last_register_check = current_time
            
            # Kiểm tra số worker đang chạy
            active_count = len([f for f in self.running_workers.values() if not f.done()])
            
            if active_count >= self.max_workers:
                logger.debug(f"ℹ️ Đã đạt max workers ({self.max_workers}), bỏ qua lần kiểm tra này")
                return
            
            # Tối ưu: Cache kết quả query pending account (5 giây)
            import time
            current_time = time.time()
            pending_account = None
            
            if current_time - self._last_pending_query < self._pending_cache_ttl:
                # Sử dụng cache
                pending_account = self._last_pending_result
                if pending_account:
                    logger.debug(f"ℹ️ Sử dụng cached pending account: {pending_account.get('email')}")
            else:
                # Query mới
                pending_account = self.db_manager.get_pending()
                self._last_pending_result = pending_account
                self._last_pending_query = current_time
                
                if pending_account:
                    logger.info(f"✅ Tìm thấy pending account: {pending_account.get('email')}")
                else:
                    logger.debug("ℹ️ Không có account pending")
            
            if not pending_account:
                return
            
            # Kiểm tra account này đã có worker chưa
            account_id_str = str(pending_account.get("_id"))
            if account_id_str in self.running_workers:
                existing_future = self.running_workers[account_id_str]
                if not existing_future.done():
                    logger.warning(f"⚠️ Account {account_id_str} đã có worker đang chạy")
                    return
            
            logger.info(
                f"🎯 Phát hiện task: account={pending_account.get('email')} "
                f"(ID: {pending_account.get('_id')})"
            )
            
            # Invalidate cache khi spawn worker (vì account đã được sử dụng)
            self._last_pending_result = None
            self._last_pending_query = 0  # Force refresh ở lần query tiếp theo
            
            # Spawn worker Create Gmail (sẽ tạo profile mới trong worker)
            await self._spawn_worker(pending_account)
            
        except Exception as e:
            logger.error(f"❌ Lỗi trong scheduler loop: {e}", exc_info=True)
    
    async def _spawn_worker(self, account: Dict[str, Any]):
        """
        Spawn worker để tạo Gmail
        
        Args:
            account: Dict chứa thông tin account
        """
        try:
            from bson import ObjectId
            # create_gmail_account đã được import ở top level
            account_id = ObjectId(account["_id"])
            account_id_str = str(account_id)
            
            # Cập nhật status account → "creating"
            self.db_manager.update_status(
                account_id=account_id,
                new_status="creating"
            )
            
            # Submit worker task vào ThreadPoolExecutor
            logger.info(f"🚀 Đang spawn worker cho account: {account.get('email')}")
            
            future = self.executor.submit(
                create_gmail_account,
                account,
                self.db_manager,
                self.gpm_manager,
                self.proxy_manager,
                self.otp_manager,
                self.telegram_client,
                self.screenshots_dir
            )
            
            self.running_workers[account_id_str] = future
            
            # Monitor worker khi hoàn thành
            asyncio.create_task(self._monitor_worker(future, account_id_str, account))
            
        except Exception as e:
            logger.error(f"❌ Lỗi spawn worker: {e}", exc_info=True)
            # Rollback status
            try:
                from bson import ObjectId
                self.db_manager.update_status(
                    account_id=ObjectId(account["_id"]),
                    new_status="pending"
                )
            except Exception as rollback_error:
                logger.error(f"❌ Lỗi rollback: {rollback_error}")
    
    async def _monitor_worker(
        self,
        future,
        account_id_str: str,
        account: Dict[str, Any]
    ):
        """
        Monitor worker và cleanup khi hoàn thành
        
        Args:
            future: Future từ ProcessPoolExecutor
            account_id_str: String ID của account
            account: Dict chứa thông tin account
        """
        try:
            # Đợi worker hoàn thành (với khả năng cancel khi shutdown)
            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, future.result),
                    timeout=None  # Đợi đến khi hoàn thành hoặc bị cancel
                )
            except asyncio.CancelledError:
                logger.info(f"⚠️ Worker đã bị cancel cho account: {account.get('email')}")
                raise
            except Exception as executor_error:
                logger.error(f"❌ Lỗi trong executor: {executor_error}", exc_info=True)
                raise
            
            logger.info(f"✅ Worker hoàn thành cho account: {account.get('email')}, result: {result}")
            
            # Kiểm tra nếu worker fail do proxy lỗi
            if result is False:
                # Lấy account để kiểm tra last_error
                try:
                    from bson import ObjectId
                    account_obj = self.db_manager.accounts.find_one({"_id": ObjectId(account_id_str)})
                    if account_obj:
                        last_error = account_obj.get("last_error", "")
                        if "proxy" in last_error.lower() or "zingproxy" in last_error.lower():
                            self._consecutive_proxy_errors += 1
                            logger.warning(f"⚠️ Phát hiện lỗi proxy (lần {self._consecutive_proxy_errors}/{self._max_consecutive_proxy_errors})")
                            
                            # Nếu có quá nhiều lỗi proxy liên tiếp → dừng orchestrator
                            if self._consecutive_proxy_errors >= self._max_consecutive_proxy_errors:
                                logger.error(f"❌ Đã có {self._consecutive_proxy_errors} lỗi proxy liên tiếp, DỪNG ORCHESTRATOR")
                                logger.error(f"❌ Vui lòng kiểm tra ZingProxy API: URL và API key")
                                self.is_running = False  # Dừng orchestrator
                                return
                except Exception as check_error:
                    logger.debug(f"⚠️ Không thể kiểm tra last_error: {check_error}")
            else:
                # Worker thành công → reset counter
                self._consecutive_proxy_errors = 0
            
            # Cleanup
            if account_id_str in self.running_workers:
                del self.running_workers[account_id_str]
            
            # Profile sẽ được giải phóng trong worker khi stop_profile (profile được tạo mới trong worker)
            
        except asyncio.CancelledError:
            logger.info(f"⚠️ Monitor worker đã bị cancel cho account: {account.get('email')}")
            # Cleanup khi cancel
            if account_id_str in self.running_workers:
                del self.running_workers[account_id_str]
            raise
        except Exception as e:
            logger.error(f"❌ Lỗi trong worker: {e}", exc_info=True)
            
            # Cleanup
            if account_id_str in self.running_workers:
                del self.running_workers[account_id_str]
            
            # Profile được tạo mới trong worker, không cần rollback
    
    def stop(self):
        """Dừng orchestrator"""
        logger.info("⏹️ Đang yêu cầu dừng Orchestrator...")
        self.is_running = False
        # Cancel các workers đang chạy
        if hasattr(self, 'running_workers'):
            for account_id, future in list(self.running_workers.items()):
                if future and not future.done():
                    logger.info(f"⏹️ Đang cancel worker cho account: {account_id}")
                    future.cancel()
        logger.info("⏹️ Đang dừng Orchestrator...")
        
        # Shutdown executor
        self.executor.shutdown(wait=False)
        logger.info("✅ Đã shutdown ThreadPoolExecutor")

