import argparse
import json
import logging
import re
import subprocess
from dotenv import load_dotenv
from datetime import datetime
from difflib import unified_diff
from getpass import getpass
from pathlib import Path
import os
import requests
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)
load_dotenv()

# =========================================================
# 1. CAU HINH DUONG DAN
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
INVENTORY_FILE = BASE_DIR / "inventory.json"
DEMO_DIR = BASE_DIR / "demo_configs"
BACKUP_DIR = BASE_DIR / "backups"
LOG_DIR = BASE_DIR / "logs"

BACKUP_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "backup.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)


# =========================================================
# 2. CAC HAM HO TRO
# =========================================================

def safe_name(name):
    """Loai bo ky tu khong phu hop trong ten file."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


def run_git(*args):
    """Chay lenh Git trong thu muc du an."""
    return subprocess.run(
        ["git", *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def initialize_git():
    """Khoi tao Git neu repository chua ton tai."""
    if not (BASE_DIR / ".git").exists():
        run_git("init")
        print("Đã khởi tạo kho lưu trữ Git.")


def load_inventory():
    """Doc va kiem tra danh sach thiet bi tu inventory.json."""
    with open(INVENTORY_FILE, "r", encoding="utf-8") as file:
        devices = json.load(file)

    if not isinstance(devices, list):
        raise ValueError(
            "Dữ liệu inventory.json phải là một danh sách JSON."
        )

    for device in devices:
        if not isinstance(device, dict):
            raise ValueError(
                "Mỗi thiết bị trong inventory phải là một đối tượng JSON."
            )

        for field in ("name", "host", "device_type"):
            if not device.get(field):
                raise ValueError(
                    f"Thiết bị thiếu trường bắt buộc: {field}."
                )

    return devices


def translate_ssh_error(error):
    """
    Chuyen loi SSH thanh thong bao tieng Viet de hieu.
    Chi dung thong bao sai thong tin dang nhap khi co
    dau hieu loi xac thuc.
    """
    if isinstance(error, NetmikoAuthenticationException):
        return (
            "Xác thực SSH thất bại. "
            "Vui lòng kiểm tra tên đăng nhập và mật khẩu."
        )

    if isinstance(error, NetmikoTimeoutException):
        return (
            "Kết nối SSH hết thời gian chờ. "
            "Vui lòng kiểm tra trạng thái thiết bị, địa chỉ IP, "
            "cổng SSH và kết nối mạng."
        )

    error_text = str(error).lower()

    if "authentication failed" in error_text:
        return (
            "Xác thực SSH thất bại. "
            "Vui lòng kiểm tra tên đăng nhập và mật khẩu."
        )

    if "connection refused" in error_text:
        return (
            "Thiết bị từ chối kết nối SSH. "
            "Vui lòng kiểm tra dịch vụ SSH trên thiết bị."
        )

    if "no route to host" in error_text:
        return (
            "Không tìm được đường kết nối đến thiết bị. "
            "Vui lòng kiểm tra cấu hình mạng."
        )

    if "connection reset" in error_text:
        return (
            "Kết nối đến thiết bị bị ngắt đột ngột. "
            "Vui lòng kiểm tra thiết bị và kết nối mạng."
        )

    return (
        "Không thể kết nối hoặc lấy cấu hình từ thiết bị. "
        "Vui lòng kiểm tra nhật ký để biết thêm chi tiết."
    )


# =========================================================
# 3. LAY CAU HINH DEMO
# =========================================================

def get_demo_config(device):
    """Doc cau hinh mau, khong ket noi SSH."""
    config_file = DEMO_DIR / f"{safe_name(device['name'])}.cfg"

    if not config_file.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy file cấu hình mẫu: {config_file.name}"
        )

    config = config_file.read_text(encoding="utf-8")

    if not config.strip():
        raise ValueError(
            f"File cấu hình mẫu đang trống: {config_file.name}"
        )

    return config.rstrip() + "\n"


# =========================================================
# 4. LAY CAU HINH THIET BI QUA SSH
# =========================================================

def get_live_config(device, username, password):
    """Lay cau hinh tu thiet bi Cisco hoac Juniper."""
    device_type = device["device_type"]

    if device_type == "juniper_junos":
        command = "show configuration | display set"
    elif device_type.startswith("cisco_"):
        command = "show running-config"
    else:
        raise ValueError(
            f"Loại thiết bị chưa được hỗ trợ: {device_type}"
        )

    connection_params = {
        "device_type": device_type,
        "host": device["host"],
        "username": username,
        "password": password,
        "conn_timeout": 10,
        "auth_timeout": 10,
        "banner_timeout": 15,
        "fast_cli": False,
    }

    connection = None

    try:
        connection = ConnectHandler(**connection_params)

        output = connection.send_command(
            command,
            read_timeout=60,
        )

        if not output.strip():
            raise RuntimeError(
                "Thiết bị không trả về nội dung cấu hình."
            )

        error_markers = (
            "% Invalid input",
            "% Authorization failed",
            "error: syntax error",
        )

        if any(marker in output for marker in error_markers):
            raise RuntimeError(
                "Thiết bị từ chối lệnh lấy cấu hình "
                "hoặc lệnh không hợp lệ."
            )

        return output.rstrip() + "\n"

    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                logging.warning(
                    "Không thể đóng kết nối SSH tới thiết bị %s",
                    device.get("name", "không xác định"),
                )


# =========================================================
# 5. KET NOI VA THU THAP THONG TIN LINUX
# =========================================================

def get_linux_info(host, username, password):
    """Ket noi SSH den Linux va thu thap thong tin he thong."""
    connection_params = {
        "device_type": "linux",
        "host": host,
        "username": username,
        "password": password,
        "conn_timeout": 10,
        "auth_timeout": 10,
        "banner_timeout": 15,
    }

    with ConnectHandler(**connection_params) as connection:
        hostname = connection.send_command("hostname")
        system_info = connection.send_command("uname -a")
        ip_addresses = connection.send_command("hostname -I")

    if not hostname.strip():
        raise RuntimeError("Không lấy được tên máy Linux.")

    if not system_info.strip():
        raise RuntimeError("Không lấy được thông tin hệ thống Linux.")

    return (
        f"Tên máy: {hostname.strip()}\n"
        f"Địa chỉ máy: {host}\n"
        f"Hệ điều hành: {system_info.strip()}\n"
        f"Địa chỉ IP: {ip_addresses.strip()}\n"
    )


# =========================================================
# 6. LUU VA SO SANH FILE BACKUP
# =========================================================

def save_config(device, config, mode):
    """Doc ban backup cu truoc khi ghi ban moi."""
    if mode == "demo":
        vendor = "demo"
    elif mode == "linux-test":
        vendor = "linux"
    else:
        vendor = device["device_type"].split("_")[0]

    device_dir = BACKUP_DIR / vendor
    device_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{safe_name(device['name'])}.cfg"
    file_path = device_dir / filename

    old_config = (
        file_path.read_text(encoding="utf-8")
        if file_path.exists()
        else None
    )

    file_path.write_text(config, encoding="utf-8")

    return file_path, old_config


def show_diff(old_config, new_config, filename):
    """So sanh noi dung backup cu va moi."""
    if old_config is None:
        print("Đây là lần sao lưu đầu tiên; chưa có bản cũ để so sánh.")
        return True

    diff = list(
        unified_diff(
            old_config.splitlines(),
            new_config.splitlines(),
            fromfile=f"{filename} (bản cũ)",
            tofile=f"{filename} (bản mới)",
            lineterm="",
        )
    )

    if diff:
        print("Phát hiện thay đổi trong cấu hình:")
        print("\n".join(diff))
        return True

    print("Không phát hiện thay đổi trong cấu hình.")
    return False


# =========================================================
# 7. QUAN LY GIT
# =========================================================

def commit_backups():
    """Chi commit cac thay doi trong thu muc backups/."""
    run_git("add", "-A", "--", "backups/")

    result = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
            "--",
            "backups/",
        ],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode == 0:
        print("Git: Không có thay đổi backup mới.")
        return

    if result.returncode != 1:
        detail = result.stderr.strip() or "Không xác định được nguyên nhân."
        raise RuntimeError(
            f"Không thể kiểm tra thay đổi Git: {detail}"
        )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    run_git(
        "commit",
        "-m",
        f"Network backup {timestamp}",
        "--",
        "backups/",
    )

    print("Git: Đã lưu commit cho các thay đổi backup.")


# =========================================================
# 8. KIEM THU SSH LINUX
# =========================================================

def run_linux_test(host):
    """Kiem tra SSH Linux, luu thong tin va so sanh diff."""
    username = input("Tên đăng nhập SSH: ").strip()
    password = getpass("Mật khẩu SSH: ")

    if not username or not password:
        print("Kiểm thử thất bại: Không được để trống tên đăng nhập hoặc mật khẩu.")
        return

    print(f"\nĐang kết nối SSH đến máy Linux {host}...")

    try:
        config = get_linux_info(host, username, password)

        device = {
            "name": "Lubuntu",
            "host": host,
            "device_type": "linux",
        }

        file_path, old_config = save_config(
            device,
            config,
            "linux-test",
        )

        changed = show_diff(
            old_config,
            config,
            str(file_path.relative_to(BASE_DIR)),
        )

        logging.info(
            "LINUX_TEST host=%s changed=%s",
            host,
            changed,
        )

        print(f"\nĐã lưu bản backup: {file_path.relative_to(BASE_DIR)}")

        try:
            commit_backups()
        except Exception:
            logging.exception("Git commit failed during Linux test")
            print("Lỗi Git: Không thể lưu commit backup.")
            print("Vui lòng kiểm tra trạng thái Git và cấu hình người dùng Git.")

    except Exception as error:
        logging.exception("Linux SSH test failed: host=%s", host)

        print("\nKIỂM THỬ THẤT BẠI")
        print(translate_ssh_error(error))
        print(f"Chi tiết kỹ thuật: {type(error).__name__}: {error}")
        print("Không tạo bản backup mới từ lần kết nối thất bại.")


# =========================================================
# 9. QUY TRINH BACKUP CHINH
# =========================================================

def run_backup(mode, devices, username=None, password=None):
    """Chạy backup, ưu tiên thông tin SSH được cấu hình trong .env."""
    if mode == "live":
        username = username or os.getenv("SSH_USERNAME")
        password = password or os.getenv("SSH_PASSWORD")

        if not username or not password:
            raise ValueError(
                "Chưa cấu hình SSH_USERNAME hoặc SSH_PASSWORD trong .env."
            )

    success_count = 0
    failed_count = 0

    print(f"\nChế độ: {mode.upper()}")

    for device in devices:
        name = device["name"]
        host = device["host"]

        print(f"\nĐang sao lưu {name} ({host})...")

        try:
            if mode == "demo":
                config = get_demo_config(device)
            else:
                config = get_live_config(
                    device,
                    username,
                    password,
                )

            file_path, old_config = save_config(
                device,
                config,
                mode,
            )

            changed = show_diff(
                old_config,
                config,
                str(file_path.relative_to(BASE_DIR)),
            )

            logging.info(
                "SUCCESS mode=%s device=%s host=%s changed=%s",
                mode,
                name,
                host,
                changed,
            )

            print(f"Đã lưu: {file_path.relative_to(BASE_DIR)}")
            success_count += 1

        except Exception as error:
            logging.exception(
                "FAILED mode=%s device=%s host=%s",
                mode,
                name,
                host,
            )

            print(f"Sao lưu thất bại: {name}")

            if mode == "live":
                print(translate_ssh_error(error))
                print(
                    f"Chi tiết kỹ thuật: "
                    f"{type(error).__name__}: {error}"
                )
            else:
                print(f"Nguyên nhân: {error}")

            failed_count += 1

    try:
        commit_backups()

    except Exception:
        logging.exception("Git commit failed")
        print("Lỗi Git: Không thể lưu commit backup.")
        print("Vui lòng kiểm tra trạng thái Git và cấu hình người dùng Git.")

    print("\n===== KẾT QUẢ SAO LƯU =====")
    # Giu nguyen cac nhan nay de web_app.py doc duoc ket qua.
    print(f"Thanh cong: {success_count}")
    print(f"That bai: {failed_count}")
    print(f"Tổng số thiết bị: {len(devices)}")

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "total_count": len(devices),
    }


# =========================================================
# 10. HAM MAIN
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description="Hệ thống sao lưu cấu hình và quản lý thiết bị mạng"
    )

    parser.add_argument(
        "--mode",
        choices=["demo", "live", "linux-test"],
        default="demo",
        help=(
            "demo: dùng file mẫu; "
            "live: sao lưu Cisco/Juniper qua SSH; "
            "linux-test: kiểm thử SSH Linux"
        ),
    )

    parser.add_argument(
        "--host",
        default="192.168.234.131",
        help="Địa chỉ IP máy Linux dùng để kiểm thử SSH",
    )

    args = parser.parse_args()

    initialize_git()

    if args.mode == "linux-test":
        run_linux_test(args.host)
        return

    devices = load_inventory()
    username = None
    password = None

    if args.mode == "live":
        username = os.getenv("SSH_USERNAME")
        password = os.getenv("SSH_PASSWORD")

        if not username or not password:
            username = input("Tên đăng nhập SSH: ").strip()
            password = getpass("Mật khẩu SSH: ")

        if not username or not password:
            raise ValueError(
                "Không được để trống tên đăng nhập hoặc mật khẩu SSH."
            )

    run_backup(
        args.mode,
        devices,
        username,
        password,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        logging.exception("Chuong trinh dung do loi")
        print("\nChương trình không thể tiếp tục.")
        print(f"Chi tiết: {type(error).__name__}: {error}")
