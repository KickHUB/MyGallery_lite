document.addEventListener("DOMContentLoaded", () => {
    const filterInput = document.getElementById("tag-filter");
    const tagGroups = Array.from(document.querySelectorAll(".tag-group"));
    const tagItems = Array.from(document.querySelectorAll(".tag-item")).map((tag) => ({
        element: tag,
        name: tag.getAttribute("data-tag") || "",
        isEmpty: tag.getAttribute("data-empty") === "true",
    }));

    if (!filterInput) return;

    function applyFilter() {
        const keyword = filterInput.value.toLowerCase();
        tagItems.forEach((tag) => {
            if (tag.isEmpty) {
                tag.element.style.display = keyword ? "none" : "inline-block";
                return;
            }
            tag.element.style.display = tag.name.includes(keyword) ? "inline-block" : "none";
        });
        tagGroups.forEach((group) => {
            const visible = Array.from(group.querySelectorAll(".tag-item"))
                .some((item) => item.style.display !== "none");
            group.style.display = visible ? "block" : "none";
        });
    }

    filterInput.addEventListener("input", applyFilter);

    tagItems.filter((tag) => !tag.isEmpty).forEach((tag) => {
        tag.element.addEventListener("click", () => {
            const searchUrl = `/?q=${encodeURIComponent(tag.name)}&match=and&tag_source=booru`;
            window.location.href = searchUrl;
        });
    });

    tagItems.filter((tag) => tag.isEmpty).forEach((tag) => {
        tag.element.addEventListener("click", () => {
            const category = tag.element.getAttribute("data-category")
                || tag.element.closest(".tag-group")?.getAttribute("data-category")
                || "";
            if (!category) return;
            const keyword = `missing:${category}`;
            const searchUrl = `/?q=${encodeURIComponent(keyword)}&match=and&tag_source=booru`;
            window.location.href = searchUrl;
        });
    });
});
