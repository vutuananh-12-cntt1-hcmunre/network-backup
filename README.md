# Network Backup & Inventory

## 1. Giới thiệu
Dự án xây dựng hệ thống tự động sao lưu cấu hình thiết bị mạng Cisco và Juniper thông qua SSH, sử dụng Python và Netmiko. Hệ thống hỗ trợ lưu trữ cấu hình, so sánh sự thay đổi giữa các lần sao lưu và quản lý phiên bản bằng Git.

## 2. Công nghệ sử dụng
- **Python:** Xây dựng chương trình tự động hóa.
- **Netmiko:** Kết nối SSH và lấy cấu hình thiết bị mạng.
- **Git:** Quản lý phiên bản và lưu lịch sử thay đổi cấu hình.
- **JSON:** Lưu danh sách thiết bị trong `inventory.json`.
- **GNS3:** Mô phỏng thiết bị mạng phục vụ kiểm thử.

## 3. Chức năng chính
- Kết nối SSH đến nhiều thiết bị mạng.
- Tự động lấy cấu hình Cisco và Juniper.
- Lưu cấu hình vào thư mục `backups/`.
- So sánh cấu hình hiện tại với bản sao lưu trước đó.
- Hiển thị các thay đổi giữa hai phiên bản cấu hình.
- Ghi nhật ký kết quả sao lưu và lỗi kết nối.
- Sử dụng Git để quản lý lịch sử thay đổi cấu hình.

## 4. Cấu trúc thư mục

```text
network-backup/
├── main.py
├── inventory.json
├── README.md
├── .gitignore
├── backups/
│   ├── cisco/
│   ├── juniper/
│   └── linux/
├── logs/
└── .venv/
```

## 5. Cài đặt và sử dụng

### Bước 1: Cài đặt thư viện

Kích hoạt môi trường ảo và cài đặt Netmiko:

```bash
pip install netmiko
```

### Bước 2: Cấu hình danh sách thiết bị

Chỉnh sửa file `inventory.json` theo địa chỉ IP và loại thiết bị cần sao lưu.

Ví dụ:

```json
[
  {
    "name": "Cisco-R1",
    "host": "192.168.234.200",
    "device_type": "cisco_ios"
  },
  {
    "name": "Cisco-R2",
    "host": "192.168.234.201",
    "device_type": "cisco_ios"
  },
  {
    "name": "Cisco-R3",
    "host": "192.168.234.202",
    "device_type": "cisco_ios"
  }
]
```

### Bước 3: Chạy chương trình

```bash
python main.py --mode live
```

Nhập tên đăng nhập và mật khẩu SSH khi chương trình yêu cầu.

## 6. Kết quả kiểm thử
Hệ thống đã được kiểm thử với 3 router Cisco được mô phỏng bằng GNS3. Chương trình kết nối SSH, lấy cấu hình, lưu bản sao lưu và hiển thị thay đổi khi phát hiện khác biệt.

Kết quả kiểm thử gần nhất: **3 thiết bị thành công, 0 thiết bị thất bại.**

## 7. Bảo mật
- Không đưa mật khẩu SSH vào file `inventory.json`.
- Không đưa mật khẩu, khóa riêng hoặc thông tin nhạy cảm vào GitHub.
- Nên đặt repository ở chế độ Private khi lưu cấu hình thiết bị mạng.
- Chỉ thực hiện kiểm thử trên thiết bị được phép quản trị.

## 8. Hướng phát triển
- Bổ sung kiểm thử thực tế với thiết bị Juniper.
- Cải thiện báo cáo và thống kê kết quả sao lưu.
- Bổ sung lịch sao lưu tự động.
- Cải thiện cơ chế phát hiện và thông báo thay đổi cấu hình.
