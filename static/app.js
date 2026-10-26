
const $ = (selector) => document.querySelector(selector);

let backupPolling = false;
let backupPollTimer = null;
let currentDeviceName = null;

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
    if (!element) return;
    element.textContent = message;
    element.hidden = false;
}

function clearError() {
    const element = $("#error-message");
    if (!element) return;
    element.hidden = true;
    element.textContent = "";
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

// ==================== DANH SACH THIET BI ====================

function renderDeviceRows(devices, mode = "dashboard") {
    const target = mode === "dashboard"
        ? "#dashboard-devices"
        : mode === "devices"
            ? "#all-devices"
            : "#backup-devices";

    const columns = mode === "dashboard"
        ? 4
        : mode === "devices" ? 5 : 4;

    const tbody = $(target);
    if (!tbody) return;

    if (!Array.isArray(devices) || devices.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="${columns}" class="empty">
                    Không có thiết bị trong inventory.
                </td>
            </tr>`;
        return;
    }

    tbody.innerHTML = devices.map((device) => {
        const name = escapeHTML(device.name);
        const host = escapeHTML(device.host);
        const type = escapeHTML(device.device_type);
        const path = escapeHTML(
            device.backup_path || "Chưa có file backup"
        );
        const modified = escapeHTML(
            device.backup_modified || "Chưa có dữ liệu"
        );

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
                <tr class="device-row"
                    data-device-name="${name}"
                    tabindex="0"
                    role="button"
                    aria-label="Xem chi tiết ${name}"
                    title="Nhấn để xem chi tiết thiết bị">
                    <td>
                        <span class="device-name">${name}</span>
                        <small class="device-open-hint">Xem chi tiết ↗</small>
                    </td>
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

    if (mode === "devices") {
        tbody.querySelectorAll(".device-row").forEach((row) => {
            const open = () => {
                openDeviceDetails(row.dataset.deviceName);
            };

            row.addEventListener("click", open);

            row.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    open();
                }
            });
        });
    }
}

function renderGit(target, history) {
    const element = $(target);
    if (!element) return;

    if (!Array.isArray(history) || history.length === 0) {
        element.innerHTML = `
            <p class="empty">
                Chưa tìm thấy commit backup hoặc không đọc được lịch sử Git.
            </p>`;
        return;
    }

    element.innerHTML = history.map((item) => `
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

    const dot = $(".sidebar .status-dot");
    if (dot) dot.style.background = "#39d98a";
}

async function loadDashboard() {
    const button = $("#refresh-btn");

    clearError();

    if (button) {
        button.disabled = true;
        button.textContent = "Đang tải...";
    }

    try {
        const data = await fetchJSON("/api/dashboard");
        updateDashboard(data);
    } catch (error) {
        $("#server-status").textContent = "Có lỗi kết nối";

        const dot = $(".sidebar .status-dot");
        if (dot) dot.style.background = "#e65c5c";

        showError(error.message);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "↻ Làm mới dữ liệu";
        }
    }
}

// ==================== CHI TIET THIET BI ====================

function initializeDeviceDetailUI() {
    const page = $("#page-devices");

    if (!page || $("#device-detail-panel")) return;

    const panel = document.createElement("section");
    panel.id = "device-detail-panel";
    panel.className = "panel";
    panel.hidden = true;
    panel.style.marginTop = "20px";

    panel.innerHTML = `
        <div class="panel-header"
             style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
            <div>
                <h3 id="device-detail-title">Chi tiết thiết bị</h3>
                <p id="device-detail-subtitle">
                    Thông tin và cấu hình backup đã lưu.
                </p>
            </div>
            <button type="button" class="btn btn-primary" id="device-detail-back">
                ← Quay lại danh sách
            </button>
        </div>

        <div id="device-detail-message" role="status"></div>

        <div id="device-detail-content">
            <p class="empty">Chọn một thiết bị để xem chi tiết.</p>
        </div>
    `;

    page.appendChild(panel);

    $("#device-detail-back").addEventListener("click", closeDeviceDetails);
}

async function openDeviceDetails(deviceName) {
    initializeDeviceDetailUI();

    const panel = $("#device-detail-panel");
    const content = $("#device-detail-content");
    const message = $("#device-detail-message");

    if (!panel || !content || !message) return;

    currentDeviceName = deviceName;
    panel.hidden = false;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });

    $("#device-detail-title").textContent = `Chi tiết ${deviceName}`;
    $("#device-detail-subtitle").textContent =
        "Đang tải thông tin thiết bị...";
    content.innerHTML = '<p class="empty">Đang tải dữ liệu...</p>';
    message.textContent = "";

    try {
        const device = await fetchJSON(
            `/api/devices/${encodeURIComponent(deviceName)}`
        );

        // Bo qua ket qua cu neu nguoi dung da chon thiet bi khac.
        if (currentDeviceName !== deviceName) return;

        renderDeviceDetails(device);
    } catch (error) {
        if (currentDeviceName !== deviceName) return;

        content.innerHTML = `
            <p class="empty">
                Không thể tải chi tiết thiết bị:
                ${escapeHTML(error.message)}
            </p>`;
    }
}

