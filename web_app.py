import os
import requests
from dotenv import load_dotenv
import io
import logging
import re
import subprocess
import threading
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
import json
import ipaddress

from main import (
    BASE_DIR,
    BACKUP_DIR,
    INVENTORY_FILE,
    load_inventory,
    run_backup,
)

from flask import Flask, jsonify, render_template, request


load_dotenv()

app = Flask(__name__)

# =========================================================
# GNS3 AUTO-DISCOVERY
# =========================================================

GNS3_URL = os.getenv("GNS3_URL", "http://127.0.0.1:3080").rstrip("/")
GNS3_USER = os.getenv("GNS3_USER", "admin")
GNS3_PASSWORD = os.getenv("GNS3_PASSWORD", "")


def discover_gns3_nodes():
    """Lay danh sach node tu project GNS3 dang mo."""
    if not GNS3_PASSWORD:
        raise RuntimeError(
            "Chua cau hinh mat khau GNS3 API trong bien moi truong."
        )

    session = requests.Session()
    session.auth = (GNS3_USER, GNS3_PASSWORD)

    try:
        response = session.get(
            f"{GNS3_URL}/v2/projects",
            timeout=10,
        )
        response.raise_for_status()
        projects = response.json()

        opened_projects = [
            project for project in projects
            if project.get("status") == "opened"
        ]

        if not opened_projects:
            raise RuntimeError(
                "Khong co project GNS3 nao dang mo."
            )

        # Uu tien project dang mo co node router.
        discovered = []

        for project in opened_projects:
            project_id = project.get("project_id")
            if not project_id:
                continue

            response = session.get(
                f"{GNS3_URL}/v2/projects/{project_id}/nodes",
                timeout=10,
            )
            response.raise_for_status()

            for node in response.json():
                node_type = str(node.get("node_type", "")).lower()

                # Khong tu dong dua Cloud va Ethernet switch vao inventory.
                if node_type not in {"dynamips", "iou", "qemu", "vpcs"}:
                    continue

                discovered.append({
                    "project_id": project_id,
                    "project_name": project.get("name"),
                    "node_id": node.get("node_id"),
                    "name": node.get("name"),
                    "node_type": node_type,
                    "status": node.get("status"),
                    "console_host": node.get("console_host"),
                    "console": node.get("console"),
                })

        return discovered

    finally:
        session.close()




@app.get("/api/gns3/discover")
def gns3_discover():
    """Phat hien node GNS3 va doi chieu voi inventory."""
    try:
        nodes = discover_gns3_nodes()
        devices = load_inventory()

        def normalize_name(name):
            """Chuan hoa ten node de doi chieu voi inventory."""
            name = str(name or "").strip().casefold()

            if name.startswith("cisco-"):
                name = name[len("cisco-"):]

            return name

        inventory_names = {
            normalize_name(device.get("name", ""))
            for device in devices
        }

        for node in nodes:
            node_name = normalize_name(node.get("name", ""))
            node["in_inventory"] = (
                bool(node_name) and node_name in inventory_names
            )

        return jsonify({
            "count": len(nodes),
            "nodes": nodes,
            "message": (
                "Da lay danh sach node tu GNS3. "
                "Voi node moi, hay nhap IP quan tri va "
                "chon loai thiet bi truoc khi them vao Inventory."
            ),
        }), 200

    except requests.RequestException:
        logger.exception("GNS3 API request failed")

        return jsonify({
            "error": (
                "Khong the ket noi GNS3 API. "
                "Hay kiem tra GNS3 server va SSH tunnel."
            ),
        }), 502


