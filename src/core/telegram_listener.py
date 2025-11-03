"""
Telegram Listener - Telethon monitor messages từ GmailFarmerBot
Parse Register Gmail và Recovery messages
"""
import re
from datetime import datetime
from typing import Optional
from telethon import TelegramClient, events
from telethon.tl.types import Message

from ..db.database_manager import DatabaseManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


class TelegramListener:
    """Lắng nghe và parse messages từ Telegram"""
    
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str,
        gmail_farmer_bot_username: str,
        db_manager: DatabaseManager
    ):
        """
        Khởi tạo TelegramListener
        
        Args:
            api_id: Telegram API ID
            api_hash: Telegram API Hash
            session_name: Tên session file
            gmail_farmer_bot_username: Username của GmailFarmerBot (ví dụ: "GmailFarmerBot")
            db_manager: DatabaseManager instance
        """
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.gmail_farmer_bot_username = gmail_farmer_bot_username
        self.db_manager = db_manager
        
        # Đăng ký event handlers
        self._register_handlers()
        
        logger.info(f"✅ Đã khởi tạo TelegramListener cho bot: {gmail_farmer_bot_username}")
    
    def _register_handlers(self):
        """Đăng ký các event handlers"""
        
        @self.client.on(events.NewMessage(from_users=self.gmail_farmer_bot_username))
        async def handle_new_message(event: events.NewMessage.Event):
            """Xử lý message mới từ GmailFarmerBot"""
            try:
                message: Message = event.message
                message_text = message.message or ""
                
                logger.info(f"📨 Nhận message từ {self.gmail_farmer_bot_username}: {message_text[:100]}")
                
                # Kiểm tra message "Register a new Gmail"
                if "Register a new Gmail" in message_text or "➕ Register" in message_text:
                    await self._handle_register_message(message)
                # Kiểm tra Recovery message (chứa email recovery)
                elif self._is_recovery_message(message_text):
                    await self._handle_recovery_message(message, message_text)
                else:
                    logger.debug(f"ℹ️ Message không khớp pattern: {message_text[:50]}")
                    
            except Exception as e:
                logger.error(f"❌ Lỗi xử lý message: {e}", exc_info=True)
    
    async def _handle_register_message(self, message: Message):
        """
        Xử lý message Register Gmail
        Parse: First Name / Last Name / Email / Password
        """
        try:
            message_text = message.message or ""
            logger.info(f"📝 Parse Register message: {message.message[:200]}")
            
            # Pattern để extract thông tin
            # Format thường: "First Name: ...\nLast Name: ...\nEmail: ...\nPassword: ..."
            patterns = {
                "first_name": r"(?:First Name|Tên):\s*([^\n]+)",
                "last_name": r"(?:Last Name|Họ):\s*([^\n]+)",
                "email": r"Email:\s*([^\n\s@]+@[^\n\s@]+\.[^\n\s@]+)",
                "password": r"Password:\s*([^\n]+)"
            }
            
            extracted = {}
            for key, pattern in patterns.items():
                match = re.search(pattern, message_text, re.IGNORECASE)
                if match:
                    extracted[key] = match.group(1).strip()
                else:
                    logger.warning(f"⚠️ Không tìm thấy {key} trong message")
            
            # Validate đủ thông tin
            required_fields = ["first_name", "last_name", "email", "password"]
            missing = [f for f in required_fields if f not in extracted]
            
            if missing:
                logger.error(f"❌ Thiếu thông tin trong Register message: {missing}")
                return
            
            # Lưu vào database với status="pending"
            account_id = self.db_manager.insert_account(
                email=extracted["email"],
                first_name=extracted["first_name"],
                last_name=extracted["last_name"],
                password=extracted["password"],
                message_id_input=message.id,
                source_chat_id=message.peer_id.channel_id if hasattr(message.peer_id, 'channel_id') else message.chat_id,
                message_ts=datetime.utcnow(),
                status="pending"
            )
            
            if account_id:
                logger.info(f"✅ Đã lưu Register account: {extracted['email']} (ID: {account_id})")
            else:
                logger.error(f"❌ Không thể lưu Register account: {extracted['email']}")
                
        except Exception as e:
            logger.error(f"❌ Lỗi xử lý Register message: {e}", exc_info=True)
    
    def _is_recovery_message(self, message_text: str) -> bool:
        """
        Kiểm tra xem message có phải Recovery message không
        Recovery message thường chứa email recovery
        """
        # Pattern: Email trong message (có thể có format "Recovery: email@example.com" hoặc chỉ có email)
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        
        # Kiểm tra có từ khóa recovery hoặc chỉ có email
        has_recovery_keyword = re.search(
            r'(recovery|phục hồi|khôi phục)', 
            message_text, 
            re.IGNORECASE
        )
        has_email = re.search(email_pattern, message_text)
        
        return bool(has_email and (has_recovery_keyword or len(re.findall(email_pattern, message_text)) == 1))
    
    async def _handle_recovery_message(self, message: Message, message_text: str):
        """
        Xử lý Recovery message
        Parse email recovery và match với account trong DB theo rules.md
        """
        try:
            # Extract email từ message
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            emails = re.findall(email_pattern, message_text)
            
            if not emails:
                logger.warning("⚠️ Recovery message không chứa email")
                return
            
            # Lấy email từ message (có thể là email chính của account hoặc recovery email)
            email_from_message = emails[0].lower().strip()
            logger.info(f"📧 Parse Recovery message, email: {email_from_message}")
            
            # Theo rules.md: Tìm document có status="waiting-recovery" (ưu tiên) và email khớp
            from bson import ObjectId
            
            # Bước 1: Tìm account có status="waiting-recovery" và email khớp
            waiting_recovery_accounts = list(
                self.db_manager.accounts.find({
                    "status": "waiting-recovery",
                    "email": email_from_message
                })
            )
            
            if len(waiting_recovery_accounts) == 1:
                # Có đúng 1 document đang waiting-recovery → gán recovery_email và set recovery-received
                account = waiting_recovery_accounts[0]
                
                # Nếu message chứa recovery email (khác email chính), dùng email từ message
                # Nếu message chứa email chính, cần extract recovery email từ message (có thể ở vị trí khác)
                recovery_email = email_from_message
                if len(emails) > 1:
                    # Nếu có nhiều email, email đầu có thể là email chính, email thứ 2 là recovery
                    recovery_email = emails[1].lower().strip()
                
                success = self.db_manager.update_status(
                    account_id=account["_id"],
                    new_status="recovery-received",
                    recovery_email=recovery_email
                )
                
                if success:
                    logger.info(f"✅ Đã cập nhật Recovery cho account: {account.get('email')} (Recovery: {recovery_email})")
                else:
                    logger.error(f"❌ Không thể cập nhật Recovery cho account: {account.get('email')}")
                    
            elif len(waiting_recovery_accounts) > 1:
                # Có >1 document cùng điều kiện → không tự gán → set waiting-observe
                logger.warning(f"⚠️ Có {len(waiting_recovery_accounts)} accounts waiting-recovery với email {email_from_message}, không tự gán")
                for acc in waiting_recovery_accounts:
                    self.db_manager.update_status(
                        account_id=acc["_id"],
                        new_status="waiting-observe",
                        operator_notified_at=datetime.utcnow(),
                        last_error=f"Nhiều accounts cùng email trong recovery message"
                    )
                    
            else:
                # Không có document nào waiting-recovery → tìm document pending gần nhất
                pending_account = self.db_manager.accounts.find_one(
                    {"email": email_from_message, "status": "pending"},
                    sort=[("created_at", -1)]  # Gần nhất
                )
                
                if pending_account:
                    # Tìm thấy pending account → có thể map
                    recovery_email = email_from_message
                    if len(emails) > 1:
                        recovery_email = emails[1].lower().strip()
                    
                    success = self.db_manager.update_status(
                        account_id=pending_account["_id"],
                        new_status="recovery-received",
                        recovery_email=recovery_email
                    )
                    
                    if success:
                        logger.info(f"✅ Đã map Recovery cho pending account: {pending_account.get('email')}")
                    else:
                        logger.error(f"❌ Không thể map Recovery cho pending account")
                else:
                    # Không tìm thấy → set waiting-observe (nhưng không có account_id)
                    logger.warning(f"⚠️ Không tìm thấy account nào với email {email_from_message}")
                    # Không thể update vì không có account_id
                
        except Exception as e:
            logger.error(f"❌ Lỗi xử lý Recovery message: {e}", exc_info=True)
    
    async def start(self):
        """Bắt đầu lắng nghe messages"""
        try:
            await self.client.start()
            logger.info("✅ TelegramListener đã bắt đầu lắng nghe")
            await self.client.run_until_disconnected()
        except Exception as e:
            logger.error(f"❌ Lỗi khởi động TelegramListener: {e}", exc_info=True)
    
    async def stop(self):
        """Dừng lắng nghe messages"""
        try:
            await self.client.disconnect()
            logger.info("✅ TelegramListener đã dừng")
        except Exception as e:
            logger.error(f"❌ Lỗi dừng TelegramListener: {e}", exc_info=True)

