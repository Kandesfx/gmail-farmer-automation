"""
Database Manager - Quản lý MongoDB cho Account và Profile
"""
from datetime import datetime
from typing import Optional, Dict, Any
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from bson import ObjectId

try:
    from ..utils.logger import get_logger
except ImportError:
    from utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Quản lý kết nối và thao tác MongoDB cho Account và Profile"""
    
    def __init__(self, mongo_uri: str, db_name: str = "gmail_farm"):
        """
        Khởi tạo DatabaseManager
        
        Args:
            mongo_uri: MongoDB connection string
            db_name: Tên database (mặc định: gmail_farm)
        """
        try:
            self.client = MongoClient(mongo_uri)
            self.db = self.client[db_name]
            self.accounts: Collection = self.db.accounts
            self.profiles: Collection = self.db.profiles
            
            # Tạo index cho email (case-insensitive search)
            self.accounts.create_index([("email", pymongo.ASCENDING)], unique=True)
            self.accounts.create_index([("status", pymongo.ASCENDING)])
            self.profiles.create_index([("status", pymongo.ASCENDING)])
            self.profiles.create_index([("profile_id", pymongo.ASCENDING)], unique=True)
            
            logger.info(f"✅ Kết nối MongoDB thành công: {db_name}")
        except Exception as e:
            logger.error(f"❌ Lỗi kết nối MongoDB: {e}")
            raise
    
    def insert_account(
        self,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        message_id_input: int,
        source_chat_id: int,
        message_ts: Optional[datetime] = None,
        status: str = "pending"
    ) -> Optional[ObjectId]:
        """
        Thêm account mới vào database
        
        Args:
            email: Email (sẽ được chuẩn hóa lowercase)
            first_name: First name
            last_name: Last name
            password: Password
            message_id_input: Message ID từ Telegram
            source_chat_id: Chat ID nơi message được gửi
            message_ts: Timestamp của message (mặc định: now)
            status: Trạng thái ban đầu (mặc định: "pending")
            
        Returns:
            ObjectId của account được tạo, hoặc None nếu lỗi
        """
        try:
            # Chuẩn hóa email (lowercase)
            email_normalized = email.lower().strip()
            
            # Kiểm tra email đã tồn tại chưa
            existing = self.accounts.find_one({"email": email_normalized})
            if existing:
                logger.warning(f"⚠️ Email đã tồn tại: {email_normalized}")
                return existing.get("_id")
            
            account_doc = {
                "email": email_normalized,
                "first_name": first_name,
                "last_name": last_name,
                "password": password,
                "status": status,
                "message_id_input": message_id_input,
                "message_chat_id": source_chat_id,
                "source_chat_id": source_chat_id,  # Alias cho backward compatibility
                "message_ts": message_ts or datetime.utcnow(),
                "recovery_email": None,
                "profile_id": None,
                "operator_notified_at": None,
                "last_error": None,
                "screenshot_path": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            result = self.accounts.insert_one(account_doc)
            logger.info(f"✅ Đã thêm account: {email_normalized} (ID: {result.inserted_id})")
            return result.inserted_id
            
        except pymongo.errors.DuplicateKeyError:
            logger.error(f"❌ Email trùng lặp: {email}")
            return None
        except Exception as e:
            logger.error(f"❌ Lỗi insert account {email}: {e}")
            return None
    
    def update_status(
        self,
        account_id: ObjectId,
        new_status: Optional[str] = None,
        recovery_email: Optional[str] = None,
        last_error: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        profile_id: Optional[str] = None,
        operator_notified_at: Optional[datetime] = None
    ) -> bool:
        """
        Cập nhật trạng thái account
        
        Args:
            account_id: ObjectId của account
            new_status: Trạng thái mới (pending, creating, waiting-recovery, ...) - có thể None nếu chỉ update field khác
            recovery_email: Recovery email (nếu có)
            last_error: Lỗi cuối cùng (nếu có)
            screenshot_path: Đường dẫn screenshot (nếu có)
            profile_id: ID của profile đang sử dụng (nếu có)
            operator_notified_at: Thời gian thông báo operator (nếu có)
            
        Returns:
            True nếu cập nhật thành công, False nếu lỗi
        """
        try:
            update_data = {
                "updated_at": datetime.utcnow()
            }
            
            # Validate và set status nếu có
            if new_status is not None:
                valid_statuses = [
                    "pending", "creating", "waiting-recovery", "recovery-received",
                    "waiting-complete", "waiting-observe", "created",
                    "failed-phone", "failed-captcha", "failed", "error"
                ]
                if new_status not in valid_statuses:
                    logger.error(f"❌ Trạng thái không hợp lệ: {new_status}")
                    return False
                update_data["status"] = new_status
            
            if recovery_email is not None:
                update_data["recovery_email"] = recovery_email.lower().strip() if recovery_email else None
            if last_error is not None:
                update_data["last_error"] = last_error
            if screenshot_path is not None:
                update_data["screenshot_path"] = screenshot_path
            if profile_id is not None:
                update_data["profile_id"] = profile_id
            if operator_notified_at is not None:
                update_data["operator_notified_at"] = operator_notified_at
            
            result = self.accounts.update_one(
                {"_id": account_id},
                {"$set": update_data}
            )
            
            if result.modified_count > 0:
                status_str = new_status or "các trường khác"
                logger.info(f"✅ Đã cập nhật account {account_id}: {status_str}")
                return True
            else:
                logger.warning(f"⚠️ Không tìm thấy account {account_id} để cập nhật")
                return False
                
        except Exception as e:
            logger.error(f"❌ Lỗi update_status account {account_id}: {e}")
            return False
    
    def get_pending(self) -> Optional[Dict[str, Any]]:
        """
        Lấy 1 account có thể xử lý (status != "created" và không đang được xử lý)
        Lấy cả pending, failed, error, v.v. để retry lại
        
        Returns:
            Dict chứa thông tin account, hoặc None nếu không có
        """
        try:
            # Các status cần loại trừ (created + các status đang xử lý)
            excluded_statuses = [
                "created",  # Đã hoàn thành - không lấy
                "creating",  # Đang được xử lý
                "waiting-recovery",  # Đang đợi recovery
                "recovery-received",  # Đã nhận recovery
                "waiting-complete",  # Đang đợi complete
                "waiting-observe"  # Đang đợi operator can thiệp
            ]
            
            # Query: status không nằm trong danh sách loại trừ
            # → Lấy: pending, failed, failed-phone, failed-captcha, error
            query = {
                "status": {"$nin": excluded_statuses}
            }
            
            account = self.accounts.find_one(
                query,
                sort=[("created_at", pymongo.ASCENDING)]  # FIFO - lấy account cũ nhất
            )
            
            if account:
                account["_id"] = str(account["_id"])  # Convert ObjectId to string cho dễ xử lý
                logger.info(f"✅ Tìm thấy account để xử lý: {account.get('email')} (status={account.get('status')})")
                return account
            else:
                logger.debug("ℹ️ Không có account nào để xử lý (tất cả đã created hoặc đang xử lý)")
                return None
                
        except Exception as e:
            logger.error(f"❌ Lỗi get_pending: {e}")
            return None
    
    def count_pending_accounts(self) -> int:
        """
        Đếm số lượng accounts có thể xử lý (status != "created" và không đang được xử lý)
        Tương tự logic trong get_pending()
        
        Returns:
            Số lượng accounts có thể xử lý
        """
        try:
            # Các status cần loại trừ (created + các status đang xử lý)
            excluded_statuses = [
                "created",  # Đã hoàn thành - không đếm
                "creating",  # Đang được xử lý
                "waiting-recovery",  # Đang đợi recovery
                "recovery-received",  # Đã nhận recovery
                "waiting-complete",  # Đang đợi complete
                "waiting-observe"  # Đang đợi operator can thiệp
            ]
            
            # Query: status không nằm trong danh sách loại trừ
            # → Đếm: pending, failed, failed-phone, failed-captcha, error
            query = {
                "status": {"$nin": excluded_statuses}
            }
            
            count = self.accounts.count_documents(query)
            return count
        except Exception as e:
            logger.error(f"❌ Lỗi count_pending_accounts: {e}")
            return 0
    
    def count_creating_accounts(self) -> int:
        """
        Đếm số lượng accounts đang được xử lý (status="creating")
        
        Returns:
            Số lượng accounts đang creating
        """
        try:
            count = self.accounts.count_documents({"status": "creating"})
            return count
        except Exception as e:
            logger.error(f"❌ Lỗi count_creating_accounts: {e}")
            return 0
    
    def count_available_accounts(self) -> int:
        """
        Đếm số lượng accounts sẵn sàng để xử lý (pending + creating)
        Dùng để kiểm tra xem có cần gửi Register messages không
        
        Returns:
            Tổng số accounts pending + creating
        """
        try:
            pending = self.count_pending_accounts()
            creating = self.count_creating_accounts()
            return pending + creating
        except Exception as e:
            logger.error(f"❌ Lỗi count_available_accounts: {e}")
            return 0
    
    def get_idle_profile(self) -> Optional[Dict[str, Any]]:
        """
        Lấy 1 profile có status="idle"
        
        Returns:
            Dict chứa thông tin profile, hoặc None nếu không có
        """
        try:
            profile = self.profiles.find_one(
                {"status": "idle"}
            )
            
            if profile:
                profile["_id"] = str(profile["_id"])
                logger.info(f"✅ Tìm thấy idle profile: {profile.get('profile_id')}")
                return profile
            else:
                logger.debug("ℹ️ Không có profile idle nào")
                return None
                
        except Exception as e:
            logger.error(f"❌ Lỗi get_idle_profile: {e}")
            return None
    
    def find_account_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Tìm account theo email (case-insensitive)
        
        Args:
            email: Email cần tìm (sẽ được chuẩn hóa)
            
        Returns:
            Dict chứa thông tin account, hoặc None nếu không tìm thấy
        """
        try:
            email_normalized = email.lower().strip()
            account = self.accounts.find_one({"email": email_normalized})
            
            if account:
                account["_id"] = str(account["_id"])
                logger.info(f"✅ Tìm thấy account theo email: {email_normalized}")
                return account
            else:
                logger.debug(f"ℹ️ Không tìm thấy account với email: {email_normalized}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Lỗi find_account_by_email {email}: {e}")
            return None
    
    def update_profile_status(
        self,
        profile_id: str,
        new_status: str,
        account_id: Optional[ObjectId] = None,
        debug_port: Optional[int] = None
    ) -> bool:
        """
        Cập nhật trạng thái profile
        
        Args:
            profile_id: ID của profile
            new_status: Trạng thái mới (idle, in_use, stopped, ...)
            account_id: ID của account đang sử dụng profile (nếu có)
            debug_port: Debug port (nếu có)
            
        Returns:
            True nếu cập nhật thành công, False nếu lỗi
        """
        try:
            update_data = {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
            
            if account_id is not None:
                update_data["account_id"] = account_id
            if debug_port is not None:
                update_data["debug_port"] = debug_port
            
            result = self.profiles.update_one(
                {"profile_id": profile_id},
                {"$set": update_data}
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Đã cập nhật status profile {profile_id}: {new_status}")
                return True
            else:
                logger.warning(f"⚠️ Không tìm thấy profile {profile_id} để cập nhật")
                return False
                
        except Exception as e:
            logger.error(f"❌ Lỗi update_profile_status {profile_id}: {e}")
            return False
    
    def sync_profiles_from_gpm(self, gpm_profiles: list) -> int:
        """
        Đồng bộ profiles từ GPM API vào MongoDB
        Insert profiles mới và update profiles đã tồn tại (không override status nếu đang in_use)
        
        Args:
            gpm_profiles: List các profiles từ GPM API (từ get_profile_list)
            
        Returns:
            Số lượng profiles đã được sync
        """
        if not gpm_profiles:
            logger.warning("⚠️ Không có profiles từ GPM để sync")
            return 0
        
        synced_count = 0
        try:
            for gpm_profile in gpm_profiles:
                try:
                    # GPM API trả về "id" nhưng MongoDB dùng "profile_id"
                    profile_id = gpm_profile.get("id") or gpm_profile.get("profile_id")
                    if not profile_id:
                        logger.warning(f"⚠️ Profile không có ID, bỏ qua: {gpm_profile}")
                        continue
                    
                    # Kiểm tra profile đã tồn tại chưa
                    existing = self.profiles.find_one({"profile_id": profile_id})
                    
                    if existing:
                        # Profile đã tồn tại - chỉ update metadata, không đổi status nếu đang in_use
                        update_data = {
                            "name": gpm_profile.get("name", existing.get("name")),
                            "browser_type": gpm_profile.get("browser_type"),
                            "browser_version": gpm_profile.get("browser_version"),
                            "group_id": gpm_profile.get("group_id"),
                            "profile_path": gpm_profile.get("profile_path"),
                            "note": gpm_profile.get("note"),
                            "updated_at": datetime.utcnow()
                        }
                        
                        # Chỉ update status nếu profile không đang được sử dụng (idle hoặc stopped)
                        current_status = existing.get("status")
                        if current_status not in ["in_use", "creating", "waiting-recovery"]:
                            # Nếu profile đang idle hoặc stopped, có thể reset về idle
                            update_data["status"] = "idle"
                            update_data["account_id"] = None  # Xóa account_id nếu reset về idle
                        
                        self.profiles.update_one(
                            {"profile_id": profile_id},
                            {"$set": update_data}
                        )
                        synced_count += 1
                    else:
                        # Profile mới - insert vào MongoDB với status="idle"
                        profile_doc = {
                            "profile_id": profile_id,
                            "name": gpm_profile.get("name", f"Profile {profile_id[:8]}"),
                            "status": "idle",  # Mặc định idle
                            "browser_type": gpm_profile.get("browser_type", "chromium"),
                            "browser_version": gpm_profile.get("browser_version"),
                            "group_id": gpm_profile.get("group_id"),
                            "profile_path": gpm_profile.get("profile_path"),
                            "note": gpm_profile.get("note", ""),
                            "account_id": None,
                            "debug_port": None,
                            "created_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow()
                        }
                        
                        self.profiles.insert_one(profile_doc)
                        synced_count += 1
                        logger.info(f"✅ Đã thêm profile mới: {profile_id} ({profile_doc.get('name')})")
                        
                except Exception as e:
                    logger.error(f"❌ Lỗi sync profile {gpm_profile.get('id')}: {e}")
                    continue
            
            logger.info(f"✅ Đã sync {synced_count}/{len(gpm_profiles)} profiles từ GPM vào MongoDB")
            return synced_count
            
        except Exception as e:
            logger.error(f"❌ Lỗi sync profiles từ GPM: {e}", exc_info=True)
            return synced_count
    
    def close(self):
        """Đóng kết nối MongoDB"""
        try:
            self.client.close()
            logger.info("✅ Đã đóng kết nối MongoDB")
        except Exception as e:
            logger.error(f"❌ Lỗi đóng kết nối MongoDB: {e}")

