#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import threading
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from typing import Optional, Dict, Any

# Setup logging
logs_dir = os.path.join(os.path.dirname(__file__), 'Logs')
os.makedirs(logs_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, f'log_{datetime.now().strftime("%Y_%m_%d")}.txt'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class OmnichannelService:
    def __init__(self):
        self.config = self.load_config()
        self.app = Flask(__name__)
        CORS(self.app)
        
        # Cache storage
        self.ticket_to_conversation = {}
        self.conversation_to_ticket = {}
        self.processed_messages = {}
        
        self.setup_routes()
        logger.info("OmnichannelService initialized")
    
    def load_config(self) -> Dict[str, Any]:
        """Load config từ file"""
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def make_chatwoot_request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Chatwoot API request"""
        chatwoot_config = self.config.get('chatwoot', {})
        base_url = chatwoot_config.get('base_url', '')
        api_token = chatwoot_config.get('api_token', '')
        account_id = chatwoot_config.get('account_id', '2')
        
        url = f"{base_url}/api/v1/accounts/{account_id}/{endpoint}"
        headers = {'Content-Type': 'application/json', 'api_access_token': api_token}
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=15)
            else:
                response = requests.post(url, json=data, headers=headers, timeout=15)
            
            if response.ok:
                return response.json()
            else:
                logger.error(f"Chatwoot API error: {method} {endpoint} - {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Chatwoot request failed: {method} {endpoint} - {str(e)}")
            return None
    
    def create_or_find_contact(self, requester_info: Dict, ticket_id: str) -> Optional[int]:
        """Tạo hoặc tìm contact"""
        identifier = f"zendesk:{requester_info['id']}:{ticket_id}"
        
        # Tìm contact hiện có
        result = self.make_chatwoot_request("GET", f"contacts/search?q={identifier}")
        if result and result.get('payload'):
            contact_id = result['payload'][0]['id']
            return contact_id
        
        # Tạo contact mới
        contact_data = {
            "name": requester_info['name'],
            "identifier": identifier
        }
        
        result = self.make_chatwoot_request("POST", "contacts", contact_data)
        if result:
            contact_id = result['id']
            return contact_id
        
        return None
    
    def create_or_find_conversation(self, contact_id: int, ticket_id: str) -> Optional[int]:
        """Tạo hoặc tìm conversation"""
        # Check cache
        if ticket_id in self.ticket_to_conversation:
            conv_id = self.ticket_to_conversation[ticket_id]
            return conv_id
        
        # Tìm conversation hiện có
        inbox_id = self.config.get('chatwoot', {}).get('inbox_id', '2')
        result = self.make_chatwoot_request("GET", f"conversations?inbox_id={inbox_id}&source_id={ticket_id}")
        if result and result.get('data', {}).get('payload'):
            conv_id = result['data']['payload'][0]['id']
            self.ticket_to_conversation[ticket_id] = conv_id
            self.conversation_to_ticket[conv_id] = ticket_id
            return conv_id
        
        # Tạo conversation mới
        conv_data = {
            "contact_id": contact_id,
            "inbox_id": int(inbox_id),
            "source_id": ticket_id
        }
        
        result = self.make_chatwoot_request("POST", "conversations", conv_data)
        if result:
            conv_id = result['id']
            self.ticket_to_conversation[ticket_id] = conv_id
            self.conversation_to_ticket[conv_id] = ticket_id
            return conv_id
        
        return None
    
    def send_chatwoot_message(self, conversation_id: int, content: str, message_type: str = "incoming") -> bool:
        """Gửi message đến Chatwoot"""
        message_data = {"content": content, "message_type": message_type}
        result = self.make_chatwoot_request("POST", f"conversations/{conversation_id}/messages", message_data)
        return result is not None
    
    def send_zendesk_comment(self, ticket_id: str, content: str) -> bool:
        """Gửi comment đến Zendesk với tags tránh loop"""
        zendesk_config = self.config.get('zendesk', {})
        subdomain = zendesk_config.get('subdomain', '')
        email = zendesk_config.get('email', '')
        api_token = zendesk_config.get('api_token', '')
        
        url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        auth = (f"{email}/token", api_token)
        
        payload = {
            "ticket": {
                "comment": {"body": content, "public": True},
                "tags": ["from_chatwoot", "api_integration", "no_webhook"]
            }
        }
        
        try:
            response = requests.put(url, json=payload, auth=auth, timeout=15)
            return response.ok
        except Exception as e:
            logger.error(f"Zendesk request error: {str(e)}")
            return False
    
    def get_ticket_id_from_conversation(self, conversation_id: int) -> Optional[str]:
        """Lấy ticket_id từ conversation"""
        # Check cache
        if conversation_id in self.conversation_to_ticket:
            ticket_id = self.conversation_to_ticket[conversation_id]
            return ticket_id
        
        # Fetch from API
        result = self.make_chatwoot_request("GET", f"conversations/{conversation_id}")
        if result:
            ticket_id = (
                result.get("source_id") or
                (result.get("custom_attributes") or {}).get("ticket_id") or
                (result.get("additional_attributes") or {}).get("source_id")
            )
            if ticket_id:
                self.conversation_to_ticket[conversation_id] = ticket_id
                self.ticket_to_conversation[ticket_id] = conversation_id
                return ticket_id
        
        return None
    
    def is_from_chatwoot(self, data: Dict) -> bool:
        """Kiểm tra message từ Chatwoot để tránh loop"""
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        
        loop_tags = ["from_chatwoot", "api_integration", "no_webhook"]
        has_loop_tag = any(tag in tags for tag in loop_tags)
        
        author = data.get("event", {}).get("comment", {}).get("author", {})
        is_staff = author.get("is_staff", False)
        
        return has_loop_tag or is_staff
    
    def is_duplicate_message(self, message_id: str) -> bool:
        """Kiểm tra duplicate message"""
        if not message_id:
            return False
        
        if message_id in self.processed_messages:
            return True
        
        self.processed_messages[message_id] = time.time()
        
        # Cleanup old entries (older than 1 hour)
        cutoff = time.time() - 3600
        old_keys = [k for k, t in self.processed_messages.items() if t < cutoff]
        for old_key in old_keys:
            del self.processed_messages[old_key]
        
        return False
    
    def process_zendesk_webhook(self, data: Dict):
        """Xử lý Zendesk webhook"""
        try:
            # Extract data first for duplicate check
            comment_id = data.get("event", {}).get("comment", {}).get("id")
            
            # Check for duplicate comment
            if self.is_duplicate_message(comment_id):
                return
            
            # Extract data
            ticket_id = (
                data.get("ticket_id") or
                data.get("detail", {}).get("id") or
                data.get("subject", "").split(":")[-1] if data.get("subject", "").startswith("zen:ticket:") else None
            )
            
            comment = (
                data.get("latest_comment") or
                data.get("event", {}).get("comment", {}).get("body", "")
            ).strip()
            
            author = data.get("event", {}).get("comment", {}).get("author", {})
            requester_info = {
                "id": str(author.get("id", "")),
                "name": author.get("name", f"User {author.get('id', '')}")
            }
            
            # Validation
            if not ticket_id or not comment:
                return
            
            if self.is_from_chatwoot(data):
                return
            
            # Process Zendesk -> Chatwoot
            contact_id = self.create_or_find_contact(requester_info, ticket_id)
            if not contact_id:
                return
            
            conversation_id = self.create_or_find_conversation(contact_id, ticket_id)
            if not conversation_id:
                return
            
            success = self.send_chatwoot_message(conversation_id, comment, "incoming")
            if success:
                logger.info(f"Zendesk → Chatwoot: {ticket_id} → {conversation_id}")
            
        except Exception as e:
            logger.error(f"Error processing Zendesk webhook: {str(e)}")
    
    def process_chatwoot_webhook(self, data: Dict):
        """Xử lý Chatwoot webhook"""
        try:
            event = data.get("event", "")
            if event != "message_created":
                return
            
            # Extract data
            conversation_id = data.get("conversation", {}).get("id")
            content = data.get("content", "")
            message_id = data.get("id")
            message_type = data.get("message_type", "")
            
            # Check for duplicate message first
            if self.is_duplicate_message(message_id):
                return
            
            # Get sender info from messages array
            sender_type = ""
            status = ""
            if data.get("conversation", {}).get("messages"):
                latest_message = data["conversation"]["messages"][0]
                sender_type = latest_message.get("sender_type", "")
                status = latest_message.get("status", "")
            
            # Validation
            if not conversation_id or not content:
                return
            
            # Only process agent messages (User, outgoing, sent)
            if sender_type != "User" or message_type != "outgoing" or status != "sent":
                return
            
            # Process Chatwoot -> Zendesk
            ticket_id = self.get_ticket_id_from_conversation(conversation_id)
            if not ticket_id:
                return
            
            success = self.send_zendesk_comment(ticket_id, content)
            if success:
                logger.info(f"Chatwoot → Zendesk: {conversation_id} → {ticket_id}")
            
        except Exception as e:
            logger.error(f"Error processing Chatwoot webhook: {str(e)}")
    
    def setup_routes(self):
        """Setup Flask routes"""
        @self.app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()}), 200
        
        @self.app.route('/service-api-webhook/zendesk-webhook', methods=['POST'])
        def zendesk_webhook():
            data = request.get_json() or {}
            
            # Process in background
            thread = threading.Thread(target=self.process_zendesk_webhook, args=(data,), daemon=True)
            thread.start()
            
            return jsonify({'status': 'success'}), 200
        
        @self.app.route('/service-api-webhook/chatwoot-webhook', methods=['POST'])
        def chatwoot_webhook():
            data = request.get_json() or {}
            event = data.get("event", "")
            
            if event == "message_created":
                logger.info(f"Chatwoot webhook: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            # Process in background
            thread = threading.Thread(target=self.process_chatwoot_webhook, args=(data,), daemon=True)
            thread.start()
            
            return jsonify({'status': 'success'}), 200
    
    def run(self):
        """Chạy Flask app"""
        api_config = self.config['api']
        host = api_config.get('host', '0.0.0.0')
        port = api_config.get('port', 8000)
        debug = api_config.get('debug', False)
        
        logger.info(f"Starting service on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)

if __name__ == '__main__':
    try:
        service = OmnichannelService()
        service.run()
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.error(f"Service crashed: {str(e)}")
        exit(1)