function renderDeviceDetails(device) {
    const content = $("#device-detail-content");

    $("#device-detail-title").textContent = device.name;
    $("#device-detail-subtitle").textContent =
        `${device.host} · ${device.device_type}`;

    const configContent = device.config !== null &&
        device.config !== undefined
        ? escapeHTML(device.config)
        : "";

    let configHTML;

    if (!device.backup_exists) {
        configHTML = `
            <div class="empty">
                Thiết bị chưa có file backup.
                Hãy thực hiện Live Backup để tạo bản cấu hình.
            </div>`;
    } else if (device.config_error) {
        configHTML = `
            <div class="empty">${escapeHTML(device.config_error)}</div>`;
    } else {
        configHTML = `
            <div style="position:relative;">
                <button type="button"
                        class="btn btn-primary"
                        id="copy-device-config"
                        style="margin-bottom:10px;">
                    Sao chép cấu hình
                </button>
                <pre id="device-config"
                     style="white-space:pre;overflow:auto;max-height:500px;padding:16px;border-radius:8px;background:#111827;color:#e5e7eb;font:13px/1.6 Consolas,monospace;">${configContent}</pre>
            </div>`;
    }

    const history = Array.isArray(device.git_history)
        ? device.git_history
        : [];

    const historyHTML = history.length
        ? history.map((item) => `
            <article class="git-item">
                <div class="git-symbol">⌘</div>
                <div>
                    <p class="git-message">
                        ${escapeHTML(item.message)}
                    </p>
                    <div class="git-meta">
                        Commit: ${escapeHTML(item.commit)}<br>
                        ${escapeHTML(item.date)}
                    </div>
                </div>
            </article>
        `).join("")
        : '<p class="empty">Chưa có lịch sử Git cho file này.</p>';

    content.innerHTML = `
        <div class="panel" style="margin:12px 0;">
            <h3>Thông tin thiết bị</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-top:16px;">
                <div>
                    <small>Địa chỉ IP</small>
                    <p><strong>${escapeHTML(device.host)}</strong></p>
                </div>
                <div>
                    <small>Loại thiết bị</small>
                    <p><strong>${escapeHTML(device.device_type)}</strong></p>
                </div>
                <div>
                    <small>Trạng thái file backup</small>
                    <p>${backupStatus(device)}</p>
                </div>
                <div>
                    <small>File backup</small>
                    <p><strong>${escapeHTML(device.backup_path || "Chưa có file")}</strong></p>
                </div>
                <div>
                    <small>Cập nhật file</small>
                    <p><strong>${escapeHTML(device.backup_modified || "Chưa có dữ liệu")}</strong></p>
                </div>
            </div>
        </div>

        <div class="panel" style="margin:12px 0;">
            <h3>Cấu hình đã sao lưu</h3>
            <p class="git-meta" style="margin:8px 0 16px;">
                Nội dung được đọc từ file backup trên máy chủ, không phải cấu hình trực tiếp đang chạy trên router.
            </p>
            ${configHTML}
        </div>

        <div class="panel" style="margin:12px 0;">
            <h3>Lịch sử Git của thiết bị</h3>
            <div style="margin-top:12px;">${historyHTML}</div>
        </div>
    `;

    const copyButton = $("#copy-device-config");

    if (copyButton) {
        copyButton.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(device.config);
                copyButton.textContent = "Đã sao chép";
            } catch {
                copyButton.textContent =
                    "Không sao chép được — hãy chọn nội dung thủ công";
            }
        });
    }
}

