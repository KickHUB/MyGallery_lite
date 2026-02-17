const { byId, qsa, showToast, fetchJSON, postForm } = window.AppUtils;

function changeLimit(limit) {
    const params = new URLSearchParams(window.location.search);
    params.set("page", "1");
    params.set("limit", limit);
    window.location.search = params.toString();
}

async function restoreImage(filename) {
    try {
        const data = await postForm("/restore_image", { file: filename });
        if (data.success) {
            showToast("✅ 복원 완료");
            location.reload();
        } else {
            showToast("❌ 오류: " + data.error, "error");
        }
    } catch (err) {
        showToast(`❌ 복원 실패: ${err?.message || err}`, "error");
    }
}
async function deleteForever(filename) {
    if (!confirm("해당 이미지를 영구 삭제하시겠습니까? (복구 불가)")) return;

    try {
        const data = await postForm("/trash_delete", { file: filename });
        if (data.success) {
            showToast("✅ 영구 삭제 완료");
            location.reload();
        } else {
            showToast("❌ 오류: " + data.error, "error");
        }
    } catch (err) {
        showToast(`❌ 삭제 실패: ${err?.message || err}`, "error");
    }
}

async function clearTrash() {
    if (!confirm("휴지통의 모든 이미지를 영구 삭제하시겠습니까? (복구 불가)")) return;

    try {
        const data = await fetchJSON("/trash_clear", { method: "POST" });
        if (data.success) {
            showToast(`✅ 휴지통 비우기 완료 (${data.removed}개 파일 삭제)`);
            location.reload();
        } else {
            showToast("❌ 오류 발생", "error");
        }
    } catch (err) {
        showToast(`❌ 휴지통 비우기 실패: ${err?.message || err}`, "error");
    }
}

document.querySelector("[data-action='trash-clear']")?.addEventListener("click", clearTrash);
byId("trash-limit")?.addEventListener("change", (event) => {
    changeLimit(event.target.value);
});
qsa("[data-action='trash-restore']").forEach((btn) => {
    btn.addEventListener("click", () => restoreImage(btn.dataset.path));
});
qsa("[data-action='trash-delete']").forEach((btn) => {
    btn.addEventListener("click", () => deleteForever(btn.dataset.path));
});