@app.post("/api/inventory/add")
def add_inventory_device():
    """Them thiet bi moi vao inventory.json."""
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Du lieu yeu cau khong hop le."
        }), 400

    name = data.get("name")
    host = data.get("host")
    device_type = data.get("device_type")

    if not all(
        isinstance(value, str)
        for value in (name, host, device_type)
    ):
        return jsonify({
            "error": "Vui long cung cap ten, IP va loai thiet bi."
        }), 400

    name = name.strip()
    host = host.strip()
    device_type = device_type.strip()

    # Kiem tra ten thiet bi.
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        return jsonify({
            "error": "Ten thiet bi khong hop le."
        }), 400

    # Kiem tra dia chi IP.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return jsonify({
            "error": "Dia chi IP khong hop le."
        }), 400

    # Chi chap nhan cac loai thiet bi da duoc ho tro.
    supported_types = {"cisco_ios", "juniper_junos"}

    if device_type not in supported_types:
        return jsonify({
            "error": "Loai thiet bi chua duoc ho tro."
        }), 400

    try:
        devices = load_inventory()

        # Khong cho phep trung ten.
        if any(
            str(device.get("name", "")).casefold() == name.casefold()
            for device in devices
        ):
            return jsonify({
                "error": "Ten thiet bi da ton tai trong Inventory."
            }), 409

        # Khong cho phep trung IP.
        if any(
            str(device.get("host", "")).strip() == host
            for device in devices
        ):
            return jsonify({
                "error": "Dia chi IP da duoc su dung trong Inventory."
            }), 409

        new_device = {
            "name": name,
            "host": host,
            "device_type": device_type,
        }

        updated_devices = devices + [new_device]

        # Ghi file tam truoc khi thay the inventory.json.
        temp_file = INVENTORY_FILE.with_suffix(".tmp")

        try:
            with temp_file.open("w", encoding="utf-8") as file:
                json.dump(
                    updated_devices,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
                file.write("\n")

            os.replace(temp_file, INVENTORY_FILE)

        finally:
            if temp_file.exists():
                temp_file.unlink()

        logger.info(
            "Added device to inventory: %s (%s)",
            name,
            host,
        )

        return jsonify({
            "message": f"Da them {name} vao Inventory.",
            "device": new_device,
        }), 201

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot add device to inventory")

        return jsonify({
            "error": "Khong the cap nhat inventory.json."
        }), 500

    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        logger.exception("GNS3 discovery failed")
        return jsonify({"error": str(error)}), 500



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

backup_lock = threading.Lock()

LOG_FILE = (BASE_DIR / "logs" / "backup.log").resolve()

LOG_LEVELS = {"INFO", "WARNING", "ERROR"}
DEFAULT_LOG_LIMIT = 50
MAX_LOG_LIMIT = 200
MAX_SEARCH_LENGTH = 200
MAX_CONFIG_SIZE = 2 * 1024 * 1024

LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
    r"\s*[-|]\s*"
    r"(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)"
    r"\s*[-|:]\s*"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)

backup_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "return_code": None,
    "output": "",
    "error": None,
    "success_count": 0,
    "failed_count": 0,
    "total_count": 0,
}