function closeDeviceDetails() {
    currentDeviceName = null;

    const panel = $("#device-detail-panel");
    if (panel) {
        panel.hidden = true;
    }

    const table = $("#all-devices");
    if (table) {
        table.closest(".table-wrapper, .table-wrap, .panel")
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
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
        element.classList.toggle(
            "active",
            element.id === `page-${page}`
        );
    });

    document.querySelectorAll(".nav-link").forEach((element) => {
        element.classList.toggle(
            "active",
            element.dataset.page === page
        );
    });

    $("#page-title").textContent = titles[page];
    $("#breadcrumb-page").textContent = titles[page];

    if (page === "logs") loadLogs();

    if (page === "backups") {
        initializeRestoreUI();
        loadRestoreCandidates();
    }

    if (page === "devices") {
        initializeDeviceDetailUI();
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

// ==================== LIVE BACKUP ====================

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

    if (state === "success") pill.classList.add("success");
    if (state === "warning") pill.classList.add("warning");
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

    errorElement.textContent = state.error || "";
    errorElement.hidden = !state.error;

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

$("#backup-form").addEventListener("submit", async (event) => {
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
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });

        $("#ssh-password").value = "";
        setBackupRunning(true);
        setBackupPill("Đang chạy", "warning");

        await pollBackupStatus();
        await loadDashboard();
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
    $("#logs-counts").innerHTML = `
        <span class="log-count log-count-info">INFO: ${Number(counts.INFO ?? 0)}</span>
        <span class="log-count log-count-warning">WARNING: ${Number(counts.WARNING ?? counts.WARN ?? 0)}</span>
        <span class="log-count log-count-error">ERROR: ${Number(counts.ERROR ?? 0)}</span>
    `;
}

function renderLogs(data) {
    const tbody = $("#logs-table-body");
    const logs = Array.isArray(data.logs) ? data.logs : [];

    logsState.total = Number(data.total ?? 0);
    logsState.page = Number(data.page ?? logsState.page);
    logsState.totalPages = Math.max(1, Number(data.total_pages ?? 1));

    if (!logs.length) {
        tbody.innerHTML = `
            <tr><td colspan="3" class="empty">
                Không tìm thấy nhật ký phù hợp.
            </td></tr>`;
    } else {
        tbody.innerHTML = logs.map((log) => {
            const level = String(log.level || "UNKNOWN").toUpperCase();

            return `
                <tr>
                    <td class="log-timestamp">${escapeHTML(log.timestamp || "—")}</td>
                    <td>
                        <span class="log-level log-level-${getLogLevelClass(level)}">
                            ${escapeHTML(level)}
                        </span>
                    </td>
                    <td class="log-message">${escapeHTML(log.message || log.raw || "")}</td>
                </tr>`;
        }).join("");
    }

    $("#logs-summary").textContent =
        `Tổng ${logsState.total} dòng nhật ký phù hợp với bộ lọc hiện tại.`;

    $("#logs-page-info").textContent =
        `Trang ${logsState.page} / ${logsState.totalPages}`;

    $("#logs-prev-btn").disabled = logsState.loading || logsState.page <= 1;
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

    if (!silent) $("#logs-summary").textContent = "Đang tải nhật ký...";

    try {
        const params = new URLSearchParams({
            level: logsState.level,
            search: logsState.search,
            page: String(logsState.page),
            limit: String(logsState.limit)
        });

        renderLogs(await fetchJSON(`/api/logs?${params.toString()}`));
    } catch (error) {
        $("#logs-table-body").innerHTML = `
            <tr><td colspan="3" class="empty">
                Không thể tải nhật ký: ${escapeHTML(error.message)}
            </td></tr>`;

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
        logsState.page--;
        loadLogs();
    }
});

$("#logs-next-btn").addEventListener("click", () => {
    if (logsState.page < logsState.totalPages && !logsState.loading) {
        logsState.page++;
        loadLogs();
    }
});

