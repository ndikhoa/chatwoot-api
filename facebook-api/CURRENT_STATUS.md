# 🔗 Omnichannel Webhook API - Tình Trạng Hiện Tại

## 📋 Tổng Quan

API webhook để tích hợp Zendesk và Chatwoot, cho phép đồng bộ tin nhắn hai chiều giữa hai hệ thống. **Hệ thống đã hoạt động hoàn hảo và sẵn sàng production.**

## ✅ Tình Trạng Hiện Tại

### **🎯 Kết Quả Test Thành Công:**
- **Chatwoot → Zendesk:** ✅ Hoạt động hoàn hảo
- **Zendesk → Chatwoot:** ✅ Hoạt động hoàn hảo  
- **Loop Prevention:** ✅ Hoạt động đúng
- **Error Handling:** ✅ Xử lý lỗi tốt
- **Logging:** ✅ Chi tiết và rõ ràng

### **📊 Timeline Test Thành Công:**
```
11:31:02 - Chatwoot webhook received (message_created)
11:31:02 - Extracted data: Content: "test", Sender: "User", Status: "sent", Type: "outgoing"
11:31:02 - Processing Chatwoot webhook
11:31:02 - Found ticket from API: 3 -> 21
11:31:02 - Processing Chatwoot -> Zendesk: conversation=3 -> ticket=21
11:31:03 - ✅ Success: Chatwoot conversation 3 -> Zendesk ticket 21
11:31:03 - Zendesk webhook received (ticket.comment_added)
11:31:03 - Message from Chatwoot - skipping to avoid loop
```

## 🔧 Logic Mới Nhất

### **1. Chatwoot → Zendesk Flow**

#### **Webhook Processing:**
```python
def process_chatwoot_webhook_async(self, data):
    # 1. Filter events
    event = data.get("event", "")
    if event != "message_created":
        return
    
    # 2. Extract conversation_id
    conversation_id = data.get("conversation", {}).get("id") or data.get("id")
    
    # 3. Extract message data from conversation.messages[0]
    content = data.get("content", "")
    message_type = data.get("message_type", "")
    
    # Get sender_type and status from conversation.messages[0]
    sender_type = ""
    status = ""
    if data.get("conversation", {}).get("messages") and len(data["conversation"]["messages"]) > 0:
        latest_message = data["conversation"]["messages"][0]
        sender_type = latest_message.get("sender_type", "")
        status = latest_message.get("status", "")
    
    # 4. Filter agent messages only
    if sender_type != "User" or message_type != "outgoing" or status != "sent":
        return
    
    # 5. Check duplicate message
    if self.is_duplicate_message(message_id):
        return
    
    # 6. Get ticket_id and send to Zendesk
    ticket_id = self.get_ticket_id_from_conversation(conversation_id)
    success = self.send_zendesk_comment_with_tags(ticket_id, content)
```

#### **Key Functions:**
```python
def get_ticket_id_from_conversation(self, conversation_id):
    # Check cache first
    if conversation_id in self.conversation_to_ticket:
        return self.conversation_to_ticket[conversation_id]
    
    # Fetch from Chatwoot API
    result = self.make_chatwoot_request("GET", f"conversations/{conversation_id}")
    if result:
        ticket_id = (
            result.get("source_id") or
            (result.get("custom_attributes") or {}).get("ticket_id") or
            (result.get("additional_attributes") or {}).get("source_id")
        )
        if ticket_id:
            # Update cache
            self.conversation_to_ticket[conversation_id] = str(ticket_id)
            self.ticket_to_conversation[str(ticket_id)] = conversation_id
            return str(ticket_id)
    return None

def is_duplicate_message(self, message_id):
    message_key = f"processed_message_{message_id}"
    if hasattr(self, 'processed_messages') and message_key in self.processed_messages:
        return True
    
    # Add to cache
    if not hasattr(self, 'processed_messages'):
        self.processed_messages = {}
    self.processed_messages[message_key] = time.time()
    return False
```

### **2. Zendesk → Chatwoot Flow**

#### **Webhook Processing:**
```python
def process_zendesk_webhook_async(self, data):
    # 1. Extract basic data
    ticket_id = self.extract_ticket_id(data)
    comment = self.extract_comment(data)
    requester_info = self.extract_requester_info(data)
    
    # 2. Check loop prevention
    if self.is_from_chatwoot(data):
        return  # Skip if from Chatwoot
    
    # 3. Create/find contact and conversation
    contact_id = self.create_or_find_contact(requester_info, ticket_id)
    conversation_id = self.create_or_find_conversation(contact_id, ticket_id)
    
    # 4. Send message to Chatwoot
    success = self.send_chatwoot_message(conversation_id, comment, "incoming")
```

