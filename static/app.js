
const $ = (selector) => document.querySelector(selector);

let backupPolling = false;
let backupPollTimer = null;

// Trang thai phan trang nhat ky
const logsState = {
    page: 1,
    limit: 20,
    total: 0,
    totalPages: 1,
    level: "ALL",
    search: "",
    loading: false
};

let logsSearchTimer = null;

function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[char]);
}

function showError(message) {
    const element = $("#error-message");
    element.textContent = message;
    element.hidden = false;
}

function clearError() {
    $("#error-message").hidden = true;
    $("#error-message").textContent = "";
}

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            Accept: "application/json",
            ...(options.headers || {})
        }
    });

    let data;

    try {
        data = await response.json();
    } catch {
        throw new Error("Máy chủ trả về dữ liệu không hợp lệ.");
    }

    if (!response.ok) {
        throw new Error(data.error || "Yêu cầu không thành công.");
    }

    return data;
}

function backupStatus(device) {
    return device.backup_exists
        ? '<span class="pill success">● Đã có file</span>'
        : '<span class="pill warning">● Chưa có file</span>';
}

function renderDeviceRows(devices, mode = "dashboard") {
    const target = mode === "dashboard"
        ? "#dashboard-devices"
        : mode === "devices"
            ? "#all-devices"
            : "#backup-devices";

    const columns = mode === "dashboard" ? 4 : mode === "devices" ? 5 : 4;

    if (!Array.isArray(devices) || devices.length === 0) {
        $(target).innerHTML = `
            <tr>
                <td colspan="${columns}" class="empty">
                    Không có thiết bị trong inventory.
                </td>
            </tr>`;
        return;
    }

    const rows = devices.map((device) => {
        const name = escapeHTML(device.name);
        const host = escapeHTML(device.host);
        const type = escapeHTML(device.device_type);
        const path = escapeHTML(device.backup_path || "Chưa có file backup");
        const modified = escapeHTML(device.backup_modified || "Chưa có dữ liệu");

        if (mode === "dashboard") {
            return `
                <tr>
                    <td><span class="device-name">${name}</span></td>
                    <td>${host}</td>
                    <td>${type}</td>
                    <td>${backupStatus(device)}</td>
                </tr>`;
        }

        if (mode === "devices") {
            return `
                <tr>
                    <td><span class="device-name">${name}</span></td>
                    <td>${host}</td>
                    <td>${type}</td>
                    <td>${backupStatus(device)}</td>
                    <td>${modified}</td>
                </tr>`;
        }

        return `
            <tr>
                <td><span class="device-name">${name}</span></td>
                <td>${path}</td>
                <td>${modified}</td>
                <td>${backupStatus(device)}</td>
            </tr>`;
    }).join("");

    $(target).innerHTML = rows;
}

function renderGit(target, history) {
    if (!Array.isArray(history) || history.length === 0) {
        $(target).innerHTML = `
            <p class="empty">
                Chưa tìm thấy commit backup hoặc không đọc được lịch sử Git.
            </p>`;
        return;
    }

    $(target).innerHTML = history.map((item) => `
        <article class="git-item">
            <div class="git-symbol">⌘</div>
            <div>
                <p class="git-message">${escapeHTML(item.message)}</p>
                <div class="git-meta">
                    Commit: ${escapeHTML(item.commit)}<br>
                    ${escapeHTML(item.date)}
                </div>
            </div>
        </article>
    `).join("");
}

function updateDashboard(data) {
    $("#total-devices").textContent = data.total_devices ?? 0;
    $("#backed-up").textContent = data.backed_up ?? 0;
    $("#not-backed-up").textContent = data.not_backed_up ?? 0;
    $("#commit-count").textContent = data.git_history?.length ?? 0;

    renderDeviceRows(data.devices || [], "dashboard");
    renderDeviceRows(data.devices || [], "devices");
    renderDeviceRows(data.devices || [], "backups");

    renderGit("#dashboard-git", data.git_history || []);
    renderGit("#all-git", data.git_history || []);

    $("#server-status").textContent = "Đã kết nối";
    $(".sidebar .status-dot").style.background = "#39d98a";
}

