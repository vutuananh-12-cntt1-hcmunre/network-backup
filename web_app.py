
import io
import logging
import re
import subprocess
import threading
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from main import BASE_DIR, BACKUP_DIR, load_inventory, run_backup


app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

backup_lock = threading.Lock()

# Chi doc file log da xac dinh trong thu muc du an.
LOG_FILE = (BASE_DIR / "logs" / "backup.log").resolve()

LOG_LEVELS = {"INFO", "WARNING", "ERROR"}
DEFAULT_LOG_LIMIT = 50
MAX_LOG_LIMIT = 200
MAX_SEARCH_LENGTH = 200

# Ho tro cac dong log theo format:
# 2026-10-26 10:30:00 - INFO - Backup thanh cong
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
        device_type = device["device_type"]
        vendor = device_type.split("_")[0]
        backup_path = BACKUP_DIR / vendor / f"{device['name']}.cfg"
        exists = backup_path.is_file()

        results.append({
            "name": device["name"],
            "host": device["host"],
            "device_type": device_type,
            "backup_exists": exists,
            "backup_path": (
                str(backup_path.relative_to(BASE_DIR))
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



def get_restore_candidates():
    """Return missing inventory backup files that exist in Git history."""
    candidates = []
    for device in load_inventory():
        device_type = device["device_type"]
        vendor = device_type.split("_")[0]
        backup_path = (BACKUP_DIR / vendor / f"{device['name']}.cfg").resolve()
        if not backup_path.is_relative_to(BACKUP_DIR.resolve()):
            continue
        if backup_path.is_file():
            continue

        relative_path = backup_path.relative_to(BASE_DIR.resolve()).as_posix()
        try:
            result = subprocess.run(
                ["git", "log", "--all", "-n", "20",
                 "--format=%H|%h|%ad|%s", "--date=iso", "--", relative_path],
                cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=10, check=True,
            )
        except (subprocess.SubprocessError, OSError):
            logger.exception("Cannot inspect Git history for %s", relative_path)
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
            # Include only commits where this path exists as a Git object.
            exists = subprocess.run(
                ["git", "cat-file", "-e", f"{full_hash}:{relative_path}"],
                cwd=BASE_DIR, capture_output=True, timeout=10,
            ).returncode == 0
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
                "device_type": device_type,
                "versions": versions,
            })
    return candidates

def parse_log_line(line, line_number):
    """Chuyen mot dong log thanh du lieu JSON cho giao dien."""
    line = line.rstrip("\r\n")

    if not line.strip():
        return None

    match = LOG_PATTERN.match(line)

    if match:
        timestamp = match.group("timestamp")
        level = match.group("level").upper()
        message = match.group("message").strip()

        if level == "WARN":
            level = "WARNING"
        elif level == "CRITICAL":
            level = "ERROR"

        return {
            "line": line_number,
            "timestamp": timestamp,
            "level": level,
            "message": message,
            "raw": line,
        }

    # Neu dong log khong dung format chuan, van hien thi de
    # nguoi dung co the xem va tim kiem noi dung.
    upper_line = line.upper()

    if "CRITICAL" in upper_line or "ERROR" in upper_line:
        level = "ERROR"
    elif "WARNING" in upper_line or "WARN" in upper_line:
        level = "WARNING"
    elif "INFO" in upper_line:
        level = "INFO"
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
    """Doc file log theo thu tu moi nhat truoc."""
    if not LOG_FILE.is_relative_to(BASE_DIR.resolve()):
        raise OSError("Duong dan log khong hop le.")

    if not LOG_FILE.is_file():
        return []

    entries = []

    # errors='replace' tranh loi khi file co ky tu khong hop le.
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
    """Chay Live Backup trong thread nen."""
    buffer = io.StringIO()
    success_count = 0
    failed_count = 0
    total_count = 0
    error_message = None
    return_code = 1

    try:
        devices = load_inventory()
        total_count = len(devices)

        # Khong ghi username/password vao backup_state.
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
                    success_count = int(
                        line.split(":", 1)[1].strip()
                    )
                except ValueError:
                    pass

            elif line.startswith("That bai:"):
                try:
                    failed_count = int(
                        line.split(":", 1)[1].strip()
                    )
                except ValueError:
                    pass

        if "Thanh cong:" not in output or "That bai:" not in output:
            error_message = (
                "Khong doc duoc tong ket backup. "
                "Hay kiem tra logs/backup.log."
            )
        elif failed_count > 0:
            return_code = 1
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


@app.get("/api/restore/available")
def restore_available():
    try:
        return jsonify({"files": get_restore_candidates()})
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot list restorable backup files")
        return jsonify({"error": "Khong the doc danh sach file co the khoi phuc."}), 500


@app.post("/api/restore")
def restore_backup_file():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Du lieu yeu cau khong hop le."}), 400

    requested_path = data.get("path")
    commit = data.get("commit")
    if not isinstance(requested_path, str) or not isinstance(commit, str):
        return jsonify({"error": "Thieu duong dan file hoac commit."}), 400
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        return jsonify({"error": "Ma commit khong hop le."}), 400

    try:
        candidates = get_restore_candidates()
        candidate = next((item for item in candidates if item["path"] == requested_path), None)
        if candidate is None:
            return jsonify({"error": "File khong bi mat hoac khong co phien ban trong Git."}), 404
        if not any(v["commit"] == commit or v["commit_full"] == commit for v in candidate["versions"]):
            return jsonify({"error": "Commit khong thuoc danh sach phien ban hop le cua file."}), 400

        # Restore only the validated inventory backup path; do not stage changes.
        subprocess.run(
            ["git", "restore", "--source", commit, "--worktree", "--", candidate["path"]],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15, check=True,
        )
        restored_path = (BASE_DIR / candidate["path"]).resolve()
        if not restored_path.is_file():
            raise OSError("File van chua duoc tao sau khi khoi phuc.")

        logger.info("Restored backup file %s from Git commit %s", candidate["path"], commit)
        return jsonify({
            "message": f"Da khoi phuc {candidate['path']} tu Git commit {commit}.",
            "path": candidate["path"],
        })
    except subprocess.CalledProcessError as error:
        logger.error("Git restore failed: %s", error.stderr or error)
        return jsonify({"error": "Git khong the khoi phuc file. Hay kiem tra lich su Git."}), 500
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Cannot restore backup file")
        return jsonify({"error": "Khong the khoi phuc file backup."}), 500


@app.get("/api/git-history")
def git_history():
    return jsonify(get_git_history())


@app.get("/api/logs")
def system_logs():
    """
    Query parameters:
      level: ALL, INFO, WARNING, ERROR
      search: tu khoa tim kiem
      page: trang bat dau tu 1
      limit: so dong moi trang, toi da 200
    """
    level = request.args.get("level", "ALL").strip().upper()
    search = request.args.get("search", "").strip()
    search = search[:MAX_SEARCH_LENGTH]

    try:
        page = max(1, int(request.args.get("page", "1")))
        limit = int(
            request.args.get("limit", str(DEFAULT_LOG_LIMIT))
        )
    except (TypeError, ValueError):
        return jsonify({
            "error": "Tham so page hoac limit khong hop le."
        }), 400

    if level not in {"ALL", *LOG_LEVELS}:
        return jsonify({
            "error": "Muc log khong hop le."
        }), 400

    limit = max(1, min(limit, MAX_LOG_LIMIT))

    try:
        entries = read_log_entries()

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
            entry["level"] for entry in read_log_entries()
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
            "error": "Khong the doc logs/backup.log. "
                     "Hay kiem tra file va quyen truy cap."
        }), 500


@app.post("/api/backup/live")
def start_live_backup():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Du lieu yeu cau khong hop le."
        }), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not username.strip():
        return jsonify({
            "error": "Vui long nhap SSH username."
        }), 400

    if not isinstance(password, str) or not password:
        return jsonify({
            "error": "Vui long nhap SSH password."
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
            "started_at": datetime.now().isoformat(
                timespec="seconds"
            ),
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
