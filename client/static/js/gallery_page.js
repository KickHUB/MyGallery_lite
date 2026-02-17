function parseJsonScript(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const rawText = el.textContent || "null";
    const sanitized = rawText
        .replace(/\b-?Infinity\b/g, "null")
        .replace(/\bNaN\b/g, "null");
    try {
        return JSON.parse(sanitized);
    } catch (err) {
        console.warn(`Failed to parse ${id}`, err);
        return fallback;
    }
}

window.searchResults = parseJsonScript("search-results-data", []);
window.initialData = parseJsonScript("initial-data", null);
window.collectionsData = parseJsonScript("collections-data", []);
window.collectionsRawData = parseJsonScript("collections-raw-data", []);

function initSearchHistory() {
    const searchInput = document.getElementById("search-input");
    const historyBox = document.getElementById("search-history");
    if (!searchInput || !historyBox) return;

    const STORAGE_KEY = "recentSearches";

    function loadHistory() {
        const history = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        historyBox.innerHTML = "";
        history.forEach((item) => {
            const span = document.createElement("span");
            span.textContent = item;
            span.addEventListener("click", () => {
                searchInput.value = item;
                document.getElementById("search-form")?.submit();
            });
            historyBox.appendChild(span);
        });
    }

    function saveHistory(query) {
        if (!query.trim()) return;
        const history = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        if (!history.includes(query)) {
            history.unshift(query);
            if (history.length > 10) history.pop();
            localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
        }
    }

    document.getElementById("search-form")?.addEventListener("submit", () => {
        saveHistory(searchInput.value.trim());
    });

    loadHistory();
}

function normalizeResultCount() {
    const el = document.getElementById("result-count");
    if (!el) return;
    const text = (el.textContent || "").replace(/\s+/g, " ").trim();
    if (!text || text.includes("집계 중") || text.includes("검색 결과가 없습니다")) return;
    const numbers = text.match(/[0-9][0-9,]*/g);
    if (!numbers || numbers.length < 2) return;
    const imgRaw = numbers[numbers.length - 2];
    const vidRaw = numbers[numbers.length - 1];
    const img = parseInt(imgRaw.replace(/,/g, ""), 10) || 0;
    const vid = parseInt(vidRaw.replace(/,/g, ""), 10) || 0;
    const sum = img + vid;
    const normalized = `결과 ${sum}개 (🖼️ ${img}개 / 🎞 ${vid}개)`;
    if (el.textContent !== normalized) {
        el.textContent = normalized;
    }
}

function initResultCountObserver() {
    normalizeResultCount();
    const el = document.getElementById("result-count");
    if (!el) return;
    const observer = new MutationObserver(() => {
        setTimeout(normalizeResultCount, 0);
    });
    observer.observe(el, { childList: true, characterData: true, subtree: true });
}

function initCenteredTopbar() {
    try {
        const h1 = document.querySelector("h1");
        const navContainer = document.querySelector(".top-nav-collections");
        const form = document.getElementById("search-form");
        if (h1 && form && (navContainer || document.querySelector("body > a[href]"))) {
            if (!document.getElementById("topbar-centered")) {
                const tb = document.createElement("div");
                tb.id = "topbar-centered";
                tb.className = "topbar-centered";
                h1.classList.add("title-deep");
                h1.style.textAlign = "center";
                h1.insertAdjacentElement("afterend", tb);
                tb.appendChild(form);
                if (navContainer) {
                    tb.appendChild(navContainer);
                }
            }
        }
    } catch (err) {
        console.error("center filter error", err);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initCenteredTopbar();
    initSearchHistory();
    initResultCountObserver();
});
