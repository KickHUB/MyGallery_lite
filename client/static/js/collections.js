const moveForm = document.getElementById("move-collection-form");
const deleteBtn = document.getElementById("delete-current");
const actionEl = document.getElementById("collection-actions");
const renameUrl = actionEl?.dataset?.renameUrl;
const deleteUrl = actionEl?.dataset?.deleteUrl;
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
        if (!confirm("정말 삭제하시겠습니까? 하위 컬렉션은 루트로 이동합니다.")) return;
        const res = await fetch(deleteUrl, { method: "DELETE" });
        if (res.ok) {
            window.location.href = backUrl || "/";
        } else {
            const data = await res.json();
            alert(data.error || "삭제 실패");
        }
    });
}