async function loadDashboard() {
    const button = $("#refresh-btn");

    clearError();
    button.disabled = true;
    button.textContent = "Đang tải...";

    try {
        const data = await fetchJSON("/api/dashboard");
        updateDashboard(data);
    } catch (error) {
        $("#server-status").textContent = "Có lỗi kết nối";
        $(".sidebar .status-dot").style.background = "#e65c5c";
        showError(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "↻ Làm mới dữ liệu";
    }
}

// ==================== DIEU HUONG ====================

function navigate(page) {
    const titles = {
        dashboard: "Dashboard",
        devices: "Thiết bị mạng",
        backups: "Quản lý Backup",
        git: "Lịch sử Git",
        logs: "Nhật ký hệ thống"
    };

    if (!titles[page]) return;

    document.querySelectorAll(".page").forEach((element) => {
        element.classList.toggle("active", element.id === `page-${page}`);
    });

    document.querySelectorAll(".nav-link").forEach((element) => {
        element.classList.toggle("active", element.dataset.page === page);
    });

    $("#page-title").textContent = titles[page];
    $("#breadcrumb-page").textContent = titles[page];

    if (page === "logs") {
        loadLogs();
    }

    if (page === "backups") {
        initializeRestoreUI();
        loadRestoreCandidates();
    }
}

document.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", (event) => {
        event.preventDefault();
        navigate(link.dataset.page);
    });
});

document.querySelectorAll("[data-goto]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.goto));
});

$("#refresh-btn").addEventListener("click", loadDashboard);

// ==================== BACKUP ====================

function setBackupRunning(running) {
    $("#start-backup-btn").disabled = running;
    $("#start-backup-btn").textContent = running
        ? "Đang chạy backup..."
        : "▶ Bắt đầu Live Backup";

    $("#backup-progress").hidden = !running;
}

function setBackupPill(text, state = "") {
    const pill = $("#backup-status-pill");
    pill.textContent = text;
    pill.className = "pill";

    if (state === "success") {
        pill.classList.add("success");
    } else if (state === "warning") {
        pill.classList.add("warning");
    }
}

function renderBackupState(state) {
    setBackupRunning(Boolean(state.running));

    let statusText = "Chưa chạy";

    if (state.running) {
        statusText = "Đang chạy";
    } else if (state.finished_at) {
        statusText = state.return_code === 0 ? "Hoàn tất" : "Có lỗi";
    }

    $("#backup-result-status").textContent = statusText;
    $("#backup-success-count").textContent = state.success_count ?? 0;
    $("#backup-failed-count").textContent = state.failed_count ?? 0;
    $("#backup-total-count").textContent = state.total_count ?? 0;
    $("#backup-started-at").textContent = state.started_at || "—";
    $("#backup-finished-at").textContent = state.finished_at || "—";

    $("#backup-output").textContent = state.output ||
        (state.running
            ? "Backup đang chạy. Đầu ra chi tiết sẽ xuất hiện sau khi kết thúc."
            : "Chưa có đầu ra.");

    const errorElement = $("#backup-error");

    if (state.error) {
        errorElement.textContent = state.error;
        errorElement.hidden = false;
    } else {
        errorElement.textContent = "";
        errorElement.hidden = true;
    }

    if (state.running) {
        setBackupPill("Đang chạy", "warning");
    } else if (state.finished_at && state.return_code === 0) {
        setBackupPill("Hoàn tất", "success");
    } else if (state.finished_at && state.return_code !== 0) {
        setBackupPill("Có lỗi", "warning");
    } else {
        setBackupPill("Chưa chạy");
    }
}

async function pollBackupStatus() {
    if (backupPolling) return;

    backupPolling = true;

    try {
        while (true) {
            const state = await fetchJSON("/api/backup/status");
            renderBackupState(state);

            if (!state.running) break;

            await new Promise((resolve) => {
                backupPollTimer = setTimeout(resolve, 2000);
            });
        }
    } catch (error) {
        showError("Không thể đọc trạng thái backup: " + error.message);
    } finally {
        backupPolling = false;
        backupPollTimer = null;
    }
}

const backupForm = $("#backup-form");

backupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();

    const username = $("#ssh-username").value.trim();
    const password = $("#ssh-password").value;

    if (!username || !password) {
        showError("Vui lòng nhập đầy đủ username và password SSH.");
        return;
    }

    const button = $("#start-backup-btn");
    button.disabled = true;

    try {
        await fetchJSON("/api/backup/live", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ username, password })
        });

        $("#ssh-password").value = "";
        setBackupRunning(true);
        setBackupPill("Đang chạy", "warning");

        await pollBackupStatus();
        await loadDashboard();

        // Cap nhat nhat ky sau khi backup ket thuc
        await loadLogs({ silent: true });
    } catch (error) {
        showError(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "▶ Bắt đầu Live Backup";
    }
});

// ==================== NHAT KY HE THONG ====================

function getLogLevelClass(level) {
    const normalized = String(level || "").toUpperCase();

    if (normalized === "ERROR") return "error";
    if (normalized === "WARNING" || normalized === "WARN") return "warning";
    if (normalized === "INFO") return "info";

    return "unknown";
}

