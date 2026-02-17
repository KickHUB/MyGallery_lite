document.addEventListener("DOMContentLoaded", () => {
    const tagsContainer = document.getElementById("tags-container");
    const filterInput = document.getElementById("tag-filter");
    const btnPopular = document.getElementById("sort-popular");
    const btnAlpha = document.getElementById("sort-alpha");

    if (!tagsContainer || !filterInput || !btnPopular || !btnAlpha) return;

    let tags = Array.from(document.querySelectorAll(".tag-item")).map((tag) => ({
        element: tag,
        name: tag.getAttribute("data-tag") || "",
        count: parseInt(tag.getAttribute("data-count"), 10) || 0,
    }));

    filterInput.addEventListener("input", () => {
        const keyword = filterInput.value.toLowerCase();
        tags.forEach((tag) => {
            tag.element.style.display = tag.name.includes(keyword) ? "inline-block" : "none";
        });
    });

    btnPopular.addEventListener("click", () => {
        btnPopular.classList.add("active");
        btnAlpha.classList.remove("active");
        tags.sort((a, b) => b.count - a.count);
        renderTags();
    });

    btnAlpha.addEventListener("click", () => {
        btnAlpha.classList.add("active");
        btnPopular.classList.remove("active");
        tags.sort((a, b) => a.name.localeCompare(b.name));
        renderTags();
    });

    function renderTags() {
        tagsContainer.innerHTML = "";
        tags.forEach((tag) => tagsContainer.appendChild(tag.element));
    }

    tags.forEach((tag) => {
        tag.element.addEventListener("click", () => {
            const searchUrl = `/?q=${encodeURIComponent(tag.name)}&match=or&tag_source=prompt`;
            window.location.href = searchUrl;
        });
    });
});
