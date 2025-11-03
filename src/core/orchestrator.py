"""
Orchestrator - Scheduler quản lý workflow tạo Gmail
Chọn pending account + idle profile → spawn worker
"""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any

from ..db.database_manager import DatabaseManager
from ..utils.logger import get_logger

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
        max_workers: int = 3,
        check_interval: int = 10
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
            max_workers: Số worker tối đa (mặc định: 3)
            check_interval: Khoảng thời gian kiểm tra DB (giây, mặc định: 10)
        """
        self.db_manager = db_manager
        self.gpm_manager = gpm_manager
        self.proxy_manager = proxy_manager
        self.otp_manager = otp_manager
        self.telegram_client = telegram_client
        self.screenshots_dir = screenshots_dir
        self.max_workers = max_workers
        self.check_interval = check_interval
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.running_workers = {}  # account_id -> future
        self.is_running = False
        
        logger.info(f"✅ Đã khởi tạo Orchestrator (max_workers={max_workers}, interval={check_interval}s)")
    
    async def start(self):
        """Bắt đầu scheduler"""
        self.is_running = True
        logger.info("🚀 Orchestrator đã bắt đầu")
        
        try:
            while self.is_running:
                await self._scheduler_loop()
                await asyncio.sleep(self.check_interval)
        except Exception as e:
            logger.error(f"❌ Lỗi trong scheduler loop: {e}", exc_info=True)
        finally:
            logger.info("⏹️ Orchestrator đã dừng")
    
    async def _scheduler_loop(self):
        """
        Vòng lặp scheduler chính
        Chọn pending account + idle profile → spawn worker
        """
        try:
            # Kiểm tra số worker đang chạy
            active_count = len([f for f in self.running_workers.values() if not f.done()])
            
            if active_count >= self.max_workers:
                logger.debug(f"ℹ️ Đã đạt max workers ({self.max_workers}), bỏ qua lần kiểm tra này")
                return
            
            # Lấy 1 account pending
            pending_account = self.db_manager.get_pending()
            if not pending_account:
                logger.debug("ℹ️ Không có account pending")
                return
            
            # Lấy 1 profile idle
            idle_profile = self.db_manager.get_idle_profile()
            if not idle_profile:
                logger.debug("ℹ️ Không có profile idle")
                return
            
            logger.info(
                f"🎯 Phát hiện task: account={pending_account.get('email')} "
                f"(ID: {pending_account.get('_id')}), "
                f"profile={idle_profile.get('profile_id')}"
            )
            
            # Kiểm tra account này đã có worker chưa
            account_id_str = str(pending_account.get("_id"))
            if account_id_str in self.running_workers:
                existing_future = self.running_workers[account_id_str]
                if not existing_future.done():
                    logger.warning(f"⚠️ Account {account_id_str} đã có worker đang chạy")
                    return
            
            # Spawn worker Create Gmail
            await self._spawn_worker(pending_account, idle_profile)
            
        except Exception as e:
            logger.error(f"❌ Lỗi trong scheduler loop: {e}", exc_info=True)
    
    async def _spawn_worker(self, account: Dict[str, Any], profile: Dict[str, Any]):
        """
        Spawn worker để tạo Gmail
        
        Args:
            account: Dict chứa thông tin account
            profile: Dict chứa thông tin profile
        """
        try:
            from bson import ObjectId
            from ..gmail.gmail_register import create_gmail_account
            
            account_id = ObjectId(account["_id"])
            account_id_str = str(account_id)
            
            # Cập nhật status account → "creating"
            self.db_manager.update_status(
                account_id=account_id,
                new_status="creating",
                profile_id=profile.get("profile_id")
            )
            
            # Cập nhật status profile → "in_use"
            self.db_manager.update_profile_status(
                profile_id=profile.get("profile_id"),
                new_status="in_use",
                account_id=account_id
            )
            
            # Submit worker task vào ThreadPoolExecutor
            logger.info(f"🚀 Đang spawn worker cho account: {account.get('email')}")
            
            future = self.executor.submit(
                create_gmail_account,
                account,
                profile,
                self.db_manager,
                self.gpm_manager,
                self.proxy_manager,
                self.otp_manager,
                self.telegram_client,
                self.screenshots_dir
            )
            
            self.running_workers[account_id_str] = future
            
            # Monitor worker khi hoàn thành
            asyncio.create_task(self._monitor_worker(future, account_id_str, account, profile))
            
        except Exception as e:
            logger.error(f"❌ Lỗi spawn worker: {e}", exc_info=True)
            # Rollback status
            try:
                from bson import ObjectId
                self.db_manager.update_status(
                    account_id=ObjectId(account["_id"]),
                    new_status="pending"
                )
                self.db_manager.update_profile_status(
                    profile_id=profile.get("profile_id"),
                    new_status="idle"
                )
            except Exception as rollback_error:
                logger.error(f"❌ Lỗi rollback: {rollback_error}")
    
    async def _monitor_worker(
        self,
        future,
        account_id_str: str,
        account: Dict[str, Any],
        profile: Dict[str, Any]
    ):
        """
        Monitor worker và cleanup khi hoàn thành
        
        Args:
            future: Future từ ProcessPoolExecutor
            account_id_str: String ID của account
            account: Dict chứa thông tin account
            profile: Dict chứa thông tin profile
        """
        try:
            # Đợi worker hoàn thành
            result = await asyncio.get_event_loop().run_in_executor(None, future.result)
            
            logger.info(f"✅ Worker hoàn thành cho account: {account.get('email')}, result: {result}")
            
            # Cleanup
            if account_id_str in self.running_workers:
                del self.running_workers[account_id_str]
            
            # Profile sẽ được giải phóng trong worker khi stop_profile
            
        except Exception as e:
            logger.error(f"❌ Lỗi trong worker: {e}", exc_info=True)
            
            # Cleanup
            if account_id_str in self.running_workers:
                del self.running_workers[account_id_str]
            
            # Rollback profile status
            try:
                self.db_manager.update_profile_status(
                    profile_id=profile.get("profile_id"),
                    new_status="idle"
                )
            except Exception as cleanup_error:
                logger.error(f"❌ Lỗi cleanup profile: {cleanup_error}")
    
    def stop(self):
        """Dừng orchestrator"""
        self.is_running = False
        logger.info("⏹️ Đang dừng Orchestrator...")
        
        # Shutdown executor
        self.executor.shutdown(wait=False)
        logger.info("✅ Đã shutdown ThreadPoolExecutor")