function renderLogCounts(counts = {}) {
    const info = Number(counts.INFO ?? 0);
    const warning = Number(counts.WARNING ?? counts.WARN ?? 0);
    const error = Number(counts.ERROR ?? 0);

    $("#logs-counts").innerHTML = `
        <span class="log-count log-count-info">INFO: ${info}</span>
        <span class="log-count log-count-warning">WARNING: ${warning}</span>
        <span class="log-count log-count-error">ERROR: ${error}</span>
    `;
}

function renderLogs(data) {
    const tbody = $("#logs-table-body");
    const logs = Array.isArray(data.logs) ? data.logs : [];

    logsState.total = Number(data.total ?? 0);
    logsState.page = Number(data.page ?? logsState.page);
    logsState.totalPages = Math.max(1, Number(data.total_pages ?? 1));

    if (logs.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="3" class="empty">
                    Không tìm thấy nhật ký phù hợp.
                </td>
            </tr>`;
    } else {
        tbody.innerHTML = logs.map((log) => {
            const timestamp = escapeHTML(log.timestamp || "—");
            const level = String(log.level || "UNKNOWN").toUpperCase();
            const levelClass = getLogLevelClass(level);
            const message = escapeHTML(log.message || log.raw || "");

            return `
                <tr>
                    <td class="log-timestamp">${timestamp}</td>
                    <td>
                        <span class="log-level log-level-${levelClass}">
                            ${escapeHTML(level)}
                        </span>
                    </td>
                    <td class="log-message">${message}</td>
                </tr>`;
        }).join("");
    }

    $("#logs-summary").textContent =
        `Tổng ${logsState.total} dòng nhật ký phù hợp với bộ lọc hiện tại.`;

    $("#logs-page-info").textContent =
        `Trang ${logsState.page} / ${logsState.totalPages}`;

    $("#logs-prev-btn").disabled =
        logsState.loading || logsState.page <= 1;

    $("#logs-next-btn").disabled =
        logsState.loading || logsState.page >= logsState.totalPages;

    renderLogCounts(data.level_counts || {});
}

async function loadLogs(options = {}) {
    const { silent = false } = options;

    if (logsState.loading) return;

    logsState.loading = true;

    const refreshButton = $("#logs-refresh-btn");
    const searchButton = $("#logs-search-btn");

    if (refreshButton) refreshButton.disabled = true;
    if (searchButton) searchButton.disabled = true;

    $("#logs-prev-btn").disabled = true;
    $("#logs-next-btn").disabled = true;

    if (!silent) {
        $("#logs-summary").textContent = "Đang tải nhật ký...";
    }

    try {
        const params = new URLSearchParams({
            level: logsState.level,
            search: logsState.search,
            page: String(logsState.page),
            limit: String(logsState.limit)
        });

        const data = await fetchJSON(`/api/logs?${params.toString()}`);
        renderLogs(data);
    } catch (error) {
        $("#logs-table-body").innerHTML = `
            <tr>
                <td colspan="3" class="empty">
                    Không thể tải nhật ký: ${escapeHTML(error.message)}
                </td>
            </tr>`;

        $("#logs-summary").textContent = "Tải nhật ký thất bại.";

        if (!silent) {
            showError("Không thể tải nhật ký hệ thống: " + error.message);
        }
    } finally {
        logsState.loading = false;

        if (refreshButton) refreshButton.disabled = false;
        if (searchButton) searchButton.disabled = false;

        $("#logs-prev-btn").disabled = logsState.page <= 1;
        $("#logs-next-btn").disabled =
            logsState.page >= logsState.totalPages;
    }
}

function applyLogFilters() {
    logsState.level = $("#logs-level").value;
    logsState.search = $("#logs-search").value.trim();
    logsState.page = 1;

    clearError();
    loadLogs();
}

$("#logs-level").addEventListener("change", applyLogFilters);

$("#logs-search-btn").addEventListener("click", applyLogFilters);

$("#logs-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
        event.preventDefault();
        applyLogFilters();
    }
});

$("#logs-search").addEventListener("input", () => {
    clearTimeout(logsSearchTimer);

    logsSearchTimer = setTimeout(() => {
        logsState.level = $("#logs-level").value;
        logsState.search = $("#logs-search").value.trim();
        logsState.page = 1;
        loadLogs();
    }, 400);
});

$("#logs-refresh-btn").addEventListener("click", () => {
    clearError();
    loadLogs();
});

$("#logs-prev-btn").addEventListener("click", () => {
    if (logsState.page > 1 && !logsState.loading) {
        logsState.page -= 1;
        loadLogs();
    }
});

$("#logs-next-btn").addEventListener("click", () => {
    if (logsState.page < logsState.totalPages && !logsState.loading) {
        logsState.page += 1;
        loadLogs();
    }
});

// ==================== KHOI PHUC BACKUP TU GIT ====================

function initializeRestoreUI() {
    const page = $("#page-backups");

    if (!page || $("#restore-panel")) return;

    const panel = document.createElement("section");
    panel.id = "restore-panel";
    panel.className = "panel";
    panel.style.marginBottom = "20px";

    panel.innerHTML = `
        <div class="panel-header"
             style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
            <div>
                <h3>Khôi phục file backup</h3>
                <p>Liệt kê file backup bị mất nhưng còn phiên bản trong Git.</p>
            </div>
            <button type="button" class="btn btn-primary" id="restore-refresh-btn">
                ↻ Tìm file có thể khôi phục
            </button>
        </div>

        <div id="restore-message" role="status" style="margin:12px 0;"></div>

        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Thiết bị</th>
                        <th>File</th>
                        <th>Phiên bản Git</th>
                        <th>Thao tác</th>
                    </tr>
                </thead>
                <tbody id="restore-table-body">
                    <tr>
                        <td colspan="4" class="empty">
                            Nhấn “Tìm file có thể khôi phục” để kiểm tra.
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    `;

    page.prepend(panel);

    $("#restore-refresh-btn").addEventListener(
        "click",
        loadRestoreCandidates
    );
}

async function loadRestoreCandidates() {
    const button = $("#restore-refresh-btn");
    const tbody = $("#restore-table-body");
    const message = $("#restore-message");

    if (!button || !tbody || !message) return;

    button.disabled = true;
    button.textContent = "Đang kiểm tra...";
    message.textContent = "";

    try {
        const data = await fetchJSON("/api/restore/available");
        const files = Array.isArray(data.files) ? data.files : [];

        if (files.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="empty">
                        Không có file backup nào bị mất có thể khôi phục từ Git.
                    </td>
                </tr>`;
            return;
        }

        tbody.innerHTML = files.map((file) => {
            const versions = (Array.isArray(file.versions) ? file.versions : [])
                .map((version) => `
                    <option value="${escapeHTML(version.commit)}">
                        ${escapeHTML(version.commit)} —
                        ${escapeHTML(version.date)} —
                        ${escapeHTML(version.message)}
                    </option>
                `).join("");

            return `
                <tr>
                    <td>
                        ${escapeHTML(file.name)}
                        <br>
                        <small>${escapeHTML(file.host)}</small>
                    </td>
                    <td>${escapeHTML(file.path)}</td>
                    <td>
                        <select class="restore-version"
                                aria-label="Chọn phiên bản cho ${escapeHTML(file.name)}">
                            ${versions}
                        </select>
                    </td>
                    <td>
                        <button type="button"
                                class="btn btn-primary restore-file-btn"
                                data-path="${escapeHTML(file.path)}"
                                ${versions ? "" : "disabled"}>
                            Khôi phục
                        </button>
                    </td>
                </tr>
            `;
        }).join("");

        tbody.querySelectorAll(".restore-file-btn").forEach((restoreButton) => {
            restoreButton.addEventListener("click", async () => {
                const row = restoreButton.closest("tr");
                const versionSelect = row.querySelector(".restore-version");
                const commit = versionSelect?.value;
                const path = restoreButton.dataset.path;

                if (!commit) {
                    message.textContent = "Không có phiên bản Git để khôi phục.";
                    return;
                }

                if (!confirm(`Khôi phục ${path} từ phiên bản Git ${commit}?`)) {
                    return;
                }

                restoreButton.disabled = true;
                message.textContent = "Đang khôi phục file...";

                try {
                    const result = await fetchJSON("/api/restore", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ path, commit })
                    });

                    message.textContent =
                        result.message || "Khôi phục thành công.";

                    await loadDashboard();
                    await loadRestoreCandidates();
                } catch (error) {
                    message.textContent =
                        "Khôi phục thất bại: " + error.message;
                } finally {
                    restoreButton.disabled = false;
                }
            });
        });
    } catch (error) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="empty">
                    Không thể tải danh sách: ${escapeHTML(error.message)}
                </td>
            </tr>`;

        message.textContent =
            "Kiểm tra API khôi phục trong web_app.py: " + error.message;
    } finally {
        button.disabled = false;
        button.textContent = "↻ Tìm file có thể khôi phục";
    }
}

// Khoi phuc trang thai neu nguoi dung tai lai trang khi backup dang chay.
pollBackupStatus();
loadDashboard();