def get_backup_path(device):
    """Tao duong dan backup tu thong tin inventory."""
    name = device.get("name")
    device_type = device.get("device_type")

    if not isinstance(name, str) or not isinstance(device_type, str):
        raise ValueError("Thong tin thiet bi khong hop le.")

    # Chi chap nhan ten file don gian, tranh path traversal.
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError("Ten thiet bi khong hop le.")

    vendor = device_type.split("_")[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", vendor):
        raise ValueError("Loai thiet bi khong hop le.")

    base = BACKUP_DIR.resolve()
    path = (BACKUP_DIR / vendor / f"{name}.cfg").resolve()

    if not path.is_relative_to(base):
        raise ValueError("Duong dan backup khong hop le.")

    return path


def get_git_history(limit=10):
    try:
        result = subprocess.run(
            [
                "git", "log", f"-{limit}",
                "--pretty=format:%h|%s|%ad",
                "--date=iso", "--", "backups/",
            ],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=True,
        )

        history = []

        for line in result.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                history.append({
                    "commit": parts[0],
                    "message": parts[1],
                    "date": parts[2],
                })

        return history

    except (subprocess.SubprocessError, OSError):
        logger.exception("Cannot read Git history")
        return []


def get_backup_devices():
    devices = load_inventory()
    results = []

    for device in devices:
        backup_path = get_backup_path(device)
        exists = backup_path.is_file()

        results.append({
            "name": device["name"],
            "host": device["host"],
            "device_type": device["device_type"],
            "backup_exists": exists,
            "backup_path": (
                backup_path.relative_to(BASE_DIR.resolve()).as_posix()
                if exists else None
            ),
            "backup_modified": (
                datetime.fromtimestamp(
                    backup_path.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S")
                if exists else None
            ),
        })

    return results


def get_device_details(device_name):
    """Lay chi tiet thiet bi va noi dung file backup da luu."""
    if not isinstance(device_name, str) or not device_name:
        return None

    devices = load_inventory()
    device = next(
        (item for item in devices if item.get("name") == device_name),
        None,
    )

    if device is None:
        return None

    backup_path = get_backup_path(device)
    exists = backup_path.is_file()
    config = None
    config_error = None
    modified = None
    relative_path = backup_path.relative_to(
        BASE_DIR.resolve()
    ).as_posix()

    if exists:
        try:
            size = backup_path.stat().st_size

            if size > MAX_CONFIG_SIZE:
                config_error = "File cau hinh vuot qua gioi han hien thi."
            else:
                config = backup_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

            modified = datetime.fromtimestamp(
                backup_path.stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M:%S")

        except OSError:
            logger.exception("Cannot read backup for %s", device_name)
            config_error = "Khong the doc file backup."

    return {
        "name": device["name"],
        "host": device["host"],
        "device_type": device["device_type"],
        "backup_exists": exists,
        "backup_path": relative_path if exists else None,
        "backup_modified": modified,
        "config": config,
        "config_error": config_error,
        "git_history": get_device_git_history(relative_path),
    }


def get_device_git_history(relative_path, limit=10):
    """Lay cac commit thay doi file backup cua mot thiet bi."""
    try:
        result = subprocess.run(
            [
                "git", "log", f"-{limit}",
                "--format=%h|%s|%ad",
                "--date=iso",
                "--",
                relative_path,
            ],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=True,
        )

        history = []

        for line in result.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                history.append({
                    "commit": parts[0],
                    "message": parts[1],
                    "date": parts[2],
                })

        return history

    except (subprocess.SubprocessError, OSError):
        logger.exception("Cannot read device Git history")
        return []


def get_restore_candidates():
    """Tim file backup bi thieu nhung van con trong Git."""
    candidates = []

    for device in load_inventory():
        backup_path = get_backup_path(device)

        if backup_path.is_file():
            continue

        relative_path = backup_path.relative_to(
            BASE_DIR.resolve()
        ).as_posix()

        try:
            result = subprocess.run(
                [
                    "git", "log", "--all", "-n", "20",
                    "--format=%H|%h|%ad|%s",
                    "--date=iso",
                    "--",
                    relative_path,
                ],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            logger.exception(
                "Cannot inspect Git history for %s", relative_path
            )
            continue

        versions = []
        seen = set()

        for line in result.stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue

            full_hash, short_hash, date, message = parts

            if full_hash in seen:
                continue

            try:
                exists = subprocess.run(
                    [
                        "git", "cat-file", "-e",
                        f"{full_hash}:{relative_path}",
                    ],
                    cwd=BASE_DIR,
                    capture_output=True,
                    timeout=10,
                ).returncode == 0
            except (subprocess.SubprocessError, OSError):
                exists = False

            if exists:
                versions.append({
                    "commit": short_hash,
                    "commit_full": full_hash,
                    "date": date,
                    "message": message,
                })
                seen.add(full_hash)

        if versions:
            candidates.append({
                "name": device["name"],
                "path": relative_path,
                "host": device["host"],
                "device_type": device["device_type"],
                "versions": versions,
            })

    return candidates


def parse_log_line(line, line_number):
    line = line.rstrip("\r\n")

    if not line.strip():
        return None

    match = LOG_PATTERN.match(line)

    if match:
        level = match.group("level").upper()

        if level == "WARN":
            level = "WARNING"
        elif level in {"DEBUG", "CRITICAL"}:
            level = "ERROR" if level == "CRITICAL" else "INFO"

        return {
            "line": line_number,
            "timestamp": match.group("timestamp"),
            "level": level,
            "message": match.group("message").strip(),
            "raw": line,
        }

    upper_line = line.upper()

    if "CRITICAL" in upper_line or "ERROR" in upper_line:
        level = "ERROR"
    elif "WARNING" in upper_line or "WARN" in upper_line:
        level = "WARNING"
    else:
        level = "INFO"

    return {
        "line": line_number,
        "timestamp": "",
        "level": level,
        "message": line,
        "raw": line,
    }


def read_log_entries():
    if not LOG_FILE.is_relative_to(BASE_DIR.resolve()):
        raise OSError("Duong dan log khong hop le.")

    if not LOG_FILE.is_file():
        return []

    entries = []

    with LOG_FILE.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as log_file:
        for line_number, line in enumerate(log_file, start=1):
            entry = parse_log_line(line, line_number)
            if entry is not None:
                entries.append(entry)

    entries.reverse()
    return entries


def run_backup_task(username, password):
    buffer = io.StringIO()
    success_count = 0
    failed_count = 0
    total_count = 0
    error_message = None
    return_code = 1

    try:
        devices = load_inventory()
        total_count = len(devices)

        with redirect_stdout(buffer):
            run_backup(
                mode="live",
                devices=devices,
                username=username,
                password=password,
            )

        output = buffer.getvalue()

        for line in output.splitlines():
            line = line.strip()

            if line.startswith("Thanh cong:"):
                try:
                    success_count = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

            elif line.startswith("That bai:"):
                try:
                    failed_count = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

        if "Thanh cong:" not in output or "That bai:" not in output:
            error_message = (
                "Khong doc duoc tong ket backup. "
                "Hay kiem tra logs/backup.log."
            )
        elif failed_count > 0:
            error_message = (
                f"Co {failed_count} thiet bi that bai. "
                "Hay xem chi tiet ket qua backup."
            )
        else:
            return_code = 0

    except Exception:
        logger.exception("Live backup failed")
        error_message = (
            "Khong the hoan tat backup. "
            "Hay kiem tra inventory va logs/backup.log."
        )

    finally:
        with backup_lock:
            backup_state.update({
                "running": False,
                "finished_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
                "return_code": return_code,
                "output": buffer.getvalue()[-20000:],
                "error": error_message,
                "success_count": success_count,
                "failed_count": failed_count,
                "total_count": total_count,
            })


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    try:
        devices = get_backup_devices()
        history = get_git_history()

        return jsonify({
            "total_devices": len(devices),
            "backed_up": sum(
                1 for device in devices
                if device["backup_exists"]
            ),
            "not_backed_up": sum(
                1 for device in devices
                if not device["backup_exists"]
            ),
            "devices": devices,
            "git_history": history,
        })

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot load dashboard")
        return jsonify({
            "error": "Khong the doc inventory hoac du lieu backup."
        }), 500


@app.get("/api/inventory")
def inventory():
    try:
        return jsonify(get_backup_devices())

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot load inventory")
        return jsonify({
            "error": "Khong the doc danh sach thiet bi."
        }), 500


@app.get("/api/devices/<device_name>")
def device_details(device_name):
    """API chi tiet mot thiet bi theo ten."""
    try:
        details = get_device_details(device_name)

        if details is None:
            return jsonify({
                "error": "Khong tim thay thiet bi."
            }), 404

        return jsonify(details)

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception(
            "Cannot load device details for %s", device_name
        )
        return jsonify({
            "error": "Khong the doc chi tiet thiet bi."
        }), 500


@app.get("/api/restore/available")
def restore_available():
    try:
        return jsonify({"files": get_restore_candidates()})
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot list restorable backup files")
        return jsonify({
            "error": "Khong the doc danh sach file co the khoi phuc."
        }), 500


@app.post("/api/restore")
def restore_backup_file():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Du lieu yeu cau khong hop le."}), 400

    requested_path = data.get("path")
    commit = data.get("commit")

    if not isinstance(requested_path, str) or not isinstance(commit, str):
        return jsonify({
            "error": "Thieu duong dan file hoac commit."
        }), 400

    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        return jsonify({"error": "Ma commit khong hop le."}), 400

    try:
        candidates = get_restore_candidates()
        candidate = next(
            (item for item in candidates if item["path"] == requested_path),
            None,
        )

        if candidate is None:
            return jsonify({
                "error": "File khong bi mat hoac khong co phien ban trong Git."
            }), 404

        if not any(
            version["commit"] == commit
            or version["commit_full"] == commit
            for version in candidate["versions"]
        ):
            return jsonify({
                "error": "Commit khong thuoc danh sach phien ban hop le cua file."
            }), 400

        subprocess.run(
            [
                "git", "restore",
                "--source", commit,
                "--worktree",
                "--",
                candidate["path"],
            ],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=True,
        )

        restored_path = (BASE_DIR / candidate["path"]).resolve()

        if not restored_path.is_file():
            raise OSError("File van chua duoc tao sau khi khoi phuc.")

        logger.info(
            "Restored backup file %s from Git commit %s",
            candidate["path"],
            commit,
        )

        return jsonify({
            "message": (
                f"Da khoi phuc {candidate['path']} "
                f"tu Git commit {commit}."
            ),
            "path": candidate["path"],
        })

    except subprocess.CalledProcessError as error:
        logger.error("Git restore failed: %s", error.stderr or error)
        return jsonify({
            "error": "Git khong the khoi phuc file. Hay kiem tra lich su Git."
        }), 500

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot restore backup file")
        return jsonify({
            "error": "Khong the khoi phuc file backup."
        }), 500


@app.get("/api/git-history")
def git_history():
    return jsonify(get_git_history())


@app.get("/api/logs")
def system_logs():
    level = request.args.get("level", "ALL").strip().upper()
    search = request.args.get("search", "").strip()[:MAX_SEARCH_LENGTH]

    try:
        page = max(1, int(request.args.get("page", "1")))
        limit = int(request.args.get("limit", str(DEFAULT_LOG_LIMIT)))
    except (TypeError, ValueError):
        return jsonify({
            "error": "Tham so page hoac limit khong hop le."
        }), 400

    if level not in {"ALL", *LOG_LEVELS}:
        return jsonify({"error": "Muc log khong hop le."}), 400

    limit = max(1, min(limit, MAX_LOG_LIMIT))

    try:
        all_entries = read_log_entries()
        entries = all_entries

        if level != "ALL":
            entries = [
                entry for entry in entries
                if entry["level"] == level
            ]

        if search:
            keyword = search.casefold()
            entries = [
                entry for entry in entries
                if keyword in entry["raw"].casefold()
            ]

        total = len(entries)
        start = (page - 1) * limit
        paginated_entries = entries[start:start + limit]
        level_counts = Counter(
            entry["level"] for entry in all_entries
        )

        return jsonify({
            "logs": paginated_entries,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
            "level_counts": {
                "INFO": level_counts.get("INFO", 0),
                "WARNING": level_counts.get("WARNING", 0),
                "ERROR": level_counts.get("ERROR", 0),
            },
            "log_file": "logs/backup.log",
        })

    except (OSError, UnicodeError):
        logger.exception("Cannot read system log")
        return jsonify({
            "error": (
                "Khong the doc logs/backup.log. "
                "Hay kiem tra file va quyen truy cap."
            )
        }), 500



@app.post("/api/backup/live")
def start_live_backup():
    data = request.get_json(silent=True)

    # Ưu tien su dung thong tin SSH tu file .env.
    username = os.getenv("SSH_USERNAME")
    password = os.getenv("SSH_PASSWORD")

    # Neu .env chua du thong tin, cho phep dung thong tin tu giao dien.
    if not username or not password:
        if not isinstance(data, dict):
            return jsonify({
                "error": "Chua cau hinh SSH trong .env va du lieu yeu cau khong hop le."
            }), 400

        username = data.get("username")
        password = data.get("password")

    if not isinstance(username, str) or not username.strip():
        return jsonify({
            "error": "Vui long cau hinh SSH_USERNAME trong .env."
        }), 400

    if not isinstance(password, str) or not password:
        return jsonify({
            "error": "Vui long cau hinh SSH_PASSWORD trong .env."
        }), 400

    try:
        devices = load_inventory()

        if not devices:
            return jsonify({
                "error": "Inventory khong co thiet bi."
            }), 400

    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot load inventory for backup")
        return jsonify({
            "error": "Khong doc duoc inventory.json."
        }), 500

    with backup_lock:
        if backup_state["running"]:
            return jsonify({
                "error": "Backup dang chay. Vui long doi ket thuc."
            }), 409

        backup_state.update({
            "running": True,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "return_code": None,
            "output": "",
            "error": None,
            "success_count": 0,
            "failed_count": 0,
            "total_count": len(devices),
        })

    try:
        thread = threading.Thread(
            target=run_backup_task,
            args=(username.strip(), password),
            daemon=True,
        )
        thread.start()

    except Exception:
        logger.exception("Cannot start backup thread")

        with backup_lock:
            backup_state.update({
                "running": False,
                "error": "Khong the khoi dong backup.",
                "finished_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            })

        return jsonify({
            "error": "Khong the khoi dong backup."
        }), 500

    return jsonify({
        "message": "Da khoi dong Live Backup.",
        "status": "running",
    }), 202


@app.get("/api/backup/status")
def live_backup_status():
    with backup_lock:
        return jsonify(dict(backup_state))


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )
