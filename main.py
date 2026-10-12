
import argparse
import json
import logging
import re
import subprocess
from datetime import datetime
from difflib import unified_diff
from getpass import getpass
from pathlib import Path

from netmiko import ConnectHandler


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


def safe_name(name):
    """Loại bỏ ký tự không phù hợp trong tên file."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


def run_git(*args):
    """Chạy lệnh Git trong thư mục dự án."""
    return subprocess.run(
        ["git", *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )


def initialize_git():
    """Khởi tạo Git nếu dự án chưa có repository."""
    if not (BASE_DIR / ".git").exists():
        run_git("init")
        print("Da khoi tao Git repository.")


def load_inventory():
    """Đọc danh sách thiết bị từ inventory.json."""
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


def get_demo_config(device):
    """Đọc cấu hình mẫu, không kết nối SSH."""
    config_file = DEMO_DIR / f"{safe_name(device['name'])}.cfg"

    if not config_file.is_file():
        raise FileNotFoundError(
            f"Khong tim thay file cau hinh mau: {config_file}"
        )

    config = config_file.read_text(encoding="utf-8")

    if not config.strip():
        raise ValueError(f"File cau hinh mau rong: {config_file}")

    return config.rstrip() + "\n"


def get_live_config(device, username, password):
    """Kết nối thiết bị thật bằng Netmiko và lấy cấu hình."""
    device_type = device["device_type"]

    if device_type == "juniper_junos":
        command = "show configuration | display set"
    elif device_type.startswith("cisco_"):
        command = "show running-config"
    else:
        raise ValueError(
            f"Device type chua duoc ho tro: {device_type}"
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

    connection = ConnectHandler(**connection_params)

    try:
        output = connection.send_command(command, read_timeout=60)

        if not output.strip():
            raise RuntimeError("Thiet bi tra ve cau hinh rong.")

        error_markers = (
            "% Invalid input",
            "% Authorization failed",
            "error: syntax error",
        )

        if any(marker in output for marker in error_markers):
            raise RuntimeError(
                "Lenh lay cau hinh co the da that bai."
            )

        return output.rstrip() + "\n"

    finally:
        connection.disconnect()


def save_config(device, config, mode):
    """Lưu cấu hình và trả về bản cũ nếu đã tồn tại."""
    if mode == "demo":
        vendor = "demo"
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
    """So sánh cấu hình cũ và mới."""
    if old_config is None:
        print("Lan dau sao luu: chua co ban cu de so sanh.")
        return True

    diff = list(
        unified_diff(
            old_config.splitlines(),
            new_config.splitlines(),
            fromfile=f"{filename} (cu)",
            tofile=f"{filename} (moi)",
            lineterm="",
        )
    )

    if diff:
        print("\n".join(diff))
        return True

    print("Khong phat hien thay doi cau hinh.")
    return False


def commit_backups():
    """Commit các file backup khi có thay đổi."""
    run_git("add", "--", "backups/")

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if result.returncode == 0:
        print("Git: khong co thay doi moi.")
        return

    if result.returncode != 1:
        raise RuntimeError("Khong the kiem tra thay doi Git.")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    run_git(
        "commit",
        "-m",
        f"Network backup {timestamp}",
    )

    print("Git: da commit cau hinh thay doi.")


def main():
    parser = argparse.ArgumentParser(
        description="Network Backup and Inventory"
    )
    parser.add_argument(
        "--mode",
        choices=["demo", "live"],
        default="demo",
        help="demo: dung file mau; live: ket noi thiet bi qua SSH",
    )
    args = parser.parse_args()
    mode = args.mode

    initialize_git()
    devices = load_inventory()

    username = None
    password = None

    if mode == "live":
        username = input("SSH username: ").strip()
        password = getpass("SSH password: ")

        if not username or not password:
            raise ValueError("Username va password khong duoc de trong.")

    print(f"\nChe do: {mode.upper()}")

    success_count = 0
    failed_count = 0

    for device in devices:
        name = device["name"]
        host = device["host"]

        print(f"\nDang sao luu {name} ({host})...")

        try:
            if mode == "demo":
                config = get_demo_config(device)
            else:
                config = get_live_config(device, username, password)

            file_path, old_config = save_config(device, config, mode)

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

            print(f"Da luu: {file_path.relative_to(BASE_DIR)}")
            success_count += 1

        except Exception as error:
            logging.exception(
                "FAILED mode=%s device=%s host=%s",
                mode,
                name,
                host,
            )
            print(f"LOI {name}: {error}")
            failed_count += 1

    try:
        commit_backups()
    except Exception as error:
        logging.exception("Git commit failed")
        print(f"LOI GIT: {error}")
        print("Hay kiem tra git status va cau hinh Git user.")

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
