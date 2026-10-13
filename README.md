# Network Backup & Inventory

## 1. Giới thiệu

Dự án xây dựng hệ thống tự động thu thập và sao lưu cấu hình thiết bị mạng Cisco và Juniper thông qua SSH, sử dụng Python và Netmiko.

Hệ thống hỗ trợ quản lý danh sách thiết bị, kết nối SSH, thu thập cấu hình, lưu bản sao lưu, so sánh sự thay đổi giữa các lần sao lưu và quản lý lịch sử phiên bản bằng Git.

Dự án sử dụng GNS3 để mô phỏng các router Cisco và kiểm thử chức năng sao lưu tự động. Ngoài ra, chương trình có chế độ kiểm thử kết nối và thu thập thông tin hệ thống Linux qua SSH.

## 2. Công nghệ sử dụng

- **Python:** Xây dựng chương trình tự động hóa.
- **Netmiko:** Kết nối SSH và thu thập thông tin thiết bị.
- **Paramiko:** Thư viện SSH nền tảng được sử dụng trong hệ sinh thái Python.
- **Git:** Quản lý lịch sử phiên bản cấu hình.
- **JSON:** Lưu danh sách thiết bị trong `inventory.json`.
- **GNS3:** Mô phỏng thiết bị mạng.
- **VMware:** Chạy máy ảo Linux phục vụ kiểm thử.
- **PowerShell:** Kiểm tra khả năng kết nối đến cổng SSH.
- **Visual Studio Code:** Môi trường viết và chạy chương trình.

## 3. Chức năng chính

- Đọc danh sách thiết bị từ `inventory.json`.
- Tự động lần lượt kết nối SSH đến nhiều thiết bị.
- Thu thập cấu hình router Cisco.
- Có nhánh xử lý cấu hình Juniper, cần kiểm thử thực tế bổ sung.
- Kiểm thử kết nối và thu thập thông tin Linux qua SSH.
- Lưu dữ liệu thu thập được vào thư mục `backups/`.
- So sánh cấu hình hiện tại với bản sao lưu trước đó.
- Hiển thị các thay đổi cấu hình bằng Diff.
- Ghi nhật ký hoạt động và lỗi.
- Tự động ghi nhận thay đổi sao lưu bằng Git khi có thay đổi cần commit.

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

Ý nghĩa:

- `main.py`: Chương trình sao lưu và kiểm thử.
- `inventory.json`: Danh sách thiết bị cần sao lưu.
- `backups/cisco/`: Lưu cấu hình Cisco.
- `backups/juniper/`: Thư mục dành cho cấu hình Juniper.
- `backups/linux/`: Lưu kết quả kiểm thử Linux.
- `logs/`: Lưu nhật ký chương trình.
- `.venv/`: Môi trường Python ảo.
- `.gitignore`: Các tệp và thư mục không đưa vào Git.

## 5. Cài đặt và chuẩn bị môi trường

### 5.1. Mở thư mục dự án

Mở PowerShell trong VS Code và chạy:

```powershell
cd "E:\Vutuananh_project\quản trị mạng nâng cao_bài nhóm\network-backup"
```

Kích hoạt môi trường ảo:

```powershell
.\.venv\Scripts\Activate.ps1
```

Nếu chưa có môi trường ảo, tạo bằng:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Cài đặt thư viện:

```powershell
pip install netmiko
```

Nếu môi trường hiện tại đã cài đầy đủ các thư viện cần thiết, không cần cài đặt lại.

### 5.2. Cấu hình danh sách thiết bị

File `inventory.json`:

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

Trong đó:

- `name`: Tên thiết bị.
- `host`: Địa chỉ IP của thiết bị.
- `device_type`: Loại thiết bị để Netmiko lựa chọn phương thức kết nối.

Tên đăng nhập và mật khẩu SSH được nhập khi chương trình yêu cầu, không khai báo trực tiếp trong file JSON.

## 6. Hướng dẫn cấu hình router Cisco

### 6.1. Khi nào cần cấu hình lại SSH?

Sau khi tắt hoặc khởi động lại máy ảo GNS3, nếu router không còn khóa RSA hoặc SSH không hoạt động, cần kiểm tra và cấu hình lại SSH.

Thực hiện trên từng router R1, R2 và R3 bằng console của GNS3.

**Lưu ý:** Các lệnh dưới đây đặt mật khẩu tài khoản cục bộ là `123456`, chỉ phù hợp với môi trường lab. Không sử dụng mật khẩu này cho hệ thống thực tế.

### 6.2. Cấu hình R1

```text
enable
configure terminal
hostname R1
ip domain-name network.local
username tuananh privilege 15 secret 123456
crypto key generate rsa
```

Khi router hỏi số bit của khóa RSA, nhập:

