const { byId, qsa, showToast, fetchJSON, postForm } = window.AppUtils;

const failedRestoreUI = {
    poller: null,
};

function renderFailedRestoreState(state) {
    const statusEl = byId("failed-restore-status");
    const barEl = byId("failed-restore-progress-bar");
    const btn = byId("failed-restore-all-btn");

    const progress = Number(state?.progress ?? 0);
    const message = state?.message || "대기 중";
    const status = state?.status || "idle";

    if (statusEl) statusEl.textContent = `${status.toUpperCase()} · ${message}`;
    if (barEl) barEl.style.width = `${Math.min(100, Math.max(0, progress))}%`;
    if (btn) btn.disabled = status === "running";

    if (status !== "running" && failedRestoreUI.poller) {
        clearInterval(failedRestoreUI.poller);
        failedRestoreUI.poller = null;
    }
}

async function fetchFailedRestoreStatus() {
    try {
        const data = await fetchJSON("/failed_restore_status", { headers: { Accept: "application/json" } });
        renderFailedRestoreState(data);
        return data;
    } catch (err) {
        console.error(err);
        return null;
    }
}

async function startFailedRestoreAll() {
    const btn = byId("failed-restore-all-btn");
    if (btn) btn.disabled = true;
    try {
        const data = await fetchJSON("/failed_restore_all", {
            method: "POST",
            headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        });
        renderFailedRestoreState(data);
        if (!failedRestoreUI.poller) {
            failedRestoreUI.poller = setInterval(fetchFailedRestoreStatus, 2000);
        }
        showToast("⚡ failed 복구 작업이 시작되었습니다.");
    } catch (err) {
        console.error(err);
        showToast("❌ failed 복구 시작에 실패했습니다.", "error");
        if (btn) btn.disabled = false;
    }
}

byId("failed-restore-all-btn")?.addEventListener("click", startFailedRestoreAll);
fetchFailedRestoreStatus().catch(() => {});

async function restoreFailed(date, filename) {
    try {
        const data = await postForm("/failed_restore", { date, file: filename });
        if (data.success) {
            showToast("✅ 복구 완료");
            location.reload();
        } else {
            showToast("❌ 오류: " + data.error, "error");
        }
    } catch (err) {
        showToast(`❌ 복구 실패: ${err?.message || err}`, "error");
    }
}

async function deleteFailed(date, filename) {
    if (!confirm("정말 삭제하시겠습니까?")) return;
    try {
        const data = await postForm("/failed_delete", { date, file: filename });
        if (data.success) {
            showToast("✅ 삭제 완료");
            location.reload();
        } else {
            showToast("❌ 오류: " + data.error, "error");
        }
    } catch (err) {
        showToast(`❌ 삭제 실패: ${err?.message || err}`, "error");
    }
}

qsa("[data-action='failed-restore']").forEach((btn) => {
    btn.addEventListener("click", () => {
        restoreFailed(btn.dataset.date, btn.dataset.path);
    });
});
qsa("[data-action='failed-delete']").forEach((btn) => {
    btn.addEventListener("click", () => {
        deleteFailed(btn.dataset.date, btn.dataset.path);
    });
});
