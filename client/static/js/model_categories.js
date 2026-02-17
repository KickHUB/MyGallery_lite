const moveForm = document.getElementById("move-category-form");
const deleteBtn = document.getElementById("delete-current");
const assignForm = document.getElementById("assign-model-form");
const assignInput = document.getElementById("assign-model-input");
const removeButtons = document.querySelectorAll(".remove-model");
const actionEl = document.getElementById("model-category-actions");

const renameUrl = actionEl?.dataset?.renameUrl;
const deleteUrl = actionEl?.dataset?.deleteUrl;
const addUrl = actionEl?.dataset?.addUrl;
const removeUrl = actionEl?.dataset?.removeUrl;
const backUrl = actionEl?.dataset?.backUrl;

if (moveForm && renameUrl) {
    moveForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const formData = new FormData(moveForm);
        const payload = { name: formData.get("name"), parent_id: formData.get("parent_id") };
        const res = await fetch(renameUrl, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (res.ok) {
            location.reload();
        } else {
            const data = await res.json();
            alert(data.error || "변경할 수 없습니다.");
        }
    });
}
if (deleteBtn && deleteUrl) {
    deleteBtn.addEventListener("click", async () => {
        if (!confirm("정말 삭제하시겠습니까? 하위 카테고리는 루트로 이동합니다.")) return;
        const res = await fetch(deleteUrl, { method: "DELETE" });
        if (res.ok) {
            window.location.href = backUrl || "/";
        } else {
            const data = await res.json();
            alert(data.error || "삭제 실패");
        }
    });
}
if (assignForm && addUrl) {
    assignForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const name = (assignInput.value || "").trim();
        if (!name) return;
        const res = await fetch(addUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_name: name }),
        });
        if (res.ok) {
            location.reload();
        } else {
            const data = await res.json();
            alert(data.error || "추가 실패");
        }
    });
}
removeButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
        const name = btn.dataset.name;
        if (!name || !removeUrl) return;
        const res = await fetch(removeUrl, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_name: name }),
        });
        if (res.ok) {
            location.reload();
        } else {
            const data = await res.json();
            alert(data.error || "삭제 실패");
        }
    });
});