```text
1024
```

Nếu router đã có khóa RSA và hỏi xác nhận thay thế, hãy kiểm tra trạng thái khóa trước khi quyết định tạo lại.

Tiếp tục:

```text
ip ssh version 2
line vty 0 4
login local
transport input ssh
end
write memory
show ip ssh
```

### 6.3. Cấu hình R2

```text
enable
configure terminal
hostname R2
ip domain-name network.local
username tuananh privilege 15 secret 123456
crypto key generate rsa
```

Khi được hỏi số bit của khóa RSA, nhập:

```text
1024
```

Tiếp tục:

```text
ip ssh version 2
line vty 0 4
login local
transport input ssh
end
write memory
show ip ssh
```

### 6.4. Cấu hình R3

```text
enable
configure terminal
hostname R3
ip domain-name network.local
username tuananh privilege 15 secret 123456
crypto key generate rsa
```

Khi được hỏi số bit của khóa RSA, nhập:

```text
1024
```

Tiếp tục:

```text
ip ssh version 2
line vty 0 4
login local
transport input ssh
end
write memory
show ip ssh
```

### 6.5. Kiểm tra cấu hình SSH

Sau khi cấu hình, trên từng router kiểm tra:

```text
show ip ssh
show running-config
```

Xác nhận SSH đã được bật và cấu hình tài khoản, đường truy cập VTY phù hợp.

Việc cấu hình SSH không thay thế việc cấu hình địa chỉ IP trên các giao diện mạng. Nếu router không thể truy cập, cần kiểm tra địa chỉ IP, trạng thái giao diện, kết nối GNS3 và khả năng định tuyến.

## 7. Hướng dẫn kiểm thử

### 7.1. Test case 1 — Kiểm tra kết nối SSH bằng PowerShell

**Mục tiêu:** Xác nhận Windows có thể kết nối đến cổng TCP 22 của ba router Cisco.

Trên PowerShell của máy Windows thật, chạy:

```powershell
Test-NetConnection 192.168.234.200 -Port 22
Test-NetConnection 192.168.234.201 -Port 22
Test-NetConnection 192.168.234.202 -Port 22
```

**Kết quả mong đợi:**

```text
TcpTestSucceeded : True
```

| Tiêu chí | Kết quả mong đợi |
|---|---|
| R1 có thể truy cập cổng 22 | `True` |
| R2 có thể truy cập cổng 22 | `True` |
| R3 có thể truy cập cổng 22 | `True` |

**Kết quả thực tế:** Các router đã được kiểm tra khả năng truy cập cổng SSH trong môi trường lab.

**Lưu ý:** Lệnh này chỉ kiểm tra kết nối TCP, không xác nhận thông tin đăng nhập hoặc khả năng thu thập cấu hình.

### 7.2. Test case 2 — Kiểm tra SSH đến máy Linux

**Mục tiêu:** Kiểm tra Windows có thể truy cập cổng SSH của máy Lubuntu trên VMware.

Chạy:

```powershell
Test-NetConnection 192.168.234.131 -Port 22
```

**Kết quả thực tế:**

```text
ComputerName     : 192.168.234.131
RemoteAddress    : 192.168.234.131
RemotePort       : 22
InterfaceAlias   : VMware Network Adapter VMnet8
SourceAddress    : 192.168.234.1
TcpTestSucceeded : True
```

**Kết luận:** Windows đã kết nối được đến cổng TCP 22 của máy Lubuntu.

### 7.3. Test case 3 — Kiểm thử chế độ Linux

**Mục tiêu:** Kiểm tra khả năng đăng nhập SSH, thu thập thông tin Linux, lưu kết quả và so sánh với bản sao lưu trước.

Chạy trong thư mục dự án:

```powershell
python main.py --mode linux-test --host 192.168.234.131
```

Nhập thông tin đăng nhập SSH khi chương trình yêu cầu.

**Kết quả thực tế:**

```text
SSH username: tuananh
SSH password:

Dang ket noi SSH den Linux: 192.168.234.131...
Khong phat hien thay doi.

Da luu: backups\linux\Lubuntu.cfg
Git: khong co thay doi backup moi.
```

**Đánh giá:**

- Chương trình đã chạy chế độ `linux-test`.
- Tệp kết quả được lưu tại `backups/linux/Lubuntu.cfg`.
- Chương trình không phát hiện thay đổi so với dữ liệu trước đó.
- Không có Git commit mới vì không có thay đổi backup cần ghi nhận.

**Kiểm tra tệp kết quả:**

```powershell
Get-Item .\backups\linux\Lubuntu.cfg
Get-Content .\backups\linux\Lubuntu.cfg
```

Kiểm tra tệp tồn tại và có nội dung thông tin hệ thống hợp lệ.

