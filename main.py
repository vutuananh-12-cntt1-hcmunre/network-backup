
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from difflib import unified_diff
from getpass import getpass

from netmiko import ConnectHandler


BASE_DIR = Path(__file__).resolve().parent
INVENTORY_FILE = BASE_DIR / "inventory.json"
BACKUP_DIR = BASE_DIR / "backups"
LOG_DIR = BASE_DIR / "logs"

BACKUP_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "backup.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)


def run_git(*args):
    """Chạy lệnh Git trong thư mục dự án."""
    return subprocess.run(
        ["git", *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True
    )


def initialize_git():
    """Khởi tạo Git repository nếu chưa có."""
    if not (BASE_DIR / ".git").exists():
        run_git("init")
        print("Da khoi tao Git repository.")


def load_inventory():
    """Đọc danh sách thiết bị từ JSON."""
    with open(INVENTORY_FILE, "r", encoding="utf-8") as file:
        devices = json.load(file)

    if not isinstance(devices, list):
        raise ValueError("Inventory phai la mot danh sach JSON.")

    for device in devices:
        for field in ("name", "host", "device_type"):
            if not device.get(field):
                raise ValueError(
                    f"Thiet bi thieu truong {field}: {device}"
                )

    return devices


def get_config(device, username, password):
    """Kết nối SSH và lấy cấu hình thiết bị."""
    connection_params = {
        "device_type": device["device_type"],
        "host": device["host"],
        "username": username,
        "password": password,
        "conn_timeout": 10,
        "auth_timeout": 10,
        "banner_timeout": 15,
        "fast_cli": False,
    }

    connection = ConnectHandler(**connection_params)

    try:
        device_type = device["device_type"]

        if device_type == "juniper_junos":
            command = "show configuration | display set"
        elif device_type.startswith("cisco_"):
            command = "show running-config"
        else:
            raise ValueError(
                f"Chua cau hinh lenh backup cho {device_type}"
            )

        output = connection.send_command(
            command,
            read_timeout=60
        )

        if not output.strip():
            raise RuntimeError("Cau hinh tra ve rong.")

        # Chặn một số thông báo lỗi CLI phổ biến.
        error_markers = (
            "% Invalid input",
            "% Authorization failed",
            "syntax error,"
            "error: syntax error",
        )

        if any(marker in output for marker in error_markers):
            raise RuntimeError(
                "Lenh lay cau hinh co the da that bai."
            )

        return output.rstrip() + "\n"

    finally:
        connection.disconnect()


def save_config(device, config):
    """Lưu cấu hình hiện tại và trả về nội dung trước đó."""
    vendor = device["device_type"].split("_")[0]
    device_dir = BACKUP_DIR / vendor
    device_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        c if c.isalnum() or c in "-_." else "_"
        for c in device["name"]
    )

    file_path = device_dir / f"{safe_name}.cfg"

    old_config = (
        file_path.read_text(encoding="utf-8")
        if file_path.exists()
        else None
    )

    file_path.write_text(config, encoding="utf-8")
    return file_path, old_config


def show_diff(old_config, new_config, filename):
    """So sánh cấu hình cũ và cấu hình mới."""
    if old_config is None:
        print("Lan dau sao luu: chua co ban cu de so sanh.")
        return False

    diff = list(unified_diff(
        old_config.splitlines(keepends=True),
        new_config.splitlines(keepends=True),
        fromfile=f"{filename} (cu)",
        tofile=f"{filename} (moi)"
    ))

    if diff:
        print("\n".join(line.rstrip("\n") for line in diff))
        return True

    print("Khong phat hien thay doi cau hinh.")
    return False


def commit_backups():
    """Commit file backup nếu có thay đổi."""
    run_git("add", "backups")

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("Git: khong co thay doi moi.")
        return

    if result.returncode != 1:
        raise RuntimeError("Khong the kiem tra thay doi Git.")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_git("commit", "-m", f"Network backup {timestamp}")

    print("Git: da commit cau hinh thay doi.")


def main():
    initialize_git()
    devices = load_inventory()

    username = input("SSH username: ").strip()
    password = getpass("SSH password: ")

    success_count = 0
    failed_count = 0

    for device in devices:
        name = device["name"]
        print(f"\nDang sao luu {name} ({device['host']})...")

        try:
            config = get_config(device, username, password)
            file_path, old_config = save_config(device, config)

            changed = show_diff(
                old_config,
                config,
                str(file_path.relative_to(BASE_DIR))
            )

            logging.info(
                "SUCCESS device=%s host=%s changed=%s",
                name, device["host"], changed
            )

            print(f"Da luu: {file_path.relative_to(BASE_DIR)}")
            success_count += 1

        except Exception as error:
            logging.exception(
                "FAILED device=%s host=%s",
                name, device["host"]
            )
            print(f"LOI {name}: {error}")
            failed_count += 1

    # Chỉ commit các file backup nếu có thay đổi.
    try:
        commit_backups()
    except Exception:
        logging.exception("Git commit failed")
        print(
            "LOI GIT: kiem tra git status va cau hinh Git user."
        )

    print("\n===== KET QUA SAO LUU =====")
    print(f"Thanh cong: {success_count}")
    print(f"That bai:   {failed_count}")
    print(f"Tong cong:  {len(devices)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        logging.exception("Chuong trinh dung do loi")
        print(f"Chuong trinh dung: {error}")
