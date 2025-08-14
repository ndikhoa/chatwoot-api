#!/home/omni_channel/service_api_webhook/.venv/bin/python
# -*- coding: utf-8 -*-

import os
import sys
import json
import logging
import threading
from typing import Optional

from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import traceback
import time
import requests
import hashlib

# Tạo folder Logs nếu chưa có
logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Logs')
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Cấu hình logging theo ngày
current_date = datetime.now().strftime('%Y_%m_%d')
log_filename = os.path.join(logs_dir, f'log_{current_date}.txt')

# Xóa cấu hình logging cũ nếu có
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Cấu hình logging mới với đường dẫn tuyệt đối
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)

logger = logging.getLogger(__name__)

# Test logging để đảm bảo hoạt động
logger.info("=== LOGGING SYSTEM INITIALIZED ===")
logger.info(f"Log file: {log_filename}")
logger.info(f"Current working directory: {os.getcwd()}")

class OmnichannelService:
    def __init__(self):
        """Khởi tạo service omnichannel"""
        logger.info("=== STARTING OmnichannelService initialization ===")
        self.config = self.load_config()
        self.app = Flask(__name__)
        # thêm storage cho mapping ticket và conversation
        self.ticket_to_conversation = {} # ticket_id -> conversation_id 
        self.conversation_to_ticket = {} # conversation_id -> ticket_id 
        self.processed_webhooks = {} # webhook_id -> timestamp

        CORS(self.app)  # Cho phép tất cả CORS connections
        self.setup_routes()
        logger.info("=== OmnichannelService initialized successfully ===")
    
    def load_config(self):
        """Load cấu hình từ file config.json"""
        logger.info("Loading configuration from config.json")
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info("Configuration loaded successfully")
            logger.info(f"Database config: {config.get('database', {})}")
            logger.info(f"API config: {config.get('api', {})}")
            return config
        except Exception as e:
            logger.error(f"Error loading config: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
     
    # def process_zalo_webhook_async(self, data):
    #     """Xử lý Zalo webhook data trong background thread"""
    #     try:
    #         logger.info(f"=== BACKGROUND PROCESSING ZALO WEBHOOK ===")
    #         logger.info(f"Processing Zalo webhook")
    #         logger.info(f"Zalo webhook data: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
    #         # Tạo timestamp cho log
    #         timestamp = datetime.now().isoformat()
            
    #         # Tạo log entry
    #         log_entry = {
    #             'timestamp': timestamp,
    #             'webhook_type': 'zalo',
    #             'data': data
    #         }
            
    #         # Ghi log chi tiết cho Zalo
    #         logger.info(f"=== LOGGING ZALO WEBHOOK DATA ===")
    #         logger.info(f"Input data: {data}")
    #         logger.info(f"Zalo webhook logged successfully at: {timestamp}")
            
    #         # Logic xử lý riêng cho Zalo
    #         # Có thể thêm xử lý đặc biệt cho Zalo ở đây
    #         logger.info("Processing Zalo specific logic...")
            
    #         logger.info(f"=== FINISHED PROCESSING ZALO WEBHOOK ===")
            
    #     except Exception as e:
    #         logger.error(f"Error in background processing Zalo webhook: {str(e)}")
    #         logger.error(f"Traceback: {traceback.format_exc()}")

    def process_zendesk_webhook_async(self, data):
        """Xử lý Zendesk webhook data - đơn giản hóa logic"""
        try:
            logger.info(f"=== PROCESSING ZENDESK WEBHOOK ===")
            logger.info(f"Zendesk webhook data: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            # 1. Kiểm tra và trích xuất dữ liệu cơ bản
            ticket_id = self.extract_ticket_id(data)
            comment = self.extract_comment(data)
            requester_info = self.extract_requester_info(data)
            
            logger.info(f"Ticket ID: {ticket_id}")
            logger.info(f"Comment: {comment}")
            logger.info(f"Requester: {requester_info}")
            
            # 2. Kiểm tra điều kiện xử lý
            if not ticket_id:
                logger.warning("Missing ticket_id - skipping")
                return
                
            if not comment:
                logger.info("No comment found - skipping")
                return
            
            # 3. Kiểm tra tránh vòng lặp (tin nhắn từ Chatwoot)
            if self.is_from_chatwoot(data):
                logger.info("Message from Chatwoot - skipping to avoid loop")
                return
            
            # 4. Xử lý tin nhắn từ Zendesk -> Chatwoot
            logger.info(f"Processing Zendesk -> Chatwoot: ticket={ticket_id}")
            
            # Tạo contact và conversation
            contact_id = self.create_or_find_contact(requester_info, ticket_id)
            if not contact_id:
                logger.error("Failed to create/find contact")
                return
                
            conversation_id = self.create_or_find_conversation(contact_id, ticket_id)
            if not conversation_id:
                logger.error("Failed to create/find conversation")
                return
            
            # Gửi tin nhắn đến Chatwoot
            success = self.send_chatwoot_message(conversation_id, comment, "incoming")
            
            if success:
                logger.info(f"✅ Success: Zendesk ticket {ticket_id} -> Chatwoot conversation {conversation_id}")
            else:
                logger.error(f"❌ Failed: Zendesk ticket {ticket_id} -> Chatwoot")
            
        except Exception as e:
            logger.error(f"Error processing Zendesk webhook: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    def extract_ticket_id(self, data):
        """Trích xuất ticket_id từ webhook data"""
        # Thứ tự ưu tiên: ticket_id > detail.id > subject
        if data.get("ticket_id"):
            return str(data.get("ticket_id"))
        elif data.get("detail", {}).get("id"):
            return str(data.get("detail", {}).get("id"))
        elif data.get("subject", "").startswith("zen:ticket:"):
            return data.get("subject", "").split(":")[-1]
        return None

    def extract_comment(self, data):
        """Trích xuất comment từ webhook data"""
        # Thứ tự ưu tiên: latest_comment > event.comment.body
        if data.get("latest_comment"):
            return data.get("latest_comment", "").strip()
        elif data.get("event", {}).get("comment", {}).get("body"):
            return data.get("event", {}).get("comment", {}).get("body", "").strip()
        return ""

    def extract_requester_info(self, data):
        """Trích xuất thông tin requester"""
        # Thứ tự ưu tiên: event.comment.author > requester > detail.requester_id
        if data.get("event", {}).get("comment", {}).get("author"):
            author = data.get("event", {}).get("comment", {}).get("author", {})
            return {
                "id": str(author.get("id", "")),
                "name": author.get("name", f"User {author.get('id', '')}")
            }
        elif data.get("requester"):
            requester = data.get("requester", {})
            return {
                "id": str(requester.get("id", "")),
                "name": requester.get("name", f"User {requester.get('id', '')}")
            }
        elif data.get("detail", {}).get("requester_id"):
            requester_id = str(data.get("detail", {}).get("requester_id", ""))
            return {
                "id": requester_id,
                "name": f"User {requester_id}"
            }
        return {"id": "unknown", "name": "Unknown User"}

    def is_from_chatwoot(self, data):
        """Kiểm tra xem webhook có phải từ Chatwoot không"""
        # Kiểm tra tags có chứa from_chatwoot
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        
        # Kiểm tra các tag để tránh vòng lặp
        loop_prevention_tags = ["from_chatwoot", "api_integration", "no_webhook"]
        has_loop_tag = any(tag in tags for tag in loop_prevention_tags)
        
        # Kiểm tra author có phải là staff không
        author = data.get("event", {}).get("comment", {}).get("author", {})
        is_staff = author.get("is_staff", False)
        
        # Kiểm tra direction
        direction = data.get("direction", "")
        
        # Trả về True nếu có tag tránh vòng lặp hoặc là staff comment
        return has_loop_tag or is_staff or direction == "outbound_api"

    def create_or_find_contact(self, requester_info, ticket_id):
        """Tạo hoặc tìm contact trong Chatwoot"""
        try:
            identifier = f"zendesk:{requester_info['id']}:{ticket_id}"
            name = requester_info['name']
            
            # Tìm contact hiện có
            result = self.make_chatwoot_request("GET", f"contacts/search?q={identifier}")
            if result and result.get("payload"):
                contact_id = result["payload"][0]["id"]
                logger.info(f"Found existing contact: {identifier} -> {contact_id}")
                return contact_id
            
            # Tạo contact mới
            contact_data = {"identifier": identifier, "name": name}
            result = self.make_chatwoot_request("POST", "contacts", contact_data)
            
            if result:
                contact_id = self.extract_id_from_response(result)
                logger.info(f"Created new contact: {identifier} -> {contact_id}")
                return contact_id
            
            return None
        except Exception as e:
            logger.error(f"Error creating/finding contact: {str(e)}")
            return None

    def create_or_find_conversation(self, contact_id, ticket_id):
        """Tạo hoặc tìm conversation trong Chatwoot"""
        try:
            # Kiểm tra cache trước
            if ticket_id in self.ticket_to_conversation:
                conv_id = self.ticket_to_conversation[ticket_id]
                logger.info(f"Found conversation in cache: {ticket_id} -> {conv_id}")
                return conv_id
            
            chatwoot_config = self.config.get('chatwoot', {})
            inbox_id = chatwoot_config.get('inbox_id', '')
            
            if not inbox_id:
                logger.error("Chatwoot inbox_id not configured")
                return None
            
            # Tìm conversation hiện có
            result = self.make_chatwoot_request("GET", f"conversations?inbox_id={inbox_id}&source_id={ticket_id}")
            if result and isinstance(result, dict) and result.get("data", {}).get("payload"):
                conversations = result["data"]["payload"]
                if conversations:
                    conv_id = conversations[0].get("id")
                    if conv_id:
                        self.update_conversation_cache(ticket_id, conv_id)
                        logger.info(f"Found existing conversation: {ticket_id} -> {conv_id}")
                        return conv_id
            
            # Tạo conversation mới
            conv_data = {
                "source_id": ticket_id,
                "inbox_id": int(inbox_id),
                "contact_id": contact_id,
                "custom_attributes": {"ticket_id": ticket_id}
            }
            
            result = self.make_chatwoot_request("POST", "conversations", conv_data)
            if result:
                conv_id = self.extract_id_from_response(result)
                if conv_id:
                    self.update_conversation_cache(ticket_id, conv_id)
                    logger.info(f"Created conversation: {ticket_id} -> {conv_id}")
                    return conv_id
            
            return None
        except Exception as e:
            logger.error(f"Error creating/finding conversation: {str(e)}")
            return None

    def extract_id_from_response(self, response):
        """Trích xuất ID từ response của Chatwoot API"""
        if isinstance(response, dict):
            # Thử các cấu trúc response khác nhau
            for key in ["id", "payload", "conversation", "contact"]:
                if key in response:
                    if isinstance(response[key], dict) and "id" in response[key]:
                        return response[key]["id"]
                    elif key == "id":
                        return response[key]
            
            # Thử cấu trúc data
            if "data" in response:
                data = response["data"]
                if isinstance(data, dict) and "id" in data:
                    return data["id"]
                elif isinstance(data, list) and len(data) > 0 and "id" in data[0]:
                    return data[0]["id"]
        
        return None

    def update_conversation_cache(self, ticket_id, conversation_id):
        """Cập nhật cache mapping"""
        self.ticket_to_conversation[ticket_id] = conversation_id
        self.conversation_to_ticket[conversation_id] = ticket_id

    def clean_zendesk_comment(self, comment: str) -> str:
        """Clean up Zendesk comment format by removing separator lines and formatting"""
        try:
            if not comment:
                return ""
            
            # Handle escaped newlines first (from JSON)
            comment = comment.replace('\\n', '\n')
            
            # Split by lines
            lines = comment.split('\n')
            cleaned_lines = []
            
            for line in lines:
                line = line.strip()
                # Skip separator lines (dashes, underscores, etc.)
                if (line.startswith('-') and line.endswith('-') and len(line) > 10) or \
                   line.startswith('----------------------------------------------') or \
                   line.startswith('==============================================') or \
                   line.startswith('______________________________________________') or \
                   line == '':
                    continue
                
                # Skip lines that contain agent name and timestamp (from Zendesk reply format)
                if any(pattern in line for pattern in [
                    'Keith  Nguyen, Aug 13, 2025, 16:41',
                    'Support, Aug 13, 2025, 16:41',
                    'Agent, Aug 13, 2025, 16:41'
                ]):
                    continue
                
                cleaned_lines.append(line)
            
            # Join lines and clean up extra whitespace
            cleaned_comment = '\n'.join(cleaned_lines).strip()
            
            # Remove multiple consecutive newlines
            while '\n\n\n' in cleaned_comment:
                cleaned_comment = cleaned_comment.replace('\n\n\n', '\n\n')
            
            return cleaned_comment
            
        except Exception as e:
            logger.error(f"Error cleaning Zendesk comment: {str(e)}")
            return comment  # Return original if cleaning fails



    def make_chatwoot_request(self, method: str, endpoint: str, data: dict = None) -> Optional[dict]:
        """Make authenticated request to Chatwoot API"""
        try:
            chatwoot_config = self.config.get('chatwoot', {})
            base_url = chatwoot_config.get('base_url', '').rstrip("/")
            account_id = chatwoot_config.get('account_id', '')
            api_token = chatwoot_config.get('api_token', '')
            
            if not all([base_url, account_id, api_token]):
                logger.error("Chatwoot config incomplete")
                return None
            
            url = f"{base_url}/api/v1/accounts/{account_id}/{endpoint}"
            headers = {
                "Content-Type": "application/json",
                "api_access_token": api_token
            }
            
            # Thêm timeout ngắn hơn để tránh blocking
            timeout = 15  # Giảm từ 30s xuống 15s
            
            logger.info(f"Making Chatwoot request: {method} {url}")
            if data:
                logger.info(f"Request data: {json.dumps(data, ensure_ascii=False)}")
            
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=timeout)
            else:
                response = requests.post(url, json=data, headers=headers, timeout=timeout)
            
            if response.ok:
                result = response.json()
                logger.info(f"Chatwoot API success: {method} {endpoint}")
                logger.info(f"Response structure: {json.dumps(result, ensure_ascii=False, indent=2)}")
                return result
            else:
                logger.error(f"Chatwoot API error: {method} {endpoint} - {response.status_code} - {response.text[:200]}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"Chatwoot request timeout: {method} {endpoint}")
            return None
        except Exception as e:
            logger.error(f"Chatwoot request failed: {method} {endpoint} - {str(e)}")
            return None



    def send_chatwoot_message(self, conversation_id: int, content: str, message_type: str = "incoming") -> bool:
        """Send message to Chatwoot conversation"""
        try:
            message_data = {
                "content": content,
                "message_type": message_type
            }
            
            result = self.make_chatwoot_request("POST", f"conversations/{conversation_id}/messages", message_data)
            success = result is not None
            logger.info(f"Sent message to Chatwoot: conv={conversation_id}, success={success}")
            return success
        except Exception as e:
            logger.error(f"Error sending Chatwoot message: {str(e)}")
            return False

    def send_zendesk_comment_with_tags(self, ticket_id: str, content: str) -> bool:
        """Add comment to Zendesk ticket with specific tags to avoid webhook loops"""
        try:
            zendesk_config = self.config.get('zendesk', {})
            subdomain = zendesk_config.get('subdomain', '')
            email = zendesk_config.get('email', '')
            api_token = zendesk_config.get('api_token', '')
            
            if not all([subdomain, email, api_token]):
                logger.error("Zendesk config incomplete")
                return False
            
            url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
            auth = (f"{email}/token", api_token)
            
            payload = {
                "ticket": {
                    "comment": {"body": content, "public": True},
                    "tags": ["from_chatwoot", "api_integration", "no_webhook"]
                }
            }
            
            response = requests.put(url, json=payload, auth=auth, timeout=15)
            success = response.ok
            if not success:
                logger.error(f"Zendesk comment failed: {response.status_code} - {response.text[:200]}")
            else:
                logger.info(f"Added comment to Zendesk ticket: {ticket_id}")
            return success
            
        except Exception as e:
            logger.error(f"Zendesk request error: {str(e)}")
            return False



    def get_ticket_id_from_conversation(self, conversation_id: int) -> Optional[str]:
        """Get ticket_id for a conversation_id"""
        try:
            # Check cache first
            if conversation_id in self.conversation_to_ticket:
                ticket_id = self.conversation_to_ticket[conversation_id]
                logger.info(f"Found ticket in cache: {conversation_id} -> {ticket_id}")
                return ticket_id
            
            # Try to fetch from Chatwoot API
            result = self.make_chatwoot_request("GET", f"conversations/{conversation_id}")
            if result:
                # Try multiple places to find ticket_id
                ticket_id = (
                    result.get("source_id") or
                    (result.get("custom_attributes") or {}).get("ticket_id") or
                    (result.get("additional_attributes") or {}).get("source_id")
                )
                
                if ticket_id:
                    # Update cache
                    self.conversation_to_ticket[conversation_id] = str(ticket_id)
                    self.ticket_to_conversation[str(ticket_id)] = conversation_id
                    logger.info(f"Found ticket from API: {conversation_id} -> {ticket_id}")
                    return str(ticket_id)
            
            logger.warning(f"Could not find ticket_id for conversation: {conversation_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting ticket_id from conversation: {str(e)}")
            return None


    def process_chatwoot_webhook_async(self, data):
        """Xử lý Chatwoot webhook data - tối ưu để tránh duplicate"""
        try:
            # 1. Trích xuất dữ liệu cơ bản
            event = data.get("event", "")
            
            # 2. Bỏ qua các event không cần thiết ngay từ đầu
            if event in ["conversation_typing_on", "conversation_typing_off", "conversation_opened", "conversation_closed", "conversation_updated"]:
                logger.debug(f"Skipping non-message event: {event}")
                return
            
            # 3. Chỉ xử lý message_created events (bỏ automation_event)
            if event != "message_created":
                logger.debug(f"Skipping non-message event: {event}")
                return
            
            # 4. Trích xuất conversation_id từ đúng vị trí
            conversation_id = None
            if data.get("conversation", {}).get("id"):
                conversation_id = data.get("conversation", {}).get("id")
            elif data.get("id") and str(data.get("id")).isdigit():
                # Nếu id là số, có thể là conversation_id
                conversation_id = data.get("id")
            
            # 5. Kiểm tra conversation_id hợp lệ
            if not conversation_id or conversation_id == "None":
                logger.debug(f"Invalid conversation_id: {conversation_id}")
                return
            
            # 6. Trích xuất message data từ đúng vị trí
            # Webhook data có cấu trúc: content ở root, sender_type/status trong conversation.messages[0]
            content = data.get("content", "")
            message_id = data.get("id")
            message_type = data.get("message_type", "")
            
            # Lấy sender_type và status từ conversation.messages[0] (cấu trúc thực tế)
            sender_type = ""
            status = ""
            if data.get("conversation", {}).get("messages") and len(data["conversation"]["messages"]) > 0:
                latest_message = data["conversation"]["messages"][0]
                sender_type = latest_message.get("sender_type", "")
                status = latest_message.get("status", "")
                logger.info(f"Found data in conversation.messages[0]: sender_type={sender_type}, status={status}")
            
            # Fallback: thử tìm ở root level nếu không tìm thấy trong messages
            if not sender_type:
                sender_type = data.get("sender_type", "")
                logger.info(f"Fallback to root level: sender_type={sender_type}")
            if not status:
                status = data.get("status", "")
                logger.info(f"Fallback to root level: status={status}")
            
            logger.info(f"Extracted data - Content: {content}, Sender: {sender_type}, Status: {status}, Type: {message_type}")
            
            if not content:
                logger.debug("No content found - skipping")
                return
            
            # 7. Chỉ xử lý tin nhắn từ agent (User sender_type, outgoing message_type) và status = sent
            if sender_type != "User" or message_type != "outgoing" or status != "sent":
                logger.debug(f"Skipping message: sender_type={sender_type}, message_type={message_type}, status={status}")
                return
            
            # 8. Kiểm tra duplicate message bằng message_id
            if self.is_duplicate_message(message_id):
                logger.debug(f"Skipping duplicate message: {message_id}")
                return
            
            # 9. Log chi tiết cho message quan trọng
            logger.info(f"=== PROCESSING CHATWOOT WEBHOOK ===")
            logger.info(f"Event: {event}")
            logger.info(f"Conversation ID: {conversation_id}")
            logger.info(f"Message ID: {message_id}")
            logger.info(f"Content: {content}")
            logger.info(f"Sender type: {sender_type}")
            logger.info(f"Status: {status}")
            
            # 10. Lấy ticket_id và gửi về Zendesk
            ticket_id = self.get_ticket_id_from_conversation(conversation_id)
            if not ticket_id:
                logger.warning(f"Could not find ticket_id for conversation {conversation_id}")
                return
            
            logger.info(f"Processing Chatwoot -> Zendesk: conversation={conversation_id} -> ticket={ticket_id}")
            
            # 11. Gửi comment về Zendesk với tag để tránh vòng lặp
            success = self.send_zendesk_comment_with_tags(ticket_id, content)
            
            if success:
                # 12. Đánh dấu message đã xử lý
                self.mark_message_processed(message_id)
                logger.info(f"✅ Success: Chatwoot conversation {conversation_id} -> Zendesk ticket {ticket_id}")
            else:
                logger.error(f"❌ Failed: Chatwoot conversation {conversation_id} -> Zendesk ticket {ticket_id}")
            
        except Exception as e:
            logger.error(f"Error processing Chatwoot webhook: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    def is_duplicate_message(self, message_id):
        """Kiểm tra message đã được xử lý chưa"""
        if not message_id:
            return False
        
        # Tạo key cho message
        message_key = f"processed_message_{message_id}"
        
        # Kiểm tra trong cache
        if hasattr(self, 'processed_messages') and message_key in self.processed_messages:
            return True
        
        # Thêm vào cache
        if not hasattr(self, 'processed_messages'):
            self.processed_messages = {}
        
        self.processed_messages[message_key] = time.time()
        
        # Cleanup old entries (older than 1 hour)
        cutoff = time.time() - 3600
        old_keys = [k for k, t in self.processed_messages.items() if t < cutoff]
        for old_key in old_keys:
            del self.processed_messages[old_key]
        
        return False

    def mark_message_processed(self, message_id):
        """Đánh dấu message đã được xử lý"""
        if not message_id:
            return
        
        message_key = f"processed_message_{message_id}"
        if not hasattr(self, 'processed_messages'):
            self.processed_messages = {}
        
        self.processed_messages[message_key] = time.time()


    
    def setup_routes(self):
        """Thiết lập các routes"""
        logger.info("Setting up Flask routes")
        
        @self.app.route('/service-api-webhook/health', methods=['GET'])
        def health_check():
            """Health check endpoint"""
            logger.info("=== HEALTH CHECK REQUEST ===")
            logger.info(f"Request method: {request.method}")
            logger.info(f"Request headers: {dict(request.headers)}")
            
            try:
                response_data = {
                    'status': 'healthy',
                    'timestamp': datetime.now().isoformat(),
                    'service': 'omnichannel-webhook-api'
                }
                
                logger.info(f"Health check response: {response_data}")
                return jsonify(response_data), 200
                
            except Exception as e:
                logger.error(f"Health check failed: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                
                response_data = {
                    'status': 'unhealthy',
                    'error': str(e),
                    'timestamp': datetime.now().isoformat(),
                    'service': 'omnichannel-webhook-api'
                }
                
                logger.info(f"Health check response: {response_data}")
                return jsonify(response_data), 500
        
        # @self.app.route('/service-api-webhook/zalo-webhook', methods=['POST'])
        # def zalo_webhook():
        #     """Webhook endpoint cho Zalo"""
        #     logger.info("=== ZALO WEBHOOK REQUEST ===")
        #     logger.info(f"Request method: {request.method}")
        #     logger.info(f"Request headers: {dict(request.headers)}")
            
        #     try:
        #         data = request.get_json() or {}
        #         logger.info(f"Request data: {data}")
                
        #         # Trả về response ngay lập tức
        #         response_data = {
        #             'status': 'success',
        #             'message': 'Zalo webhook received',
        #             'timestamp': datetime.now().isoformat()
        #         }
                
        #         logger.info(f"Zalo webhook response: {response_data}")
                
        #         # Khởi tạo background thread để xử lý webhook
        #         thread = threading.Thread(
        #             target=self.process_zalo_webhook_async,
        #             args=(data,),
        #             daemon=True
        #         )
        #         thread.start()
        #         logger.info("Started background thread for Zalo webhook processing")
                
        #         return jsonify(response_data), 200
                
        #     except Exception as e:
        #         logger.error(f"Error processing Zalo webhook: {str(e)}")
        #         logger.error(f"Traceback: {traceback.format_exc()}")
                
        #         response_data = {
        #             'status': 'error',
        #             'message': 'Error processing Zalo webhook',
        #             'error': str(e),
        #             'timestamp': datetime.now().isoformat()
        #         }
                
        #         logger.info(f"Zalo webhook error response: {response_data}")
        #         return jsonify(response_data), 200  # Vẫn trả về 200 OK
        
        @self.app.route('/service-api-webhook/zendesk-webhook', methods=['POST'])
        def zendesk_webhook():
            """Webhook endpoint cho Zendesk -> Chatwoot"""
            try:
                data = request.get_json() or {}
                logger.info(f"=== ZENDESK WEBHOOK RECEIVED ===")
                logger.info(f"Request data: {data}")
                
                # Trả về response ngay lập tức
                response_data = {
                    'status': 'success',
                    'message': 'Zendesk webhook received',
                    'timestamp': datetime.now().isoformat()
                }
                
                # Xử lý trong background thread
                thread = threading.Thread(
                    target=self.process_zendesk_webhook_async,
                    args=(data,),
                    daemon=True
                )
                thread.start()
                
                return jsonify(response_data), 200
                
            except Exception as e:
                logger.error(f"Error in Zendesk webhook: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': str(e),
                    'timestamp': datetime.now().isoformat()
                }), 200





                
        
        @self.app.route('/service-api-webhook/chatwoot-webhook', methods=['POST'])
        def chatwoot_webhook():
            """Webhook endpoint cho Chatwoot -> Zendesk"""
            try:
                data = request.get_json() or {}
                event = data.get("event", "")
                
                # Chỉ log chi tiết cho message_created events
                if event == "message_created":
                    logger.info(f"=== CHATWOOT WEBHOOK RECEIVED ===")
                    logger.info(f"Event: {event}")
                    # Log thông tin conversation chính xác
                    conv_id = data.get("conversation", {}).get("id", data.get("id", "unknown"))
                    logger.info(f"Conversation ID: {conv_id}")
                    # Thêm debug log để xem cấu trúc data
                    logger.info(f"Full webhook data: {json.dumps(data, ensure_ascii=False, indent=2)}")
                else:
                    logger.debug(f"Chatwoot webhook - Event: {event}")
                
                # Trả về response ngay lập tức
                response_data = {
                    'status': 'success',
                    'message': 'Chatwoot webhook received',
                    'timestamp': datetime.now().isoformat()
                }
                
                # Xử lý trong background thread
                thread = threading.Thread(
                    target=self.process_chatwoot_webhook_async,
                    args=(data,),
                    daemon=True
                )
                thread.start()
                
                return jsonify(response_data), 200
                
            except Exception as e:
                logger.error(f"Error in Chatwoot webhook: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': str(e),
                    'timestamp': datetime.now().isoformat()
                }), 200


        
        logger.info("Flask routes setup completed")
    
    def run(self):
        """Chạy Flask application"""
        logger.info("=== STARTING OMNICHANNEL SERVICE ===")
        
        try:
            api_config = self.config['api']
            host = api_config.get('host', '0.0.0.0')
            port = api_config.get('port', 5015)
            debug = api_config.get('debug', False)
            
            logger.info(f"Starting Flask app on {host}:{port}")
            logger.info(f"Debug mode: {debug}")
            
            self.app.run(
                host=host,
                port=port,
                debug=debug
            )
            
        except Exception as e:
            logger.error(f"Error starting service: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

if __name__ == '__main__':
    try:
        service = OmnichannelService()
        service.run()
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.error(f"Service crashed: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