**Kết luận:** Chế độ kiểm thử Linux đã chạy thành công và tạo tệp kết quả sao lưu.

### 7.4. Test case 4 — Sao lưu ba router Cisco

**Mục tiêu:** Kiểm tra chương trình có thể tự động kết nối và sao lưu nhiều router trong một lần chạy.

Đảm bảo GNS3 đang chạy, các router hoạt động, địa chỉ IP chính xác và SSH đã được cấu hình.

Chạy:

```powershell
python main.py --mode live
```

Nhập tên đăng nhập và mật khẩu SSH khi được yêu cầu.

Chương trình đọc danh sách thiết bị từ `inventory.json`, lần lượt kết nối đến các router, thu thập cấu hình, lưu bản sao lưu và kiểm tra thay đổi.

**Kết quả thực tế gần nhất:**

| Tiêu chí | Kết quả |
|---|---|
| Số router Cisco | 3 |
| Thiết bị sao lưu thành công | 3 |
| Thiết bị thất bại | 0 |
| Thu thập cấu hình | Thành công |
| Lưu bản sao lưu | Thành công |

**Kết luận:** Chương trình đã tự động xử lý ba router Cisco trong cùng một lần chạy mà không cần mở console và đăng nhập thủ công từng router mỗi lần sao lưu.

### 7.5. Test case 5 — Phát hiện thay đổi cấu hình bằng Diff

**Mục tiêu:** Kiểm tra chương trình phát hiện được sự khác biệt giữa cấu hình hiện tại và bản sao lưu trước đó.

Trên router R1, mở console GNS3 và chạy:

```text
enable
configure terminal
interface Loopback2
ip address 10.10.10.3 255.255.255.255
end
write memory
```

Sau đó chạy lại chương trình trên PowerShell:

```powershell
python main.py --mode live
```

Quan sát phần Diff của R1.

**Kết quả mong đợi:** Các dòng cấu hình mới của Loopback2 được hiển thị, ví dụ:

```diff
+interface Loopback2
+ ip address 10.10.10.3 255.255.255.255
```

**Kết luận:** Nếu chương trình hiển thị phần cấu hình mới đúng như trên, chức năng phát hiện thay đổi đã hoạt động. Sau khi kiểm thử, có thể giữ Loopback2 làm dữ liệu kiểm thử hoặc xóa giao diện nếu không còn cần thiết.

### 7.6. Test case 6 — Kiểm tra trường hợp không có thay đổi

**Mục tiêu:** Xác nhận chương trình không báo có thay đổi khi cấu hình thiết bị không đổi so với bản sao lưu trước.

Chạy lại:

```powershell
python main.py --mode live
```

nếu vừa chạy sao lưu thành công và không thay đổi cấu hình thiết bị.

**Kết quả mong đợi:** Chương trình thông báo không phát hiện thay đổi đối với các thiết bị có cấu hình giống bản sao lưu trước đó. Không tạo commit mới nếu không có thay đổi backup cần ghi nhận.

**Kết luận:** Kiểm thử này giúp xác nhận chương trình phân biệt được trường hợp cấu hình thay đổi và không thay đổi.

### 7.7. Test case 7 — Kiểm tra lịch sử và trạng thái Git

Sau khi sao lưu và kiểm thử Diff, chạy:

```powershell
git log -5 --oneline
git status
```

**Mục tiêu:**

- `git log -5 --oneline`: Xem năm commit gần nhất.
- `git status`: Kiểm tra trạng thái các tệp trong repository.

**Kết quả mong đợi:**

- Lịch sử Git hiển thị các commit đã được ghi nhận.
- Nếu không còn thay đổi chưa commit, trạng thái hiển thị working tree sạch.

Nếu chương trình đã commit nhưng GitHub chưa cập nhật, chạy:

```powershell
git push origin master
```

Chỉ thực hiện lệnh này khi branch hiện tại là `master` và repository đã được cấu hình remote tương ứng.

**Kết luận:** Git hỗ trợ theo dõi lịch sử phiên bản của các tệp backup. Commit cục bộ và push lên GitHub là hai thao tác riêng biệt.

### 7.8. Test case 8 — Kiểm tra khả năng xử lý lỗi kết nối

**Mục tiêu:** Kiểm tra cách chương trình xử lý thiết bị không thể kết nối.

Chỉ thực hiện trong môi trường lab được phép. Có thể tạm thời sử dụng một địa chỉ IP kiểm thử không hoạt động trong bản sao `inventory.json`, hoặc ngắt một thiết bị mô phỏng sau khi đã sao lưu dữ liệu cần thiết.

Chạy:

```powershell
python main.py --mode live
```

**Kết quả mong đợi:**