// ==================== RESTORE TU GIT ====================

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
                <p>File backup bị mất nhưng còn phiên bản trong Git.</p>
            </div>
            <button type="button" class="btn btn-primary" id="restore-refresh-btn">
                ↻ Tìm file có thể khôi phục
            </button>
        </div>
        <div id="restore-message" role="status" style="margin:12px 0;"></div>
        <div class="table-wrapper">
            <table>
                <thead><tr>
                    <th>Thiết bị</th><th>File</th>
                    <th>Phiên bản Git</th><th>Thao tác</th>
                </tr></thead>
                <tbody id="restore-table-body">
                    <tr><td colspan="4" class="empty">
                        Nhấn nút để kiểm tra file có thể khôi phục.
                    </td></tr>
                </tbody>
            </table>
        </div>`;

    page.prepend(panel);
    $("#restore-refresh-btn").addEventListener("click", loadRestoreCandidates);
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

        if (!files.length) {
            tbody.innerHTML = `
                <tr><td colspan="4" class="empty">
                    Không có file backup bị mất có thể khôi phục.
                </td></tr>`;
            return;
        }

        tbody.innerHTML = files.map((file) => {
            const versions = (file.versions || []).map((version) => `
                <option value="${escapeHTML(version.commit)}">
                    ${escapeHTML(version.commit)} —
                    ${escapeHTML(version.date)} —
                    ${escapeHTML(version.message)}
                </option>`).join("");

            return `
                <tr>
                    <td>${escapeHTML(file.name)}<br>
                        <small>${escapeHTML(file.host)}</small></td>
                    <td>${escapeHTML(file.path)}</td>
                    <td><select class="restore-version">${versions}</select></td>
                    <td><button type="button"
                        class="btn btn-primary restore-file-btn"
                        data-path="${escapeHTML(file.path)}"
                        ${versions ? "" : "disabled"}>Khôi phục</button></td>
                </tr>`;
        }).join("");

        tbody.querySelectorAll(".restore-file-btn").forEach((restoreButton) => {
            restoreButton.addEventListener("click", async () => {
                const row = restoreButton.closest("tr");
                const commit = row.querySelector(".restore-version")?.value;
                const path = restoreButton.dataset.path;

                if (!commit) {
                    message.textContent = "Không có phiên bản để khôi phục.";
                    return;
                }

                if (!confirm(`Khôi phục ${path} từ commit ${commit}?`)) return;

                restoreButton.disabled = true;
                message.textContent = "Đang khôi phục file...";

                try {
                    const result = await fetchJSON("/api/restore", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ path, commit })
                    });

                    message.textContent = result.message || "Khôi phục thành công.";
                    await loadDashboard();
                    await loadRestoreCandidates();
                } catch (error) {
                    message.textContent = "Khôi phục thất bại: " + error.message;
                } finally {
                    restoreButton.disabled = false;
                }
            });
        });
    } catch (error) {
        tbody.innerHTML = `
            <tr><td colspan="4" class="empty">
                Không thể tải danh sách: ${escapeHTML(error.message)}
            </td></tr>`;
        message.textContent = "Lỗi API khôi phục: " + error.message;
    } finally {
        button.disabled = false;
        button.textContent = "↻ Tìm file có thể khôi phục";
    }
}

// ==================== KHOI DONG ====================
// ==================== GNS3 AUTO-DISCOVERY ====================


 // ==================== GNS3 AUTO-DISCOVERY ====================

const gns3DiscoverButton = $("#gns3-discover-btn");

async function addGns3NodeToInventory(node) {
    const name = String(node.name || "").trim();

    if (!name) {
        throw new Error("Node không có tên hợp lệ.");
    }

    // IP quan tri khong duoc tu dong suy ra tu GNS3.
    const host = prompt(
        `Nhập IP quản trị của thiết bị ${name}:`
    );

    if (host === null) return;

    const normalizedHost = host.trim();

    if (!normalizedHost) {
        throw new Error("Bạn chưa nhập IP quản trị.");
    }

    const detectedType = String(node.node_type || "").toLowerCase();

    let deviceType = "cisco_ios";

    if (
        detectedType.includes("juniper") ||
        detectedType.includes("junos")
    ) {
        deviceType = "juniper_junos";
    } else {
        const choice = prompt(
            `Chọn loại thiết bị cho ${name}:\n` +
            "1. Cisco IOS (nhập 1)\n" +
            "2. Juniper JunOS (nhập 2)",
            "1"
        );

        if (choice === null) return;

        if (choice.trim() === "1") {
            deviceType = "cisco_ios";
        } else if (choice.trim() === "2") {
            deviceType = "juniper_junos";
        } else {
            throw new Error("Lựa chọn loại thiết bị không hợp lệ.");
        }
    }

    const result = await fetchJSON("/api/inventory/add", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            name: name.startsWith("Cisco-") ||
                  name.startsWith("Juniper-")
                ? name
                : `${deviceType === "cisco_ios" ? "Cisco-" : "Juniper-"}${name}`,
            host: normalizedHost,
            device_type: deviceType
        })
    });

    return result;
}

async function discoverGns3Devices() {
    const panel = $("#gns3-discovery-panel");
    const message = $("#gns3-discovery-message");
    const tbody = $("#gns3-discovery-results");

    if (!panel || !message || !tbody) {
        showError("Không tìm thấy khu vực hiển thị kết quả GNS3 trong HTML.");
        return;
    }

    panel.hidden = false;
    gns3DiscoverButton.disabled = true;
    gns3DiscoverButton.textContent = "Đang phát hiện...";

    message.textContent = "Đang truy vấn GNS3 API...";
    tbody.innerHTML = `
        <tr>
            <td colspan="5" class="empty">Đang tải dữ liệu...</td>
        </tr>`;

    try {
        const data = await fetchJSON("/api/gns3/discover");
        const nodes = Array.isArray(data.nodes) ? data.nodes : [];

        message.textContent =
            `${data.message || "Đã phát hiện thiết bị."} ` +
            `Tổng số node: ${data.count ?? nodes.length}.`;

        if (!nodes.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="empty">
                        Không tìm thấy node phù hợp.
                    </td>
                </tr>`;
            return;
        }

        tbody.innerHTML = nodes.map((node, index) => `
            <tr>
                <td>${escapeHTML(node.name || "Không tên")}</td>
                <td>${escapeHTML(node.node_type || "Không rõ")}</td>
                <td>${escapeHTML(node.status || "Không rõ")}</td>
                <td>
                    ${node.in_inventory
                        ? '<span class="pill success">Đã có</span>'
                        : '<span class="pill warning">Chưa có</span>'}
                </td>
                <td>
                    ${node.in_inventory
                        ? '<span class="pill success">Đã đăng ký</span>'
                        : `<button type="button"
                            class="btn btn-primary gns3-add-btn"
                            data-node-index="${index}">
                            + Thêm vào Inventory
                           </button>`}
                </td>
            </tr>
        `).join("");

        tbody.querySelectorAll(".gns3-add-btn").forEach((button) => {
            button.addEventListener("click", async () => {
                const index = Number(button.dataset.nodeIndex);
                const node = nodes[index];

                if (!node) {
                    showError("Không tìm thấy thông tin node được chọn.");
                    return;
                }

                button.disabled = true;
                button.textContent = "Đang thêm...";
                clearError();

                try {
                    const result = await addGns3NodeToInventory(node);

                    if (!result) {
                        button.disabled = false;
                        button.textContent = "+ Thêm vào Inventory";
                        return;
                    }

                    message.textContent =
                        result.message || "Đã thêm thiết bị vào Inventory.";

                    // Tai lai danh sach de cap nhat trang thai Da co.
                    await discoverGns3Devices();
                    await loadDashboard();
                } catch (error) {
                    showError(error.message);
                    button.disabled = false;
                    button.textContent = "+ Thêm vào Inventory";
                }
            });
        });
    } catch (error) {
        message.textContent = `Phát hiện thất bại: ${error.message}`;
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="empty">
                    Không thể lấy danh sách node từ GNS3.
                </td>
            </tr>`;
    } finally {
        gns3DiscoverButton.disabled = false;
        gns3DiscoverButton.textContent = "🔍 Phát hiện thiết bị GNS3";
    }
}

if (gns3DiscoverButton) {
    gns3DiscoverButton.addEventListener("click", discoverGns3Devices);
}

initializeDeviceDetailUI();
initializeRestoreUI();
pollBackupStatus();
loadDashboard();