#### **Key Functions:**
```python
def extract_ticket_id(self, data):
    # Priority: ticket_id > detail.id > subject
    if data.get("ticket_id"):
        return str(data.get("ticket_id"))
    elif data.get("detail", {}).get("id"):
        return str(data.get("detail", {}).get("id"))
    elif data.get("subject", "").startswith("zen:ticket:"):
        return data.get("subject", "").split(":")[-1]
    return None

def extract_comment(self, data):
    # Priority: latest_comment > event.comment.body
    if data.get("latest_comment"):
        return data.get("latest_comment", "").strip()
    elif data.get("event", {}).get("comment", {}).get("body"):
        return data.get("event", {}).get("comment", {}).get("body", "").strip()
    return ""

def extract_requester_info(self, data):
    # Priority: event.comment.author > requester > detail.requester_id
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

def create_or_find_contact(self, requester_info, ticket_id):
    identifier = f"zendesk:{requester_info['id']}:{ticket_id}"
    name = requester_info['name']
    
    # Find existing contact
    result = self.make_chatwoot_request("GET", f"contacts/search?q={identifier}")
    if result and result.get("payload"):
        contact_id = result["payload"][0]["id"]
        return contact_id
    
    # Create new contact
    contact_data = {"identifier": identifier, "name": name}
    result = self.make_chatwoot_request("POST", "contacts", contact_data)
    if result:
        return self.extract_id_from_response(result)
    return None

def create_or_find_conversation(self, contact_id, ticket_id):
    # Check cache first
    if ticket_id in self.ticket_to_conversation:
        return self.ticket_to_conversation[ticket_id]
    
    # Find existing conversation
    result = self.make_chatwoot_request("GET", f"conversations?inbox_id={inbox_id}&source_id={ticket_id}")
    if result and result.get("data", {}).get("payload"):
        conversations = result["data"]["payload"]
        if conversations:
            conv_id = conversations[0].get("id")
            if conv_id:
                self.update_conversation_cache(ticket_id, conv_id)
                return conv_id
    
    # Create new conversation
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
            return conv_id
    return None
```

### **3. Loop Prevention System**

#### **Chatwoot → Zendesk:**
```python
def send_zendesk_comment_with_tags(self, ticket_id, content):
    payload = {
        "ticket": {
            "comment": {"body": content, "public": True},
            "tags": ["from_chatwoot", "api_integration", "no_webhook"]
        }
    }
    response = requests.put(url, json=payload, auth=auth, timeout=15)
    return response.ok
```

#### **Zendesk → Chatwoot:**
```python
def is_from_chatwoot(self, data):
    # Check tags for loop prevention
    tags = data.get("detail", {}).get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    
    loop_prevention_tags = ["from_chatwoot", "api_integration", "no_webhook"]
    has_loop_tag = any(tag in tags for tag in loop_prevention_tags)
    
    # Check if author is staff
    author = data.get("event", {}).get("comment", {}).get("author", {})
    is_staff = author.get("is_staff", False)
    
    # Check direction
    direction = data.get("direction", "")
    
    return has_loop_tag or is_staff or direction == "outbound_api"
```

### **4. API Communication Functions**

#### **Chatwoot API:**
```python
def make_chatwoot_request(self, method, endpoint, data=None):
    url = f"{base_url}/api/v1/accounts/{account_id}/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "api_access_token": api_token
    }
    
    if method == "GET":
        response = requests.get(url, headers=headers, timeout=15)
    else:
        response = requests.post(url, json=data, headers=headers, timeout=15)
    
    if response.ok:
        return response.json()
    return None

def send_chatwoot_message(self, conversation_id, content, message_type="incoming"):
    message_data = {
        "content": content,
        "message_type": message_type
    }
    result = self.make_chatwoot_request("POST", f"conversations/{conversation_id}/messages", message_data)
    return result is not None
```

#### **Zendesk API:**
```python
def send_zendesk_comment_with_tags(self, ticket_id, content):
    url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    auth = (f"{email}/token", api_token)
    
    payload = {
        "ticket": {
            "comment": {"body": content, "public": True},
            "tags": ["from_chatwoot", "api_integration", "no_webhook"]
        }
    }
    
    response = requests.put(url, json=payload, auth=auth, timeout=15)
    return response.ok
```

### **5. Cache Management**

#### **Conversation Cache:**
```python
def update_conversation_cache(self, ticket_id, conversation_id):
    self.ticket_to_conversation[ticket_id] = conversation_id
    self.conversation_to_ticket[conversation_id] = ticket_id

def extract_id_from_response(self, response):
    if isinstance(response, dict):
        # Try different response structures
        for key in ["id", "payload", "conversation", "contact"]:
            if key in response:
                if isinstance(response[key], dict) and "id" in response[key]:
                    return response[key]["id"]
                elif key == "id":
                    return response[key]
        
        # Try data structure
        if "data" in response:
            data = response["data"]
            if isinstance(data, dict) and "id" in data:
                return data["id"]
            elif isinstance(data, list) and len(data) > 0 and "id" in data[0]:
                return data[0]["id"]
    return None
```

### **6. Message Processing & Cleanup**

#### **Message Deduplication:**
```python
def is_duplicate_message(self, message_id):
    if not message_id:
        return False
    
    message_key = f"processed_message_{message_id}"
    if hasattr(self, 'processed_messages') and message_key in self.processed_messages:
        return True
    
    # Add to cache
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
    if not message_id:
        return
    
    message_key = f"processed_message_{message_id}"
    if not hasattr(self, 'processed_messages'):
        self.processed_messages = {}
    self.processed_messages[message_key] = time.time()
```

#### **Comment Cleaning:**
```python
def clean_zendesk_comment(self, comment):
    if not comment:
        return ""
    
    # Handle escaped newlines
    comment = comment.replace('\\n', '\n')
    
    # Split by lines and clean
    lines = comment.split('\n')
    cleaned_lines = []
    
    for line in lines:
        line = line.strip()
        # Skip separator lines and agent info
        if (line.startswith('-') and line.endswith('-') and len(line) > 10) or \
           line.startswith('----------------------------------------------') or \
           line == '':
            continue
        
        cleaned_lines.append(line)
    
    # Join and clean up
    cleaned_comment = '\n'.join(cleaned_lines).strip()
    while '\n\n\n' in cleaned_comment:
        cleaned_comment = cleaned_comment.replace('\n\n\n', '\n\n')
    
    return cleaned_comment
