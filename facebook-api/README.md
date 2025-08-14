# 🔗 Omnichannel Webhook API

## 📋 Mô Tả

API webhook để tích hợp Zendesk và Chatwoot, cho phép đồng bộ tin nhắn hai chiều giữa hai hệ thống.

## 🎯 Tính Năng

- **Zendesk → Chatwoot**: Tự động tạo conversation và gửi tin nhắn khi có comment mới từ Zendesk
- **Chatwoot → Zendesk**: Tự động thêm comment vào ticket khi agent reply từ Chatwoot
- **Tránh vòng lặp**: Logic thông minh để tránh webhook loop
- **Cache hiệu quả**: Cache mapping giữa ticket và conversation
- **Xử lý async**: Background processing để tránh timeout

## 📁 Cấu Trúc Project

```
facebook-api/
├── app.py              # Main application file
├── config.json         # Cấu hình API keys và endpoints
├── requirements.txt    # Python dependencies
├── README.md          # Hướng dẫn sử dụng
├── Logs/              # Thư mục chứa log files
└── venv/              # Virtual environment
```

## 🚀 Cài Đặt

### 1. Cài đặt dependencies
```bash
pip install -r requirements.txt
```

### 2. Cấu hình
Chỉnh sửa file `config.json`:
```json
{
  "api": {
    "host": "0.0.0.0",
    "port": 8000,
    "debug": false
  },
  "chatwoot": {
    "base_url": "https://your-chatwoot-domain.com",
    "account_id": "your_account_id",
    "api_token": "your_api_token",
    "inbox_id": "your_inbox_id"
  },
  "zendesk": {
    "subdomain": "your_subdomain",
    "email": "your_email@domain.com",
    "api_token": "your_api_token"
  }
}
```

### 3. Chạy server
```bash
python app.py
```

## 🔧 Cấu Hình Webhook

### Zendesk Webhook
- **URL**: `https://your-domain.com/service-api-webhook/zendesk-webhook`
- **Events**: `ticket.comment_created`
- **Method**: POST

### Chatwoot Webhook
- **URL**: `https://your-domain.com/service-api-webhook/chatwoot-webhook`
- **Events**: `message_created`
- **Method**: POST

## 📊 API Endpoints

### Health Check
```
GET /service-api-webhook/health
```

### Zendesk Webhook
```
POST /service-api-webhook/zendesk-webhook
```

### Chatwoot Webhook
```
POST /service-api-webhook/chatwoot-webhook
```

## 🔄 Luồng Xử Lý

### Zendesk → Chatwoot
1. Nhận webhook từ Zendesk khi có comment mới
2. Trích xuất ticket_id, comment, requester_info
3. Kiểm tra tránh vòng lặp (tin nhắn từ Chatwoot)
4. Tạo/find contact trong Chatwoot
5. Tạo/find conversation trong Chatwoot
6. Gửi tin nhắn đến Chatwoot

### Chatwoot → Zendesk
1. Nhận webhook từ Chatwoot khi có message mới
2. Trích xuất event, conversation_id, messages
3. Chỉ xử lý message_created events
4. Chỉ xử lý tin nhắn từ agent (User sender_type)
5. Lấy ticket_id từ conversation
6. Gửi comment về Zendesk với tag tránh vòng lặp

## 🛠️ Tính Năng Nâng Cao

### Cache System
- Cache mapping giữa ticket_id và conversation_id
- Giảm API calls không cần thiết
- Tăng tốc độ xử lý

### Duplicate Prevention
- Kiểm tra webhook trùng lặp
- Hash-based deduplication
- Timeout 5 phút

### Error Handling
- Try-catch cho từng hàm riêng biệt
- Log chi tiết cho debugging
- Không crash toàn bộ hệ thống

## 📝 Logging

Logs được lưu trong thư mục `Logs/` theo ngày:
- `log_YYYY_MM_DD.txt`

### Log Levels
- **INFO**: Thông tin quan trọng về webhook processing
- **DEBUG**: Thông tin chi tiết cho debugging
- **ERROR**: Lỗi và exceptions

## 🔍 Monitoring

### Health Check
```bash
curl http://localhost:5015/service-api-webhook/health
```

### Log Monitoring
```bash
tail -f Logs/log_$(date +%Y_%m_%d).txt
```

## 🚨 Troubleshooting

### Webhook không hoạt động
1. Kiểm tra cấu hình trong `config.json`
2. Kiểm tra logs trong thư mục `Logs/`
3. Kiểm tra network connectivity
4. Kiểm tra webhook URL configuration

### Vòng lặp webhook
1. Kiểm tra logic `is_from_chatwoot()`
2. Kiểm tra tags trong Zendesk comments
3. Kiểm tra cache mapping

### Performance issues
1. Kiểm tra cache hit rate
2. Kiểm tra API response times
3. Kiểm tra background thread processing

## 📞 Support

Nếu gặp vấn đề, hãy kiểm tra:
1. Log files trong thư mục `Logs/`
2. Cấu hình trong `config.json`
3. Network connectivity
4. API credentials

## 🔄 Version History

- **v1.0**: Initial release với tích hợp Zendesk-Chatwoot
- **v1.1**: Tối ưu logic và cải thiện performance
- **v1.2**: Thêm cache system và duplicate prevention
