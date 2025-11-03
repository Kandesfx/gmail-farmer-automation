"""
Telegram Listener - Telethon monitor messages từ GmailFarmerBot
Parse Register Gmail và Recovery messages
"""
import re
from datetime import datetime
from typing import Optional
from telethon import TelegramClient, events
from telethon.tl.types import Message

try:
    from ..db.database_manager import DatabaseManager
    from ..utils.logger import get_logger
except ImportError:
    from db.database_manager import DatabaseManager
    from utils.logger import get_logger

logger = get_logger(__name__)


class TelegramListener:
    """Lắng nghe và parse messages từ Telegram"""
    
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str,
        gmail_farmer_bot_username: str,
        db_manager: DatabaseManager,
        on_rate_limit_callback=None  # Callback khi phát hiện rate limit
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
        self._on_rate_limit_detected = on_rate_limit_callback  # Callback khi rate limit
        
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
                
                # Xử lý message rate limit từ bot
                if "too often" in message_text.lower() or "try again later" in message_text.lower():
                    logger.warning(f"⚠️ Bot trả về rate limit: {message_text[:100]}")
                    # Thông báo rate limit (nếu có callback)
                    if hasattr(self, '_on_rate_limit_detected'):
                        await self._on_rate_limit_detected()
                    return
                
                # Kiểm tra message Register Gmail từ bot (chứa First name, Email, Password)
                # Bot trả về message có format: "First name: ...\nLast name: ...\nEmail: ...\nPassword: ..."
                if self._is_register_message(message_text):
                    await self._handle_register_message(message)
                # Kiểm tra Recovery message (chứa email recovery)
                elif self._is_recovery_message(message_text):
                    await self._handle_recovery_message(message, message_text)
                else:
                    logger.debug(f"ℹ️ Message không khớp pattern: {message_text[:50]}")
                    
            except Exception as e:
                logger.error(f"❌ Lỗi xử lý message: {e}", exc_info=True)
    
    def _is_register_message(self, message_text: str) -> bool:
        """
        Kiểm tra xem message có phải Register message từ bot không
        Register message từ bot chứa: First name, Email, Password
        """
        # Kiểm tra có chứa các từ khóa đặc trưng của Register message
        has_first_name = re.search(r"(?:First\s+name|Firstname):\s*\w+", message_text, re.IGNORECASE)
        has_email = re.search(r"Email:\s*[^\n\s@]+@[^\n\s@]+\.[^\n\s@]+", message_text, re.IGNORECASE)
        has_password = re.search(r"Password:\s*\S+", message_text, re.IGNORECASE)
        
        # Message từ bot cũng có thể chứa "Register a Gmail account" hoặc "Register a new Gmail"
        has_register_keyword = re.search(r"Register.*Gmail", message_text, re.IGNORECASE)
        
        # Có thể có nút "Done", "Cancel registration"
        has_buttons = "Done" in message_text or "Cancel" in message_text
        
        # Nếu có đủ First name + Email + Password thì là Register message
        # Hoặc có Register keyword + Email
        return bool((has_first_name and has_email and has_password) or 
                   (has_register_keyword and has_email and has_buttons))
    
    async def _handle_register_message(self, message: Message):
        """
        Xử lý message Register Gmail từ bot
        Parse: First name / Last name / Email / Password
        Format từ bot: "First name: ...\nLast name: ...\nEmail: ...\nPassword: ..."
        """
        try:
            message_text = message.message or ""
            logger.info(f"📝 Parse Register message: {message.message[:200]}")
            
            # Pattern để extract thông tin theo format từ bot
            # Format từ bot: "First name: Dylan\nLast name: ✖️\nEmail: ziguvotix38@gmail.com\nPassword: PNEZ0mt0zixm"
            patterns = {
                "first_name": r"(?:First\s+name|Firstname|Tên):\s*([^\n\r]+)",
                "last_name": r"(?:Last\s+name|Lastname|Họ):\s*([^\n\r]+)",
                "email": r"Email:\s*([^\n\r\s@]+@[^\n\r\s@]+\.[^\n\r\s@]+)",
                "password": r"Password:\s*([^\n\r]+)"
            }
            
            extracted = {}
            for key, pattern in patterns.items():
                match = re.search(pattern, message_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip()
                    # Xử lý đặc biệt cho last_name: nếu là "✖️" hoặc emoji tương tự → chuyển thành "X"
                    if key == "last_name" and value in ["✖️", "✖", "❌", "×", "x", "X", ""]:
                        value = "X"
                    extracted[key] = value
                else:
                    logger.warning(f"⚠️ Không tìm thấy {key} trong message")
            
            # Validate đủ thông tin (first_name, email, password là bắt buộc; last_name có thể rỗng hoặc "X")
            required_fields = ["first_name", "email", "password"]
            missing = [f for f in required_fields if f not in extracted]
            
            if missing:
                logger.error(f"❌ Thiếu thông tin trong Register message: {missing}")
                logger.debug(f"Message content: {message_text}")
                return
            
            # Last name có thể không có hoặc là "X", set mặc định nếu thiếu
            if "last_name" not in extracted or not extracted["last_name"] or extracted["last_name"].strip() in ["✖️", "✖", "❌", "×", ""]:
                extracted["last_name"] = "X"
            
            # Lấy chat_id đúng cách (từ message.chat_id hoặc peer_id)
            try:
                if hasattr(message, 'peer_id'):
                    if hasattr(message.peer_id, 'channel_id'):
                        chat_id = message.peer_id.channel_id
                    elif hasattr(message.peer_id, 'user_id'):
                        chat_id = message.peer_id.user_id
                    else:
                        chat_id = getattr(message, 'chat_id', None)
                else:
                    chat_id = getattr(message, 'chat_id', None)
                
                if chat_id is None:
                    logger.warning("⚠️ Không thể lấy chat_id, sử dụng message.id làm fallback")
                    chat_id = message.id
            except Exception as e:
                logger.warning(f"⚠️ Lỗi khi lấy chat_id: {e}, sử dụng message.id")
                chat_id = message.id
            
            # Lưu vào database với status="pending"
            account_id = self.db_manager.insert_account(
                email=extracted["email"],
                first_name=extracted["first_name"],
                last_name=extracted.get("last_name", "X"),
                password=extracted["password"],
                message_id_input=message.id,
                source_chat_id=chat_id,
                message_ts=datetime.utcnow(),
                status="pending"
            )
            
            if account_id:
                logger.info(f"✅ Đã lưu Register account: {extracted['email']} (ID: {account_id}, First: {extracted['first_name']}, Last: {extracted.get('last_name', 'X')})")
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
            # Kiểm tra xem đã có session chưa bằng cách thử connect trước
            # Nếu connect thành công và đã authorized thì không cần đăng nhập
            if not self.client.is_connected():
                try:
                    await self.client.connect()
                    # Kiểm tra xem đã authorized chưa
                    if await self.client.is_user_authorized():
                        logger.info("✅ Đã kết nối với session listener hiện có (không cần đăng nhập)")
                    else:
                        logger.warning("⚠️ Session listener không hợp lệ hoặc chưa authorized, cần đăng nhập lại...")
                        await self.client.start()
                except Exception as connect_error:
                    logger.info(f"📝 Chưa có session hoặc session lỗi, tạo mới... ({connect_error})")
                    await self.client.start()
            else:
                # Đã connected, kiểm tra authorized
                if await self.client.is_user_authorized():
                    logger.info("✅ Client listener đã được kết nối và authorized")
                else:
                    logger.warning("⚠️ Client đã connect nhưng chưa authorized, cần đăng nhập...")
                    await self.client.start()
            
            logger.info("✅ TelegramListener đã bắt đầu lắng nghe")
            
            # Sử dụng loop để có thể kiểm tra flag dừng
            try:
                await self.client.run_until_disconnected()
            except (asyncio.CancelledError, KeyboardInterrupt):
                logger.info("⚠️ TelegramListener nhận tín hiệu dừng")
                raise
        except asyncio.CancelledError:
            logger.info("⏹️ TelegramListener đã bị cancel")
        except KeyboardInterrupt:
            logger.info("⚠️ TelegramListener nhận KeyboardInterrupt")
        except Exception as e:
            logger.error(f"❌ Lỗi khởi động TelegramListener: {e}", exc_info=True)
    
    async def send_register_message(self) -> tuple[bool, Optional[str]]:
        """
        Gửi tin nhắn "➕ Register a new Gmail" cho @GmailFarmerBot
        
        Returns:
            Tuple (success: bool, error_message: Optional[str])
            - success: True nếu gửi thành công, False nếu lỗi
            - error_message: Thông báo lỗi (nếu có), hoặc None nếu thành công
        """
        try:
            # Đảm bảo client đã được start
            if not self.client.is_connected():
                await self.client.connect()
                # Kiểm tra xem đã authorized chưa
                if not await self.client.is_user_authorized():
                    await self.client.start()
            
            # Gửi tin nhắn cho bot
            sent_message = await self.client.send_message(
                self.gmail_farmer_bot_username,
                "➕ Register a new Gmail"
            )
            
            logger.info(f"✅ Đã gửi tin nhắn '➕ Register a new Gmail' cho {self.gmail_farmer_bot_username}")
            return True, None
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Lỗi gửi tin nhắn Register cho bot: {e}", exc_info=True)
            return False, error_msg
    
    async def stop(self):
        """Dừng lắng nghe messages"""
        try:
            if self.client.is_connected():
                await self.client.disconnect()
            logger.info("✅ TelegramListener đã dừng")
        except Exception as e:
            logger.error(f"❌ Lỗi dừng TelegramListener: {e}", exc_info=True)