- Chương trình thông báo lỗi đối với thiết bị không kết nối được.
- Lỗi được ghi nhận theo cơ chế xử lý của chương trình.
- Các thiết bị còn lại vẫn được xử lý nếu chương trình hỗ trợ tiếp tục sau lỗi từng thiết bị.

**Lưu ý:** Chỉ ghi test case này là đã thành công sau khi thực sự chạy và quan sát kết quả. Không sử dụng địa chỉ IP không hoạt động để thay thế danh sách thiết bị chính thức khi trình diễn.

### 7.9. Test case 9 — Kiểm tra tệp backup

**Mục tiêu:** Xác nhận các tệp sao lưu được tạo tại đúng thư mục và có nội dung.

Kiểm tra thư mục Cisco:

```powershell
Get-ChildItem .\backups\cisco\
```

Kiểm tra thư mục Linux:

```powershell
Get-ChildItem .\backups\linux\
```

Có thể mở một tệp cấu hình để xem nội dung:

```powershell
Get-Content .\backups\linux\Lubuntu.cfg
```

**Kết quả mong đợi:** Các tệp sao lưu tồn tại, có nội dung hợp lệ và tương ứng với thiết bị đã kiểm thử.

### 7.10. Bảng tổng hợp test case

| STT | Test case | Kết quả |
|---|---|---|
| 1 | Kiểm tra cổng SSH của R1, R2, R3 bằng PowerShell | Đã kiểm tra kết nối |
| 2 | Kiểm tra cổng SSH của Lubuntu | Thành công, `TcpTestSucceeded : True` |
| 3 | Chạy chế độ `linux-test` | Thành công, đã lưu `Lubuntu.cfg` |
| 4 | Sao lưu ba router Cisco bằng `live` | Thành công 3/3 thiết bị |
| 5 | Phát hiện thay đổi cấu hình bằng Diff | Đã kiểm thử với thay đổi Loopback trên R1 |
| 6 | Chạy lại khi không có thay đổi | Đã quan sát trường hợp không có thay đổi |
| 7 | Kiểm tra Git log và trạng thái repository | Có lệnh kiểm tra và lịch sử commit |
| 8 | Xử lý lỗi kết nối | Kiểm thử bổ sung nếu chưa thực hiện |
| 9 | Kiểm tra sự tồn tại và nội dung tệp backup | Thực hiện xác nhận tệp |

## 8. Quy trình chạy lại sau khi tắt máy ảo

Khi cần trình diễn hoặc kiểm thử lại dự án, thực hiện theo thứ tự:

1. Khởi động máy Windows, VMware và GNS3.
2. Bật các router R1, R2, R3 trong GNS3.
3. Kiểm tra kết nối mạng và địa chỉ IP của từng router.
4. Nếu SSH không hoạt động hoặc khóa RSA bị mất, cấu hình lại SSH theo mục 6.
5. Trên PowerShell của Windows, kiểm tra cổng SSH:

   ```powershell
   Test-NetConnection 192.168.234.200 -Port 22
   Test-NetConnection 192.168.234.201 -Port 22
   Test-NetConnection 192.168.234.202 -Port 22
   ```

6. Chạy chương trình sao lưu:

   ```powershell
   python main.py --mode live
   ```

7. Nếu cần kiểm thử Linux, bật máy Lubuntu và chạy:

   ```powershell
   Test-NetConnection 192.168.234.131 -Port 22
   python main.py --mode linux-test --host 192.168.234.131
   ```

8. Kiểm tra kết quả Diff, tệp backup và lịch sử Git:

   ```powershell
   git log -5 --oneline
   git status
   ```

9. Nếu cần cập nhật commit mới lên GitHub:

   ```powershell
   git push origin master
   ```

## 9. Bảo mật

- Không lưu mật khẩu SSH trong `inventory.json`.
- Không đưa mật khẩu, khóa riêng hoặc thông tin xác thực vào GitHub.
- Nên đặt repository ở chế độ Private khi lưu cấu hình thiết bị mạng.
- Cấu hình router có thể chứa thông tin nhạy cảm, kể cả thông tin xác thực đã mã hóa.
- Chỉ thực hiện kiểm thử trên thiết bị được phép quản trị.
- Không sử dụng tài khoản và mật khẩu của môi trường lab cho hệ thống thực tế.

## 10. Hướng phát triển

- Kiểm thử thực tế với thiết bị Juniper.
- Bổ sung báo cáo thống kê các lần sao lưu.
- Bổ sung lịch sao lưu tự động.
- Cải thiện cơ chế thông báo khi phát hiện thay đổi.
- Hoàn thiện chức năng quản lý và tra cứu lịch sử backup.
- Cải thiện bảo mật thông tin xác thực SSH.