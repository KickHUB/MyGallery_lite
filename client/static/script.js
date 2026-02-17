let currentImageIndex = -1;
// deep-ui: center title, smaller result-count
(function(){
  function injectCSS(){
    if (document.getElementById('deep-ui-style')) return;
    var st = document.createElement('style');
    st.id = 'deep-ui-style';
    st.textContent = [
      ".title-deep,h1{ text-align:center; margin:16px 0 8px; }",
      "#result-count{ font-size:18px; line-height:1.25; }",
    ].join("\n");
    document.head.appendChild(st);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectCSS, { once:true });
  } else { injectCSS(); }
})();
let currentImagePath = "";
let currentExifPath = "";
let currentMediaType = "";
let isModalExpanded = false;
let results = [];
let galleryEl = null;
let cursorHistory = new Map();
let lastSearchKey = "";
let currentSearchState = null;
let useOffsetPagination = true;
let totalCache = new Map();
let detailCache = new Map();
let detailRequestToken = 0;
let totalRequestToken = 0;
const dataTaskState = {
    statusEl: null,
    detailEl: null,
    logEl: null,
    progressBarEl: null,
    progressValueEl: null,
    logTailBtn: null,
    logCopyBtn: null,
    cancelBtn: null,
    dbBackupBtn: null,
    imageScanBtn: null,
    failedRecoveryBtn: null,
    imageCleanupBtn: null,
    orphanCleanupBtn: null,
    videoIndexBtn: null,
    videoCleanupBtn: null,
    thumbBtn: null,
    phashIndexBtn: null,
    phashForceToggle: null,
    phashGroupBuildBtn: null,
    phashGroupDistanceInput: null,
    phashGroupRebuildToggle: null,
    integrityBtn: null,
    dbQuickCheckBtn: null,
    dbIntegrityCheckBtn: null,
    dbFkCheckBtn: null,
    dbVacuumBtn: null,
    dbAnalyzeBtn: null,
    dbOptimizeBtn: null,
    dbWalCheckpointBtn: null,
    walCheckpointModeSelect: null,
    ftsRebuildBtn: null,
    booruAutoTagBtn: null,
    dbBackupRefreshBtn: null,
    dbBackupSelect: null,
    dbRestoreBtn: null,
    dbRestoreConfirm: null,
    dbDedupeConfirm: null,
    dbDedupeCheckBtn: null,
    dbDedupeCleanBtn: null,
    booruDictUpdateBtn: null,
    booruDictStatusEl: null,
    runtimeFfmpegInstallBtn: null,
    runtimeExiftoolInstallBtn: null,
    runtimeWd14InstallBtn: null,
    runtimeWd14ModelSelect: null,
    runtimeAssetsStatusEl: null,
    summaryReportEl: null,
    summaryLabelEl: null,
    summaryListEl: null,
    integrityReportEl: null,
    integritySampleLimitEl: null,
    integrityReportDownloadEl: null,
    integritySampleNoMetaEl: null,
    integritySampleNoKSamplerEl: null,
    integritySampleMissingPositiveEl: null,
    integritySampleReadFailedEl: null,
    dbDedupeReportEl: null,
    dbDedupeSampleInfoEl: null,
    dbDedupeSampleListEl: null,
};
const dataTaskUIState = {
    poller: null,
    lastPayload: null,
    bound: false,
    logTailEnabled: true,
};
const unifiedTaskLogState = {
    logEl: null,
    tailBtn: null,
    copyBtn: null,
    summaryEl: null,
    bound: false,
    tailEnabled: true,
    pendingDataLog: null,
    pendingRefreshLog: null,
};
const booruDictStatusState = {
    loading: false,
    lastMeta: null,
    lastTaskUpdatedAt: 0,
};

const runtimeAssetsState = {
    loading: false,
    lastMeta: null,
    lastTaskUpdatedAt: 0,
};

const profileMenuState = {
    root: null,
    toggle: null,
    panel: null,
    open: false,
};

const booruTagState = {
    media: "",
    path: "",
    manualTags: [],
    items: [],
    sources: [],
    rating: null,
    loading: false,
    saving: false,
    loadToken: 0,
    queryToken: 0,
    saveTimer: null,
    suggestTimer: null,
    suggestItems: [],
    suggestIndex: -1,
    bound: false,
    popoverEl: null,
};

const modalCopyState = {
    bound: false,
};

const selectionBooruState = {
    suggestItems: [],
    suggestIndex: -1,
    suggestTimer: null,
    queryToken: 0,
    bound: false,
};

const BOORU_MANUAL_SOURCE = "manual";
const BOORU_AUTO_PREFIX = "auto:";

const monitoringShellState = {
    currentTab: "overview",
    dbAdminInitialized: false,
    tabOverviewBtn: null,
    tabAdminBtn: null,
    tabOverviewPanel: null,
    tabAdminPanel: null,
    refreshStatusChip: null,
    dataTaskStatusChip: null,
    lastUpdatedChip: null,
    logSection: null,
    activityFeedEl: null,
    activityEmptyEl: null,
    activitySummaryEl: null,
};

function initTaskStatusChips() {
    monitoringShellState.refreshStatusChip = document.getElementById("refreshStatusChip");
    monitoringShellState.dataTaskStatusChip = document.getElementById("dataTaskStatusChip");
    monitoringShellState.lastUpdatedChip = document.getElementById("lastUpdatedChip");
}

const collectionState = {
    raw: Array.isArray(window.collectionsRawData) ? window.collectionsRawData : [],
    list: Array.isArray(window.collectionsData) ? window.collectionsData : [],
    selectedIds: Array.isArray(window.initialData?.collection_ids) ? window.initialData.collection_ids.map(String) : [],
    filterSummary: null,
    filterSearchInput: null,
    filterClearBtn: null,
    filterChipList: null,
    hiddenInputs: null,
    addSelect: null,
    renameSelect: null,
    deleteSelect: null,
    createParentSelect: null,
    renameParentSelect: null,
};

const collectionIndex = {
    byId: new Map(),
    labelById: new Map(),
};

const selectionState = {
    active: false,
    selected: new Set(),
    lastIndex: null,
    longPressTimer: null,
    ignoreClickOnce: false,
    dragSelecting: false,
    dragPointerId: null,
    dragStart: { x: 0, y: 0 },
    dragBaseModeAdd: true,
    dragModeAdd: true,
    preDragSelected: new Set(),
    dragStarted: false,
    dragBox: null,
    toolbar: null,
    countLabel: null,
    deleteButton: null,
    cancelButton: null,
    addButton: null,
    addSelect: null,
    removeButton: null,
    downloadButton: null,
    compareButton: null,
    booruTagInput: null,
    booruTagButton: null,
    booruTagRemoveButton: null,
};

const compareState = {
    modal: null,
    canvas: null,
    img1: null,
    img2: null,
    orientationButtons: [],
    lastOrientation: "horizontal",
};

const pairedMediaState = {
    button: null,
    item: null,
    type: null,
    requestId: 0,
};

const relatedContentState = {
    button: null,
    panel: null,
    listEl: null,
    metaEl: null,
    scrim: null,
    closeBtn: null,
    open: false,
    requestId: 0,
    lastPath: "",
    items: [],
    limit: 60,
    distance: 0,
    includeImages: true,
    includeVideos: true,
    includeVideoPairs: false,
    distanceInput: null,
    distanceValueEl: null,
    filterImagesEl: null,
    filterVideosEl: null,
    filterPairsEl: null,
};

const modelChipState = {
    all: Array.isArray(window.initialData?.models) ? window.initialData.models : [],
    selected: new Set(Array.isArray(window.initialData?.models) ? window.initialData.models : []),
};

function getThumbElements() {
    return Array.from(document.querySelectorAll(".gallery .thumb"));
}

function getSelectedItems() {
    return Array.from(selectionState.selected)
        .map(idx => results[idx])
        .filter(Boolean);
}

function refreshThumbIndices() {
    const newSelected = new Set();
    getThumbElements().forEach((thumb, idx) => {
        thumb.dataset.index = idx;
        if (thumb.classList.contains("selected")) {
            newSelected.add(idx);
        }
    });
    selectionState.selected = newSelected;
    if (selectionState.active) {
        if (newSelected.size === 0) {
            disableSelectionMode();
        } else {
            updateSelectionToolbar();
        }
    }
}

function updateSelectionToolbar() {
    if (!selectionState.toolbar) return;
    const count = selectionState.selected.size;
    if (selectionState.countLabel) {
        selectionState.countLabel.textContent = count ? `${count}개 선택됨` : "선택된 항목이 없습니다";
    }
    if (selectionState.deleteButton) {
        selectionState.deleteButton.disabled = count === 0;
    }
    if (selectionState.addButton) {
        const hasTarget = selectionState.addSelect && selectionState.addSelect.value;
        selectionState.addButton.disabled = count === 0 || !hasTarget;
    }
    if (selectionState.removeButton) {
        const hasTarget = selectionState.addSelect && selectionState.addSelect.value;
        selectionState.removeButton.disabled = count === 0 || !hasTarget;
    }
    if (selectionState.downloadButton) {
        selectionState.downloadButton.disabled = count === 0;
    }
    if (selectionState.booruTagButton) {
        const hasTags = Boolean(selectionState.booruTagInput?.value?.trim());
        selectionState.booruTagButton.disabled = count === 0 || !hasTags;
    }
    if (selectionState.booruTagRemoveButton) {
        const hasTags = Boolean(selectionState.booruTagInput?.value?.trim());
        selectionState.booruTagRemoveButton.disabled = count === 0 || !hasTags;
    }
    if (selectionState.compareButton) {
        const selectedItems = getSelectedItems();
        const compareReady = selectedItems.length === 2 && selectedItems.every(item => item && item.media !== "video");
        selectionState.compareButton.disabled = !compareReady;
    }
}

function isEditableElement(el) {
    if (!el) return false;
    const tag = el.tagName;
    return el.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function copyTextToClipboard(rawText, messages = {}) {
    const text = String(rawText || "").trim();
    const emptyMessage = messages.emptyMessage || "복사할 내용이 없습니다.";
    const successMessage = messages.successMessage || "✅ 클립보드에 복사되었습니다.";
    const errorMessage = messages.errorMessage || "❌ 복사 실패";

    if (!text) {
        showToast(emptyMessage, "error");
        return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text)
            .then(() => showToast(successMessage))
            .catch(err => showToast(`${errorMessage}: ${err?.message || err}`, "error"));
        return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    try {
        const successful = document.execCommand("copy");
        if (successful) {
            showToast(successMessage);
        } else {
            showToast(errorMessage, "error");
        }
    } catch (err) {
        showToast(`${errorMessage}: ${err?.message || err}`, "error");
    }
    textarea.remove();
}

function resolveImageSrc(item) {
    const path = item?.file || item?.img || item?.rel_thumb || item?.thumb_rel;
    if (!path) return "";
    if (isGifFile(path)) {
        return `/file?path=${encodeURIComponent(path)}`;
    }
    return `/img?path=${encodeURIComponent(path)}`;
}

function applyCompactParam(params) {
    params.set("compact", "1");
    return params;
}

function applyOffsetParam(params, enabled = true) {
    params.set("use_offset", enabled ? "1" : "0");
    return params;
}

function setCompareOrientation(mode) {
    if (!compareState.canvas) return;
    const orientation = mode === "vertical" ? "vertical" : "horizontal";
    compareState.canvas.classList.remove("horizontal", "vertical");
    compareState.canvas.classList.add(orientation);
    compareState.lastOrientation = orientation;
    compareState.orientationButtons.forEach(btn => {
        if (btn) {
            const btnMode = btn.dataset.orientation;
            btn.classList.toggle("active", btnMode === orientation);
        }
    });
}

function openCompareModal() {
    const selectedItems = getSelectedItems();
    if (selectedItems.length !== 2) {
        showToast("이미지 2개를 선택하세요.", "error");
        return;
    }
    if (selectedItems.some(item => item?.media === "video")) {
        showToast("동영상은 비교할 수 없습니다. 이미지 2개를 선택하세요.", "error");
        return;
    }

    const [first, second] = selectedItems;
    if (compareState.img1) compareState.img1.src = resolveImageSrc(first);
    if (compareState.img2) compareState.img2.src = resolveImageSrc(second);
    setCompareOrientation(compareState.lastOrientation);

    if (compareState.modal) {
        compareState.modal.classList.remove("hidden");
        document.body.style.overflow = "hidden";
    }
}

function closeCompareModal() {
    if (compareState.modal) {
        compareState.modal.classList.add("hidden");
        document.body.style.overflow = "";
    }
}

function enableSelectionMode() {
    if (selectionState.active) return;
    selectionState.active = true;
    document.body.classList.add("selection-mode");
    selectionState.toolbar?.classList.remove("hidden");
    updateSelectionToolbar();
}

function disableSelectionMode() {
    selectionState.active = false;
    selectionState.selected = new Set();
    selectionState.lastIndex = null;
    selectionState.toolbar?.classList.add("hidden");
    document.body.classList.remove("selection-mode");
    getThumbElements().forEach(thumb => thumb.classList.remove("selected"));
    hideDragBox();
    updateSelectionToolbar();
}

function applySelectionSet(newSet, options = {}) {
    const { skipAutoExit = false } = options;
    selectionState.selected = newSet;
    getThumbElements().forEach(thumb => {
        const idx = Number(thumb.dataset.index);
        thumb.classList.toggle("selected", newSet.has(idx));
    });
    if (newSet.size > 0 && !selectionState.active) {
        enableSelectionMode();
    }
    updateSelectionToolbar();
    if (newSet.size === 0 && !skipAutoExit) {
        disableSelectionMode();
    }
}

function toggleSelection(index, desiredState) {
    const newSet = new Set(selectionState.selected);
    const shouldSelect = desiredState !== undefined ? desiredState : !newSet.has(index);
    if (shouldSelect) {
        newSet.add(index);
    } else {
        newSet.delete(index);
    }
    applySelectionSet(newSet);
}

function selectRange(start, end, keepExisting = true) {
    const newSet = keepExisting ? new Set(selectionState.selected) : new Set();
    const [minIdx, maxIdx] = start < end ? [start, end] : [end, start];
    for (let i = minIdx; i <= maxIdx; i++) {
        newSet.add(i);
    }
    applySelectionSet(newSet);
}

function buildCollectionTreeFromRaw(rawList) {
    const nodes = {};
    (rawList || []).forEach((c) => {
        nodes[c.id] = { ...c, children: [] };
    });
    const roots = [];
    Object.values(nodes).forEach((node) => {
        const pid = node.parent_id;
        if (pid && nodes[pid] && pid !== node.id) {
            nodes[pid].children.push(node);
        } else {
            roots.push(node);
        }
    });
    const sortFn = (a, b) => (a.name || '').localeCompare(b.name || '');
    Object.values(nodes).forEach((n) => n.children.sort(sortFn));
    roots.sort(sortFn);
    return roots;
}

function flattenCollectionTree(tree, prefix = [], depth = 0) {
    const result = [];
    (tree || []).forEach((node) => {
        const path = [...prefix, node.name || ''];
        result.push({
            id: node.id,
            name: node.name,
            label: path.filter(Boolean).join(' / '),
            depth,
        });
        if (node.children && node.children.length) {
            result.push(...flattenCollectionTree(node.children, path, depth + 1));
        }
    });
    return result;
}

function rebuildCollectionIndex() {
    collectionIndex.byId = new Map();
    (collectionState.raw || []).forEach((c) => {
        if (c && c.id !== undefined && c.id !== null) {
            collectionIndex.byId.set(c.id, c);
        }
    });
    collectionIndex.labelById = new Map();
    (collectionState.list || []).forEach((c) => {
        if (c && c.id !== undefined && c.id !== null) {
            collectionIndex.labelById.set(c.id, c.label || c.name || "");
        }
    });
}

function getCollectionLabelById(id) {
    if (id === undefined || id === null) return "";
    return collectionIndex.labelById.get(id) || collectionIndex.byId.get(id)?.name || "";
}

function getRootCollectionId(id) {
    if (id === undefined || id === null) return null;
    let current = collectionIndex.byId.get(id);
    if (!current) return null;

    let guard = 0;
    while (current && current.parent_id && guard < 1024) {
        const parent = collectionIndex.byId.get(current.parent_id);
        if (!parent) break;
        current = parent;
        guard += 1;
    }
    return current?.id ?? null;
}

function refreshCollectionList() {
    if (collectionState.raw && collectionState.raw.length) {
        const tree = buildCollectionTreeFromRaw(collectionState.raw);
        collectionState.list = flattenCollectionTree(tree);
    }
    rebuildCollectionIndex();
}

refreshCollectionList();
if (!collectionState.list.length && Array.isArray(window.collectionsData)) {
    collectionState.list = window.collectionsData;
    rebuildCollectionIndex();
}

function cancelLongPressTimer() {
    if (selectionState.longPressTimer) {
        clearTimeout(selectionState.longPressTimer);
        selectionState.longPressTimer = null;
    }
}

function handleThumbPointerDown(event) {
    if (selectionState.active) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const thumb = event.currentTarget;
    const index = Number(thumb.dataset.index);
    cancelLongPressTimer();
    selectionState.longPressTimer = window.setTimeout(() => {
        enableSelectionMode();
        const newSet = new Set(selectionState.selected);
        newSet.add(index);
        selectionState.ignoreClickOnce = true;
        selectionState.lastIndex = index;
        applySelectionSet(newSet, { skipAutoExit: true });
    }, 450);
}

function handleThumbClick(event) {
    const thumb = event.currentTarget;
    const index = Number(thumb.dataset.index);
    const previousAnchor = selectionState.lastIndex;

    if (selectionState.ignoreClickOnce) {
        selectionState.ignoreClickOnce = false;
        return;
    }

    if (!selectionState.active && !(event.shiftKey || event.ctrlKey || event.metaKey)) {
        selectionState.lastIndex = index;
        showModalFromIndex(index);
        return;
    }

    if (!selectionState.active) {
        enableSelectionMode();
    }

    let newSet = new Set(selectionState.selected);

    if (event.shiftKey) {
        const anchor = previousAnchor !== null && previousAnchor !== undefined ? previousAnchor : index;
        const [minIdx, maxIdx] = anchor < index ? [anchor, index] : [index, anchor];
        if (!(event.ctrlKey || event.metaKey)) {
            newSet = new Set();
        }
        for (let i = minIdx; i <= maxIdx; i++) {
            newSet.add(i);
        }
    } else if (event.ctrlKey || event.metaKey) {
        if (newSet.has(index)) {
            newSet.delete(index);
        } else {
            newSet.add(index);
        }
    } else {
        if (newSet.has(index) && newSet.size === 1) {
            newSet.delete(index);
        } else if (newSet.has(index)) {
            newSet.delete(index);
        } else {
            newSet.add(index);
        }
    }

    selectionState.lastIndex = newSet.size ? index : null;
    applySelectionSet(newSet);
}

function bindThumbEvents(thumb) {
    thumb.addEventListener("click", handleThumbClick);
    thumb.addEventListener("pointerdown", handleThumbPointerDown);
    thumb.addEventListener("pointerup", cancelLongPressTimer);
    thumb.addEventListener("pointerleave", cancelLongPressTimer);
    thumb.addEventListener("pointercancel", cancelLongPressTimer);
    thumb.addEventListener("dragstart", event => event.preventDefault());
}

function bindGalleryThumbs() {
    getThumbElements().forEach(bindThumbEvents);
}

function buildCollectionBadgeGroups(collections = []) {
    const groupMap = new Map();

    collections.forEach((col) => {
        const label = col.label || getCollectionLabelById(col.id) || col.name || "";
        const rootId = getRootCollectionId(col.id);

        const rootLabelFromPath = label ? label.split(" / ")[0] : "";
        const rootLabel = rootId !== null
            ? (getCollectionLabelById(rootId) || rootLabelFromPath || "모음집")
            : (rootLabelFromPath || "모음집");
        const groupKey = rootId !== null ? `root-${rootId}` : `rootlabel-${rootLabel}`;

        if (!groupMap.has(groupKey)) {
            groupMap.set(groupKey, {
                rootId,
                rootLabel,
                labels: new Set(),
            });
        }

        if (label) {
            groupMap.get(groupKey).labels.add(label);
        }
    });

    const groups = Array.from(groupMap.values()).map((g) => {
        const paths = Array.from(g.labels).sort();
        const leafPaths = paths.filter(
            (p) => !paths.some((q) => q !== p && q.startsWith(p + " / "))
        );
        return {
            rootId: g.rootId,
            rootLabel: g.rootLabel || "모음집",
            count: leafPaths.length,
            items: leafPaths.map((p) => ({ label: p })),
        };
    });

    groups.sort((a, b) => (a.rootLabel || "").localeCompare(b.rootLabel || ""));
    return groups;
}

function createThumbElement(item, index) {
    const wrapper = document.createElement("div");
    wrapper.className = "gallery-item";

    const img = document.createElement("img");
    const thumbPath = item.img || item.file;
    const filePath = item.file || thumbPath || "";
    const indicatorPath = getIndicatorPath(item, filePath);
    const classes = ["thumb"];
    const isVideo = item.media === "video";
    if (isVideo) {
        classes.push("video");
    }
    const isAudio = isVideo && hasSoundFlag(item.sound);
    const isGif = isGifFile(indicatorPath);
    if (isAudio) {
        classes.push("audio");
    } else if (isGif) {
        classes.push("gif");
    }
    img.src = `/thumb?path=${encodeURIComponent(thumbPath)}`;
    img.className = classes.join(" ");
    img.alt = "thumbnail";
    img.loading = "lazy";
    img.dataset.index = index;
    img.dataset.path = item.file || "";
    img.dataset.media = item.media || "image";
    img.dataset.retry = "0";
    img.dataset.thumbStatus = "loading";
    bindThumbEvents(img);
    img.addEventListener("load", () => {
        if (img.naturalWidth === 1 && img.naturalHeight === 1) {
            const retryCount = Number.parseInt(img.dataset.retry || "0", 10);
            const maxRetries = 3;
            if (retryCount >= maxRetries) {
                img.dataset.thumbStatus = "failed";
                return;
            }
            img.dataset.retry = String(retryCount + 1);
            img.dataset.thumbStatus = "retrying";
            const delayMs = 300 + Math.floor(Math.random() * 500);
            const retryPath = img.dataset.path || thumbPath || "";
            setTimeout(() => {
                img.src = `/thumb?path=${encodeURIComponent(retryPath)}&t=${Date.now()}`;
            }, delayMs);
            return;
        }
        img.dataset.thumbStatus = "loaded";
    });

    wrapper.appendChild(img);

    const collections = Array.isArray(item.collections) ? item.collections : [];
    const mappingCollections = collections.filter((col) => col && typeof col === "object" && !Array.isArray(col));
    if (mappingCollections.length) {
        const badges = document.createElement("div");
        badges.className = "collection-badges";
        const normalizedCollections = mappingCollections.map((col) => ({
            ...col,
            parent_id: col.parent_id ?? null,
            label: col.label || getCollectionLabelById(col.id) || col.name || "",
        }));
        const groups = buildCollectionBadgeGroups(normalizedCollections);
        groups.forEach((group) => {
            const badge = document.createElement("span");
            badge.className = "collection-badge";
            badge.textContent = `${group.rootLabel}${group.count > 1 ? " +" + group.count : ""}`;

            const tooltip = document.createElement("div");
            tooltip.className = "collection-tooltip";
            const list = document.createElement("ul");
            list.className = "collection-tooltip__list";
            group.items.forEach((col) => {
                const li = document.createElement("li");
                li.textContent = col.label || col.name || "";
                list.appendChild(li);
            });
            tooltip.appendChild(list);
            badge.appendChild(tooltip);

            badges.appendChild(badge);
        });
        wrapper.appendChild(badges);
    } else if (collections.length) {
        const badges = document.createElement("div");
        badges.className = "collection-badges";
        badges.title = collections.join(", ");
        collections.forEach((col) => {
            const badge = document.createElement("span");
            badge.className = "collection-badge";
            badge.textContent = col;
            badges.appendChild(badge);
        });
        wrapper.appendChild(badges);
    }

    return wrapper;
}

function ensureDragBox() {
    if (selectionState.dragBox) return;
    const box = document.createElement("div");
    box.id = "drag-selection-box";
    document.body.appendChild(box);
    selectionState.dragBox = box;
}

function updateDragBoxRect(rect) {
    if (!selectionState.dragBox) return;
    selectionState.dragBox.style.display = "block";
    selectionState.dragBox.style.left = `${rect.left}px`;
    selectionState.dragBox.style.top = `${rect.top}px`;
    selectionState.dragBox.style.width = `${rect.right - rect.left}px`;
    selectionState.dragBox.style.height = `${rect.bottom - rect.top}px`;
}

function hideDragBox() {
    if (!selectionState.dragBox) return;
    selectionState.dragBox.style.display = "none";
}

function applyDragSelection(currentPoint) {
    const start = selectionState.dragStart;
    const rect = {
        left: Math.min(start.x, currentPoint.x),
        right: Math.max(start.x, currentPoint.x),
        top: Math.min(start.y, currentPoint.y),
        bottom: Math.max(start.y, currentPoint.y),
    };

    updateDragBoxRect(rect);

    const indicesInRect = new Set();
    getThumbElements().forEach(thumb => {
        const idx = Number(thumb.dataset.index);
        const bounds = thumb.getBoundingClientRect();
        const intersects = !(rect.right < bounds.left || rect.left > bounds.right || rect.bottom < bounds.top || rect.top > bounds.bottom);
        if (intersects) {
            indicesInRect.add(idx);
        }
    });

    const newSet = new Set(selectionState.preDragSelected);
    if (selectionState.dragModeAdd) {
        indicesInRect.forEach(idx => newSet.add(idx));
    } else {
        indicesInRect.forEach(idx => newSet.delete(idx));
    }

    applySelectionSet(newSet, { skipAutoExit: true });
}

function startDragSelection(event) {
    if (!selectionState.active) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;

    ensureDragBox();
    selectionState.dragSelecting = true;
    selectionState.dragPointerId = event.pointerId;
    selectionState.dragStart = { x: event.clientX, y: event.clientY };
    const target = event.target;
    const targetIndex = target && target.dataset ? Number(target.dataset.index) : NaN;
    const targetSelected = Number.isInteger(targetIndex) && selectionState.selected.has(targetIndex);
    selectionState.dragBaseModeAdd = targetSelected ? false : true;
    selectionState.dragModeAdd = event.altKey ? !selectionState.dragBaseModeAdd : selectionState.dragBaseModeAdd;
    selectionState.preDragSelected = new Set(selectionState.selected);
    selectionState.dragStarted = false;
    if (galleryEl && galleryEl.setPointerCapture) {
        try {
            galleryEl.setPointerCapture(event.pointerId);
        } catch (err) {
            // ignore capture errors
        }
    }
}

function onDragPointerMove(event) {
    if (!selectionState.dragSelecting) return;
    if (event.pointerId !== selectionState.dragPointerId) return;
    const deltaX = Math.abs(event.clientX - selectionState.dragStart.x);
    const deltaY = Math.abs(event.clientY - selectionState.dragStart.y);
    if (!selectionState.dragStarted) {
        if (deltaX < 3 && deltaY < 3) return;
        selectionState.dragStarted = true;
    }
    selectionState.dragModeAdd = event.altKey ? !selectionState.dragBaseModeAdd : selectionState.dragBaseModeAdd;
    applyDragSelection({ x: event.clientX, y: event.clientY });
    if (event.pointerType === "touch") {
        event.preventDefault();
    }
}

function endDragSelection(event) {
    if (!selectionState.dragSelecting) return;
    if (event.pointerId !== selectionState.dragPointerId) return;
    const wasDragging = selectionState.dragStarted;
    selectionState.dragSelecting = false;
    selectionState.dragPointerId = null;
    selectionState.dragStarted = false;
    hideDragBox();
    if (galleryEl && galleryEl.releasePointerCapture) {
        try {
            galleryEl.releasePointerCapture(event.pointerId);
        } catch (err) {
            // ignore
        }
    }
    if (!wasDragging) {
        return;
    }
    if (selectionState.selected.size === 0) {
        disableSelectionMode();
    } else {
        updateSelectionToolbar();
    }
}

async function deleteSelectedMedia() {
    if (selectionState.selected.size === 0) return;
    const sortedIndexes = Array.from(selectionState.selected).sort((a, b) => a - b);
    const targets = sortedIndexes
        .map(index => ({ index, item: results[index] }))
        .filter(entry => entry.item && entry.item.file);

    if (targets.length === 0) return;

    if (!confirm(`선택한 ${targets.length}개 항목을 삭제하시겠습니까?`)) return;

    try {
        const res = await fetch("/delete_media_batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ paths: targets.map(t => t.item.file) })
        });
        const data = await res.json();

        if (!res.ok || !data.success) {
            const msg = data && data.error ? data.error : "삭제에 실패했습니다.";
            showToast(`❌ ${msg}`, "error");
            return;
        }

        const failedPaths = (data.errors || []).map(err => err.path);
        const succeeded = targets.filter(t => !failedPaths.includes(t.item.file));

        if (succeeded.length) {
            const removeIndexes = succeeded.map(t => t.index).sort((a, b) => b - a);
            removeIndexes.forEach(idx => {
                const thumb = document.querySelector(`.thumb[data-index='${idx}']`);
                if (thumb && thumb.parentNode) {
                    thumb.parentNode.removeChild(thumb);
                }
                if (idx >= 0 && idx < results.length) {
                    results.splice(idx, 1);
                }
            });
            refreshThumbIndices();
            showToast(`✅ ${succeeded.length}개 항목 삭제 완료`);
        }

        if (data.errors && data.errors.length) {
            const errorMsg = data.errors.map(err => err.message || err).join("\n");
            showToast(`⚠️ 일부 항목 삭제 실패:\n${errorMsg}`, "error");
            updateSelectionToolbar();
        } else {
            disableSelectionMode();
        }
    } catch (error) {
        showToast(`❌ 삭제 중 오류 발생: ${error}`, "error");
    }
}

async function addSelectedToCollection() {
    const targetId = selectionState.addSelect ? selectionState.addSelect.value : "";
    if (!targetId) {
        showToast("모음집을 선택하세요.", "error");
        return;
    }
    const targets = Array.from(selectionState.selected)
        .map(idx => results[idx])
        .filter(item => item && item.file);
    if (targets.length === 0) {
        showToast("선택된 항목이 없습니다.", "error");
        return;
    }

    let successCount = 0;
    const failures = [];

    for (const item of targets) {
        try {
            const res = await fetch(`/api/collections/${targetId}/items`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: item.file, media_type: item.media || "image" })
            });
            const data = await res.json();
            if (res.ok && data && data.status === "added") {
                successCount += 1;
            } else {
                failures.push(data && data.error ? data.error : "추가 실패");
            }
        } catch (err) {
            failures.push(err.message || String(err));
        }
    }

    if (successCount > 0) {
        showToast(`✅ ${successCount}개 항목을 모음집에 추가했습니다.`);
    }
    if (failures.length) {
        showToast(`❌ 일부 추가 실패: ${failures.join(", ")}`, "error");
    }
    updateSelectionToolbar();
}

async function removeSelectedFromCollection() {
    const targetId = selectionState.addSelect ? selectionState.addSelect.value : "";
    if (!targetId) {
        showToast("모음집을 선택하세요.", "error");
        return;
    }
    const targets = Array.from(selectionState.selected)
        .map(idx => results[idx])
        .filter(item => item && item.file);
    if (targets.length === 0) {
        showToast("선택된 항목이 없습니다.", "error");
        return;
    }

    try {
        const res = await fetch(`/api/collections/${targetId}/items`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ paths: targets.map(t => t.file) }),
        });
        const data = await res.json();
        if (!res.ok || !data || data.status !== "removed") {
            const msg = data && data.error ? data.error : "모음집에서 제거하지 못했습니다.";
            showToast(`❌ ${msg}`, "error");
            return;
        }

        const removed = data.removed_count ?? targets.length;
        const missing = Array.isArray(data.missing_paths) ? data.missing_paths.length : 0;
        const invalid = data.invalid_count || 0;
        const parts = [`${removed}개 제거`];
        if (missing) parts.push(`${missing}개는 모음집에 없었습니다`);
        if (invalid) parts.push(`${invalid}개 경로 무시됨`);
        showToast(`✅ ${parts.join(" / ")}`);
    } catch (err) {
        showToast(`❌ ${err.message || err}`, "error");
    }
    updateSelectionToolbar();
}

function parseBooruTagList(raw) {
    const rawText = String(raw || "").trim();
    if (!rawText) return [];
    const tokens = rawText
        .split(/[,\s]+/)
        .map((token) => normalizeBooruTagInput(token))
        .filter(Boolean)
        .filter(tag => !isRatingBooruTag(tag));
    const unique = [];
    tokens.forEach((tag) => {
        if (!unique.includes(tag)) {
            unique.push(tag);
        }
    });
    return unique;
}

function getSelectionBooruElements() {
    return {
        input: selectionState.booruTagInput,
        suggestions: document.getElementById("selection-booru-suggestions"),
        inputWrap: document.querySelector(".selection-booru-input-wrap"),
    };
}

function clearSelectionBooruSuggestions() {
    const { suggestions } = getSelectionBooruElements();
    if (!suggestions) return;
    suggestions.innerHTML = "";
    suggestions.style.display = "none";
    selectionBooruState.suggestItems = [];
    selectionBooruState.suggestIndex = -1;
}

function setActiveSelectionBooruSuggestion(index) {
    const { suggestions } = getSelectionBooruElements();
    const items = Array.isArray(selectionBooruState.suggestItems) ? selectionBooruState.suggestItems : [];
    const max = items.length;
    if (!suggestions || !max) {
        selectionBooruState.suggestIndex = -1;
        return;
    }
    const next = Number.isFinite(index) ? index : -1;
    selectionBooruState.suggestIndex = next;

    const rows = Array.from(suggestions.querySelectorAll(".booru-tag-suggestion"));
    rows.forEach((row, i) => {
        if (i === next) row.classList.add("active");
        else row.classList.remove("active");
    });

    if (next >= 0 && rows[next]) {
        try {
            rows[next].scrollIntoView({ block: "nearest" });
        } catch (err) {
            // ignore
        }
    }
}

function getSelectionBooruQuery(rawValue) {
    const raw = String(rawValue || "");
    const match = raw.match(/(?:^|[,\s])([^,\s]*)$/);
    return normalizeBooruTagInput(match ? match[1] : "");
}

function applySelectionBooruSuggestion(tag) {
    const { input } = getSelectionBooruElements();
    if (!input) return;
    const raw = String(input.value || "");
    const tokens = raw.split(/[,\s]+/).filter(Boolean);
    const endsWithSeparator = /[,\s]$/.test(raw);
    if (!tokens.length || endsWithSeparator) {
        tokens.push(tag);
    } else {
        tokens[tokens.length - 1] = tag;
    }
    input.value = `${tokens.join(" ")} `;
    input.focus();
    updateSelectionToolbar();
    clearSelectionBooruSuggestions();
}

function renderSelectionBooruSuggestions(items = []) {
    const { suggestions, input } = getSelectionBooruElements();
    if (!suggestions || !input) return;
    const existing = new Set(parseBooruTagList(input.value));
    const filtered = (items || []).filter(item => item && item.tag && !existing.has(item.tag));

    selectionBooruState.suggestItems = filtered;
    selectionBooruState.suggestIndex = -1;

    suggestions.innerHTML = "";
    if (!filtered.length) {
        suggestions.style.display = "none";
        return;
    }

    filtered.forEach((item, idx) => {
        const row = document.createElement("div");
        row.className = "booru-tag-suggestion";

        const label = document.createElement("span");
        const category = item.category || "general";
        const count = Number.isFinite(item.post_count) ? item.post_count : 0;
        label.textContent = `${item.tag} · ${category} · ${count.toLocaleString()}`;

        row.appendChild(label);

        row.addEventListener("mousedown", (e) => e.preventDefault());
        row.addEventListener("mouseenter", () => setActiveSelectionBooruSuggestion(idx));
        row.addEventListener("click", () => {
            applySelectionBooruSuggestion(item.tag);
        });

        suggestions.appendChild(row);
    });

    suggestions.style.display = "block";
}

function scheduleSelectionBooruSuggestions(query) {
    if (selectionBooruState.suggestTimer) {
        clearTimeout(selectionBooruState.suggestTimer);
    }
    selectionBooruState.suggestTimer = setTimeout(() => {
        fetchSelectionBooruSuggestions(query);
    }, 200);
}

async function fetchSelectionBooruSuggestions(query) {
    const normalized = normalizeBooruTagInput(query);
    if (!normalized) {
        clearSelectionBooruSuggestions();
        return;
    }
    const token = ++selectionBooruState.queryToken;
    try {
        const res = await fetch(`/api/booru/tags?q=${encodeURIComponent(normalized)}&limit=30`);
        const data = await res.json().catch(() => ({}));
        if (token !== selectionBooruState.queryToken) return;
        if (!res.ok) {
            throw new Error(data?.error || "불러오기 실패");
        }
        const items = Array.isArray(data.items) ? data.items : [];
        renderSelectionBooruSuggestions(items);
    } catch (err) {
        console.error("selection booru tag search error", err);
        clearSelectionBooruSuggestions();
    }
}

async function addSelectedBooruTags() {
    const input = selectionState.booruTagInput;
    const rawValue = input ? input.value : "";
    const tags = parseBooruTagList(rawValue);
    if (!tags.length) {
        showToast("추가할 Danbooru 태그를 입력하세요.", "error");
        return;
    }

    const targets = Array.from(selectionState.selected)
        .map(idx => results[idx])
        .filter(item => item && (item.file || item.img))
        .map(item => ({
            media: item.media || "image",
            path: item.file || item.img,
        }));

    if (!targets.length) {
        showToast("선택된 항목이 없습니다.", "error");
        return;
    }

    const button = selectionState.booruTagButton;
    if (button) button.disabled = true;

    try {
        const res = await fetch("/api/booru/item-tags/batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items: targets, tags }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.ok === false) {
            throw new Error(data?.error || "태그 추가 실패");
        }
        const updated = Number.isFinite(data?.updated) ? data.updated : targets.length;
        const skipped = Number.isFinite(data?.skipped) ? data.skipped : 0;
        const suffix = skipped ? ` (스킵 ${skipped}개)` : "";
        showToast(`✅ ${updated}개 항목에 태그 추가 완료${suffix}`);
        if (input) {
            input.value = "";
        }
        clearSelectionBooruSuggestions();
    } catch (err) {
        console.error("booru batch tag error", err);
        showToast(err?.message || "태그 추가 실패", "error");
    } finally {
        updateSelectionToolbar();
    }
}

async function removeSelectedBooruTags() {
    const input = selectionState.booruTagInput;
    const rawValue = input ? input.value : "";
    const tags = parseBooruTagList(rawValue);
    if (!tags.length) {
        showToast("삭제할 Danbooru 태그를 입력하세요.", "error");
        return;
    }

    const targets = Array.from(selectionState.selected)
        .map(idx => results[idx])
        .filter(item => item && (item.file || item.img))
        .map(item => ({
            media: item.media || "image",
            path: item.file || item.img,
        }));

    if (!targets.length) {
        showToast("선택된 항목이 없습니다.", "error");
        return;
    }

    const button = selectionState.booruTagRemoveButton;
    if (button) button.disabled = true;

    try {
        const res = await fetch("/api/booru/item-tags/batch-remove", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items: targets, tags }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.ok === false) {
            throw new Error(data?.error || "태그 삭제 실패");
        }
        const updated = Number.isFinite(data?.updated) ? data.updated : targets.length;
        const skipped = Number.isFinite(data?.skipped) ? data.skipped : 0;
        const suffix = skipped ? ` (스킵 ${skipped}개)` : "";
        showToast(`✅ ${updated}개 항목에서 태그 삭제 완료${suffix}`);
        if (input) {
            input.value = "";
        }
        clearSelectionBooruSuggestions();
    } catch (err) {
        console.error("booru batch tag remove error", err);
        showToast(err?.message || "태그 삭제 실패", "error");
    } finally {
        updateSelectionToolbar();
    }
}

function initSelectionBooruAutocomplete() {
    if (selectionBooruState.bound) return;
    const { input, suggestions, inputWrap } = getSelectionBooruElements();
    if (!input || !suggestions) return;
    selectionBooruState.bound = true;

    input.addEventListener("input", () => {
        updateSelectionToolbar();
        const query = getSelectionBooruQuery(input.value);
        if (!query) {
            clearSelectionBooruSuggestions();
            return;
        }
        scheduleSelectionBooruSuggestions(query);
    });

    input.addEventListener("keydown", event => {
        const key = event.key;
        const hasSuggestions = Array.isArray(selectionBooruState.suggestItems)
            && selectionBooruState.suggestItems.length > 0
            && suggestions.style.display !== "none";

        if (key === "ArrowDown" && hasSuggestions) {
            event.preventDefault();
            const max = selectionBooruState.suggestItems.length;
            const next = (selectionBooruState.suggestIndex + 1) % max;
            setActiveSelectionBooruSuggestion(next);
            return;
        }

        if (key === "ArrowUp" && hasSuggestions) {
            event.preventDefault();
            const max = selectionBooruState.suggestItems.length;
            const cur = selectionBooruState.suggestIndex;
            const next = (cur <= 0 ? (max - 1) : (cur - 1));
            setActiveSelectionBooruSuggestion(next);
            return;
        }

        if (key === "Enter" && hasSuggestions && selectionBooruState.suggestIndex >= 0) {
            event.preventDefault();
            const picked = selectionBooruState.suggestItems[selectionBooruState.suggestIndex];
            if (picked && picked.tag) {
                applySelectionBooruSuggestion(picked.tag);
            }
            return;
        }

        if (key === "Escape") {
            clearSelectionBooruSuggestions();
        }
    });

    document.addEventListener("click", event => {
        const wrap = inputWrap || input.parentElement;
        if (wrap && wrap.contains(event.target)) return;
        clearSelectionBooruSuggestions();
    });
}

async function downloadSelectedBatch() {
    const targets = Array.from(selectionState.selected)
        .map(idx => results[idx])
        .filter(item => item && item.file);

    if (targets.length === 0) {
        showToast("선택된 항목이 없습니다.", "error");
        return;
    }

    const button = selectionState.downloadButton;
    if (button) button.disabled = true;

    try {
        const payload = { paths: targets.map(t => t.file) };
        const scalePayload = getDownloadScalePayload("selection-download-scale");
        if (scalePayload) {
            Object.assign(payload, scalePayload);
        }
        const res = await fetch("/api/download_batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            let errorMsg = "다운로드에 실패했습니다.";
            try {
                const data = await res.json();
                if (data && data.error) errorMsg = data.error;
            } catch (err) {
                // ignore json parse error
            }
            throw new Error(errorMsg);
        }

        const blob = await res.blob();
        let fileName = "batch-download.zip";
        const disposition = res.headers.get("Content-Disposition");
        if (disposition && disposition.includes("filename=")) {
            fileName = disposition.split("filename=")[1].split(";")[0].replace(/"/g, "");
        }

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);

        const successCount = parseInt(res.headers.get("X-Download-Count") || `${targets.length}`, 10) || targets.length;
        const mode = res.headers.get("X-Download-Mode") || "strip";
        const actionText = mode === "single" ? "EXIF 제거 후 다운로드" : "EXIF 제거 후 압축";
        showToast(`✅ ${successCount}개 파일 ${actionText}했습니다.`);
    } catch (err) {
        showToast(`❌ ${err.message || err}`, "error");
    } finally {
        if (button) {
            button.disabled = selectionState.selected.size === 0;
        }
    }
}

function getDownloadScalePayload(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return null;
    const value = parseFloat(select.value);
    if (!Number.isFinite(value) || value <= 0) return null;
    if (value < 1) return { ratio: value };
    if (value > 1) return { scale: Math.round(value) };
    return null;
}

function renderCollectionOptions(select, { includeAll = false, placeholder = "" } = {}) {
    if (!select) return;
    const current = select.value;
    select.innerHTML = "";
    if (includeAll) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = placeholder || "전체";
        select.appendChild(opt);
    }
    collectionState.list.forEach(col => {
        const opt = document.createElement("option");
        opt.value = col.id;
        const indent = col.depth ? "— ".repeat(col.depth) : "";
        opt.textContent = indent + (col.label || col.name);
        select.appendChild(opt);
    });
    if (current) {
        select.value = current;
    }
}

function normalizeCollectionIds(selectedIds) {
    const ids = Array.isArray(selectedIds) ? selectedIds : (selectedIds ? [selectedIds] : []);
    const cleaned = [];
    const seen = new Set();
    ids.forEach((id) => {
        if (id === undefined || id === null || id === "") return;
        const idStr = String(id);
        if (seen.has(idStr)) return;
        seen.add(idStr);
        cleaned.push(idStr);
    });
    return cleaned;
}

function syncCollectionHiddenInputs() {
    if (!collectionState.hiddenInputs) return;
    collectionState.hiddenInputs.innerHTML = "";
    collectionState.selectedIds.forEach((id) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "collection_id";
        input.value = id;
        collectionState.hiddenInputs.appendChild(input);
    });
}

function updateCollectionFilterSummary() {
    if (!collectionState.filterSummary) return;
    const labels = collectionState.selectedIds
        .map(id => getCollectionLabelById(Number(id)) || `#${id}`)
        .filter(Boolean);
    let summaryText = "전체";
    if (labels.length === 1) {
        summaryText = labels[0];
    } else if (labels.length === 2) {
        summaryText = `${labels[0]} · ${labels[1]}`;
    } else if (labels.length > 2) {
        summaryText = `${labels[0]} 외 ${labels.length - 1}개`;
    }
    collectionState.filterSummary.textContent = summaryText;
    collectionState.filterSummary.title = labels.join(", ") || "전체";
}

function renderCollectionChips(filterText = "") {
    const chipList = collectionState.filterChipList;
    if (!chipList) return;
    chipList.innerHTML = "";
    const keyword = (filterText || "").toLowerCase();
    const filtered = collectionState.list.filter(col => {
        const label = (col.label || col.name || "").toLowerCase();
        return !keyword || label.includes(keyword);
    });
    if (!filtered.length) {
        const empty = document.createElement("div");
        empty.textContent = "일치하는 모음집이 없습니다.";
        empty.className = "small-dimmed";
        chipList.appendChild(empty);
        return;
    }
    filtered.forEach((col) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "collection-chip";
        button.dataset.id = col.id;
        button.textContent = col.label || col.name;
        if (collectionState.selectedIds.includes(String(col.id))) {
            button.classList.add("active");
        }
        button.setAttribute("aria-pressed", collectionState.selectedIds.includes(String(col.id)) ? "true" : "false");
        button.addEventListener("click", () => {
            const idStr = String(col.id);
            if (collectionState.selectedIds.includes(idStr)) {
                collectionState.selectedIds = collectionState.selectedIds.filter(id => id !== idStr);
            } else {
                collectionState.selectedIds = [...collectionState.selectedIds, idStr];
            }
            button.setAttribute("aria-pressed", collectionState.selectedIds.includes(idStr) ? "true" : "false");
            syncCollectionHiddenInputs();
            updateCollectionFilterSummary();
            renderCollectionChips(collectionState.filterSearchInput?.value || "");
        });
        chipList.appendChild(button);
    });
}

function syncCollectionSelections(selectedIds) {
    collectionState.selectedIds = normalizeCollectionIds(selectedIds);
    if (collectionState.addSelect && !collectionState.addSelect.value && collectionState.selectedIds.length) {
        collectionState.addSelect.value = collectionState.selectedIds[0];
    }
    if (collectionState.renameSelect && collectionState.selectedIds.length === 1) {
        collectionState.renameSelect.value = String(collectionState.selectedIds[0]);
    }
    if (collectionState.deleteSelect && collectionState.selectedIds.length === 1) {
        collectionState.deleteSelect.value = String(collectionState.selectedIds[0]);
    }
    syncCollectionHiddenInputs();
    updateCollectionFilterSummary();
    renderCollectionChips(collectionState.filterSearchInput?.value || "");
    updateSelectionToolbar();
}

const modelCategorySelect = document.getElementById("model-category-select");

function syncModelCategorySelection(selectedId) {
    if (selectedId === undefined || selectedId === null) selectedId = "";
    if (modelCategorySelect) modelCategorySelect.value = selectedId || "";
}

async function reloadCollections(selectedId) {
    try {
        const res = await fetch("/api/collections");
        const data = await res.json();
        if (Array.isArray(data)) {
            collectionState.raw = data;
            refreshCollectionList();
        }
    } catch (err) {
        console.error("컬렉션 목록 불러오기 실패", err);
    }
    renderCollectionOptions(collectionState.addSelect, { includeAll: true, placeholder: "모음집 선택" });
    renderCollectionOptions(collectionState.renameSelect, {});
    renderCollectionOptions(collectionState.deleteSelect, {});
    renderCollectionOptions(collectionState.createParentSelect, { includeAll: true, placeholder: "(루트)" });
    renderCollectionOptions(collectionState.renameParentSelect, { includeAll: true, placeholder: "(루트)" });
    const fallback = window.initialData && (window.initialData.collection_ids || window.initialData.collection_id);
    syncCollectionSelections(selectedId !== undefined ? selectedId : fallback);
}

function initializeSelectionUI() {
    selectionState.toolbar = document.getElementById("selection-toolbar");
    selectionState.countLabel = document.getElementById("selection-count");
    selectionState.deleteButton = document.getElementById("selection-delete");
    selectionState.cancelButton = document.getElementById("selection-cancel");
    selectionState.addButton = document.getElementById("selection-add");
    selectionState.removeButton = document.getElementById("selection-remove");
    selectionState.addSelect = document.getElementById("add-to-collection-select");
    selectionState.downloadButton = document.getElementById("selection-download");
    selectionState.compareButton = document.getElementById("selection-compare");
    selectionState.booruTagInput = document.getElementById("selection-booru-tags");
    selectionState.booruTagButton = document.getElementById("selection-booru-add");
    selectionState.booruTagRemoveButton = document.getElementById("selection-booru-remove");

    selectionState.deleteButton?.addEventListener("click", deleteSelectedMedia);
    selectionState.cancelButton?.addEventListener("click", () => disableSelectionMode());
    selectionState.addButton?.addEventListener("click", addSelectedToCollection);
    selectionState.removeButton?.addEventListener("click", removeSelectedFromCollection);
    selectionState.addSelect?.addEventListener("change", updateSelectionToolbar);
    selectionState.downloadButton?.addEventListener("click", downloadSelectedBatch);
    selectionState.compareButton?.addEventListener("click", openCompareModal);
    selectionState.booruTagButton?.addEventListener("click", addSelectedBooruTags);
    selectionState.booruTagRemoveButton?.addEventListener("click", removeSelectedBooruTags);
    initSelectionBooruAutocomplete();
    ensureDragBox();
    updateSelectionToolbar();
}

// ✅ 모달 표시
function showModalFromIndex(index, options = {}) {
    if (index >= 0 && index < results.length) {
        const item = results[index];
        currentImageIndex = index;
        showModal(item, options);
    }
}

function formatReadableDate(value) {
    if (value === undefined || value === null || value === "") return "";

    const toDate = (val) => {
        if (val instanceof Date) return val;
        if (typeof val === "number") {
            const millis = val < 1e12 ? val * 1000 : val;
            return new Date(millis);
        }
        if (typeof val === "string") {
            const trimmed = val.trim();
            if (!trimmed) return new Date(NaN);
            const numeric = Number(trimmed);
            if (!Number.isNaN(numeric)) {
                const millis = numeric < 1e12 ? numeric * 1000 : numeric;
                return new Date(millis);
            }
            return new Date(trimmed);
        }
        return new Date(val);
    };

    const dateObj = toDate(value);
    if (Number.isNaN(dateObj.getTime())) return "";

    const pad = (num) => String(num).padStart(2, "0");
    const year = dateObj.getFullYear();
    const month = pad(dateObj.getMonth() + 1);
    const day = pad(dateObj.getDate());
    const hours = pad(dateObj.getHours());
    const minutes = pad(dateObj.getMinutes());

    return `${year}-${month}-${day} ${hours}:${minutes}`;
}

function normalizeMediaPath(path) {
    if (typeof path !== "string") return "";
    return path.split("?")[0].split("#")[0];
}

function getIndicatorPath(item, fallbackPath = "") {
    if (!item || typeof item !== "object") return fallbackPath;
    return item.file || item.img || item.rel_thumb || item.thumb_rel || fallbackPath;
}

function hasSoundFlag(value) {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value === 1;
    if (typeof value !== "string") return false;
    const normalized = value.trim().toLowerCase();
    return ["y", "yes", "true", "1"].includes(normalized);
}

function isGifFile(path) {
    const cleaned = normalizeMediaPath(path);
    return typeof cleaned === "string" && cleaned.toLowerCase().endsWith(".gif");
}

function getDetailPath(item) {
    return item?.file || item?.img || "";
}

function shouldFetchDetail(item) {
    if (!item) return false;
    if (item.compact === true) return true;
    return item.positive === undefined
        && item.negative === undefined
        && item.loras === undefined
        && item.seed === undefined
        && item.sampler === undefined
        && item.cfg === undefined
        && item.models === undefined
        && item.model === undefined;
}

function setModalMetadataLoading() {
    document.getElementById("modal-positive").textContent = "불러오는 중...";
    document.getElementById("modal-negative").textContent = "불러오는 중...";
    document.getElementById("modal-size").textContent = "";
    document.getElementById("modal-seed").textContent = "";
    document.getElementById("modal-sampler").textContent = "";
    document.getElementById("modal-model").textContent = "불러오는 중...";
    document.getElementById("modal-date").textContent = "불러오는 중...";
    document.getElementById("modal-cfg").textContent = "";
    const profileBox = document.getElementById("modal-profiles");
    if (profileBox) {
        profileBox.textContent = "불러오는 중...";
    }
}

function renderModalMetadata(item) {
    const meta = item.meta || {};
    const prompt = item.prompt || item.positive || meta.prompt || "";
    const negative = item.negative || meta.negative || "";
    const width = item.width ?? meta.width;
    const height = item.height ?? meta.height;
    const seed = item.seed ?? meta.seed;
    const sampler = item.sampler || meta.sampler || "";
    const cfg = item.cfg ?? meta.cfg;
    const rawModels = Array.isArray(item.models) ? item.models : (Array.isArray(meta.models) ? meta.models : []);
    const cleanedModels = rawModels.map(m => String(m || "").trim()).filter(Boolean);
    const model = cleanedModels.length
        ? cleanedModels.join(", ")
        : (item.model || meta.model || meta.model_name || meta.model_checkpoint || "");
    const rawDate = item.date ?? meta.created ?? item.ts ?? meta.date ?? "";
    const formattedDate = formatReadableDate(rawDate);

    document.getElementById("modal-positive").textContent = prompt;
    document.getElementById("modal-negative").textContent = negative;
    document.getElementById("modal-size").textContent = (width && height) ? `${width}×${height}` : "";
    document.getElementById("modal-seed").textContent = (seed !== undefined && seed !== null) ? seed : "";
    document.getElementById("modal-sampler").textContent = sampler;
    document.getElementById("modal-model").textContent = model || "정보 없음";
    document.getElementById("modal-date").textContent = formattedDate || "정보 없음";
    document.getElementById("modal-cfg").textContent = (cfg !== undefined && cfg !== null) ? cfg : "";
    const profileBox = document.getElementById("modal-profiles");
    if (profileBox) {
        profileBox.innerHTML = "";
        const loras = Array.isArray(item.loras) ? item.loras : [];
        if (loras.length) {
            loras.forEach((lora) => {
                const row = document.createElement("div");
                row.className = "profile-row";

                const name = document.createElement("span");
                name.className = "profile-name";
                name.textContent = lora.name || "(이름 없음)";

                const weight = document.createElement("span");
                weight.className = "profile-weight";
                const rawWeight = lora.weight ?? lora.strength;
                let weightText = "";
                if (rawWeight !== undefined && rawWeight !== null && rawWeight !== "") {
                    const asNum = Number(rawWeight);
                    const formatted = Number.isFinite(asNum)
                        ? asNum.toFixed(3).replace(/\.0+$/, "").replace(/\.([0-9]*[1-9])0+$/, ".$1")
                        : String(rawWeight);
                    weightText = `가중치: ${formatted}`;
                } else {
                    weightText = "가중치 정보 없음";
                }
                weight.textContent = weightText;

                row.appendChild(name);
                row.appendChild(weight);
                profileBox.appendChild(row);
            });
        } else {
            profileBox.textContent = "정보 없음";
        }
    }
}

function initModalCopyHeaders() {
    if (modalCopyState.bound) return;
    const table = document.querySelector(".modal-meta-table");
    if (!table) return;
    modalCopyState.bound = true;

    const bindTitle = (valueId, label) => {
        const valueEl = document.getElementById(valueId);
        const titleEl = valueEl?.previousElementSibling;
        if (!titleEl || titleEl.tagName !== "DT") return;
        titleEl.classList.add("modal-copy-title");
        titleEl.dataset.copyTarget = valueId;
        titleEl.dataset.copyLabel = label;
        titleEl.title = `${label} 복사`;
    };

    bindTitle("modal-positive", "긍정 프롬프트");
    bindTitle("modal-negative", "부정 프롬프트");

    table.addEventListener("click", (event) => {
        const target = event.target.closest(".modal-copy-title");
        if (!target || !table.contains(target)) return;
        const targetId = target.dataset.copyTarget;
        const label = target.dataset.copyLabel || "내용";
        const value = document.getElementById(targetId)?.textContent || "";
        copyTextToClipboard(value, {
            successMessage: `✅ ${label} 복사됨`,
            emptyMessage: "복사할 내용이 없습니다.",
        });
    });
}

function initRelatedPanel() {
    relatedContentState.button = document.getElementById("related-content-toggle");
    relatedContentState.panel = document.getElementById("modal-related-panel");
    relatedContentState.listEl = document.getElementById("modal-related-list");
    relatedContentState.metaEl = document.getElementById("modal-related-meta");
    relatedContentState.scrim = document.getElementById("modal-related-scrim");
    relatedContentState.closeBtn = document.getElementById("modal-related-close");
    relatedContentState.distanceInput = document.getElementById("related-distance");
    relatedContentState.distanceValueEl = document.getElementById("related-distance-value");
    relatedContentState.filterImagesEl = document.getElementById("related-filter-images");
    relatedContentState.filterVideosEl = document.getElementById("related-filter-videos");
    relatedContentState.filterPairsEl = document.getElementById("related-filter-pairs");

    if (relatedContentState.button) {
        relatedContentState.button.addEventListener("click", toggleRelatedPanel);
    }
    if (relatedContentState.closeBtn) {
        relatedContentState.closeBtn.addEventListener("click", closeRelatedPanel);
    }
    if (relatedContentState.scrim) {
        relatedContentState.scrim.addEventListener("click", closeRelatedPanel);
    }
    const settingsKey = "mygallery.relatedSettings";
    const updateControls = () => {
        if (relatedContentState.distanceInput) {
            const value = Number.parseInt(relatedContentState.distanceInput.value, 10);
            relatedContentState.distance = Number.isFinite(value) ? value : 0;
            if (relatedContentState.distanceValueEl) {
                relatedContentState.distanceValueEl.textContent = String(relatedContentState.distance);
            }
        }
        if (relatedContentState.filterImagesEl) {
            relatedContentState.includeImages = relatedContentState.filterImagesEl.checked;
        }
        if (relatedContentState.filterVideosEl) {
            relatedContentState.includeVideos = relatedContentState.filterVideosEl.checked;
        }
        if (relatedContentState.filterPairsEl) {
            relatedContentState.includeVideoPairs = relatedContentState.filterPairsEl.checked;
        }
        try {
            localStorage.setItem(
                settingsKey,
                JSON.stringify({
                    distance: relatedContentState.distance,
                    includeImages: relatedContentState.includeImages,
                    includeVideos: relatedContentState.includeVideos,
                    includeVideoPairs: relatedContentState.includeVideoPairs,
                })
            );
        } catch (err) {
            console.warn("related settings save failed", err);
        }
        if (relatedContentState.open) {
            fetchRelatedForCurrentItem(true);
        }
    };
    try {
        const saved = JSON.parse(localStorage.getItem(settingsKey) || "{}");
        if (relatedContentState.distanceInput && Number.isFinite(saved?.distance)) {
            relatedContentState.distanceInput.value = String(saved.distance);
        }
        if (relatedContentState.filterImagesEl && typeof saved?.includeImages === "boolean") {
            relatedContentState.filterImagesEl.checked = saved.includeImages;
        }
        if (relatedContentState.filterVideosEl && typeof saved?.includeVideos === "boolean") {
            relatedContentState.filterVideosEl.checked = saved.includeVideos;
        }
        if (relatedContentState.filterPairsEl && typeof saved?.includeVideoPairs === "boolean") {
            relatedContentState.filterPairsEl.checked = saved.includeVideoPairs;
        }
    } catch (err) {
        console.warn("related settings load failed", err);
    }
    if (relatedContentState.distanceInput) {
        relatedContentState.distanceInput.addEventListener("input", updateControls);
        relatedContentState.distanceInput.addEventListener("change", updateControls);
    }
    relatedContentState.filterImagesEl?.addEventListener("change", updateControls);
    relatedContentState.filterVideosEl?.addEventListener("change", updateControls);
    relatedContentState.filterPairsEl?.addEventListener("change", updateControls);
    updateControls();
}

function setProfileMenuOpen(open) {
    profileMenuState.open = open;
    if (profileMenuState.root) {
        profileMenuState.root.classList.toggle("open", open);
    }
    if (profileMenuState.toggle) {
        profileMenuState.toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
}

function initProfileMenu() {
    profileMenuState.root = document.getElementById("profile-menu");
    profileMenuState.toggle = document.getElementById("profile-menu-toggle");
    profileMenuState.panel = document.getElementById("profile-menu-panel");
    if (!profileMenuState.root || !profileMenuState.toggle || !profileMenuState.panel) return;

    profileMenuState.toggle.addEventListener("click", (event) => {
        event.stopPropagation();
        setProfileMenuOpen(!profileMenuState.open);
    });

    profileMenuState.panel.addEventListener("click", (event) => {
        const target = event.target.closest(".profile-menu-item");
        if (target) {
            setProfileMenuOpen(false);
        }
    });

    document.addEventListener("click", (event) => {
        if (!profileMenuState.open) return;
        if (!profileMenuState.root.contains(event.target)) {
            setProfileMenuOpen(false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && profileMenuState.open) {
            setProfileMenuOpen(false);
        }
    });
}

async function fetchDetailForItem(item) {
    const path = getDetailPath(item);
    if (!path) return null;
    if (detailCache.has(path)) {
        return detailCache.get(path);
    }

    const requestToken = ++detailRequestToken;
    setModalMetadataLoading();
    try {
        const res = await fetch(`/api/detail?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data?.error || "상세 정보를 불러올 수 없습니다.");
        }
        const detailItem = data.item || data;
        detailCache.set(path, detailItem);
        if (requestToken !== detailRequestToken) {
            return detailItem;
        }
        if (currentImagePath === item.file || currentImagePath === detailItem.file) {
            const merged = { ...item, ...detailItem, compact: false };
            if (currentImageIndex >= 0) {
                results[currentImageIndex] = merged;
            }
            renderModalMetadata(merged);
        }
        return detailItem;
    } catch (err) {
        console.error("상세 정보 로딩 실패", err);
        return null;
    }
}

function setVideoErrorMessage(message = "") {
    const errorEl = document.getElementById("modal-video-error");
    if (!errorEl) return;
    if (message) {
        errorEl.textContent = message;
        errorEl.style.display = "block";
    } else {
        errorEl.textContent = "";
        errorEl.style.display = "none";
    }
}

function attachVideoErrorListeners(videoEl) {
    if (!videoEl || videoEl.dataset.errorListenerAttached === "true") return;
    const handleError = () => {
        const err = videoEl.error;
        const code = err?.code ?? "unknown";
        const message = err?.message || "알 수 없는 오류";
        const detailText = [
            `영상 재생 오류 (code: ${code}, message: ${message}).`,
            "파일의 MIME 타입이 맞지 않거나 브라우저에서 지원하지 않는 코덱일 수 있습니다.",
        ].join("\n");
        console.error("영상 재생 오류", { code, message, error: err });
        setVideoErrorMessage(detailText);
    };
    const clearError = () => {
        setVideoErrorMessage("");
    };

    videoEl.addEventListener("error", handleError);
    videoEl.addEventListener("loadeddata", clearError);
    videoEl.addEventListener("canplay", clearError);
    videoEl.dataset.errorListenerAttached = "true";
}

function normalizeBooruTagInput(value) {
    if (!value) return "";
    return String(value)
        .trim()
        .toLowerCase()
        .replace(/\s+/g, " ")
        .replace(/ /g, "_");
}

function applyBooruTagSearch(tag) {
    const form = document.getElementById("search-form");
    const input = document.getElementById("search-input");
    const matchInput = document.getElementById("search-match-input");
    const tagSourceInput = document.getElementById("search-tag-source");
    const tagSourceButtons = Array.from(document.querySelectorAll(".search-toggle .toggle-btn[data-tag-source]"));
    const matchButtons = Array.from(document.querySelectorAll(".search-toggle .toggle-btn[data-match]"));
    if (input) {
        input.value = tag;
    }
    if (matchInput) {
        matchInput.value = "and";
    }
    if (tagSourceInput) {
        tagSourceInput.value = "booru";
    }
    tagSourceButtons.forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tagSource === "booru");
    });
    matchButtons.forEach(btn => {
        btn.classList.toggle("active", btn.dataset.match === "and");
    });
    form?.submit();
}

function isRatingBooruTag(tag) {
    const t = String(tag || "").toLowerCase();
    if (t.startsWith("rating:")) return true;
    // WD CSV rating segment can be bare labels without the "rating:" prefix.
    // Treat them as rating markers so they don't show up as normal tag chips.
    return t === "general" || t === "sensitive" || t === "questionable" || t === "explicit";
}

function normalizeBooruSource(source) {
    return source || BOORU_MANUAL_SOURCE;
}

function isAutoBooruSource(source) {
    return normalizeBooruSource(source).startsWith(BOORU_AUTO_PREFIX);
}

function getBooruTagElements() {
    return {
        section: document.querySelector(".booru-tags-section"),
        groups: document.getElementById("booru-tags-groups"),
        input: document.getElementById("booru-tag-input"),
        suggestions: document.getElementById("booru-tag-suggestions"),
        addBtn: document.getElementById("booru-tag-add"),
        autoTagBtn: document.getElementById("booru-tag-auto"),
        inputWrap: document.querySelector(".booru-tag-input-wrap"),
        ratingSelect: document.getElementById("booru-rating-select"),
    };
}

function clearBooruSuggestions() {
    const { suggestions } = getBooruTagElements();
    if (!suggestions) return;
    suggestions.innerHTML = "";
    suggestions.style.display = "none";

    booruTagState.suggestItems = [];
    booruTagState.suggestIndex = -1;
}

function closeBooruChipPopover() {
    if (!booruTagState.popoverEl) return;
    booruTagState.popoverEl.remove();
    booruTagState.popoverEl = null;
}

function showBooruChipPopover(target, { message, onYes }) {
    if (!target) return;
    closeBooruChipPopover();
    const popover = document.createElement("div");
    popover.className = "booru-chip-popover";

    const msg = document.createElement("div");
    msg.className = "booru-chip-popover-message";
    msg.textContent = message;
    popover.appendChild(msg);

    const actions = document.createElement("div");
    actions.className = "booru-chip-popover-actions";

    const close = () => {
        closeBooruChipPopover();
    };

    if (onYes) {
        const yesBtn = document.createElement("button");
        yesBtn.type = "button";
        yesBtn.className = "booru-chip-popover-btn yes";
        yesBtn.textContent = "Y";
        yesBtn.addEventListener("click", event => {
            event.stopPropagation();
            onYes();
            close();
        });

        const noBtn = document.createElement("button");
        noBtn.type = "button";
        noBtn.className = "booru-chip-popover-btn no";
        noBtn.textContent = "N";
        noBtn.addEventListener("click", event => {
            event.stopPropagation();
            close();
        });

        actions.appendChild(yesBtn);
        actions.appendChild(noBtn);
    } else {
        const okBtn = document.createElement("button");
        okBtn.type = "button";
        okBtn.className = "booru-chip-popover-btn ok";
        okBtn.textContent = "OK";
        okBtn.addEventListener("click", event => {
            event.stopPropagation();
            close();
        });
        actions.appendChild(okBtn);
    }

    popover.appendChild(actions);
    popover.addEventListener("click", event => {
        event.stopPropagation();
    });

    document.body.appendChild(popover);
    booruTagState.popoverEl = popover;

    const rect = target.getBoundingClientRect();
    const top = rect.bottom + window.scrollY + 6;
    const left = rect.left + window.scrollX;
    popover.style.top = `${top}px`;
    popover.style.left = `${left}px`;
}

function getVisibleBooruItems() {
    return booruTagState.items.filter(item => {
        if (!item || !item.tag) return false;
        return !isRatingBooruTag(item.tag);
    });
}

function renderBooruTagsGrouped() {
    const { groups } = getBooruTagElements();
    if (!groups) return;
    groups.innerHTML = "";
    closeBooruChipPopover();
    const order = ["copyright", "character", "artist", "general", "meta"];
    const titles = {
        copyright: "Copyright",
        character: "Character",
        artist: "Artist",
        general: "General",
        meta: "Meta",
    };
    const grouped = new Map();
    getVisibleBooruItems().forEach(item => {
        if (!item || !item.tag) return;
        const category = (item.category || "general").toLowerCase();
        if (!grouped.has(category)) {
            grouped.set(category, []);
        }
        grouped.get(category).push(item);
    });

    const sortBooruItems = items =>
        [...items].sort((a, b) => String(a.tag || "").localeCompare(String(b.tag || ""), undefined, { sensitivity: "base" }));
    const createBooruTagChip = item => {
        const tag = item.tag;
        const chip = document.createElement("span");
        const source = normalizeBooruSource(item.source);
        const isAuto = isAutoBooruSource(source);
        chip.className = `booru-tag-chip ${isAuto ? "auto" : "manual"}`;

        const label = document.createElement("span");
        label.textContent = tag;
        chip.appendChild(label);

        chip.addEventListener("click", event => {
            event.stopPropagation();
            applyBooruTagSearch(tag);
        });

        chip.addEventListener("contextmenu", event => {
            event.preventDefault();
            event.stopPropagation();
            if (isAuto) {
                showBooruChipPopover(chip, {
                    message: "이 태그는 WD로 자동 추가된 태그입니다.\n수정/삭제는 수동 태그만 가능합니다.",
                });
                return;
            }
            showBooruChipPopover(chip, {
                message: `태그 "${tag}" 를 삭제할까요?`,
                onYes: () => removeBooruTag(tag),
            });
        });

        return chip;
    };

    order.forEach(category => {
        const items = sortBooruItems(grouped.get(category) || []);
        const group = document.createElement("div");
        group.className = "booru-tags-group";

        const titleLabel = titles[category] || category;
        const title = document.createElement("div");
        title.className = "booru-tags-group-title is-copyable";
        title.textContent = titleLabel;
        title.title = `${titleLabel} 태그 복사`;
        title.addEventListener("click", event => {
            event.stopPropagation();
            const tags = items.map(item => item.tag).filter(Boolean);
            copyTextToClipboard(tags.join(", "), {
                successMessage: `✅ ${titleLabel} 태그 ${tags.length}개 복사됨`,
                emptyMessage: "복사할 태그가 없습니다.",
            });
        });

        const count = document.createElement("span");
        count.className = "count";
        count.textContent = `(${items.length})`;
        title.appendChild(count);

        const chips = document.createElement("div");
        chips.className = "booru-tags-group-chips";

        if (!items.length) {
            const empty = document.createElement("span");
            empty.className = "booru-tag-empty";
            empty.textContent = "태그 없음";
            chips.appendChild(empty);
        } else {
            items.forEach(item => {
                chips.appendChild(createBooruTagChip(item));
            });
        }

        group.appendChild(title);
        group.appendChild(chips);
        groups.appendChild(group);
    });

    Array.from(grouped.keys())
        .filter(category => !order.includes(category))
        .forEach(category => {
            const items = sortBooruItems(grouped.get(category) || []);
            if (!items.length) return;
            const group = document.createElement("div");
            group.className = "booru-tags-group";

            const titleLabel = category;
            const title = document.createElement("div");
            title.className = "booru-tags-group-title is-copyable";
            title.textContent = titleLabel;
            title.title = `${titleLabel} 태그 복사`;
            title.addEventListener("click", event => {
                event.stopPropagation();
                const tags = items.map(item => item.tag).filter(Boolean);
                copyTextToClipboard(tags.join(", "), {
                    successMessage: `✅ ${titleLabel} 태그 ${tags.length}개 복사됨`,
                    emptyMessage: "복사할 태그가 없습니다.",
                });
            });

            const count = document.createElement("span");
            count.className = "count";
            count.textContent = `(${items.length})`;
            title.appendChild(count);

        const chips = document.createElement("div");
        chips.className = "booru-tags-group-chips";

        items.forEach(item => {
            chips.appendChild(createBooruTagChip(item));
        });

            group.appendChild(title);
            group.appendChild(chips);
            groups.appendChild(group);
        });
}

function setActiveBooruSuggestion(index) {
    const { suggestions } = getBooruTagElements();
    const items = Array.isArray(booruTagState.suggestItems) ? booruTagState.suggestItems : [];
    const max = items.length;
    if (!suggestions || !max) {
        booruTagState.suggestIndex = -1;
        return;
    }
    const next = Number.isFinite(index) ? index : -1;
    booruTagState.suggestIndex = next;

    const rows = Array.from(suggestions.querySelectorAll('.booru-tag-suggestion'));
    rows.forEach((row, i) => {
        if (i == next) row.classList.add('active');
        else row.classList.remove('active');
    });

    if (next >= 0 && rows[next]) {
        try {
            rows[next].scrollIntoView({ block: 'nearest' });
        } catch (e) {
            // ignore
        }
    }
}

function renderBooruSuggestions(items = []) {
    const { suggestions } = getBooruTagElements();
    if (!suggestions) return;
    const existing = new Set(booruTagState.manualTags);
    const filtered = (items || []).filter(item => item && item.tag && !existing.has(item.tag));

    booruTagState.suggestItems = filtered;
    booruTagState.suggestIndex = -1;

    suggestions.innerHTML = "";
    if (!filtered.length) {
        suggestions.style.display = "none";
        return;
    }

    filtered.forEach((item, idx) => {
        const row = document.createElement("div");
        row.className = "booru-tag-suggestion";

        const label = document.createElement("span");
        const category = item.category || "general";
        const count = Number.isFinite(item.post_count) ? item.post_count : 0;
        label.textContent = `${item.tag} · ${category} · ${count.toLocaleString()}`;

        row.appendChild(label);

        // Keep focus on the input when clicking suggestions.
        row.addEventListener('mousedown', (e) => e.preventDefault());
        row.addEventListener('mouseenter', () => setActiveBooruSuggestion(idx));
        row.addEventListener("click", () => {
            addBooruTag(item.tag);
        });

        suggestions.appendChild(row);
    });

    suggestions.style.display = "block";
}


function scheduleBooruSuggestions(query) {
    if (booruTagState.suggestTimer) {
        clearTimeout(booruTagState.suggestTimer);
    }
    booruTagState.suggestTimer = setTimeout(() => {
        fetchBooruSuggestions(query);
    }, 200);
}

async function fetchBooruSuggestions(query) {
    const normalized = normalizeBooruTagInput(query);
    if (!normalized) {
        clearBooruSuggestions();
        return;
    }
    const token = ++booruTagState.queryToken;
    try {
        const res = await fetch(`/api/booru/tags?q=${encodeURIComponent(normalized)}&limit=30`);
        const data = await res.json().catch(() => ({}));
        if (token !== booruTagState.queryToken) return;
        if (!res.ok) {
            throw new Error(data?.error || "불러오기 실패");
        }
        const items = Array.isArray(data.items) ? data.items : [];
        renderBooruSuggestions(items);
    } catch (err) {
        console.error("booru tag search error", err);
        clearBooruSuggestions();
    }
}

function addBooruTag(rawTag) {
    const tag = normalizeBooruTagInput(rawTag);
    const { input, ratingSelect } = getBooruTagElements();
    if (input) input.value = "";
    clearBooruSuggestions();
    if (!tag) return;
    if (isRatingBooruTag(tag)) {
        const ratingKey = tag.slice("rating:".length);
        const ratingMap = {
            general: 0,
            sensitive: 1,
            questionable: 2,
            explicit: 3,
        };
        if (ratingKey in ratingMap) {
            const value = ratingMap[ratingKey];
            if (ratingSelect) ratingSelect.value = String(value);
            saveBooruRating(value);
        }
        return;
    }
    if (booruTagState.manualTags.includes(tag)) return;
    booruTagState.manualTags = [...booruTagState.manualTags, tag];
    if (!booruTagState.items.some(item => item.tag === tag && normalizeBooruSource(item.source) === BOORU_MANUAL_SOURCE)) {
        booruTagState.items = [
            ...booruTagState.items,
            { tag, category: "general", post_count: 0, source: BOORU_MANUAL_SOURCE, editable: true },
        ];
    }
    renderBooruTagsGrouped();
    scheduleBooruTagSave();
}

function removeBooruTag(tag) {
    booruTagState.manualTags = booruTagState.manualTags.filter(item => item !== tag);
    booruTagState.items = booruTagState.items.filter(
        item => !(item.tag === tag && normalizeBooruSource(item.source) === BOORU_MANUAL_SOURCE)
    );
    renderBooruTagsGrouped();
    scheduleBooruTagSave();
}

function scheduleBooruTagSave() {
    if (booruTagState.saveTimer) {
        clearTimeout(booruTagState.saveTimer);
    }
    booruTagState.saveTimer = setTimeout(() => {
        saveBooruTags();
    }, 400);
}

async function saveBooruTags() {
    if (!booruTagState.path) return;
    // Rating is handled by the dropdown. Never persist rating markers as normal manual tags.
    booruTagState.manualTags = (booruTagState.manualTags || []).filter(t => !isRatingBooruTag(t));
    const payload = {
        media: booruTagState.media || "image",
        path: booruTagState.path,
        tags: booruTagState.manualTags,
    };
    booruTagState.saving = true;
    try {
        const res = await fetch("/api/booru/item-tags", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.ok === false) {
            throw new Error(data?.error || "저장 실패");
        }
        if (Array.isArray(data.manual_tags)) {
            booruTagState.manualTags = data.manual_tags;
        }
        if (Array.isArray(data.items)) {
            booruTagState.items = data.items;
            renderBooruTagsGrouped();
        }
        if (Array.isArray(data.sources)) {
            booruTagState.sources = data.sources;
        }
        showToast("저장됨", "success");
    } catch (err) {
        console.error("booru tag save error", err);
        showToast(err?.message || "저장 실패", "error");
    } finally {
        booruTagState.saving = false;
    }
}

function setBooruAutoTagState(isBusy) {
    const { autoTagBtn } = getBooruTagElements();
    if (!autoTagBtn) return;
    if (isBusy) {
        autoTagBtn.disabled = true;
        autoTagBtn.textContent = "태깅 중...";
        return;
    }
    autoTagBtn.textContent = "자동 태깅";
    autoTagBtn.disabled = !booruTagState.path || booruTagState.media === "video";
}

async function runBooruAutoTag() {
    if (!booruTagState.path) return;
    setBooruAutoTagState(true);
    try {
        const payload = {
            media: booruTagState.media || "image",
            path: booruTagState.path,
        };
        const res = await fetch("/api/booru/auto-tag", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.ok === false) {
            throw new Error(data?.error || "자동 태깅 실패");
        }
        if (Array.isArray(data.items)) {
            booruTagState.items = data.items;
        }
        if (Array.isArray(data.sources)) {
            booruTagState.sources = data.sources;
        }
        booruTagState.rating = data.rating || booruTagState.rating || null;
        const { ratingSelect } = getBooruTagElements();
        if (ratingSelect) {
            ratingSelect.value = booruTagState.rating?.value ?? "";
        }
        renderBooruTagsGrouped();
        showToast("자동 태깅 완료", "success");
    } catch (err) {
        console.error("booru auto tag error", err);
        showToast(err?.message || "자동 태깅 실패", "error");
    } finally {
        setBooruAutoTagState(false);
    }
}

async function loadBooruTagsForCurrentItem() {
    const { input, ratingSelect } = getBooruTagElements();
    if (input) input.value = "";
    clearBooruSuggestions();
    booruTagState.media = currentMediaType || "image";
    booruTagState.path = currentImagePath || "";
    const { autoTagBtn } = getBooruTagElements();
    if (autoTagBtn) {
        autoTagBtn.textContent = "자동 태깅";
        autoTagBtn.disabled = !booruTagState.path || booruTagState.media === "video";
    }
    if (!booruTagState.path) {
        booruTagState.manualTags = [];
        booruTagState.items = [];
        booruTagState.sources = [];
        booruTagState.rating = null;
        if (ratingSelect) ratingSelect.value = "";
        renderBooruTagsGrouped();
        return;
    }
    const token = ++booruTagState.loadToken;
    try {
        const params = new URLSearchParams({
            media: booruTagState.media,
            path: booruTagState.path,
        });
        const res = await fetch(`/api/booru/item-tags?${params.toString()}`);
        const data = await res.json().catch(() => ({}));
        if (token !== booruTagState.loadToken) return;
        if (!res.ok) {
            throw new Error(data?.error || "불러오기 실패");
        }
        if (Array.isArray(data.manual_tags)) {
            booruTagState.manualTags = data.manual_tags;
        } else {
            booruTagState.manualTags = Array.isArray(data.tags) ? data.tags : [];
        }
        // Rating is handled by the dropdown. Don't treat rating markers as manual tags.
        booruTagState.manualTags = (booruTagState.manualTags || []).filter(t => !isRatingBooruTag(t));
        booruTagState.items = Array.isArray(data.items)
            ? data.items
            : booruTagState.manualTags.map(tag => ({
                tag,
                category: "general",
                post_count: 0,
                source: BOORU_MANUAL_SOURCE,
                editable: true,
            }));
        booruTagState.sources = Array.isArray(data.sources)
            ? data.sources
            : [BOORU_MANUAL_SOURCE];
        booruTagState.rating = data.rating || null;
        if (ratingSelect) {
            ratingSelect.value = booruTagState.rating?.value ?? "";
        }
        renderBooruTagsGrouped();
    } catch (err) {
        console.error("booru tag load error", err);
        booruTagState.manualTags = [];
        booruTagState.items = [];
        booruTagState.sources = [];
        booruTagState.rating = null;
        if (ratingSelect) ratingSelect.value = "";
        renderBooruTagsGrouped();
        showToast(err?.message || "불러오기 실패", "error");
    }
}

async function saveBooruRating(value) {
    if (!booruTagState.path) return;
    const payload = {
        media: booruTagState.media || "image",
        path: booruTagState.path,
        rating: value === "" ? null : value,
    };
    try {
        const res = await fetch("/api/booru/item-rating", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.ok === false) {
            throw new Error(data?.error || "저장 실패");
        }
        booruTagState.rating = data.rating || null;
        showToast("저장됨", "success");
    } catch (err) {
        console.error("booru rating save error", err);
        showToast(err?.message || "저장 실패", "error");
    }
}

function initBooruTagUI() {
    if (booruTagState.bound) return;
    const { input, addBtn, autoTagBtn, suggestions, inputWrap, ratingSelect } = getBooruTagElements();
    if (!input || !suggestions) return;
    booruTagState.bound = true;

    input.addEventListener("input", () => {
        scheduleBooruSuggestions(input.value);
    });
    input.addEventListener("keydown", event => {
        const key = event.key;
        const hasSuggestions = Array.isArray(booruTagState.suggestItems)
            && booruTagState.suggestItems.length > 0
            && suggestions.style.display !== "none";

        if (key === "ArrowDown" && hasSuggestions) {
            event.preventDefault();
            const max = booruTagState.suggestItems.length;
            const next = (booruTagState.suggestIndex + 1) % max;
            setActiveBooruSuggestion(next);
            return;
        }

        if (key === "ArrowUp" && hasSuggestions) {
            event.preventDefault();
            const max = booruTagState.suggestItems.length;
            const cur = booruTagState.suggestIndex;
            const next = (cur <= 0 ? (max - 1) : (cur - 1));
            setActiveBooruSuggestion(next);
            return;
        }

        if (key === "Enter") {
            event.preventDefault();
            if (hasSuggestions && booruTagState.suggestIndex >= 0) {
                const picked = booruTagState.suggestItems[booruTagState.suggestIndex];
                if (picked && picked.tag) {
                    addBooruTag(picked.tag);
                    return;
                }
            }
            addBooruTag(input.value);
            return;
        }

        if (key === "Escape") {
            clearBooruSuggestions();
            return;
        }
    });
    addBtn?.addEventListener("click", () => {
        addBooruTag(input.value);
    });

    autoTagBtn?.addEventListener("click", () => {
        runBooruAutoTag();
    });

    document.addEventListener("click", event => {
        const wrap = inputWrap || input.parentElement;
        if (wrap && wrap.contains(event.target)) return;
        if (booruTagState.popoverEl && booruTagState.popoverEl.contains(event.target)) return;
        clearBooruSuggestions();
        closeBooruChipPopover();
    });

    ratingSelect?.addEventListener("change", () => {
        const raw = ratingSelect.value;
        if (raw === "") {
            saveBooruRating(null);
            return;
        }
        const parsed = Number(raw);
        if (Number.isNaN(parsed)) {
            saveBooruRating(null);
            return;
        }
        saveBooruRating(parsed);
    });

    ratingSelect?.addEventListener("keydown", (event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
        }
    });
}

function setPairedMediaButtonState({ label, disabled = false, visible = false } = {}) {
    const btn = pairedMediaState.button || document.getElementById("paired-media-toggle");
    if (!btn) return;
    pairedMediaState.button = btn;
    if (!visible) {
        btn.style.display = "none";
        btn.disabled = true;
        return;
    }
    btn.style.display = "inline-flex";
    btn.disabled = disabled;
    if (label) {
        btn.textContent = label;
    }
}

async function loadPairedMediaForCurrentItem() {
    const path = currentImagePath || "";
    const media = currentMediaType || "image";
    if (!path) {
        pairedMediaState.item = null;
        pairedMediaState.type = null;
        setPairedMediaButtonState({ visible: false });
        return;
    }
    const requestId = ++pairedMediaState.requestId;
    setPairedMediaButtonState({ label: "페어링 찾는 중...", disabled: true, visible: true });
    try {
        const params = new URLSearchParams({ path, media });
        const res = await fetch(`/api/paired_media?${params.toString()}`);
        const data = await res.json().catch(() => ({}));
        if (requestId !== pairedMediaState.requestId) return;
        if (!res.ok) {
            throw new Error(data?.error || "페어링 조회 실패");
        }
        if (!data || !data.pair) {
            pairedMediaState.item = null;
            pairedMediaState.type = null;
            setPairedMediaButtonState({ visible: false });
            return;
        }
        pairedMediaState.item = data.pair;
        pairedMediaState.type = data.pair_type || data.pair.media || null;
        const label = pairedMediaState.type === "video"
            ? "🎞 페어링 영상 보기"
            : "🖼 페어링 이미지 보기";
        setPairedMediaButtonState({ label, disabled: false, visible: true });
    } catch (err) {
        console.error("paired media load error", err);
        pairedMediaState.item = null;
        pairedMediaState.type = null;
        setPairedMediaButtonState({ visible: false });
    }
}

function showPairedMedia() {
    const item = pairedMediaState.item;
    if (!item) return;
    currentImageIndex = -1;
    showModal(item, { preserveExpansion: true });
}

function setRelatedPanelOpen(open) {
    relatedContentState.open = open;
    const modal = document.getElementById("modal");
    if (modal) {
        modal.classList.toggle("related-open", open);
    }
    if (relatedContentState.panel) {
        relatedContentState.panel.setAttribute("aria-hidden", open ? "false" : "true");
    }
    if (relatedContentState.scrim) {
        relatedContentState.scrim.setAttribute("aria-hidden", open ? "false" : "true");
    }
    if (relatedContentState.button) {
        relatedContentState.button.classList.toggle("active", open);
        relatedContentState.button.setAttribute("aria-pressed", open ? "true" : "false");
    }
}

function renderRelatedPanel(items, metaText) {
    if (relatedContentState.metaEl) {
        relatedContentState.metaEl.textContent = metaText || "";
    }
    if (!relatedContentState.listEl) return;
    relatedContentState.listEl.innerHTML = "";
    if (!items || !items.length) {
        const empty = document.createElement("div");
        empty.className = "modal-related-empty";
        empty.textContent = "연관 콘텐츠가 없습니다.";
        relatedContentState.listEl.appendChild(empty);
        return;
    }
    items.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "modal-related-item";
        const thumb = document.createElement("img");
        thumb.className = "modal-related-thumb";
        const imgPath = item.img || item.file || "";
        thumb.src = "/thumb?path=" + encodeURIComponent(imgPath);
        thumb.alt = "";
        const label = document.createElement("div");
        label.className = "modal-related-label";
        const mediaLabel = document.createElement("span");
        if (item._paired) {
            mediaLabel.textContent = "🧷 페어링";
        } else {
            mediaLabel.textContent = item.media === "video" ? "🎞 영상" : "🖼 이미지";
        }
        const distance = item._distance;
        const distanceLabel = document.createElement("span");
        distanceLabel.textContent = distance === undefined ? "" : `d${distance}`;
        label.appendChild(mediaLabel);
        if (distanceLabel.textContent) {
            label.appendChild(distanceLabel);
        }
        button.appendChild(thumb);
        button.appendChild(label);
        button.addEventListener("click", () => {
            currentImageIndex = -1;
            showModal(item, { preserveExpansion: true });
        });
        relatedContentState.listEl.appendChild(button);
    });
}

async function fetchRelatedForCurrentItem(force = false) {
    const path = currentImagePath || "";
    if (!path) {
        relatedContentState.items = [];
        renderRelatedPanel([], "");
        return;
    }
    if (!relatedContentState.includeImages && !relatedContentState.includeVideos && !relatedContentState.includeVideoPairs) {
        relatedContentState.items = [];
        renderRelatedPanel([], "필터가 모두 꺼져 있습니다.");
        return;
    }
    if (!force && relatedContentState.lastPath === path && relatedContentState.items.length) {
        return;
    }
    const requestId = ++relatedContentState.requestId;
    renderRelatedPanel([], "연관 콘텐츠 불러오는 중...");
    try {
        const params = new URLSearchParams({
            path,
            limit: String(relatedContentState.limit),
            distance: String(relatedContentState.distance),
            include_images: relatedContentState.includeImages ? "1" : "0",
            include_videos: relatedContentState.includeVideos ? "1" : "0",
            include_video_pairs: relatedContentState.includeVideoPairs ? "1" : "0",
        });
        const res = await fetch(`/api/related?${params.toString()}`);
        const data = await res.json().catch(() => ({}));
        if (requestId !== relatedContentState.requestId) return;
        if (!res.ok) {
            throw new Error(data?.error || "연관 콘텐츠 조회 실패");
        }
        let items = Array.isArray(data?.items) ? data.items : [];
        if (!relatedContentState.includeVideoPairs) {
            items = items.filter((item) => !item?._paired);
        }
        relatedContentState.items = items;
        relatedContentState.lastPath = path;
        if (data?.reason === "phash_missing") {
            renderRelatedPanel([], "pHash가 없는 항목입니다.");
            return;
        }
        if (data?.reason === "filters_off") {
            renderRelatedPanel([], "필터가 모두 꺼져 있습니다.");
            return;
        }
        const metaParts = [`총 ${items.length}건`];
        const distance = Number.isFinite(data?.distance) ? data.distance : relatedContentState.distance;
        if (distance > 0) metaParts.push(`거리 ≤ ${distance}`);
        const filterLabels = [];
        if (relatedContentState.includeImages) filterLabels.push("이미지");
        if (relatedContentState.includeVideos) filterLabels.push("영상");
        if (relatedContentState.includeVideoPairs) filterLabels.push("페어링 이미지");
        if (filterLabels.length) metaParts.push(filterLabels.join(", "));
        renderRelatedPanel(items, metaParts.join(" · "));
    } catch (err) {
        console.error("related content load error", err);
        renderRelatedPanel([], "연관 콘텐츠를 불러오지 못했습니다.");
    }
}

function toggleRelatedPanel() {
    const nextOpen = !relatedContentState.open;
    setRelatedPanelOpen(nextOpen);
    if (nextOpen) {
        fetchRelatedForCurrentItem(true);
    }
}

function closeRelatedPanel() {
    if (!relatedContentState.open) return;
    setRelatedPanelOpen(false);
}

function showModal(item, options = {}) {
    const { preserveExpansion = false } = options;
    currentImagePath = item.file;
    const indicatorPath = getIndicatorPath(item);
    const isGif = item.media === "video" && isGifFile(indicatorPath);
    const isVideo = item.media === "video" && !isGif;
    currentExifPath = isGif
        ? (item.file || item.img || "")
        : isVideo
            ? (item.rel_thumb || item.thumb_rel || item.img || "")
            : (item.file || item.img || "");
    currentMediaType = item.media;
    const imgEl = document.getElementById("modal-image");
    const vidEl = document.getElementById("modal-video");
    const imgControls = document.getElementById("image-controls");
    const expandToggle = document.getElementById("modal-expand-toggle");
    const showExifButton = document.getElementById("show-exif");
    const copyExifButton = document.getElementById("copy-exif");
    const downloadNoExifButton = document.getElementById("download-no-exif");
    const downloadScaleSelect = document.getElementById("modal-download-scale");
    const pairedBtn = document.getElementById("paired-media-toggle");
    const imageOnlyActions = imgControls
        ? Array.from(imgControls.querySelectorAll(".image-only-action"))
            .filter((action) => !action.classList.contains("modal-delete-action"))
        : [];

    if (pairedBtn) {
        pairedMediaState.button = pairedBtn;
        if (pairedBtn.dataset.bound !== "true") {
            pairedBtn.addEventListener("click", showPairedMedia);
            pairedBtn.dataset.bound = "true";
        }
        pairedBtn.style.display = "none";
        pairedBtn.disabled = true;
    }

    const setActionDisabled = (element, disabled, message) => {
        if (!element) return;
        const supportsDisabled = "disabled" in element;
        if (supportsDisabled) {
            element.disabled = disabled;
        }
        element.setAttribute("aria-disabled", disabled ? "true" : "false");
        if (disabled) {
            if (element.dataset.originalTitle === undefined) {
                element.dataset.originalTitle = element.title || "";
            }
            element.title = message;
            if (element.dataset.originalAriaLabel === undefined) {
                element.dataset.originalAriaLabel = element.getAttribute("aria-label") || "";
            }
            element.setAttribute("aria-label", message);
        } else if (element.dataset.originalTitle !== undefined) {
            element.title = element.dataset.originalTitle;
            delete element.dataset.originalTitle;
            if (element.dataset.originalAriaLabel !== undefined) {
                const original = element.dataset.originalAriaLabel;
                if (original) {
                    element.setAttribute("aria-label", original);
                } else {
                    element.removeAttribute("aria-label");
                }
                delete element.dataset.originalAriaLabel;
            }
        }
    };

    const shouldCollapseExpansion = !preserveExpansion || isVideo;
    setModalExpanded(shouldCollapseExpansion ? false : isModalExpanded);
    if (expandToggle) {
        const isImage = !isVideo;
        expandToggle.disabled = !isImage;
        expandToggle.title = isImage
            ? "정보를 숨기고 이미지를 크게 보여줍니다"
            : "이미지에서만 사용할 수 있습니다";
    }

    if (isVideo) {
        imgEl.style.display = "none";
        setVideoErrorMessage("");
        attachVideoErrorListeners(vidEl);
        vidEl.src = "/file?path=" + encodeURIComponent(item.file);
        vidEl.style.display = "block";
        vidEl.load();
        vidEl.play().catch(()=>{});
        if (imgControls) {
            imgControls.style.display = "flex";
        }
        imageOnlyActions.forEach((action) => {
            setActionDisabled(action, true, "영상에서는 사용할 수 없습니다");
        });
    } else {
        imgEl.src = isGif ? "/file?path=" + encodeURIComponent(item.file) : "/img?path=" + item.file;
        imgEl.style.display = "block";
        vidEl.pause();
        vidEl.removeAttribute("src");
        vidEl.style.display = "none";
        setVideoErrorMessage("");
        if (imgControls) {
            imgControls.style.display = "flex";
        }
        imageOnlyActions.forEach((action) => {
            setActionDisabled(action, false);
        });
    }

    const exifTarget = currentMediaType === "video" ? currentExifPath : (currentExifPath || currentImagePath);
    const hasExifTarget = Boolean(exifTarget);
    const downloadTarget = isVideo ? currentImagePath : (currentExifPath || currentImagePath);
    const hasDownloadTarget = Boolean(downloadTarget);
    const exifUnavailableMessage = isVideo
        ? "영상은 썸네일 PNG가 있을 때만 EXIF 정보를 볼 수 있습니다"
        : "EXIF 정보를 불러올 수 없습니다";
    const downloadUnavailableMessage = isVideo
        ? "영상 파일을 불러올 수 없습니다"
        : "EXIF를 제거하고 다운로드할 수 없습니다";
    const exifDownloadMessage = isVideo
        ? "영상은 썸네일 PNG 기준으로 EXIF 제거 다운로드됩니다"
        : "EXIF를 제거하고 다운로드합니다";

    if (showExifButton) {
        setActionDisabled(showExifButton, !hasExifTarget, exifUnavailableMessage);
        if (hasExifTarget && isVideo) {
            showExifButton.title = "영상 썸네일 PNG의 EXIF 정보를 확인합니다";
        }
    }
    if (copyExifButton) {
        setActionDisabled(copyExifButton, !hasExifTarget, exifUnavailableMessage);
        if (hasExifTarget && isVideo) {
            copyExifButton.title = "영상 썸네일 PNG의 EXIF 정보를 복사합니다";
        }
    }
    if (downloadNoExifButton) {
        if (downloadNoExifButton.dataset.defaultLabel === undefined) {
            downloadNoExifButton.dataset.defaultLabel = downloadNoExifButton.textContent || "";
        }
        if (downloadNoExifButton.dataset.defaultTitle === undefined) {
            downloadNoExifButton.dataset.defaultTitle = downloadNoExifButton.title || "";
        }
        const videoLabel = "⬇ 동영상(메타데이터 제거) 다운로드";
        const defaultLabel = downloadNoExifButton.dataset.defaultLabel;
        const defaultTitle = downloadNoExifButton.dataset.defaultTitle;

        downloadNoExifButton.textContent = isVideo ? videoLabel : defaultLabel;
        downloadNoExifButton.title = isVideo ? videoLabel : defaultTitle;
        downloadNoExifButton.setAttribute("aria-label", isVideo ? videoLabel : defaultTitle);

        setActionDisabled(downloadNoExifButton, !hasDownloadTarget, downloadUnavailableMessage);
        if (hasDownloadTarget && isVideo) {
            downloadNoExifButton.title = videoLabel;
            downloadNoExifButton.setAttribute("aria-label", videoLabel);
        }
    }
    if (downloadScaleSelect) {
        setActionDisabled(downloadScaleSelect, !hasDownloadTarget, downloadUnavailableMessage);
        if (hasDownloadTarget && isVideo) {
            downloadScaleSelect.title = "영상은 썸네일 PNG 기준으로 배율이 적용됩니다";
        }
    }
    const detailPath = getDetailPath(item);
    const cachedDetail = detailPath ? detailCache.get(detailPath) : null;
    if (cachedDetail) {
        const merged = { ...item, ...cachedDetail, compact: false };
        renderModalMetadata(merged);
        if (currentImageIndex >= 0) {
            results[currentImageIndex] = merged;
        }
    } else {
        renderModalMetadata(item);
        if (shouldFetchDetail(item)) {
            fetchDetailForItem(item);
        }
    }
    loadBooruTagsForCurrentItem();
    loadPairedMediaForCurrentItem();
    if (relatedContentState.open) {
        fetchRelatedForCurrentItem(true);
    }
    document.getElementById("modal").style.display = "block";
}

function findNavigableIndex(step, options = {}) {
    const { skipVideos = false } = options;
    if (!results.length) return null;

    let idx = currentImageIndex + step;
    while (idx >= 0 && idx < results.length) {
        const candidate = results[idx];
        if (!skipVideos || candidate?.media !== "video") {
            return idx;
        }
        idx += step;
    }
    return null;
}

function setModalExpanded(expanded) {
    isModalExpanded = expanded;
    const modal = document.getElementById("modal");
    const toggleBtn = document.getElementById("modal-expand-toggle");
    if (modal) {
        modal.classList.toggle("expanded", expanded);
    }
    if (expanded) {
        closeRelatedPanel();
    }
    if (toggleBtn) {
        toggleBtn.textContent = expanded ? "ℹ️ 정보 보기" : "🖼 크게 보기";
        toggleBtn.setAttribute("aria-pressed", expanded ? "true" : "false");
        toggleBtn.title = expanded
            ? "메타데이터를 다시 표시합니다"
            : "정보를 숨기고 이미지를 크게 보여줍니다";
    }
}

function toggleModalExpanded() {
    setModalExpanded(!isModalExpanded);
}

function hideModal() {
    const vidEl = document.getElementById("modal-video");
    vidEl.pause();
    vidEl.removeAttribute("src");
    vidEl.load();
    setModalExpanded(false);
    closeRelatedPanel();
    clearBooruSuggestions();
    closeBooruChipPopover();
    document.getElementById("modal").style.display = "none";
}

function hideSettingsModal() {
    document.getElementById("settings-modal").style.display = "none";
    document.body.style.overflow = "";
}

window.addEventListener("click", function (event) {
    const modal = document.getElementById("settings-modal");
    if (event.target === modal) {
        hideSettingsModal();
    }
});

function showPrevImage() {
    const targetIndex = findNavigableIndex(-1, { skipVideos: isModalExpanded });
    if (targetIndex !== null) {
        showModalFromIndex(targetIndex, { preserveExpansion: true });
    }
}
function showNextImage() {
    const targetIndex = findNavigableIndex(1, { skipVideos: isModalExpanded });
    if (targetIndex !== null) {
        showModalFromIndex(targetIndex, { preserveExpansion: true });
    }
}

function activateSettingsTab(targetId) {
    const buttons = document.querySelectorAll(".settings-tab-button");
    const panels = document.querySelectorAll(".settings-tab-panel");
    buttons.forEach(btn => {
        const isActive = btn.dataset.tabTarget === targetId;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    panels.forEach(panel => {
        panel.classList.toggle("active", panel.id === targetId);
    });
    if (targetId === "settings-server" || targetId === "settings-engine" || targetId === "settings-tags") {
        loadEnvBasic();
    }
    if (targetId === "settings-advanced") {
        loadEnvRaw();
    }
}

function initSettingsTabs() {
    const buttons = document.querySelectorAll(".settings-tab-button");
    if (!buttons.length) return;
    buttons.forEach(btn => {
        btn.addEventListener("click", () => {
            activateSettingsTab(btn.dataset.tabTarget);
        });
    });
}

const envSettingsState = {
    schema: null,
    values: {},
    loadingBasic: false,
    loadingAdvanced: false,
    basicLoaded: false,
    advancedLoaded: false,
};

function setEnvStatus(targetId, message = "", type = "info") {
    const statusEl = document.getElementById(targetId);
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.dataset.type = type;
}

function normalizeEnvPicker(field) {
    if (!field || !field.picker) return null;
    if (typeof field.picker === "string") {
        return { kind: field.picker };
    }
    if (typeof field.picker === "object") {
        return {
            kind: field.picker.kind || field.picker.type || "file",
            title: field.picker.title,
        };
    }
    return null;
}

async function requestEnvPathPicker(picker, initialValue = "") {
    const payload = {
        kind: picker?.kind || "file",
        title: picker?.title,
        initial: initialValue || "",
    };
    const res = await fetch("/api/settings/env/pick_path", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
        throw new Error(data.error || "Path picker failed");
    }
    return data.path || "";
}


function renderEnvBasic(schema, values = {}, options = {}) {
    const {
        containerId = "env-basic-groups",
        filterGroup = null,
        emptyText = "표시할 환경설정 항목이 없습니다.",
    } = options;
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = "";

    const groups = Array.isArray(schema?.groups) ? schema.groups : [];
    const visibleGroups = filterGroup ? groups.filter(filterGroup) : groups;
    if (!visibleGroups.length) {
        const empty = document.createElement("div");
        empty.className = "env-empty";
        empty.textContent = emptyText;
        container.appendChild(empty);
        return;
    }

    visibleGroups.forEach(group => {
        const fields = Array.isArray(group.fields) ? group.fields : [];
        if (!fields.length) return;

        const groupEl = document.createElement("div");
        groupEl.className = "env-group";

        const header = document.createElement("div");
        header.className = "env-group-header";
        const title = document.createElement("h4");
        title.textContent = group.label || group.id;
        const desc = document.createElement("p");
        desc.className = "env-group-desc";
        desc.textContent = group.description || "";
        header.appendChild(title);
        if (group.description) header.appendChild(desc);
        groupEl.appendChild(header);

        const list = document.createElement("div");
        list.className = "env-field-list";

        fields.forEach(field => {
            const card = document.createElement("div");
            card.className = "env-field-card";

            const fieldHeader = document.createElement("div");
            fieldHeader.className = "env-field-header";

            const titleWrap = document.createElement("div");
            const fieldTitle = document.createElement("div");
            fieldTitle.className = "env-field-title";
            const titleText = String(field.label || field.key || "").trim();
            const keyText = String(field.key || "").trim();
            fieldTitle.textContent = titleText;
            titleWrap.appendChild(fieldTitle);
            if (keyText && keyText !== titleText) {
                const fieldKey = document.createElement("div");
                fieldKey.className = "env-field-key";
                fieldKey.textContent = keyText;
                titleWrap.appendChild(fieldKey);
            }

            const badgeWrap = document.createElement("div");
            badgeWrap.className = "env-field-badges";
            if (field.restart_required) {
                const badge = document.createElement("span");
                badge.className = "env-field-badge restart";
                badge.textContent = "재시작 필요";
                badgeWrap.appendChild(badge);
            }
            if (field.danger) {
                const badge = document.createElement("span");
                badge.className = "env-field-badge danger";
                badge.textContent = "주의";
                badgeWrap.appendChild(badge);
            }

            fieldHeader.appendChild(titleWrap);
            fieldHeader.appendChild(badgeWrap);

            const fieldDesc = document.createElement("div");
            fieldDesc.className = "env-field-desc";
            fieldDesc.textContent = field.description || "";

            const control = document.createElement("div");
            control.className = "env-field-control";
            const fieldType = field.type || "string";
            if (fieldType === "bool") {
                const input = document.createElement("input");
                input.type = "checkbox";
                input.dataset.envKey = field.key;
                input.checked = Boolean(values[field.key]);
                const label = document.createElement("span");
                label.textContent = "활성화";
                control.appendChild(input);
                control.appendChild(label);
            } else if (fieldType === "float") {
                const input = document.createElement("input");
                input.type = "number";
                input.step = "0.01";
                input.dataset.envKey = field.key;
                input.value = values[field.key] ?? "";
                control.appendChild(input);
            } else if (fieldType === "select") {
                const select = document.createElement("select");
                select.dataset.envKey = field.key;
                const options = Array.isArray(field.options) ? field.options : [];
                options.forEach(opt => {
                    const option = document.createElement("option");
                    option.value = opt.value;
                    option.textContent = opt.label || opt.value;
                    select.appendChild(option);
                });
                if (values[field.key] !== undefined && values[field.key] !== null) {
                    select.value = String(values[field.key]);
                }
                control.appendChild(select);
            } else {
                const input = document.createElement("input");
                input.type = fieldType === "int" ? "number" : "text";
                input.dataset.envKey = field.key;
                input.value = values[field.key] ?? "";
                control.appendChild(input);

                const picker = fieldType === "string" ? normalizeEnvPicker(field) : null;
                if (picker && input.type === "text") {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "env-browse-button";
                    button.textContent = "Browse";
                    button.addEventListener("click", async () => {
                        const previous = button.textContent;
                        button.disabled = true;
                        button.textContent = "Opening...";
                        try {
                            const picked = await requestEnvPathPicker(picker, input.value);
                            if (picked) input.value = picked;
                        } catch (err) {
                            showToast(err.message || "Path picker failed", "error");
                        } finally {
                            button.disabled = false;
                            button.textContent = previous;
                        }
                    });
                    control.appendChild(button);
                }
            }

            card.appendChild(fieldHeader);
            if (field.description) card.appendChild(fieldDesc);
            card.appendChild(control);
            list.appendChild(card);
        });

        groupEl.appendChild(list);
        container.appendChild(groupEl);
    });

}

function renderEnvDiffSummary(summary) {
    const container = document.getElementById("env-diff-summary");
    if (!container) return;

    const added = summary?.added_keys || [];
    const changed = summary?.changed_keys || [];
    const removed = summary?.removed_keys || [];

    if (!added.length && !changed.length && !removed.length) {
        container.hidden = true;
        container.innerHTML = "";
        return;
    }

    container.hidden = false;
    container.innerHTML = "";

    const sections = [
        { title: "추가", keys: added, className: "added" },
        { title: "변경", keys: changed, className: "changed" },
        { title: "삭제", keys: removed, className: "removed" },
    ];

    sections.forEach(section => {
        if (!section.keys.length) return;
        const block = document.createElement("div");
        block.className = "env-diff-block";

        const badge = document.createElement("span");
        badge.className = `env-diff-badge ${section.className}`;
        badge.textContent = `${section.title} ${section.keys.length}`;

        const list = document.createElement("div");
        list.className = "env-diff-keys";
        list.textContent = section.keys.join(", ");

        block.appendChild(badge);
        block.appendChild(list);
        container.appendChild(block);
    });
}

async function loadEnvSchema() {
    if (envSettingsState.schema) return envSettingsState.schema;
    const res = await fetch("/api/settings/env/schema", { headers: { Accept: "application/json" } });
    if (!res.ok) {
        throw new Error("환경설정 스키마를 불러오지 못했습니다.");
    }
    const data = await res.json();
    envSettingsState.schema = data;
    return data;
}

async function loadEnvBasic({ force = false } = {}) {
    if (envSettingsState.loadingBasic) return;
    if (envSettingsState.basicLoaded && !force) return;
    envSettingsState.loadingBasic = true;
    setEnvStatus("env-server-status", "불러오는 중...");
    setEnvStatus("env-engine-status", "불러오는 중...");
    setEnvStatus("env-tags-status", "불러오는 중...");
    try {
        const schema = await loadEnvSchema();
        renderEnvBasic(schema, envSettingsState.values, {
            containerId: "env-server-groups",
            filterGroup: (group) => group.id !== "engine" && group.id !== "tags",
        });
        renderEnvBasic(schema, envSettingsState.values, {
            containerId: "env-engine-groups",
            filterGroup: (group) => group.id === "engine",
            emptyText: "표시할 엔진 설정 항목이 없습니다.",
        });
        renderEnvBasic(schema, envSettingsState.values, {
            containerId: "env-tags-groups",
            filterGroup: (group) => group.id === "tags",
            emptyText: "표시할 태그 설정 항목이 없습니다.",
        });
        const res = await fetch("/api/settings/env", { headers: { Accept: "application/json" } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            throw new Error(data.error || "환경설정 값을 불러오지 못했습니다.");
        }
        envSettingsState.values = data.values || {};
        renderEnvBasic(schema, envSettingsState.values, {
            containerId: "env-server-groups",
            filterGroup: (group) => group.id !== "engine" && group.id !== "tags",
        });
        renderEnvBasic(schema, envSettingsState.values, {
            containerId: "env-engine-groups",
            filterGroup: (group) => group.id === "engine",
            emptyText: "표시할 엔진 설정 항목이 없습니다.",
        });
        renderEnvBasic(schema, envSettingsState.values, {
            containerId: "env-tags-groups",
            filterGroup: (group) => group.id === "tags",
            emptyText: "표시할 태그 설정 항목이 없습니다.",
        });
        envSettingsState.basicLoaded = true;
        setEnvStatus("env-server-status", "로드 완료");
        setEnvStatus("env-engine-status", "로드 완료");
        setEnvStatus("env-tags-status", "로드 완료");
    } catch (err) {
        showToast(err.message || "환경설정 로드 실패", "error");
        setEnvStatus("env-server-status", "로드 실패", "error");
        setEnvStatus("env-engine-status", "로드 실패", "error");
        setEnvStatus("env-tags-status", "로드 실패", "error");
    } finally {
        envSettingsState.loadingBasic = false;
    }
}

async function loadEnvRaw({ force = false } = {}) {
    if (envSettingsState.loadingAdvanced) return;
    if (envSettingsState.advancedLoaded && !force) return;
    envSettingsState.loadingAdvanced = true;
    setEnvStatus("env-raw-status", "불러오는 중...");
    try {
        const res = await fetch("/api/settings/env/raw", { headers: { Accept: "application/json" } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            throw new Error(data.error || "환경설정 텍스트를 불러오지 못했습니다.");
        }
        const textarea = document.getElementById("env-raw-text");
        if (textarea) textarea.value = data.text || "";
        renderEnvDiffSummary(null);
        envSettingsState.advancedLoaded = true;
        setEnvStatus("env-raw-status", "로드 완료");
    } catch (err) {
        showToast(err.message || "환경설정 텍스트 로드 실패", "error");
        setEnvStatus("env-raw-status", "로드 실패", "error");
    } finally {
        envSettingsState.loadingAdvanced = false;
    }
}

async function saveEnvBasicSection({ containerId, statusId, restartBannerId }) {
    const container = document.getElementById(containerId);
    const inputs = container ? container.querySelectorAll("[data-env-key]") : [];
    if (!inputs.length) return;
    const payload = {};
    inputs.forEach(input => {
        const key = input.dataset.envKey;
        if (!key) return;
        if (input.type === "checkbox") {
            payload[key] = input.checked;
        } else {
            payload[key] = input.value;
        }
    });

    const saveBtn = container ? container.closest(".settings-section")?.querySelector("button.env-save-button") : null;
    if (saveBtn) saveBtn.disabled = true;
    setEnvStatus(statusId, "저장 중...");
    try {
        const res = await fetch("/api/settings/env", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ updates: payload }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            throw new Error(data.error || "환경설정 저장 실패");
        }
        envSettingsState.values = data.values || {};
        envSettingsState.basicLoaded = true;
        renderEnvBasic(envSettingsState.schema, envSettingsState.values, {
            containerId: "env-server-groups",
            filterGroup: (group) => group.id !== "engine",
        });
        renderEnvBasic(envSettingsState.schema, envSettingsState.values, {
            containerId: "env-engine-groups",
            filterGroup: (group) => group.id === "engine",
            emptyText: "표시할 엔진 설정 항목이 없습니다.",
        });
        const restartBanner = document.getElementById(restartBannerId);
        if (data.restart_required) {
            if (restartBanner) restartBanner.hidden = false;
            showToast("⚠️ 변경 사항 적용을 위해 재시작이 필요합니다.", "warning");
        } else {
            if (restartBanner) restartBanner.hidden = true;
            showToast("✅ 환경설정이 저장되었습니다.", "success");
        }
        setEnvStatus(statusId, "저장 완료");
    } catch (err) {
        showToast(err.message || "환경설정 저장 실패", "error");
        setEnvStatus(statusId, "저장 실패", "error");
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

async function validateEnvRaw() {
    const textarea = document.getElementById("env-raw-text");
    const text = textarea ? textarea.value : "";
    setEnvStatus("env-raw-status", "검증 중...");
    try {
        const res = await fetch("/api/settings/env/raw?dry_run=1", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ text }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            throw new Error(data.error || "검증 실패");
        }
        renderEnvDiffSummary(data);
        setEnvStatus("env-raw-status", "검증 완료");
        showToast("✅ 문법 검증 완료", "success");
    } catch (err) {
        renderEnvDiffSummary(null);
        setEnvStatus("env-raw-status", "검증 실패", "error");
        showToast(err.message || "검증 실패", "error");
    }
}

async function saveEnvRaw() {
    const textarea = document.getElementById("env-raw-text");
    const text = textarea ? textarea.value : "";
    setEnvStatus("env-raw-status", "저장 중...");
    try {
        const res = await fetch("/api/settings/env/raw", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ text }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            throw new Error(data.error || "저장 실패");
        }
        renderEnvDiffSummary(data);
        setEnvStatus("env-raw-status", "저장 완료");
        showToast("✅ 환경설정이 저장되었습니다. 재시작이 필요합니다.", "warning");
    } catch (err) {
        renderEnvDiffSummary(null);
        setEnvStatus("env-raw-status", "저장 실패", "error");
        showToast(err.message || "저장 실패", "error");
    }
}

function initEnvModeTabs() {
    // Deprecated: settings tabs now control env sections.
}

function getIncludeVideosValue() {
    const toggle = document.getElementById("data-include-videos");
    return toggle ? toggle.checked : true;
}

function getImageScanForceRescanValue() {
    const toggle = document.getElementById("data-force-rescan");
    return toggle ? toggle.checked : false;
}

function getIntegrityDateOnlyValue() {
    const toggle = document.getElementById("integrity-date-only");
    return toggle ? toggle.checked : false;
}

function getIntegrityExcludeFailedValue() {
    const toggle = document.getElementById("integrity-exclude-failed");
    return toggle ? toggle.checked : false;
}

function getIntegrityIncludeQuarantineValue() {
    const toggle = document.getElementById("integrity-include-quarantine");
    return toggle ? toggle.checked : false;
}

function getThumbPrebuildFailureAction() {
    const select = document.getElementById("thumb-prebuild-failure-action");
    return select ? select.value : "none";
}

function getPhashForceValue() {
    const toggle = document.getElementById("phash-force-rebuild");
    return toggle ? toggle.checked : false;
}

function getPhashGroupDistanceValue() {
    const input = document.getElementById("phash-group-distance");
    if (!input) return 12;
    const value = Number.parseInt(input.value, 10);
    return Number.isFinite(value) && value >= 0 ? value : 12;
}

function getPhashGroupRebuildValue() {
    const toggle = document.getElementById("phash-group-rebuild");
    return toggle ? toggle.checked : true;
}

function getBooruAutoTagForceValue() {
    const toggle = document.getElementById("booru-auto-tag-force");
    return toggle ? toggle.checked : false;
}

function getIntegrityRootValue() {
    const input = document.getElementById("integrity-root-input");
    return input ? input.value.trim() : "";
}

function getIntegrityLimitValue() {
    const input = document.getElementById("integrity-limit");
    if (!input) return 0;
    const value = Number.parseInt(input.value, 10);
    return Number.isFinite(value) && value > 0 ? value : 0;
}

function getDbDedupeSampleLimitValue() {
    const input = document.getElementById("db-dedupe-sample-limit");
    if (!input) return 20;
    const value = Number.parseInt(input.value, 10);
    return Number.isFinite(value) && value >= 0 ? value : 20;
}

function getWalCheckpointModeValue() {
    const select = document.getElementById("wal-checkpoint-mode");
    return select ? select.value : "PASSIVE";
}

function initDataTaskUI() {
    dataTaskState.statusEl = document.getElementById("data-task-status");
    dataTaskState.detailEl = document.getElementById("data-task-detail");
    dataTaskState.logEl = document.getElementById("data-task-log");
    dataTaskState.progressBarEl = document.getElementById("data-task-progress-bar");
    dataTaskState.progressValueEl = document.getElementById("data-task-progress-value");
    dataTaskState.logTailBtn = document.getElementById("data-task-log-tail");
    dataTaskState.logCopyBtn = document.getElementById("data-task-log-copy");
    dataTaskState.cancelBtn = document.getElementById("data-task-cancel");
    dataTaskState.dbBackupBtn = document.getElementById("refresh-db-backup-btn");
    dataTaskState.imageScanBtn = document.getElementById("refresh-image-scan-btn");
    dataTaskState.failedRecoveryBtn = document.getElementById("refresh-failed-recovery-btn");
    dataTaskState.imageCleanupBtn = document.getElementById("refresh-image-cleanup-btn");
    dataTaskState.orphanCleanupBtn = document.getElementById("refresh-orphan-cleanup-btn");
    dataTaskState.videoIndexBtn = document.getElementById("refresh-video-index-btn");
    dataTaskState.videoCleanupBtn = document.getElementById("refresh-video-cleanup-btn");
    dataTaskState.thumbBtn = document.getElementById("thumb-prebuild-btn");
    dataTaskState.phashIndexBtn = document.getElementById("phash-index-btn");
    dataTaskState.phashForceToggle = document.getElementById("phash-force-rebuild");
    dataTaskState.phashGroupBuildBtn = document.getElementById("phash-group-build-btn");
    dataTaskState.phashGroupDistanceInput = document.getElementById("phash-group-distance");
    dataTaskState.phashGroupRebuildToggle = document.getElementById("phash-group-rebuild");
    dataTaskState.integrityBtn = document.getElementById("db-integrity-btn");
    dataTaskState.dbQuickCheckBtn = document.getElementById("db-quick-check-btn");
    dataTaskState.dbIntegrityCheckBtn = document.getElementById("db-integrity-check-btn");
    dataTaskState.dbFkCheckBtn = document.getElementById("db-fk-check-btn");
    dataTaskState.dbVacuumBtn = document.getElementById("db-vacuum-btn");
    dataTaskState.dbAnalyzeBtn = document.getElementById("db-analyze-btn");
    dataTaskState.dbOptimizeBtn = document.getElementById("db-optimize-btn");
    dataTaskState.dbWalCheckpointBtn = document.getElementById("db-wal-checkpoint-btn");
    dataTaskState.walCheckpointModeSelect = document.getElementById("wal-checkpoint-mode");
    dataTaskState.ftsRebuildBtn = document.getElementById("fts-rebuild-btn");
    dataTaskState.booruAutoTagBtn = document.getElementById("booru-auto-tag-btn");
    dataTaskState.booruDictUpdateBtn = document.getElementById("btn-booru-dict-update");
    dataTaskState.booruDictStatusEl = document.getElementById("booru-dict-status");
    dataTaskState.runtimeFfmpegInstallBtn = document.getElementById("btn-runtime-ffmpeg-install");
    dataTaskState.runtimeExiftoolInstallBtn = document.getElementById("btn-runtime-exiftool-install");
    dataTaskState.runtimeWd14InstallBtn = document.getElementById("btn-runtime-wd14-install");
    dataTaskState.runtimeWd14ModelSelect = document.getElementById("runtime-wd14-model");
    dataTaskState.runtimeAssetsStatusEl = document.getElementById("runtime-assets-status");
    dataTaskState.dbBackupRefreshBtn = document.getElementById("db-backup-refresh-btn");
    dataTaskState.dbBackupSelect = document.getElementById("db-backup-select");
    dataTaskState.dbRestoreBtn = document.getElementById("db-restore-btn");
    dataTaskState.dbRestoreConfirm = document.getElementById("db-restore-confirm");
    dataTaskState.dbDedupeConfirm = document.getElementById("db-dedupe-confirm");
    dataTaskState.dbDedupeCheckBtn = document.getElementById("db-dedupe-check-btn");
    dataTaskState.dbDedupeCleanBtn = document.getElementById("db-dedupe-clean-btn");
    dataTaskState.summaryReportEl = document.getElementById("data-task-summary-report");
    dataTaskState.summaryLabelEl = document.getElementById("data-task-summary-label");
    dataTaskState.summaryListEl = document.getElementById("data-task-summary-list");
    dataTaskState.integrityReportEl = document.getElementById("data-integrity-report");
    dataTaskState.integritySampleLimitEl = document.getElementById("integrity-sample-limit");
    dataTaskState.integrityReportDownloadEl = document.getElementById("integrity-report-download");
    dataTaskState.integritySampleNoMetaEl = document.getElementById("integrity-sample-no-meta");
    dataTaskState.integritySampleNoKSamplerEl = document.getElementById("integrity-sample-no-ksampler");
    dataTaskState.integritySampleMissingPositiveEl = document.getElementById("integrity-sample-missing-positive");
    dataTaskState.integritySampleReadFailedEl = document.getElementById("integrity-sample-read-failed");
    dataTaskState.dbDedupeReportEl = document.getElementById("data-dedupe-report");
    dataTaskState.dbDedupeSampleInfoEl = document.getElementById("db-dedupe-sample-info");
    dataTaskState.dbDedupeSampleListEl = document.getElementById("db-dedupe-sample-list");
}

function setupDataTaskUI() {
    initTaskStatusChips();
    initUnifiedTaskLogUI();
    initDataTaskUI();
    if (dataTaskUIState.bound) return;
    dataTaskUIState.bound = true;

    if (dataTaskState.logTailBtn) {
        updateLogTailButton(dataTaskState.logTailBtn, dataTaskUIState.logTailEnabled);
        dataTaskState.logTailBtn.addEventListener("click", () => {
            dataTaskUIState.logTailEnabled = !dataTaskUIState.logTailEnabled;
            updateLogTailButton(dataTaskState.logTailBtn, dataTaskUIState.logTailEnabled);
            scrollLogIfTail(dataTaskState.logEl, dataTaskUIState.logTailEnabled);
        });
    }
    if (dataTaskState.logCopyBtn) {
        dataTaskState.logCopyBtn.addEventListener("click", () => {
            copyTextToClipboard(dataTaskState.logEl?.textContent || "", {
                emptyMessage: "복사할 데이터 작업 로그가 없습니다.",
                successMessage: "✅ 데이터 작업 로그가 복사되었습니다.",
            });
        });
    }

    if (dataTaskState.dbBackupBtn) {
        dataTaskState.dbBackupBtn.addEventListener("click", () => runRefreshStep("db_backup", "DB 백업"));
    }
    if (dataTaskState.imageScanBtn) {
        dataTaskState.imageScanBtn.addEventListener("click", () => runRefreshStep("image_scan", "이미지 스캔"));
    }
    if (dataTaskState.failedRecoveryBtn) {
        dataTaskState.failedRecoveryBtn.addEventListener("click", () => runRefreshStep("failed_recovery", "failed 복구"));
    }
    if (dataTaskState.imageCleanupBtn) {
        dataTaskState.imageCleanupBtn.addEventListener("click", () => runRefreshStep("image_cleanup", "이미지 정리"));
    }
    if (dataTaskState.orphanCleanupBtn) {
        dataTaskState.orphanCleanupBtn.addEventListener("click", () => runRefreshStep("orphan_cleanup", "고아 데이터 정리"));
    }
    if (dataTaskState.videoIndexBtn) {
        dataTaskState.videoIndexBtn.addEventListener("click", () => runRefreshStep("video_index", "영상 인덱스"));
    }
    if (dataTaskState.videoCleanupBtn) {
        dataTaskState.videoCleanupBtn.addEventListener("click", () => runRefreshStep("video_cleanup", "영상 정리"));
    }
    if (dataTaskState.thumbBtn) dataTaskState.thumbBtn.addEventListener("click", runThumbnailPrebuild);
    if (dataTaskState.phashIndexBtn) dataTaskState.phashIndexBtn.addEventListener("click", runPhashIndex);
    if (dataTaskState.phashGroupBuildBtn) {
        dataTaskState.phashGroupBuildBtn.addEventListener("click", runPhashGroupBuild);
    }
    if (dataTaskState.booruAutoTagBtn) dataTaskState.booruAutoTagBtn.addEventListener("click", runBooruAutoTagTask);
    if (dataTaskState.integrityBtn) dataTaskState.integrityBtn.addEventListener("click", runDbIntegrityCheck);
    if (dataTaskState.dbQuickCheckBtn) dataTaskState.dbQuickCheckBtn.addEventListener("click", () => runDbCheck("quick"));
    if (dataTaskState.dbIntegrityCheckBtn) dataTaskState.dbIntegrityCheckBtn.addEventListener("click", () => runDbCheck("full"));
    if (dataTaskState.dbFkCheckBtn) dataTaskState.dbFkCheckBtn.addEventListener("click", runFkCheck);
    if (dataTaskState.dbVacuumBtn) dataTaskState.dbVacuumBtn.addEventListener("click", () => runDbMaintenance("vacuum"));
    if (dataTaskState.dbAnalyzeBtn) dataTaskState.dbAnalyzeBtn.addEventListener("click", () => runDbMaintenance("analyze"));
    if (dataTaskState.dbOptimizeBtn) dataTaskState.dbOptimizeBtn.addEventListener("click", () => runDbMaintenance("optimize"));
    if (dataTaskState.dbWalCheckpointBtn) dataTaskState.dbWalCheckpointBtn.addEventListener("click", () => runDbMaintenance("wal_checkpoint"));
    if (dataTaskState.ftsRebuildBtn) dataTaskState.ftsRebuildBtn.addEventListener("click", runFtsRebuild);
    if (dataTaskState.booruDictUpdateBtn) {
        dataTaskState.booruDictUpdateBtn.addEventListener("click", (event) => {
            runBooruDictUpdate({ force: Boolean(event.shiftKey) });
        });
    }
    if (dataTaskState.runtimeFfmpegInstallBtn) {
        dataTaskState.runtimeFfmpegInstallBtn.addEventListener("click", () => {
            runRuntimeAssetInstall("ffmpeg");
        });
    }
    if (dataTaskState.runtimeExiftoolInstallBtn) {
        dataTaskState.runtimeExiftoolInstallBtn.addEventListener("click", () => {
            runRuntimeAssetInstall("exiftool");
        });
    }
    if (dataTaskState.runtimeWd14InstallBtn) {
        dataTaskState.runtimeWd14InstallBtn.addEventListener("click", () => {
            runRuntimeAssetInstall("wd14", {
                modelKey: dataTaskState.runtimeWd14ModelSelect?.value || "",
            });
        });
    }
    if (dataTaskState.dbDedupeCheckBtn) {
        dataTaskState.dbDedupeCheckBtn.addEventListener("click", () => runDbDedupe("dry"));
    }
    if (dataTaskState.dbDedupeCleanBtn) {
        dataTaskState.dbDedupeCleanBtn.addEventListener("click", () => runDbDedupe("execute"));
    }
    if (dataTaskState.dbRestoreBtn) dataTaskState.dbRestoreBtn.addEventListener("click", runDbRestore);
    if (dataTaskState.dbBackupRefreshBtn) dataTaskState.dbBackupRefreshBtn.addEventListener("click", loadDbBackups);
    if (dataTaskState.dbBackupSelect) dataTaskState.dbBackupSelect.addEventListener("change", updateDangerActionState);
    if (dataTaskState.dbDedupeConfirm) dataTaskState.dbDedupeConfirm.addEventListener("change", updateDangerActionState);
    if (dataTaskState.dbRestoreConfirm) dataTaskState.dbRestoreConfirm.addEventListener("change", updateDangerActionState);
    if (dataTaskState.cancelBtn) dataTaskState.cancelBtn.addEventListener("click", cancelDataTask);
    if (dataTaskState.booruDictStatusEl) {
        fetchBooruDictStatus().catch(() => {});
    }
    if (dataTaskState.runtimeAssetsStatusEl) {
        fetchRuntimeAssetsStatus().catch(() => {});
    }

    if (dataTaskState.dbBackupSelect) {
        loadDbBackups();
    }
    updateDangerActionState();
}

function setDataTaskStatus(status, detail = "") {
    if (dataTaskState.statusEl) {
        dataTaskState.statusEl.textContent = status;
    }
    if (dataTaskState.detailEl) {
        dataTaskState.detailEl.textContent = detail;
    }
    if (monitoringShellState.dataTaskStatusChip) {
        monitoringShellState.dataTaskStatusChip.textContent = `Task: ${status || "대기 중"}`;
    }
}

function updateLogTailButton(btn, enabled) {
    if (!btn) return;
    btn.classList.toggle("active", enabled);
    btn.setAttribute("aria-pressed", String(enabled));
}

function initUnifiedTaskLogUI() {
    if (unifiedTaskLogState.bound) return;
    unifiedTaskLogState.logEl = document.getElementById("task-unified-log");
    if (!unifiedTaskLogState.logEl) return;
    unifiedTaskLogState.tailBtn = document.getElementById("task-log-tail");
    unifiedTaskLogState.copyBtn = document.getElementById("task-log-copy");
    unifiedTaskLogState.summaryEl = document.getElementById("task-log-summary");
    unifiedTaskLogState.bound = true;

    if (unifiedTaskLogState.tailBtn) {
        updateLogTailButton(unifiedTaskLogState.tailBtn, unifiedTaskLogState.tailEnabled);
        unifiedTaskLogState.tailBtn.addEventListener("click", () => {
            unifiedTaskLogState.tailEnabled = !unifiedTaskLogState.tailEnabled;
            updateLogTailButton(unifiedTaskLogState.tailBtn, unifiedTaskLogState.tailEnabled);
            scrollLogIfTail(unifiedTaskLogState.logEl, unifiedTaskLogState.tailEnabled);
        });
    }
    if (unifiedTaskLogState.copyBtn) {
        unifiedTaskLogState.copyBtn.addEventListener("click", () => {
            copyTextToClipboard(unifiedTaskLogState.logEl?.textContent || "", {
                emptyMessage: "복사할 통합 로그가 없습니다.",
                successMessage: "통합 로그가 복사되었습니다.",
            });
        });
    }
    syncUnifiedTaskLog();
}

function scrollLogIfTail(logEl, tailEnabled) {
    if (!logEl || !tailEnabled) return;
    logEl.scrollTop = logEl.scrollHeight;
}

function setDataTaskLog(lines, options = {}) {
    const mode = options.mode || "pending";
    if (dataTaskState.logEl) {
        if (Array.isArray(lines) && lines.length) {
            dataTaskState.logEl.textContent = lines.join("\n");
        } else {
            dataTaskState.logEl.textContent = "데이터 작업 로그가 여기에 표시됩니다.";
        }
        scrollLogIfTail(dataTaskState.logEl, dataTaskUIState.logTailEnabled);
    }
    if (unifiedTaskLogState.logEl) {
        if (mode === "payload") {
            unifiedTaskLogState.pendingDataLog = null;
        } else {
            unifiedTaskLogState.pendingDataLog = Array.isArray(lines) ? lines : [];
        }
        syncUnifiedTaskLog();
    }
}

function setDataTaskProgress(progress) {
    const clamped = Math.min(100, Math.max(0, Number(progress) || 0));
    if (dataTaskState.progressBarEl) {
        dataTaskState.progressBarEl.style.width = `${clamped}%`;
    }
    if (dataTaskState.progressValueEl) {
        dataTaskState.progressValueEl.textContent = `${Math.round(clamped)}%`;
    }
}

function renderIntegritySampleList(targetEl, items, guideHref) {
    if (!targetEl) return;
    targetEl.innerHTML = "";
    if (!Array.isArray(items) || items.length === 0) {
        const empty = document.createElement("li");
        empty.className = "empty";
        empty.textContent = "문제 없음";
        targetEl.appendChild(empty);
        return;
    }
    const copyPathToClipboard = (path) => {
        if (!path) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(path)
                .then(() => showToast("✅ 경로가 클립보드에 복사되었습니다."))
                .catch(err => showToast("❌ 복사 실패: " + err));
            return;
        }
        const textarea = document.createElement("textarea");
        textarea.value = path;
        document.body.appendChild(textarea);
        textarea.select();
        try {
            const successful = document.execCommand("copy");
            if (successful) {
                showToast("✅ 경로가 클립보드에 복사되었습니다.");
            } else {
                showToast("❌ 복사 실패");
            }
        } catch (err) {
            showToast("❌ 복사 실패: " + err);
        }
        textarea.remove();
    };
    items.forEach(item => {
        const path = String(item || "");
        const normalizedPath = path.replace(/\\/g, "/");
        const fileName = normalizedPath.split("/").pop() || path;
        const li = document.createElement("li");
        li.className = "data-integrity-sample-item";
        const details = document.createElement("details");
        details.className = "data-integrity-sample-card";
        const summary = document.createElement("summary");
        summary.className = "data-integrity-sample-summary";
        summary.title = path;
        const nameSpan = document.createElement("span");
        nameSpan.className = "data-integrity-sample-name";
        nameSpan.textContent = fileName;
        const actions = document.createElement("div");
        actions.className = "data-integrity-sample-actions";
        if (guideHref) {
            const guideLink = document.createElement("a");
            guideLink.className = "data-integrity-sample-guide";
            guideLink.href = guideHref;
            guideLink.target = "_blank";
            guideLink.rel = "noopener noreferrer";
            guideLink.textContent = "조치 가이드 보기";
            guideLink.addEventListener("click", (event) => {
                event.stopPropagation();
            });
            actions.appendChild(guideLink);
        }
        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "data-integrity-sample-copy";
        copyBtn.textContent = "경로 복사";
        copyBtn.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            copyPathToClipboard(path);
        });
        actions.appendChild(copyBtn);
        summary.appendChild(nameSpan);
        summary.appendChild(actions);
        const fullPath = document.createElement("div");
        fullPath.className = "data-integrity-sample-path";
        fullPath.textContent = path;
        details.appendChild(summary);
        details.appendChild(fullPath);
        li.appendChild(details);
        targetEl.appendChild(li);
    });
}

function renderIntegrityReport(summary) {
    if (!dataTaskState.integrityReportEl) return;
    const sampleReport = summary && typeof summary === "object" ? summary.sample_report : null;
    if (!sampleReport) {
        dataTaskState.integrityReportEl.classList.add("hidden");
        return;
    }
    dataTaskState.integrityReportEl.classList.remove("hidden");
    const limitValue = Number(sampleReport.limit || 0);
    const limitApplied = Boolean(sampleReport.limit_applied);
    if (dataTaskState.integritySampleLimitEl) {
        let limitText = limitValue > 0 ? `샘플 제한: 최대 ${limitValue}건` : "샘플 제한: 없음";
        if (limitApplied) {
            limitText += " · 샘플 제한 적용됨";
        }
        dataTaskState.integritySampleLimitEl.textContent = limitText;
    }
    const reportMeta = sampleReport.report || {};
    if (dataTaskState.integrityReportDownloadEl) {
        if (reportMeta.download_url) {
            dataTaskState.integrityReportDownloadEl.href = reportMeta.download_url;
            dataTaskState.integrityReportDownloadEl.classList.remove("hidden");
        } else {
            dataTaskState.integrityReportDownloadEl.classList.add("hidden");
        }
    }
    const samples = sampleReport.samples || {};
    renderIntegritySampleList(
        dataTaskState.integritySampleNoMetaEl,
        samples.no_meta || [],
        "/static/integrity_guide.md#no_meta"
    );
    renderIntegritySampleList(
        dataTaskState.integritySampleNoKSamplerEl,
        samples.no_ksampler || [],
        "/static/integrity_guide.md#no_ksampler"
    );
    renderIntegritySampleList(
        dataTaskState.integritySampleMissingPositiveEl,
        samples.missing_positive || [],
        "/static/integrity_guide.md#missing_positive"
    );
    renderIntegritySampleList(
        dataTaskState.integritySampleReadFailedEl,
        samples.read_failed || [],
        "/static/integrity_guide.md#read_failed"
    );
}

function renderDbDedupeReport(summary) {
    if (!dataTaskState.dbDedupeReportEl) return;
    if (!summary || typeof summary !== "object") {
        dataTaskState.dbDedupeReportEl.classList.add("hidden");
        return;
    }
    const samples = Array.isArray(summary.samples) ? summary.samples : [];
    dataTaskState.dbDedupeReportEl.classList.remove("hidden");
    if (dataTaskState.dbDedupeSampleInfoEl) {
        const limitValue = Number(summary.sample_limit || 0);
        const text = limitValue > 0 ? `샘플 표시: 최대 ${limitValue}건` : "샘플 표시: 없음";
        dataTaskState.dbDedupeSampleInfoEl.textContent = text;
    }
    if (!dataTaskState.dbDedupeSampleListEl) return;
    dataTaskState.dbDedupeSampleListEl.innerHTML = "";
    if (!samples.length) {
        const empty = document.createElement("li");
        empty.className = "empty";
        empty.textContent = "중복 없음";
        dataTaskState.dbDedupeSampleListEl.appendChild(empty);
        return;
    }
    samples.forEach(sample => {
        const li = document.createElement("li");
        li.className = "data-integrity-sample-item";
        const details = document.createElement("details");
        details.className = "data-integrity-sample-card";
        const summaryEl = document.createElement("summary");
        summaryEl.className = "data-integrity-sample-summary";
        const nameSpan = document.createElement("span");
        nameSpan.className = "data-integrity-sample-name";
        const type = sample.type || "unknown";
        const key = sample.key || sample.tag || sample.name || "중복 항목";
        nameSpan.textContent = `[${type}] ${key}`;
        summaryEl.appendChild(nameSpan);
        const fullPath = document.createElement("div");
        fullPath.className = "data-integrity-sample-path";
        fullPath.textContent = JSON.stringify(sample, null, 2);
        details.appendChild(summaryEl);
        details.appendChild(fullPath);
        li.appendChild(details);
        dataTaskState.dbDedupeSampleListEl.appendChild(li);
    });
}

function renderDataTaskSummary(summary) {
    if (!dataTaskState.summaryReportEl || !dataTaskState.summaryListEl) return;
    if (!summary || typeof summary !== "object") {
        dataTaskState.summaryReportEl.classList.add("hidden");
        return;
    }
    const sampleItems = Array.isArray(summary.sample_items) ? summary.sample_items : [];
    const extraItems = [];
    if (summary.restart_required) {
        extraItems.push("재시작 필요: 서버를 재시작해야 합니다.");
    }
    if (summary.backup_path) {
        extraItems.push(`복원 대상: ${summary.backup_path}`);
    }
    if (summary.safety_backup_path) {
        extraItems.push(`자동 백업: ${summary.safety_backup_path}`);
    }
    const mergedItems = [...extraItems, ...sampleItems];
    if (!mergedItems.length) {
        dataTaskState.summaryReportEl.classList.add("hidden");
        return;
    }

    const label = summary.sample_label || "샘플";
    const count = sampleItems.length;
    if (dataTaskState.summaryLabelEl) {
        dataTaskState.summaryLabelEl.textContent = count ? `${label} · ${count}건` : label;
    }
    dataTaskState.summaryListEl.innerHTML = "";
    mergedItems.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = typeof item === "string" ? item : JSON.stringify(item, null, 2);
        dataTaskState.summaryListEl.appendChild(li);
    });
    dataTaskState.summaryReportEl.classList.remove("hidden");
}

function resolveDataTaskState(payload) {
    if (!payload || typeof payload !== "object") return null;
    const tasks = payload.tasks || {};
    if (payload.active_task && tasks[payload.active_task]) {
        return tasks[payload.active_task];
    }
    const candidates = Object.values(tasks).filter(Boolean);
    if (!candidates.length) return null;
    candidates.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
    return candidates[0];
}

function formatDataTaskStatus(status) {
    switch (status) {
        case "running":
            return "진행 중";
        case "completed":
            return "완료";
        case "failed":
            return "실패";
        case "cancelled":
            return "취소됨";
        case "cancelling":
            return "취소 요청";
        default:
            return "대기 중";
    }
}

function normalizeLogTimestamp(tsSeconds, fallbackSeconds) {
    if (Number.isFinite(tsSeconds) && tsSeconds > 0) return tsSeconds * 1000;
    if (Number.isFinite(fallbackSeconds) && fallbackSeconds > 0) return fallbackSeconds * 1000;
    return Date.now();
}

function extractRefreshLogEntries(state) {
    if (!state || typeof state !== "object") return [];
    const updatedAt = Number(state.updated_at || 0);
    const entries = [];
    const logs = Array.isArray(state.logs) ? state.logs : [];
    logs.forEach((entry) => {
        const message = entry?.message || "";
        if (!message) return;
        if (message.includes("이전 전체 재정리 작업")) return;
        entries.push({
            ts: normalizeLogTimestamp(Number(entry?.ts), updatedAt),
            sourceLabel: "REFRESH",
            message,
        });
    });
    if (!entries.length) {
        const fallback = state.message || state.status || "";
        if (fallback && !fallback.includes("이전 전체 재정리 작업")) {
            entries.push({
                ts: normalizeLogTimestamp(updatedAt || Date.now() / 1000),
                sourceLabel: "REFRESH",
                message: fallback,
            });
        }
    }
    return entries;
}

function extractDataTaskLogEntries(payload) {
    const state = resolveDataTaskState(payload);
    if (!state) return [];
    const label = state.label || state.task || "데이터 작업";
    const updatedAt = Number(state.updated_at || 0);
    const prefix = label ? `${label} · ` : "";
    const logs = Array.isArray(state.logs) ? state.logs : [];
    const entries = [];
    logs.forEach((entry) => {
        const message = entry?.message || "";
        if (!message) return;
        entries.push({
            ts: normalizeLogTimestamp(Number(entry?.ts), updatedAt),
            sourceLabel: "TASK",
            message: `${prefix}${message}`,
        });
    });
    if (state.summary && typeof state.summary === "object") {
        entries.push({
            ts: normalizeLogTimestamp(updatedAt || Date.now() / 1000),
            sourceLabel: "TASK",
            message: `${prefix}summary: ${JSON.stringify(state.summary)}`,
        });
    }
    if (!entries.length) {
        const statusText = formatDataTaskStatus(state.status);
        const fallback = state.message || `${label} ${statusText}`;
        entries.push({
            ts: normalizeLogTimestamp(updatedAt || Date.now() / 1000),
            sourceLabel: "TASK",
            message: fallback,
        });
    }
    return entries;
}

function syncUnifiedTaskLog() {
    if (!unifiedTaskLogState.logEl) return;
    const entries = [];
    const refreshEntries = extractRefreshLogEntries(refreshUIState.lastState);
    const dataEntries = extractDataTaskLogEntries(dataTaskUIState.lastPayload);

    if (refreshEntries.length) {
        entries.push(...refreshEntries);
    } else if (Array.isArray(unifiedTaskLogState.pendingRefreshLog) && unifiedTaskLogState.pendingRefreshLog.length) {
        const base = Date.now();
        unifiedTaskLogState.pendingRefreshLog.forEach((line, idx) => {
            const message = String(line || "").trim();
            if (!message) return;
            entries.push({
                ts: base + idx,
                sourceLabel: "REFRESH",
                message,
            });
        });
    }

    if (dataEntries.length) {
        entries.push(...dataEntries);
    } else if (Array.isArray(unifiedTaskLogState.pendingDataLog) && unifiedTaskLogState.pendingDataLog.length) {
        const base = Date.now();
        unifiedTaskLogState.pendingDataLog.forEach((line, idx) => {
            const message = String(line || "").trim();
            if (!message) return;
            entries.push({
                ts: base + idx,
                sourceLabel: "TASK",
                message,
            });
        });
    }

    entries.sort((a, b) => (a.ts || 0) - (b.ts || 0));
    if (!entries.length) {
        unifiedTaskLogState.logEl.textContent = "작업 로그가 여기에 표시됩니다.";
        if (unifiedTaskLogState.summaryEl) {
            unifiedTaskLogState.summaryEl.textContent = "로그 없음";
        }
        return;
    }
    const lines = entries.map((entry) => {
        const timeLabel = new Date(entry.ts).toLocaleTimeString("ko-KR", { hour12: false });
        const sourceLabel = entry.sourceLabel ? `[${entry.sourceLabel}] ` : "";
        return `[${timeLabel}] ${sourceLabel}${entry.message}`;
    });
    unifiedTaskLogState.logEl.textContent = lines.join("\n");
    if (unifiedTaskLogState.summaryEl) {
        const lastTime = entries.length ? new Date(entries[entries.length - 1].ts).toLocaleTimeString("ko-KR", { hour12: false }) : "-";
        unifiedTaskLogState.summaryEl.textContent = `로그 ${entries.length}줄 · 최신 ${lastTime}`;
    }
    scrollLogIfTail(unifiedTaskLogState.logEl, unifiedTaskLogState.tailEnabled);
    if (monitoringShellState.lastUpdatedChip) {
        monitoringShellState.lastUpdatedChip.textContent = `Updated: ${new Date().toLocaleTimeString("ko-KR", { hour12: false })}`;
    }
}


function updateUnifiedTaskProgress() {
    // Data Tasks 페이지 상단 상태 패널을 "단일 진행바"로 사용할 때만 동작한다.
    const metaEl = document.getElementById("unified-task-meta");
    if (!metaEl) return;

    const statusEl = document.getElementById("data-task-status");
    const detailEl = document.getElementById("data-task-detail");
    const progressBarEl = document.getElementById("data-task-progress-bar");
    const progressValueEl = document.getElementById("data-task-progress-value");
    const cancelBtn = document.getElementById("data-task-cancel");

    const refreshState = refreshUIState?.lastState || null;
    const refreshStatus = refreshState?.status || "idle";
    const refreshProgress = Number(refreshState?.progress ?? 0);
    const refreshUpdatedAt = Number(refreshState?.updated_at ?? 0);
    const rawRefreshMessage = typeof refreshState?.message === "string" ? refreshState.message : "";
    const isLegacyStaleNotice = rawRefreshMessage.includes("이전 전체 재정리 작업 상태가");
    const refreshMessage = isLegacyStaleNotice ? (refreshStatus === "completed" ? "완료" : "") : (rawRefreshMessage || "");
    const refreshRemaining = Array.isArray(refreshState?.remaining_steps) ? refreshState.remaining_steps : [];
    const refreshDetailParts = [];
    if (refreshMessage) refreshDetailParts.push(refreshMessage);
    if (refreshStatus === "running") refreshDetailParts.push(`진행률 ${Math.round(refreshProgress)}%`);
    const refreshDetail = refreshDetailParts.join(" · ");

    const payload = dataTaskUIState?.lastPayload || null;
    const taskState = resolveDataTaskState(payload);
    let taskStatus = "idle";
    let taskProgress = 0;
    let taskUpdatedAt = 0;
    let taskLabel = "데이터 작업";
    let taskDetail = "";
    if (taskState) {
        taskStatus = taskState.status || "idle";
        taskProgress = Number(taskState.progress ?? (taskStatus === "completed" ? 100 : 0));
        taskUpdatedAt = Number(taskState.updated_at || 0);
        taskLabel = taskState.label || taskState.task || "데이터 작업";
        const parts = [];
        if (taskState.message) parts.push(taskState.message);
        if (taskStatus === "running") parts.push(`진행률 ${Math.round(taskProgress)}%`);
        taskDetail = parts.join(" · ");
    }

    const taskIsRunning = taskStatus === "running" || taskStatus === "cancelling";
    const refreshIsRunning = refreshStatus === "running";
    const taskNonIdle = Boolean(taskState && taskStatus && taskStatus !== "idle");
    const refreshNonIdle = Boolean(refreshState && refreshStatus && refreshStatus !== "idle");

    let chosen = "none";
    if (taskIsRunning) {
        chosen = "task";
    } else if (refreshIsRunning) {
        chosen = "refresh";
    } else if (taskNonIdle && refreshNonIdle) {
        chosen = taskUpdatedAt >= refreshUpdatedAt ? "task" : "refresh";
    } else if (taskNonIdle) {
        chosen = "task";
    } else if (refreshNonIdle) {
        chosen = "refresh";
    }

    let labelText = "대기 중";
    let detailText = "";
    let progress = 0;
    let metaText = "";

    if (chosen === "task" && taskState) {
        labelText = `${taskLabel} ${formatDataTaskStatus(taskStatus)}`;
        detailText = taskDetail;
        progress = taskProgress;
        metaText = "";
        if (cancelBtn) {
            cancelBtn.hidden = false;
            cancelBtn.disabled = !taskIsRunning;
        }
    } else if (chosen === "refresh" && refreshState) {
        labelText = `전체 재정리 ${String(refreshStatus || "idle").toUpperCase()}`;
        detailText = refreshDetail;
        progress = refreshProgress;
        metaText = refreshRemaining.length ? `남은 단계: ${refreshRemaining.join(" → ")}` : "";
        if (cancelBtn) cancelBtn.hidden = true;
    } else {
        if (cancelBtn) {
            cancelBtn.hidden = false;
            cancelBtn.disabled = true;
        }
    }

    const clamped = Math.min(100, Math.max(0, Number(progress) || 0));
    if (statusEl) statusEl.textContent = labelText;
    if (detailEl) detailEl.textContent = detailText;
    if (progressBarEl) progressBarEl.style.width = `${clamped}%`;
    if (progressValueEl) progressValueEl.textContent = `${Math.round(clamped)}%`;
    metaEl.textContent = metaText;
}

function setPendingRefreshLog(lines) {
    if (!unifiedTaskLogState.logEl) return;
    unifiedTaskLogState.pendingRefreshLog = Array.isArray(lines) ? lines : [];
    syncUnifiedTaskLog();
}

function renderDataTaskState(payload) {
    dataTaskUIState.lastPayload = payload;
    const state = resolveDataTaskState(payload);
    if (!state) {
        setDataTaskStatus("대기 중", "");
        setDataTaskLog([], { mode: "payload" });
        setDataTaskProgress(0);
        renderDataTaskSummary(null);
        renderIntegrityReport(null);
        renderDbDedupeReport(null);
        if (dataTaskState.cancelBtn) dataTaskState.cancelBtn.disabled = true;
        setDataTaskButtonsDisabled(false);
        updateUnifiedTaskProgress();
        return;
    }
    const label = state.label || state.task || "데이터 작업";
    const statusText = formatDataTaskStatus(state.status);
    const progress = Number(state.progress ?? (state.status === "completed" ? 100 : 0));
    const detailParts = [];
    if (state.message) detailParts.push(state.message);
    if (state.status === "running") detailParts.push(`진행률 ${Math.round(progress)}%`);
    setDataTaskStatus(`${label} ${statusText}`, detailParts.join(" · "));
    setDataTaskProgress(progress);
    updateUnifiedTaskProgress();

    const lines = (state.logs || []).map(entry => {
        const d = entry?.ts ? new Date(entry.ts * 1000) : new Date();
        const ts = d.toLocaleTimeString();
        return `[${ts}] ${entry?.message || ""}`;
    });
    if (state.summary && typeof state.summary === "object") {
        lines.push(`요약: ${JSON.stringify(state.summary)}`);
    }
    setDataTaskLog(lines, { mode: "payload" });
    renderDataTaskSummary(state.summary);
    renderIntegrityReport(state.summary);
    if (state.task === "db_dedupe") {
        renderDbDedupeReport(state.summary);
    } else {
        renderDbDedupeReport(null);
    }
    maybeRefreshBooruDictStatus(state);
    maybeRefreshRuntimeAssetsStatus(state);

    const isRunning = state.status === "running" || state.status === "cancelling";
    if (dataTaskState.cancelBtn) {
        dataTaskState.cancelBtn.disabled = !isRunning;
    }
    setDataTaskButtonsDisabled(isRunning);
    if (!isRunning) {
        updateDangerActionState();
    }

    if (!isRunning && dataTaskUIState.poller) {
        clearInterval(dataTaskUIState.poller);
        dataTaskUIState.poller = null;
    }
    if (!isRunning && state.status && state.status !== "idle") {
        const toastType = state.status === "completed" ? "success" : "error";
        showToast(state.message || `${label} ${statusText}`, toastType);
    }
}

function setDataTaskButtonsDisabled(disabled) {
    const buttons = [
        dataTaskState.dbBackupBtn,
        dataTaskState.imageScanBtn,
        dataTaskState.failedRecoveryBtn,
        dataTaskState.imageCleanupBtn,
        dataTaskState.orphanCleanupBtn,
        dataTaskState.videoIndexBtn,
        dataTaskState.videoCleanupBtn,
        dataTaskState.thumbBtn,
        dataTaskState.phashIndexBtn,
        dataTaskState.phashGroupBuildBtn,
        dataTaskState.booruAutoTagBtn,
        dataTaskState.integrityBtn,
        dataTaskState.dbQuickCheckBtn,
        dataTaskState.dbIntegrityCheckBtn,
        dataTaskState.dbFkCheckBtn,
        dataTaskState.dbVacuumBtn,
        dataTaskState.dbAnalyzeBtn,
        dataTaskState.dbOptimizeBtn,
        dataTaskState.dbWalCheckpointBtn,
        dataTaskState.ftsRebuildBtn,
        dataTaskState.booruDictUpdateBtn,
        dataTaskState.runtimeFfmpegInstallBtn,
        dataTaskState.runtimeExiftoolInstallBtn,
        dataTaskState.runtimeWd14InstallBtn,
        dataTaskState.dbBackupRefreshBtn,
        dataTaskState.dbRestoreBtn,
        dataTaskState.dbDedupeCheckBtn,
        dataTaskState.dbDedupeCleanBtn,
    ];
    buttons.forEach(btn => {
        if (btn) btn.disabled = disabled;
    });
    if (!disabled) {
        updateDangerActionState();
    }
}

function updateDangerActionState() {
    if (dataTaskState.dbDedupeCleanBtn && dataTaskState.dbDedupeConfirm) {
        dataTaskState.dbDedupeCleanBtn.disabled = !dataTaskState.dbDedupeConfirm.checked;
    }
    if (dataTaskState.dbRestoreBtn && dataTaskState.dbRestoreConfirm) {
        const hasSelection = dataTaskState.dbBackupSelect && dataTaskState.dbBackupSelect.value;
        dataTaskState.dbRestoreBtn.disabled = !dataTaskState.dbRestoreConfirm.checked || !hasSelection;
    }
}

async function loadDbBackups() {
    if (!dataTaskState.dbBackupSelect) return;
    try {
        const res = await fetch("/data/db-backups", { headers: { Accept: "application/json" } });
        const payload = await res.json();
        const items = Array.isArray(payload?.items) ? payload.items : [];
        dataTaskState.dbBackupSelect.innerHTML = "";
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = items.length ? "백업을 선택하세요" : "백업 없음";
        dataTaskState.dbBackupSelect.appendChild(placeholder);
        items.forEach((item) => {
            const option = document.createElement("option");
            option.value = item.name;
            const mtime = item.mtime ? new Date(item.mtime * 1000).toLocaleString("ko-KR") : "알 수 없음";
            option.textContent = `${item.name} (${mtime})`;
            dataTaskState.dbBackupSelect.appendChild(option);
        });
        updateDangerActionState();
    } catch (err) {
        console.error(err);
        showToast("❌ DB 백업 목록을 불러오지 못했습니다.", "error");
    }
}

async function fetchDataTaskStatus() {
    try {
        const res = await fetch("/data/status", { headers: { Accept: "application/json" } });
        const payload = await res.json();
        renderDataTaskState(payload);
        return payload;
    } catch (err) {
        console.error("data task status error", err);
    }
}

async function runThumbnailPrebuild() {
    setDataTaskStatus("썸네일 프리빌드 실행 중", "요청을 전송했습니다.");
    setDataTaskLog(["썸네일 프리빌드 요청 중..."]);
    try {
        const params = new URLSearchParams({
            include_videos: getIncludeVideosValue() ? "1" : "0",
            failure_action: getThumbPrebuildFailureAction(),
        });
        const res = await fetch("/data/thumb-prebuild", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || "썸네일 프리빌드 실패");
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus("썸네일 프리빌드 실패", "요청 처리 중 오류가 발생했습니다.");
        showToast("❌ 썸네일 프리빌드 실행에 실패했습니다.", "error");
    }
}

async function runPhashIndex() {
    setDataTaskStatus("pHash 추출 실행 중", "요청을 전송했습니다.");
    setDataTaskLog(["pHash 추출 요청 중..."]);
    try {
        const params = new URLSearchParams({
            include_images: "1",
            include_videos: getIncludeVideosValue() ? "1" : "0",
            force: getPhashForceValue() ? "1" : "0",
        });
        const res = await fetch("/data/phash-index", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || "pHash 추출 실패");
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus("pHash 추출 실패", "요청 처리 중 오류가 발생했습니다.");
        showToast("❌ pHash 추출 실행에 실패했습니다.", "error");
    }
}

async function runPhashGroupBuild() {
    setDataTaskStatus("pHash 연관관계 구축 중", "요청을 전송했습니다.");
    setDataTaskLog(["pHash 연관관계 구축 요청 중..."]);
    try {
        const params = new URLSearchParams({
            distance: String(getPhashGroupDistanceValue()),
            mode: getPhashGroupRebuildValue() ? "rebuild" : "incremental",
            include_images: "1",
            include_videos: getIncludeVideosValue() ? "1" : "0",
        });
        const res = await fetch("/data/phash-groups", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || "pHash 연관관계 구축 실패");
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus("pHash 연관관계 구축 실패", "요청 처리 중 오류가 발생했습니다.");
        showToast("❌ pHash 연관관계 구축에 실패했습니다.", "error");
    }
}

async function runBooruAutoTagTask() {
    const label = "Danbooru \uC790\uB3D9 \uD0DC\uAE45";
    setDataTaskStatus(`${label} \uC2E4\uD589 \uC911`, "\uC694\uCCAD\uC744 \uC804\uC1A1\uD588\uC2B5\uB2C8\uB2E4.");
    setDataTaskLog([`${label} \uC694\uCCAD \uC911..`]);
    try {
        const params = new URLSearchParams();
        if (getBooruAutoTagForceValue()) {
            params.set("force", "1");
        }
        const res = await fetch("/data/booru-auto-tag", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} \uC2E4\uD328`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} \uC2E4\uD328`, "\uC694\uCCAD \uCC98\uB9AC \uC911 \uC624\uB958\uAC00 \uBC1C\uC0DD\uD588\uC2B5\uB2C8\uB2E4.");
        showToast(`${label} \uC2E4\uD589\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.`, "error");
    }
}





async function runRefreshStep(step, label) {
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    setDataTaskLog([`${label} 요청 중...`]);
    try {
        const params = new URLSearchParams({ step });
        if (step === "image_scan") {
            params.set("force_rescan", getImageScanForceRescanValue() ? "1" : "0");
        }
        if (step === "orphan_cleanup") {
            params.set("include_videos", getIncludeVideosValue() ? "1" : "0");
        }
        const res = await fetch("/data/refresh-step", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        showToast(`❌ ${label} 실행에 실패했습니다.`, "error");
    }
}

async function runDbDedupe(mode) {
    const isExecute = mode === "execute";
    const label = isExecute ? "DB 중복 제거" : "DB 중복 검사";
    if (isExecute && dataTaskState.dbDedupeConfirm && !dataTaskState.dbDedupeConfirm.checked) {
        showToast("⚠️ 확인 체크박스를 선택한 뒤 실행하세요.", "warning");
        return;
    }
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    setDataTaskLog([`${label} 요청 중...`]);
    try {
        const params = new URLSearchParams({
            mode: isExecute ? "execute" : "dry",
            sample_limit: String(getDbDedupeSampleLimitValue()),
        });
        if (isExecute) {
            params.set("confirm", "1");
        }
        const res = await fetch("/data/db-dedupe", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        showToast(`❌ ${label} 실행에 실패했습니다.`, "error");
    }
}

async function runDbIntegrityCheck() {
    const modeInput = document.querySelector('input[name="db-integrity-mode"]:checked');
    const mode = modeInput ? modeInput.value : "dry";
    setDataTaskStatus("PNG 무결성 검사 실행 중", mode === "execute" ? "실행 모드" : "드라이런");
    setDataTaskLog(["PNG 무결성 검사 요청 중..."]);
    try {
        const params = new URLSearchParams({
            mode,
            summary_only: "1",
            include_videos: getIncludeVideosValue() ? "1" : "0",
            date_folder_only: getIntegrityDateOnlyValue() ? "1" : "0",
            exclude_failed: getIntegrityExcludeFailedValue() ? "1" : "0",
            include_quarantine: getIntegrityIncludeQuarantineValue() ? "1" : "0",
            limit: String(getIntegrityLimitValue()),
        });
        const rootOverride = getIntegrityRootValue();
        if (rootOverride) {
            params.set("root", rootOverride);
        }
        const res = await fetch("/data/integrity-check", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || "무결성 검사 실패");
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus("PNG 무결성 검사 실패", "요청 처리 중 오류가 발생했습니다.");
        showToast("❌ PNG 무결성 검사 실행에 실패했습니다.", "error");
    }
}

async function runDbCheck(mode) {
    const label = mode === "full" ? "DB integrity_check" : "DB quick_check";
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    setDataTaskLog([`${label} 요청 중...`]);
    try {
        const params = new URLSearchParams({ mode });
        const res = await fetch("/data/db-check", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        showToast(`❌ ${label} 실행에 실패했습니다.`, "error");
    }
}

async function runFkCheck() {
    const label = "Foreign Key 검사";
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    setDataTaskLog([`${label} 요청 중...`]);
    try {
        const res = await fetch("/data/fk-check", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        showToast(`❌ ${label} 실행에 실패했습니다.`, "error");
    }
}

async function runDbMaintenance(op) {
    const labelMap = {
        vacuum: "DB VACUUM",
        analyze: "DB ANALYZE",
        optimize: "DB optimize",
        wal_checkpoint: "WAL checkpoint",
    };
    const label = labelMap[op] || "DB 유지보수";
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    setDataTaskLog([`${label} 요청 중...`]);
    try {
        const params = new URLSearchParams({ op });
        if (op === "wal_checkpoint") {
            params.set("mode", getWalCheckpointModeValue());
        }
        const res = await fetch("/data/db-maintenance", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        showToast(`❌ ${label} 실행에 실패했습니다.`, "error");
    }
}

function setBooruDictStatusText(text, type = "info") {
    const el = dataTaskState.booruDictStatusEl;
    if (!el) return;
    el.textContent = text;
    if (type === "error") {
        el.style.color = "#dc3545";
    } else if (type === "warning") {
        el.style.color = "#d39e00";
    } else {
        el.style.color = "#555";
    }
}

function formatBooruDictStatus(meta) {
    if (!meta || typeof meta !== "object" || !Object.keys(meta).length) {
        return "태그DB 상태: 정보 없음";
    }
    const parts = [];
    if (meta.imported_at) parts.push(`마지막 업데이트: ${meta.imported_at}`);
    if (meta.tag_count !== undefined && meta.tag_count !== null) {
        parts.push(`태그 수: ${meta.tag_count}`);
    }
    const sha = meta.last_sha256 || meta.sha256;
    if (sha) parts.push(`sha256: ${sha}`);
    if (meta.category_counts_json) {
        try {
            const parsed = JSON.parse(meta.category_counts_json);
            if (parsed && typeof parsed === "object") {
                const orderedKeys = ["general", "character", "copyright", "artist", "meta"];
                const entries = orderedKeys
                    .map((key) => [key, Number(parsed[key])])
                    .filter(([, value]) => Number.isFinite(value));
                if (entries.length) {
                    const formatted = entries.map(
                        ([key, value]) => `${key}=${value.toLocaleString()}`
                    );
                    parts.push(`category: ${formatted.join(", ")}`);
                }
            }
        } catch (err) {
        }
    }
    return `태그DB 상태: ${parts.join(" · ")}`;
}

async function fetchBooruDictStatus({ force = false } = {}) {
    if (!dataTaskState.booruDictStatusEl) return;
    if (booruDictStatusState.loading && !force) return;
    booruDictStatusState.loading = true;
    try {
        setBooruDictStatusText("태그DB 상태: 불러오는 중...");
        const res = await fetch("/data/booru-dict-meta", { headers: { Accept: "application/json" } });
        const payload = await res.json();
        if (!res.ok) {
            throw new Error(payload?.error || `HTTP ${res.status}`);
        }
        const meta = payload?.meta || {};
        booruDictStatusState.lastMeta = meta;
        setBooruDictStatusText(formatBooruDictStatus(meta));
    } catch (err) {
        console.error("booru dict status error", err);
        setBooruDictStatusText("태그DB 상태: 로드 실패", "error");
    } finally {
        booruDictStatusState.loading = false;
    }
}

function maybeRefreshBooruDictStatus(state) {
    if (!dataTaskState.booruDictStatusEl) return;
    if (!state || state.task !== "booru_dict_update") return;
    if (state.status === "running" || state.status === "cancelling") {
        setBooruDictStatusText("태그DB 상태: 업데이트 진행 중...");
        return;
    }
    const updatedAt = Number(state.updated_at || 0);
    if (updatedAt && updatedAt === booruDictStatusState.lastTaskUpdatedAt) return;
    booruDictStatusState.lastTaskUpdatedAt = updatedAt || Date.now() / 1000;
    fetchBooruDictStatus({ force: true }).catch(() => {});
}

function setRuntimeAssetsStatusText(text, type = "info") {
    const el = dataTaskState.runtimeAssetsStatusEl;
    if (!el) return;
    el.textContent = text;
    if (type === "error") {
        el.style.color = "#dc3545";
    } else if (type === "warning") {
        el.style.color = "#d39e00";
    } else {
        el.style.color = "#555";
    }
}

function formatRuntimeAssetsStatus(meta) {
    if (!meta || typeof meta !== "object") {
        return "런타임 도구 상태: 정보 없음";
    }
    const ffmpegReady = Boolean(meta.ffmpeg?.exists);
    const ffprobeReady = Boolean(meta.ffprobe?.exists);
    const exiftoolReady = Boolean(meta.exiftool?.exists);
    const wd14Ready = Boolean(meta.wd14?.model_exists && meta.wd14?.tags_exists);
    const wd14Label = meta.wd14?.model_key ? `${meta.wd14.model_key}` : "미설치";
    return `런타임 도구 상태: FFmpeg=${ffmpegReady ? "OK" : "없음"} · FFprobe=${ffprobeReady ? "OK" : "없음"} · ExifTool=${exiftoolReady ? "OK" : "없음"} · WD14=${wd14Ready ? wd14Label : "없음"}`;
}

async function fetchRuntimeAssetsStatus({ force = false } = {}) {
    if (!dataTaskState.runtimeAssetsStatusEl) return;
    if (runtimeAssetsState.loading && !force) return;
    runtimeAssetsState.loading = true;
    try {
        setRuntimeAssetsStatusText("런타임 도구 상태: 불러오는 중...");
        const res = await fetch("/data/runtime-assets-meta", { headers: { Accept: "application/json" } });
        const payload = await res.json();
        if (!res.ok) {
            throw new Error(payload?.error || `HTTP ${res.status}`);
        }
        const meta = payload?.meta || {};
        runtimeAssetsState.lastMeta = meta;
        setRuntimeAssetsStatusText(formatRuntimeAssetsStatus(meta));
    } catch (err) {
        console.error("runtime assets status error", err);
        setRuntimeAssetsStatusText("런타임 도구 상태: 로드 실패", "error");
    } finally {
        runtimeAssetsState.loading = false;
    }
}

function maybeRefreshRuntimeAssetsStatus(state) {
    if (!dataTaskState.runtimeAssetsStatusEl) return;
    if (!state) return;
    if (!["runtime_ffmpeg_install", "runtime_exiftool_install", "runtime_wd14_install"].includes(state.task || "")) {
        return;
    }
    if (state.status === "running" || state.status === "cancelling") {
        setRuntimeAssetsStatusText("런타임 도구 상태: 설치 진행 중...");
        return;
    }
    const updatedAt = Number(state.updated_at || 0);
    if (updatedAt && updatedAt === runtimeAssetsState.lastTaskUpdatedAt) return;
    runtimeAssetsState.lastTaskUpdatedAt = updatedAt || Date.now() / 1000;
    fetchRuntimeAssetsStatus({ force: true }).catch(() => {});
}

async function runRuntimeAssetInstall(target, { modelKey = "" } = {}) {
    const labelMap = {
        ffmpeg: "FFmpeg/FFprobe 설치",
        exiftool: "ExifTool 설치",
        wd14: "WD14 모델 설치",
    };
    const label = labelMap[target] || "런타임 도구 설치";
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    const logLines = [`${label} 요청 중...`];
    if (target === "wd14" && modelKey) {
        logLines.push(`선택 모델: ${modelKey}`);
    }
    setDataTaskLog(logLines);
    setRuntimeAssetsStatusText("런타임 도구 상태: 설치 요청 중...");
    try {
        const params = new URLSearchParams({ target });
        if (modelKey) params.set("model_key", modelKey);
        const res = await fetch("/data/runtime-install", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        setRuntimeAssetsStatusText("런타임 도구 상태: 설치 실패", "error");
        showToast(`❌ ${label} 실패`, "error");
    }
}

async function runBooruDictUpdate({ force = false } = {}) {
    const label = "Danbooru 태그DB 업데이트";
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    const logLines = [`${label} 요청 중...`];
    if (force) {
        const forceMessage = "강제 재적재(force)로 실행합니다 (sha256 동일해도 import)";
        logLines.push(forceMessage);
        showToast(forceMessage, "info");
    }
    setDataTaskLog(logLines);
    setBooruDictStatusText("태그DB 상태: 업데이트 요청 중...");
    try {
        const params = new URLSearchParams();
        if (force) params.set("force", "1");
        const res = await fetch("/data/booru-dict-update", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        setBooruDictStatusText("태그DB 상태: 업데이트 실패", "error");
        showToast(`❌ ${label} 실패`, "error");
    }
}

async function runFtsRebuild() {
    const label = "FTS 재구축";
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    setDataTaskLog([`${label} 요청 중...`]);
    try {
        const res = await fetch("/data/fts-rebuild", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        showToast(`❌ ${label} 실행에 실패했습니다.`, "error");
    }
}

async function runDbRestore() {
    const label = "DB 백업 복원";
    if (dataTaskState.dbRestoreConfirm && !dataTaskState.dbRestoreConfirm.checked) {
        showToast("⚠️ 확인 체크박스를 선택한 뒤 실행하세요.", "warning");
        return;
    }
    const selected = dataTaskState.dbBackupSelect ? dataTaskState.dbBackupSelect.value : "";
    if (!selected) {
        showToast("⚠️ 복원할 백업을 선택하세요.", "warning");
        return;
    }
    setDataTaskStatus(`${label} 실행 중`, "요청을 전송했습니다.");
    setDataTaskLog([`${label} 요청 중...`]);
    try {
        const params = new URLSearchParams({
            backup_name: selected,
            confirm: "1",
        });
        const res = await fetch("/data/db-restore", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
        });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || `${label} 실패`);
        if (!dataTaskUIState.poller) {
            dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        setDataTaskStatus(`${label} 실패`, "요청 처리 중 오류가 발생했습니다.");
        showToast(`❌ ${label} 실행에 실패했습니다.`, "error");
    }
}

async function cancelDataTask() {
    try {
        const res = await fetch("/data/cancel", { method: "POST", headers: { Accept: "application/json" } });
        const payload = await res.json();
        renderDataTaskState(payload);
        if (!res.ok) throw new Error(payload?.error || "취소 실패");
    } catch (err) {
        console.error(err);
        showToast("❌ 작업 취소에 실패했습니다.", "error");
    }
}

document.addEventListener("keydown", function (event) {
    const isCompareOpen = compareState.modal && !compareState.modal.classList.contains("hidden");
    if (isCompareOpen && event.key === "Escape") {
        event.preventDefault();
        closeCompareModal();
        return;
    }

    if (selectionState.active) {
        if (event.key === "Escape") {
            event.preventDefault();
            disableSelectionMode();
            return;
        }
        if (event.key === "Delete" || event.key === "Backspace") {
            if (isEditableElement(document.activeElement)) {
                return;
            }
            event.preventDefault();
            deleteSelectedMedia();
            return;
        }
    }

    if (event.key === "Escape") hideModal();
    if (event.key === "ArrowLeft") showPrevImage();
    if (event.key === "ArrowRight") showNextImage();
});

window.addEventListener("click", function (event) {
    if (event.target === document.getElementById("modal")) hideModal();
});

document.addEventListener("DOMContentLoaded", function () {
    const hasSearchForm = Boolean(document.getElementById("search-form"));

    setupDataTaskUI();
    const hasDataTaskSection = Boolean(document.getElementById("data-task-status"));

    if (hasDataTaskSection) {
        fetchDataTaskStatus().then(payload => {
            const state = resolveDataTaskState(payload);
            if (state && (state.status === "running" || state.status === "cancelling")) {
                if (!dataTaskUIState.poller) {
                    dataTaskUIState.poller = setInterval(fetchDataTaskStatus, 2000);
                }
            }
        });
    }

    // 🔄 전체 재정리 이벤트 연결
    const refreshStartBtn = document.getElementById("refresh-start-btn");
    const refreshCancelBtn = document.getElementById("refresh-cancel");
    const refreshCloseBtn = document.getElementById("refresh-close");
    const refreshCloseBtn2 = document.getElementById("refresh-close-btn");
    const refreshRetryBtn = document.getElementById("refresh-retry");

    setupRefreshLogControls();

    if (refreshStartBtn) {
        refreshStartBtn.addEventListener("click", startRefreshTask);
        fetchRefreshStatus().then(state => {
            if (state?.status === "running") {
                openRefreshModal();
                if (!refreshUIState.poller) {
                    refreshUIState.poller = setInterval(fetchRefreshStatus, 2000);
                }
            } else {
                setRefreshButtonDisabled(state?.status === "running");
            }
        });
    }
    if (refreshCancelBtn) refreshCancelBtn.addEventListener("click", cancelRefreshTask);
    if (refreshRetryBtn) refreshRetryBtn.addEventListener("click", () => {
        startRefreshTask();
    });
    if (refreshCloseBtn) refreshCloseBtn.addEventListener("click", closeRefreshModal);
    if (refreshCloseBtn2) refreshCloseBtn2.addEventListener("click", closeRefreshModal);

    if (!hasSearchForm) {
        return;
    }

    results = window.searchResults || [];

    compareState.modal = document.getElementById("compare-modal");
    compareState.canvas = document.getElementById("compare-canvas");
    compareState.img1 = document.getElementById("compare-image-1");
    compareState.img2 = document.getElementById("compare-image-2");
    compareState.orientationButtons = [
        document.getElementById("compare-orientation-horizontal"),
        document.getElementById("compare-orientation-vertical"),
    ].filter(Boolean);

    const expandToggleBtn = document.getElementById("modal-expand-toggle");
    if (expandToggleBtn) {
        expandToggleBtn.addEventListener("click", toggleModalExpanded);
    }

    compareState.orientationButtons.forEach(btn => {
        btn.addEventListener("click", () => setCompareOrientation(btn.dataset.orientation || "horizontal"));
    });

    document.getElementById("compare-close")?.addEventListener("click", closeCompareModal);
    if (compareState.modal) {
        compareState.modal.addEventListener("click", (e) => {
            if (e.target === compareState.modal) closeCompareModal();
        });
    }
    setCompareOrientation(compareState.lastOrientation);

    initializeSelectionUI();

    collectionState.filterSummary = document.getElementById("collection-filter-summary");
    collectionState.filterSearchInput = document.getElementById("collection-filter-search");
    collectionState.filterClearBtn = document.getElementById("collection-filter-clear");
    collectionState.filterChipList = document.getElementById("collection-chip-list");
    collectionState.hiddenInputs = document.getElementById("collection-hidden-inputs");
    collectionState.addSelect = document.getElementById("add-to-collection-select");
    collectionState.renameSelect = document.getElementById("rename-collection-select");
    collectionState.deleteSelect = document.getElementById("delete-collection-select");
    collectionState.createParentSelect = document.getElementById("new-collection-parent");
    collectionState.renameParentSelect = document.getElementById("rename-parent-select");
    reloadCollections(window.initialData && (window.initialData.collection_ids || window.initialData.collection_id));

    // ✅ 초기 페이지네이션 렌더링
    if (window.initialData) {
        const initialState = { ...window.initialData, results };
        currentSearchState = initialState;
        renderPagination(initialState);
        updateResultCountDisplay(initialState);
        fetchTotalsForSearch(initialState);
    }

    galleryEl = document.querySelector(".gallery");
    if (galleryEl) {
        bindGalleryThumbs();
        refreshThumbIndices();
        galleryEl.addEventListener("pointerdown", startDragSelection);
        galleryEl.addEventListener("pointermove", onDragPointerMove);
        galleryEl.addEventListener("pointerup", endDragSelection);
        galleryEl.addEventListener("pointercancel", endDragSelection);
    }
    document.addEventListener("pointerup", endDragSelection);
    document.addEventListener("pointercancel", endDragSelection);

    // ✅ 설정 모달 열기
    document.getElementById("settings-btn")?.addEventListener("click", async function() {
        if (profileMenuState.open) {
            setProfileMenuOpen(false);
        }
        document.getElementById("settings-modal").style.display = "block";
        document.body.style.overflow = "hidden";
        loadEnvBasic();
    });
    initSettingsTabs();
    initEnvModeTabs();

    document.getElementById("env-server-save")?.addEventListener("click", () => {
        saveEnvBasicSection({
            containerId: "env-server-groups",
            statusId: "env-server-status",
            restartBannerId: "env-server-restart-banner",
        });
    });
    document.getElementById("env-engine-save")?.addEventListener("click", () => {
        saveEnvBasicSection({
            containerId: "env-engine-groups",
            statusId: "env-engine-status",
            restartBannerId: "env-engine-restart-banner",
        });
    });
    document.getElementById("env-tags-save")?.addEventListener("click", () => {
        saveEnvBasicSection({
            containerId: "env-tags-groups",
            statusId: "env-tags-status",
            restartBannerId: "env-tags-restart-banner",
        });
    });
    document.getElementById("env-raw-reload")?.addEventListener("click", () => loadEnvRaw({ force: true }));
    document.getElementById("env-raw-validate")?.addEventListener("click", validateEnvRaw);
    document.getElementById("env-raw-save")?.addEventListener("click", saveEnvRaw);
    document.querySelectorAll(".env-restart-button").forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.restartUrl || "/restart";
            window.location.href = target;
        });
    });

    document.getElementById("modal-prev")?.addEventListener("click", showPrevImage);
    document.getElementById("modal-next")?.addEventListener("click", showNextImage);
    document.getElementById("modal-close")?.addEventListener("click", hideModal);
    document.getElementById("show-exif")?.addEventListener("click", showExif);
    document.querySelector(".modal-delete-action")?.addEventListener("click", deleteImage);
    document.getElementById("settings-close")?.addEventListener("click", hideSettingsModal);
    document.getElementById("restart-form")?.addEventListener("submit", () => {
        showRestarting();
    });
    document.getElementById("scrollTopBtn")?.addEventListener("click", scrollToTop);

    // ✅ 모달 이미지 클릭 → 새 창 열기
    document.getElementById("modal-image")?.addEventListener("click", function () {
        if (currentImagePath) window.open("/img?path=" + currentImagePath, "_blank");
    });

    // ✅ scroll to top button
    window.onscroll = function () {
        const btn = document.getElementById("scrollTopBtn");
        if (document.body.scrollTop > 200 || document.documentElement.scrollTop > 200) {
            btn.style.display = "block";
        } else {
            btn.style.display = "none";
        }
    };

    // ✅ autocomplete
    const input = document.getElementById("search-input");
    const box = document.getElementById("autocomplete-box");
    let activeIndex = -1;
    const matchInput = document.getElementById("search-match-input");
    const tagSourceInput = document.getElementById("search-tag-source");
    const tagSourceButtons = Array.from(document.querySelectorAll(".search-toggle .toggle-btn[data-tag-source]"));
    const matchButtons = Array.from(document.querySelectorAll(".search-toggle .toggle-btn[data-match]"));

    function normalizeBooruQueryValue(raw) {
        return raw
            .split(",")
            .map(token => normalizeBooruTagInput(token))
            .filter(Boolean)
            .join(", ");
    }

    function updateSearchPlaceholder(tagSource) {
        if (!input) return;
        if (tagSource === "booru") {
            input.placeholder = "예: 1girl, rating:general";
        } else {
            input.placeholder = "예: cyberpunk, 1girl";
        }
    }

    function setActiveButtons(buttons, activeValue, dataKey) {
        buttons.forEach(btn => {
            const value = btn.dataset[dataKey];
            btn.classList.toggle("active", value === activeValue);
        });
    }

    function applySearchMode({ tagSource, matchMode }, options = {}) {
        const resolvedTagSource = tagSource || tagSourceInput?.value || "prompt";
        const resolvedMatch = matchMode || matchInput?.value || "and";
        if (matchInput) matchInput.value = resolvedMatch;
        if (tagSourceInput) tagSourceInput.value = resolvedTagSource;
        setActiveButtons(tagSourceButtons, resolvedTagSource, "tagSource");
        setActiveButtons(matchButtons, resolvedMatch, "match");
        updateSearchPlaceholder(resolvedTagSource);
        if (options.normalize && resolvedTagSource === "booru" && input?.value) {
            input.value = normalizeBooruQueryValue(input.value);
        }
        box.style.display = "none";
        box.innerHTML = "";
    }

    tagSourceButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            applySearchMode({ tagSource: btn.dataset.tagSource }, { normalize: true });
        });
    });

    matchButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            applySearchMode({ matchMode: btn.dataset.match }, { normalize: false });
        });
    });

    applySearchMode({
        tagSource: tagSourceInput?.value || "prompt",
        matchMode: matchInput?.value || "and",
    });

    input.addEventListener("input", async function () {
        const val = this.value;
        const last = val.split(',').pop().trim();
        if (last.length < 1) return box.style.display = "none";

        const tagSource = tagSourceInput?.value || "prompt";
        let suggestions = [];
        if (tagSource === "booru") {
            const normalized = normalizeBooruTagInput(last);
            if (!normalized) return box.style.display = "none";
            const res = await fetch(`/api/booru/tags?q=${encodeURIComponent(normalized)}&limit=30`);
            const data = await res.json().catch(() => ({}));
            suggestions = (Array.isArray(data.items) ? data.items : []).map(item => item.tag);
        } else {
            const res = await fetch("/autocomplete?q=" + encodeURIComponent(last));
            suggestions = await res.json();
        }

        if (suggestions.length === 0) {
            box.style.display = "none";
            return;
        }

        const rect = this.getBoundingClientRect();
        box.style.left = rect.left + "px";
        box.style.top = (rect.bottom + window.scrollY) + "px";
        box.innerHTML = "";
        box.style.display = "block";

        suggestions.forEach((tag) => {
            const div = document.createElement("div");
            div.textContent = tag;
            div.classList.add("autocomplete-item");
            div.addEventListener("click", () => {
                let parts = val.split(",");
                parts[parts.length - 1] = " " + tag;
                input.value = parts.join(", ").trim() + ", ";
                box.style.display = "none";
                input.focus();
            });
            box.appendChild(div);
        });

        activeIndex = -1;
    });

    document.addEventListener("keydown", function (e) {
        const items = box.querySelectorAll(".autocomplete-item");
        if (box.style.display === "block" && items.length > 0) {
            if (e.key === "ArrowDown") {
                activeIndex = (activeIndex + 1) % items.length;
                highlight();
                e.preventDefault();
            } else if (e.key === "ArrowUp") {
                activeIndex = (activeIndex - 1 + items.length) % items.length;
                highlight();
                e.preventDefault();
            } else if (e.key === "Enter" && activeIndex >= 0) {
                items[activeIndex].click();
                e.preventDefault();
            }
        }
    });

    function highlight() {
        const items = box.querySelectorAll(".autocomplete-item");
        items.forEach((item, idx) => {
            item.style.backgroundColor = idx === activeIndex ? "#ddd" : "";
        });
    }

    document.addEventListener("click", (e) => {
        if (!box.contains(e.target) && e.target !== input) box.style.display = "none";
    });

    // ✅ AJAX 검색 + 페이지네이션
    const form = document.getElementById("search-form");
    const gallery = document.querySelector(".gallery");
    const mediaInput = form ? form.querySelector('input[name="media"]') : null;

    form?.addEventListener("submit", () => {
        const tagSource = tagSourceInput?.value || "prompt";
        if (tagSource === "booru" && input?.value) {
            input.value = normalizeBooruQueryValue(input.value);
        }
    });

    const loader = document.createElement("div");
    loader.textContent = "🔄 로딩 중...";
    loader.style.textAlign = "center";
    loader.style.padding = "10px";
    loader.style.fontSize = "16px";
    loader.style.display = "none";
    gallery.parentNode.insertBefore(loader, gallery);

    function setActiveMediaTab(mediaValue) {
        const target = (mediaValue || "images").toLowerCase();
        document.querySelectorAll(".media-link[data-media]").forEach((link) => {
            const linkMedia = (link.dataset.media || "").toLowerCase();
            const isDraftGroup = target.startsWith("draft");
            const matches = linkMedia === target || (isDraftGroup && linkMedia === "drafts");
            link.classList.toggle("active", matches);
        });
        if (mediaInput) {
            mediaInput.value = target;
        }
    }
    setActiveMediaTab(window.initialData?.media || mediaInput?.value || "images");

    function updateMediaLinks(data) {
        if (!data) return;
        const links = document.querySelectorAll(".media-link[data-media]");
        if (!links.length) return;
        links.forEach((link) => {
            const targetMedia = (link.dataset.media || "").toLowerCase();
            if (!targetMedia) return;
            const params = buildSearchParamsFromData({ ...data, media: targetMedia, page: 1 });
            link.href = `?${params.toString()}`;
        });
    }
    updateMediaLinks(window.initialData);

    const randomBtn = document.getElementById("random-recommend");
    const randomContinueBtn = document.getElementById("random-continue");
    const randomTopBtn = document.getElementById("random-recommend-top");
    async function fetchRandomRecommendation(triggerBtn) {
        const btn = triggerBtn || randomBtn || randomContinueBtn;
        const originalLabel = btn ? btn.textContent : "";
        if (btn) {
            btn.disabled = true;
            btn.textContent = "🎲 선택 중...";
        }
        try {
            const mediaInput = form ? form.querySelector('input[name="media"]') : null;
            const preferredMedia = mediaInput ? mediaInput.value : "images";
            const res = await fetch(`/api/random_media?media=${encodeURIComponent(preferredMedia || "images")}`);
            const data = await res.json();
            if (!res.ok || !data || !data.item) {
                const errMsg = (data && data.error) ? data.error : "랜덤 추천 실패";
                throw new Error(errMsg);
            }
            currentImageIndex = -1;
            showModal(data.item);
        } catch (error) {
            console.error("랜덤 추천 실패", error);
            showToast(`❌ 랜덤 추천 실패: ${error.message || error}`);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalLabel || btn.textContent;
            }
        }
    }
    randomBtn?.addEventListener("click", () => fetchRandomRecommendation(randomBtn));
    randomContinueBtn?.addEventListener("click", () => fetchRandomRecommendation(randomContinueBtn));
    randomTopBtn?.addEventListener("click", () => fetchRandomRecommendation(randomTopBtn));

    const filterPanelBackdrop = document.getElementById("filter-panel");
    const openFilterBtn = document.getElementById("open-filter-panel");
    const openFilterSecondaryBtn = document.getElementById("open-filter-panel-secondary");
    const closeFilterBtn = document.getElementById("close-filter-panel");
    const clearActiveFiltersBtn = document.getElementById("clear-active-filters");

    function openFilterPanel() {
        if (filterPanelBackdrop) {
            filterPanelBackdrop.classList.add("open");
            filterPanelBackdrop.setAttribute("aria-hidden", "false");
        }
    }

    function closeFilterPanel() {
        if (filterPanelBackdrop) {
            filterPanelBackdrop.classList.remove("open");
            filterPanelBackdrop.setAttribute("aria-hidden", "true");
        }
    }

    [openFilterBtn, openFilterSecondaryBtn].forEach(btn => btn?.addEventListener("click", openFilterPanel));
    closeFilterBtn?.addEventListener("click", closeFilterPanel);
    filterPanelBackdrop?.addEventListener("click", (e) => {
        if (e.target === filterPanelBackdrop) closeFilterPanel();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && filterPanelBackdrop?.classList.contains("open")) {
            closeFilterPanel();
        }
    });
    clearActiveFiltersBtn?.addEventListener("click", () => {
        if (!form) return;
        modelChipState.selected.clear();
        syncModelHiddenInputs();
        renderModelChips(document.getElementById("model-filter-search")?.value || "");

        collectionState.selectedIds = [];
        syncCollectionHiddenInputs();
        updateCollectionFilterSummary();
        renderCollectionChips(collectionState.filterSearchInput?.value || "");

        const samplerInput = document.getElementById("sampler-input");
        const seedInput = document.getElementById("seed-input");
        const stepsInput = document.getElementById("steps-input");
        if (samplerInput) samplerInput.value = "";
        if (seedInput) seedInput.value = "";
        if (stepsInput) stepsInput.value = "";
        syncModelCategorySelection("");

        const params = new URLSearchParams(new FormData(form));
        params.set("include_total", "0");
        params.delete("model_category_id");
        applyCompactParam(params);
        applyOffsetParam(params);
        fetchResults(`/api/search?${params.toString()}`);
    });

    const collectionPanel = document.getElementById("collection-panel");
    const collectionTab = document.getElementById("collection-manager-tab");
    const openCollectionBtn = document.getElementById("open-collection-panel");
    const closeCollectionBtn = document.getElementById("close-collection-panel");
    const createCollectionBtn = document.getElementById("create-collection-btn");
    const renameCollectionBtn = document.getElementById("rename-collection-btn");
    const deleteCollectionBtn = document.getElementById("delete-collection-btn");

    function openCollectionPanel() {
        if (collectionPanel) collectionPanel.style.display = "flex";
    }
    function closeCollectionPanel() {
        if (collectionPanel) collectionPanel.style.display = "none";
    }
    [collectionTab, openCollectionBtn].forEach(btn => btn?.addEventListener("click", e => { e.preventDefault(); openCollectionPanel(); }));
    closeCollectionBtn?.addEventListener("click", closeCollectionPanel);
    collectionPanel?.addEventListener("click", (e) => { if (e.target === collectionPanel) closeCollectionPanel(); });

    async function handleCreateCollection() {
        const nameInput = document.getElementById("new-collection-name");
        const name = (nameInput?.value || "").trim();
        const parentId = collectionState.createParentSelect ? collectionState.createParentSelect.value : "";
        if (!name) return showToast("이름을 입력하세요.", "error");
        try {
            const res = await fetch("/api/collections", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, parent_id: parentId })
            });
            const data = await res.json();
            if (res.ok) {
                showToast("✅ 모음집이 생성되었습니다.");
                nameInput.value = "";
                if (collectionState.createParentSelect) collectionState.createParentSelect.value = "";
                await reloadCollections(data.id);
            } else {
                showToast(data.error || "생성 실패", "error");
            }
        } catch (err) {
            showToast(err.message || "생성 실패", "error");
        }
    }

    async function handleRenameCollection() {
        const targetId = collectionState.renameSelect ? collectionState.renameSelect.value : "";
        const newName = (document.getElementById("rename-collection-name")?.value || "").trim();
        const parentId = collectionState.renameParentSelect ? collectionState.renameParentSelect.value : "";
        if (!targetId) return showToast("대상 모음집을 선택하세요.", "error");
        if (!newName) return showToast("새 이름을 입력하세요.", "error");
        try {
            const res = await fetch(`/api/collections/${targetId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: newName, parent_id: parentId })
            });
            const data = await res.json();
            if (res.ok) {
                showToast("✅ 이름을 변경했습니다.");
                document.getElementById("rename-collection-name").value = "";
                await reloadCollections(targetId);
            } else {
                showToast(data.error || "변경 실패", "error");
            }
        } catch (err) {
            showToast(err.message || "변경 실패", "error");
        }
    }

    async function handleDeleteCollection() {
        const targetId = collectionState.deleteSelect ? collectionState.deleteSelect.value : "";
        if (!targetId) return showToast("삭제할 모음집을 선택하세요.", "error");
        if (!confirm("정말 삭제하시겠습니까?")) return;
        try {
            const res = await fetch(`/api/collections/${targetId}`, { method: "DELETE" });
            const data = await res.json();
            if (res.ok) {
                showToast("🗑 모음집을 삭제했습니다.");
                await reloadCollections("");
                applyCollectionFilter([]);
            } else {
                showToast(data.error || "삭제 실패", "error");
            }
        } catch (err) {
            showToast(err.message || "삭제 실패", "error");
        }
    }

    createCollectionBtn?.addEventListener("click", handleCreateCollection);
    renameCollectionBtn?.addEventListener("click", handleRenameCollection);
    deleteCollectionBtn?.addEventListener("click", handleDeleteCollection);

    function applyCollectionFilter(selectedIds) {
        syncCollectionSelections(selectedIds);
        const params = new URLSearchParams(new FormData(form));
        params.set("include_total", "0");
        applyCompactParam(params);
        applyOffsetParam(params);
        fetchResults(`/api/search?${params.toString()}`);
    }

    syncModelCategorySelection(window.initialData && window.initialData.model_category_id);
    syncFilterLogicFromState(window.initialData);

    initModelChipFilter();
    initCollectionFilter();

    function buildSearchParamsFromData(data, options = {}) {
        const params = new URLSearchParams();
        params.set("q", data.query || "");
        params.set("match", data.match || "and");
        params.set("tag_source", data.tag_source || "prompt");
        params.set("sort", data.sort || "desc");
        params.set("limit", data.limit ?? "");
        params.set("page", data.page ?? 1);
        (Array.isArray(data.models) ? data.models : []).forEach(m => params.append("model", m));
        params.set("model_match", data.model_match || "and");
        if (data.sampler) params.set("sampler", data.sampler);
        if (data.seed || data.seed === 0) params.set("seed", data.seed);
        if (data.steps || data.steps === 0) params.set("steps", data.steps);
        params.set("media", data.media || "images");
        (Array.isArray(data.collection_ids) ? data.collection_ids : (data.collection_id ? [data.collection_id] : []))
            .forEach(id => params.append("collection_id", id));
        params.set("collection_match", data.collection_match || "and");
        if (data.model_category_id) params.set("model_category_id", data.model_category_id);
        if (options.cursor) params.set("cursor", JSON.stringify(options.cursor));
        applyOffsetParam(params, options.useOffset !== false);
        if (options.includeTotal !== undefined) {
            params.set("include_total", options.includeTotal ? "1" : "0");
        } else {
            params.set("include_total", "0");
        }
        applyCompactParam(params);
        return params;
    }

    function buildSearchKey(data) {
        const collectionIds = (Array.isArray(data.collection_ids) ? data.collection_ids : (data.collection_id ? [data.collection_id] : []))
            .map(String)
            .sort();
        return JSON.stringify({
            query: data.query || "",
            match: data.match || "and",
            tag_source: data.tag_source || "prompt",
            sort: data.sort || "desc",
            limit: data.limit ?? "",
            models: Array.isArray(data.models) ? data.models : [],
            model_match: data.model_match || "and",
            sampler: data.sampler || "",
            seed: data.seed ?? "",
            steps: data.steps ?? "",
            media: data.media || "images",
            collection_ids: collectionIds,
            collection_match: data.collection_match || "and",
            model_category_id: data.model_category_id || "",
        });
    }

    function getSearchDataFromParams(params) {
        return {
            query: params.get("q") || "",
            match: params.get("match") || "and",
            tag_source: params.get("tag_source") || "prompt",
            sort: params.get("sort") || "desc",
            limit: params.get("limit") ?? "",
            page: Number(params.get("page") || 1),
            models: params.getAll("model"),
            model_match: params.get("model_match") || "and",
            sampler: params.get("sampler") || "",
            seed: params.get("seed") ?? "",
            steps: params.get("steps") ?? "",
            media: params.get("media") || "images",
            collection_ids: params.getAll("collection_id"),
            collection_match: params.get("collection_match") || "and",
            model_category_id: params.get("model_category_id") || "",
        };
    }

    function shouldFetchTotals(data) {
        const searchKey = buildSearchKey(data);
        return !totalCache.has(searchKey);
    }

    function shouldSkipTotalsForSearch(data) {
        const query = (data?.query ?? data?.q ?? "").trim();
        if (query) return false;
        const mediaType = (data?.media || "all").toLowerCase();
        if (mediaType.startsWith("draft")) return false;
        const hasFilters = Boolean(
            (Array.isArray(data?.models) && data.models.length) ||
            (Array.isArray(data?.collection_ids) && data.collection_ids.length) ||
            (data?.model_category_id ?? "") ||
            (data?.sampler ?? "").trim() ||
            (data?.seed ?? "").toString().trim() ||
            (data?.steps ?? "").toString().trim()
        );
        if (hasFilters) return false;
        return Boolean(window.initialData?.large_dataset);
    }

    function applyTotalsToData(target, totals) {
        if (!totals || !target) return;
        target.total_results = totals.total_results;
        target.total_pages = totals.total_pages;
        if (totals.videos_total !== undefined) {
            target.videos_total = totals.videos_total;
        }
    }

    function updateResultCountDisplay(data) {
        const totalInfo = document.getElementById("result-count") || document.querySelector("h2");
        if (!totalInfo) return;
        const mediaType = (data.media || "images").toLowerCase();
        const isDraft = mediaType.startsWith("draft");
        const isAll = mediaType === "all";
        const isVideos = mediaType === "videos";
        const isImagesOnly = mediaType === "images" || isDraft;
        const hasTotal = data.total_results !== null && data.total_results !== undefined;
        const resultCount = Array.isArray(data.results) ? data.results.length : 0;
        if (hasTotal) {
            const imgCount = isVideos ? 0 : (isAll ? (data.total_results - data.videos_total) : data.total_results);
            const vidCount = isImagesOnly ? 0 : (isAll ? data.videos_total : data.total_results);
            const combined = imgCount + vidCount;
            totalInfo.textContent = `결과 ${combined}개 (🖼️ ${imgCount}개 / 🎞 ${vidCount}개)`;
        } else if (resultCount > 0) {
            totalInfo.textContent = "총계 계산 중...";
        } else {
            totalInfo.textContent = "검색 결과가 없습니다. (🖼️ 0개 / 🎞 0개)";
        }
    }

    async function fetchTotalsForSearch(data) {
        if (!data || !shouldFetchTotals(data)) return;
        const searchKey = buildSearchKey(data);
        if (shouldSkipTotalsForSearch(data)) {
            totalCache.set(searchKey, { skipped: true, total_results: null, total_pages: null });
            if (currentSearchState && buildSearchKey(currentSearchState) === searchKey) {
                currentSearchState.total_results = null;
                currentSearchState.total_pages = null;
                updateResultCountDisplay(currentSearchState);
                renderPagination(currentSearchState);
            }
            return;
        }
        const requestId = ++totalRequestToken;
        const params = buildSearchParamsFromData({ ...data, page: 1 }, { includeTotal: true, useOffset: true });
        try {
            const res = await fetch(`/api/search_total?${params.toString()}`);
            if (!res.ok) {
                return;
            }
            const payload = await res.json();
            if (requestId !== totalRequestToken) return;
            if (!currentSearchState || buildSearchKey(currentSearchState) !== searchKey) return;
            const totals = {
                total_results: payload.total_results,
                total_pages: payload.total_pages,
                videos_total: payload.videos_total ?? 0,
            };
            if (payload.total_state === "skipped") {
                totalCache.set(searchKey, { skipped: true, ...totals });
            } else {
                totalCache.set(searchKey, totals);
            }
            applyTotalsToData(currentSearchState, totals);
            updateResultCountDisplay(currentSearchState);
            renderPagination(currentSearchState);
            const urlParams = buildSearchParamsFromData(currentSearchState);
            history.replaceState(currentSearchState, "", `?${urlParams.toString()}`);
        } catch (error) {
            console.warn("총계 조회 실패:", error);
        }
    }

    function syncModelHiddenInputs() {
        const hiddenWrap = document.getElementById("model-hidden-inputs");
        if (!hiddenWrap) return;
        hiddenWrap.innerHTML = "";
        modelChipState.selected.forEach((name) => {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = "model";
            input.value = name;
            hiddenWrap.appendChild(input);
        });
    }

    function renderModelChips(filterText = "") {
        const chipList = document.getElementById("model-chip-list");
        if (!chipList) return;
        chipList.innerHTML = "";
        const keyword = (filterText || "").toLowerCase();
        const filtered = modelChipState.all.filter(name => name && name.toLowerCase().includes(keyword));

        if (!filtered.length) {
            const empty = document.createElement("div");
            empty.textContent = "일치하는 모델이 없습니다.";
            empty.className = "small-dimmed";
            chipList.appendChild(empty);
            return;
        }

        filtered.forEach(name => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = `model-chip${modelChipState.selected.has(name) ? " active" : ""}`;
            btn.dataset.value = name;
            btn.textContent = name;
            btn.addEventListener("click", () => {
                if (modelChipState.selected.has(name)) {
                    modelChipState.selected.delete(name);
                } else {
                    modelChipState.selected.add(name);
                }
                btn.classList.toggle("active");
                syncModelHiddenInputs();
            });
            chipList.appendChild(btn);
        });
    }

    function initModelChipFilter() {
        const chipList = document.getElementById("model-chip-list");
        if (!chipList) return;

        try {
            const rawModels = JSON.parse(chipList.dataset.models || "[]");
            modelChipState.all = Array.isArray(rawModels) ? rawModels : [];
        } catch (err) {
            console.warn("모델 목록을 불러오지 못했습니다.", err);
            modelChipState.all = [];
        }

        try {
            const preselected = JSON.parse(chipList.dataset.selected || "[]");
            modelChipState.selected = new Set(Array.isArray(preselected) ? preselected : []);
        } catch (err) {
            modelChipState.selected = new Set();
        }

        const searchInput = document.getElementById("model-filter-search");
        const clearBtn = document.getElementById("model-filter-clear");

        renderModelChips(searchInput?.value || "");
        syncModelHiddenInputs();

        searchInput?.addEventListener("input", (e) => {
            renderModelChips(e.target.value || "");
        });

        clearBtn?.addEventListener("click", () => {
            modelChipState.selected.clear();
            syncModelHiddenInputs();
            renderModelChips(searchInput?.value || "");
        });
    }

    function initCollectionFilter() {
        renderCollectionChips(collectionState.filterSearchInput?.value || "");
        updateCollectionFilterSummary();
        syncCollectionHiddenInputs();

        collectionState.filterSearchInput?.addEventListener("input", (e) => {
            renderCollectionChips(e.target.value || "");
        });

        collectionState.filterClearBtn?.addEventListener("click", () => {
            collectionState.selectedIds = [];
            syncCollectionHiddenInputs();
            updateCollectionFilterSummary();
            renderCollectionChips(collectionState.filterSearchInput?.value || "");
        });
    }

    function syncModelFilterFromState(models) {
        const next = Array.isArray(models) ? models : (models ? [models] : []);
        modelChipState.selected = new Set(next);
        syncModelHiddenInputs();
        const keyword = document.getElementById("model-filter-search")?.value || "";
        renderModelChips(keyword);
    }

    function syncFilterLogicFromState(data) {
        const modelMatchSelect = document.getElementById("model-match-select");
        const collectionMatchSelect = document.getElementById("collection-match-select");
        if (modelMatchSelect) {
            modelMatchSelect.value = data?.model_match || "and";
        }
        if (collectionMatchSelect) {
            collectionMatchSelect.value = data?.collection_match || "and";
        }
        if (matchInput && tagSourceInput) {
            matchInput.value = data?.match || "and";
            tagSourceInput.value = data?.tag_source || "prompt";
            setActiveButtons(tagSourceButtons, tagSourceInput.value, "tagSource");
            setActiveButtons(matchButtons, matchInput.value, "match");
            updateSearchPlaceholder(tagSourceInput.value);
        }
    }

    async function fetchResults(url) {
        try {
            loader.style.display = "block";

            const res = await fetch(url);
            const data = await res.json();

            data.models = Array.isArray(data.models) ? data.models : [];
            data.collection_ids = Array.isArray(data.collection_ids)
                ? data.collection_ids
                : (data.collection_id ? [data.collection_id] : []);
            data.model_match = data.model_match || "and";
            data.collection_match = data.collection_match || "and";
            data.tag_source = data.tag_source || "prompt";
            setActiveMediaTab(data.media);

            useOffsetPagination = true;
            const searchKey = buildSearchKey(data);
            if (searchKey !== lastSearchKey) {
                cursorHistory = new Map();
                lastSearchKey = searchKey;
            }
            applyCursorHints(data);

            if (data.total_results !== null && data.total_results !== undefined) {
                totalCache.set(searchKey, {
                    total_results: data.total_results,
                    total_pages: data.total_pages,
                    videos_total: data.videos_total ?? 0,
                });
            } else if (totalCache.has(searchKey)) {
                applyTotalsToData(data, totalCache.get(searchKey));
            }
            currentSearchState = data;

            // ✅ 총 결과 개수 업데이트
            updateResultCountDisplay(data);

            // ✅ 전역 데이터 갱신
            results = data.results;
            syncCollectionSelections(data.collection_ids || data.collection_id);
            syncModelFilterFromState(data.models);
            syncModelCategorySelection(data.model_category_id);
            syncFilterLogicFromState(data);

            // ✅ 갤러리 렌더링
            disableSelectionMode();
            gallery.innerHTML = "";
            results.forEach((item, index) => {
                const thumbEl = createThumbElement(item, index);
                gallery.appendChild(thumbEl);
            });
            refreshThumbIndices();

            // ✅ 페이지네이션 갱신
            renderPagination(data);

            // ✅ URL 업데이트 (History API)
            const urlParams = buildSearchParamsFromData(data);
            history.pushState(data, "", `?${urlParams.toString()}`);
            updateMediaLinks(data);
            fetchTotalsForSearch(data);
        } catch (error) {
            console.error("❌ 검색 실패:", error);
        } finally {
            loader.style.display = "none";
        }
    }

    function applyCursorHints(data) {
        if (!data || useOffsetPagination) return;
        const pageNum = Number(data.page) || 1;
        if (pageNum > 1 && data.prev_cursor) {
            cursorHistory.set(pageNum - 1, data.prev_cursor);
        }
        if (data.next_cursor) {
            cursorHistory.set(pageNum, data.next_cursor);
        }
        const cursorMap = data.cursor_map;
        if (cursorMap && typeof cursorMap === "object") {
            Object.entries(cursorMap).forEach(([pageKey, cursorVal]) => {
                const hintPage = Number(pageKey);
                if (!Number.isNaN(hintPage) && hintPage > 0 && cursorVal) {
                    cursorHistory.set(hintPage, cursorVal);
                }
            });
        }
    }

    function renderPagination(data) {
        const { page, total_pages, query, match, sort, limit, models = [], sampler, seed, steps, media, collection_ids, model_category_id } = data;
        const totalsKnown = total_pages !== null && total_pages !== undefined;
        const totalPages = totalsKnown ? total_pages : 1;
        const resultCount = Array.isArray(data.results) ? data.results.length : 0;
        const paginationHTML = [];
        const isCursorMode = !useOffsetPagination;
        const cursorModeNote = "커서 기반 탐색 모드에서는 페이지 점프가 제한됩니다. 오프셋 모드를 켜면 페이지 번호 이동이 가능합니다.";

        const createBtnHTML = (text, p, disabled = false) =>
            `<button ${disabled ? "disabled" : ""} data-page="${p}">${text}</button>`;

        if (isCursorMode) {
            paginationHTML.push(`<span class="pagination-note">${cursorModeNote}</span>`);
        }

        if (!totalsKnown) {
            const canGoNext = useOffsetPagination
                ? (Number(limit) ? resultCount >= Number(limit) : resultCount > 0)
                : Boolean(data.next_cursor);
            paginationHTML.push(`<span class="pagination-note">부분 탐색 모드</span>`);
            paginationHTML.push(createBtnHTML("⬅ 이전", page - 1, page <= 1));
            paginationHTML.push(`<span class="pagination-current">${page}</span>`);
            paginationHTML.push(createBtnHTML("다음 ➡", page + 1, !canGoNext));
        } else if (isCursorMode) {
            const canGoNext = Boolean(data.next_cursor);
            paginationHTML.push(createBtnHTML("⬅ 이전", page - 1, page <= 1));
            paginationHTML.push(`<span class="pagination-current">페이지 ${page} / ${totalPages}</span>`);
            paginationHTML.push(createBtnHTML("다음 ➡", page + 1, !canGoNext));
        } else {
            paginationHTML.push(createBtnHTML("⏮ 처음", 1, page === 1));
            paginationHTML.push(createBtnHTML("⬅ 이전", page - 1, page === 1));

            // ✅ 새 로직: 6페이지 이상부터 밀기
            let start = 1;
            let end = Math.min(totalPages, 10);

            if (totalPages > 10) {
                if (page >= 6) {
                    start = page - 4; // 6페이지면 start=2
                    end = page + 5;   // 현재 페이지 뒤로 5개
                    if (end > totalPages) {
                        end = totalPages;
                        start = totalPages - 9; // 뒤쪽에서도 10개 유지
                    }
                }
            }

            for (let i = start; i <= end; i++) {
                paginationHTML.push(
                    `<a href="#" class="${i === page ? "active" : ""}" data-page="${i}">${i}</a>`
                );
            }

            paginationHTML.push(createBtnHTML("다음 ➡", page + 1, page === totalPages));
            paginationHTML.push(createBtnHTML("마지막 ⏭", totalPages, page === totalPages));
        }

        const html = paginationHTML.join("");

        ["pagination-top", "pagination-bottom"].forEach(id => {
            const container = document.getElementById(id);
            if (container) {
                container.innerHTML = html;
                container.querySelectorAll("[data-page]").forEach(el => {
                    el.addEventListener("click", async e => {
                        e.preventDefault();
                        const newPage = el.getAttribute("data-page");
                        const targetPageNum = Number(newPage) || 1;
                        let cursor = null;
                        applyCursorHints(data);
                        if (!useOffsetPagination && Math.abs(targetPageNum - page) > 1) {
                            showToast("커서 기반 탐색 모드에서는 페이지 점프가 제한됩니다.", "warning");
                            return;
                        }
                        if (!useOffsetPagination && targetPageNum > 1) {
                            cursor = cursorHistory.get(targetPageNum - 1) || null;
                            if (!cursor) {
                                showToast("커서 기반 탐색 모드에서는 페이지 점프가 제한됩니다.", "warning");
                                return;
                            }
                        }
                        const nextData = {
                            query,
                            match,
                            tag_source: data.tag_source,
                            sort,
                            limit,
                            page: newPage,
                            models,
                            model_match: data.model_match,
                            sampler,
                            seed,
                            steps,
                            media,
                            collection_ids,
                            collection_match: data.collection_match,
                            model_category_id,
                        };
                        const params = buildSearchParamsFromData(nextData, {
                            cursor,
                            useOffset: true,
                            includeTotal: false,
                        });
                        fetchResults(`/api/search?${params.toString()}`);
                    });
                });
            }
        });
    }

    const sortSelect = document.querySelector('select[name="sort"][form="search-form"], #search-form select[name="sort"]');
    const limitSelect = document.querySelector('select[name="limit"][form="search-form"], #search-form select[name="limit"]');
    [sortSelect, limitSelect].forEach(selectEl => {
        selectEl?.addEventListener("change", () => {
            if (!form) return;
            form.dispatchEvent(new Event("submit", { cancelable: true }));
        });
    });

    // ✅ 폼 서브밋 → AJAX
    form.addEventListener("submit", function (e) {
        e.preventDefault();
        closeFilterPanel();
        const params = new URLSearchParams(new FormData(form));
        params.set("include_total", "0");
        applyCompactParam(params);
        applyOffsetParam(params);
        fetchResults(`/api/search?${params.toString()}`);
    });

    // ✅ 뒤로가기/앞으로가기 지원
    window.addEventListener("popstate", e => {
            if (e.state) {
                results = e.state.results;
                useOffsetPagination = true;
                const searchKey = buildSearchKey(e.state);
                if (searchKey !== lastSearchKey) {
                    cursorHistory = new Map();
                    lastSearchKey = searchKey;
                }
                applyCursorHints(e.state);
                disableSelectionMode();
                gallery.innerHTML = "";
                syncCollectionSelections(e.state.collection_ids || e.state.collection_id);
                syncModelFilterFromState(e.state.models);
                syncModelCategorySelection(e.state.model_category_id);
                results.forEach((item, index) => {
                    const thumbEl = createThumbElement(item, index);
                    gallery.appendChild(thumbEl);
                });
                refreshThumbIndices();
                renderPagination(e.state);
                setActiveMediaTab(e.state.media);
                currentSearchState = e.state;
                updateResultCountDisplay(e.state);
                fetchTotalsForSearch(e.state);
            }
        });
});

// ✅ EXIF 보기 + 복사
let lastExifData = "";

function getExifTarget() {
    if (currentMediaType === "video") {
        return currentExifPath || "";
    }
    return currentExifPath || currentImagePath;
}

function showExif() {
    const exifTarget = getExifTarget();
    if (!exifTarget) {
        showToast("ℹ️ EXIF 정보를 확인할 수 없습니다.", "error");
        return;
    }
    fetch("/exif?path=" + encodeURIComponent(exifTarget))
        .then(res => res.text())
        .then(data => {
            const box = document.getElementById("exif-box");
            if (!data.trim()) {
                box.textContent = "ℹ️ EXIF 정보 없음";
                lastExifData = "";
                return;
            }
            box.innerHTML = "<strong>EXIF 정보:</strong><br>" + data;
            lastExifData = data;
        })
        .catch(err => {
            document.getElementById("exif-box").textContent = "❌ 오류: " + err;
            lastExifData = "";
        });
}

document.getElementById("copy-exif")?.addEventListener("click", function () {
    if (!lastExifData) {
        alert("ℹ️ 먼저 'EXIF 보기' 버튼을 눌러 정보를 불러오세요.");
        return;
    }
    const plainText = lastExifData.replace(/<[^>]*>?/gm, "");
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(plainText)
            .then(() => showToast("✅ EXIF 정보가 클립보드에 복사되었습니다."))
            .catch(err => showToast("❌ 복사 실패: " + err));
    } else {
        const textarea = document.createElement("textarea");
        textarea.value = plainText;
        document.body.appendChild(textarea);
        textarea.select();
        try {
            const successful = document.execCommand('copy');
            if (successful) {
                showToast("✅ EXIF 정보가 클립보드에 복사되었습니다.");
            } else {
                showToast("❌ 복사 실패");
            }
        } catch (err) {
            showToast("❌ 복사 실패: " + err);
        }
        textarea.remove();
    }
});

function scrollToTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
}

document.getElementById("clear-search")?.addEventListener("click", function () {
    const input = document.getElementById("search-input");
    input.value = "";
    input.focus();
    document.getElementById("autocomplete-box").style.display = "none";
});

document.getElementById("clear-history")?.addEventListener("click", function () {
    localStorage.removeItem('recentSearches');
    document.getElementById('search-history').innerHTML = '';
    alert("검색 기록이 삭제되었습니다.");
});

// 🔄 전체 재정리 상태 관리
const refreshUIState = {
    poller: null,
    lastState: null,
    logTailEnabled: true,
    lastToastKey: null,
};

function setupRefreshLogControls() {
    const tailBtn = document.getElementById("refresh-log-tail");
    const copyBtn = document.getElementById("refresh-log-copy");
    const logBox = document.getElementById("refresh-log");

    if (tailBtn) {
        updateLogTailButton(tailBtn, refreshUIState.logTailEnabled);
        tailBtn.addEventListener("click", () => {
            refreshUIState.logTailEnabled = !refreshUIState.logTailEnabled;
            updateLogTailButton(tailBtn, refreshUIState.logTailEnabled);
            scrollLogIfTail(logBox, refreshUIState.logTailEnabled);
        });
    }
    if (copyBtn) {
        copyBtn.addEventListener("click", () => {
            copyTextToClipboard(logBox?.textContent || "", {
                emptyMessage: "복사할 전체 재정리 로그가 없습니다.",
                successMessage: "✅ 전체 재정리 로그가 복사되었습니다.",
            });
        });
    }
}

function openRefreshModal() {
    const modal = document.getElementById("refresh-modal");
    if (modal) {
        modal.style.display = "block";
        document.body.style.overflow = "hidden";
    }
}

function closeRefreshModal() {
    const modal = document.getElementById("refresh-modal");
    if (modal) {
        modal.style.display = "none";
        document.body.style.overflow = "";
    }
}

function setRefreshButtonDisabled(disabled) {
    const btn = document.getElementById("refresh-start-btn");
    if (btn) {
        btn.disabled = disabled;
    }
}

function renderRefreshState(state) {
    refreshUIState.lastState = state;
    const statusLabel = document.getElementById("refresh-status-label");
    const progressBar = document.getElementById("refresh-progress-bar");
    const progressValue = document.getElementById("refresh-progress-value");
    const logBox = document.getElementById("refresh-log");
    const remainingEl = document.getElementById("refresh-remaining");
    const retryBtn = document.getElementById("refresh-retry");
    const cancelBtn = document.getElementById("refresh-cancel");

    const progress = Number(state?.progress ?? 0);
    const status = state?.status || "idle";
    const rawMessage = typeof state?.message === "string" ? state.message : "";
    // 특정 버전에서 'completed/failed...' 상태가 디스크에 남아있음을 매 요청마다 경고로 남기던 노이즈를 무시한다.
    // (사용자가 실제로 보고 싶은 로그/상태를 가리는 문제가 있어 UI에서는 표시하지 않는다.)
    const isLegacyStaleNotice = rawMessage.includes("이전 전체 재정리 작업 상태가");
    const message = isLegacyStaleNotice ? (status === "completed" ? "완료" : "") : (rawMessage || "대기 중");
    if (monitoringShellState.refreshStatusChip) {
        const progressLabel = status === "running" ? ` (${Math.round(progress)}%)` : "";
        monitoringShellState.refreshStatusChip.textContent = `Refresh: ${status}${progressLabel}`;
    }

    if (statusLabel) statusLabel.textContent = `${status.toUpperCase()} · ${message}`;
    if (progressBar) progressBar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
    if (progressValue) progressValue.textContent = `${Math.round(progress)}%`;
    if (remainingEl) {
        const remaining = state?.remaining_steps || [];
        remainingEl.textContent = remaining.length ? `남은 단계: ${remaining.join(" → ")}` : "";
    }

    if (logBox) {
        const lines = (state?.logs || [])
            .filter((entry) => {
                const msg = typeof entry?.message === "string" ? entry.message : "";
                return !msg.includes("이전 전체 재정리 작업 상태가");
            })
            .map(entry => {
            const d = entry?.ts ? new Date(entry.ts * 1000) : new Date();
            const ts = d.toLocaleTimeString();
            return `[${ts}] ${entry?.message || ""}`;
        });
        if (!lines.length && message) {
            const updatedAt = state?.updated_at ? new Date(state.updated_at * 1000) : new Date();
            lines.push(`[${updatedAt.toLocaleTimeString()}] ${message}`);
        }
        logBox.textContent = lines.join("\n") || "대기 중...";
        scrollLogIfTail(logBox, refreshUIState.logTailEnabled);
    }

    const isRunning = status === "running";
    if (cancelBtn) {
        cancelBtn.disabled = !isRunning;
        cancelBtn.textContent = isRunning ? "취소" : "취소됨";
    }
    if (retryBtn) {
        retryBtn.style.display = status === "failed" || status === "cancelled" ? "inline-block" : "none";
    }

    setRefreshButtonDisabled(isRunning);
    if (unifiedTaskLogState.logEl) {
        unifiedTaskLogState.pendingRefreshLog = null;
        syncUnifiedTaskLog();
    }
    updateUnifiedTaskProgress();

    if (!isRunning && refreshUIState.poller) {
        clearInterval(refreshUIState.poller);
        refreshUIState.poller = null;
    }

    if (!isRunning && status && status !== "idle" && status !== "running" && state) {
        const toastKey = `${status}|${state?.updated_at || ""}|${state?.message || ""}`;
        if (refreshUIState.lastToastKey !== toastKey) {
            refreshUIState.lastToastKey = toastKey;
            const type = status === "completed" ? "success" : "error";
            if (!isLegacyStaleNotice) {
                showToast(rawMessage || `상태: ${status}`, type === "success" ? "success" : "error");
            }
        }
    }
}

async function fetchRefreshStatus() {
    try {
        const res = await fetch("/refresh/status", { headers: { Accept: "application/json" } });
        const data = await res.json();
        renderRefreshState(data);
        return data;
    } catch (err) {
        console.error("refresh status error", err);
    }
}

async function startRefreshTask() {
    openRefreshModal();
    setRefreshButtonDisabled(true);
    setPendingRefreshLog(["전체 재정리 요청 중..."]);
    try {
        const params = new URLSearchParams({
            include_videos: getIncludeVideosValue() ? "1" : "0",
        });
        const res = await fetch("/refresh", {
            method: "POST",
            headers: {
                Accept: "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: params,
        });
        if (!res.ok) throw new Error("작업 시작 실패");
        const data = await res.json();
        renderRefreshState(data);
        if (!refreshUIState.poller) {
            refreshUIState.poller = setInterval(fetchRefreshStatus, 2000);
        }
    } catch (err) {
        console.error(err);
        showToast("❌ 전체 재정리 시작에 실패했습니다.", "error");
        setRefreshButtonDisabled(false);
    }
}

async function cancelRefreshTask() {
    try {
        const res = await fetch("/refresh/cancel", { method: "POST", headers: { Accept: "application/json" } });
        const data = await res.json();
        renderRefreshState(data);
    } catch (err) {
        showToast("❌ 취소 요청에 실패했습니다.", "error");
    }
}

function showRestarting() {
    document.getElementById('restart-msg').style.display = 'block';
    setTimeout(() => {
        window.close();
        window.location.href = "/restarting";
    }, 2000);
    return true;
}

document.getElementById("download-no-exif")?.addEventListener("click", async function () {
    if (currentMediaType === "video") {
        if (!currentImagePath) {
            showToast("ℹ️ 다운로드할 영상이 없습니다.", "error");
            return;
        }
        try {
            const response = await fetch(`/download_video?path=${encodeURIComponent(currentImagePath)}`);
            if (!response.ok) {
                const defaultMessage = "동영상 다운로드 실패";
                const bodyText = await response.text();
                let message = bodyText || defaultMessage;
                if (bodyText) {
                    try {
                        const payload = JSON.parse(bodyText);
                        message = payload?.reason || payload?.error || bodyText;
                    } catch (err) {
                        message = bodyText;
                    }
                }
                throw new Error(message);
            }
            const disposition = response.headers.get("Content-Disposition");
            let fileName = "download.mp4";
            if (disposition && disposition.includes("filename=")) {
                fileName = disposition.split("filename=")[1].replace(/"/g, "");
            }
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = fileName;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
            showToast(`✅ 동영상 다운로드 완료! 다운로드 파일: ${fileName}`);
        } catch (err) {
            const errorMessage = err?.message || String(err);
            showToast(errorMessage, "error");
        }
        return;
    }

    const exifTarget = getExifTarget();
    if (!exifTarget) {
        showToast("ℹ️ EXIF 제거 대상이 없습니다.", "error");
        return;
    }
    const isGifTarget = isGifFile(exifTarget);

    const newFileName = prompt("새 파일명을 입력하세요 (비워두면 랜덤 생성):", "");
    const params = new URLSearchParams({
        path: exifTarget,
        name: newFileName
    });
    const scalePayload = getDownloadScalePayload("modal-download-scale");
    if (scalePayload?.scale) {
        params.set("scale", String(scalePayload.scale));
    } else if (scalePayload?.ratio) {
        params.set("ratio", String(scalePayload.ratio));
    }

    try {
        const response = await fetch(`/remove_exif?${params.toString()}`);
        if (!response.ok) {
            const defaultMessage = isGifTarget ? "GIF 메타데이터 제거 실패" : "EXIF 제거 실패";
            const message = (await response.text()) || defaultMessage;
            throw new Error(message);
        }
        // ✅ 서버 응답 헤더에서 파일명 추출
        const disposition = response.headers.get("Content-Disposition");
        let fileName = "download.png";
        if (disposition && disposition.includes("filename=")) {
            fileName = disposition.split("filename=")[1].replace(/"/g, "");
        }
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = fileName; // 서버에서 받은 실제 파일명
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
        const successMessage = isGifTarget
            ? `✅ GIF 메타데이터 제거 완료! 다운로드 파일: ${fileName}`
            : `✅ EXIF 제거 완료! 다운로드 파일: ${fileName}`;
        showToast(successMessage);
    } catch (err) {
        const errorMessage = err?.message || String(err);
        showToast(errorMessage, "error");
    }
});

// ✅ 이미지 삭제 함수
async function deleteImage() {
    if (!currentImagePath) return;
    if (!confirm("정말 이 이미지를 삭제하시겠습니까?")) return;

    const formData = new URLSearchParams();
    formData.append("path", currentImagePath);

    const res = await fetch("/delete_image", {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: formData
    });

    const data = await res.json();
    if (data.success) {
        showToast("✅ 삭제 완료");
        hideModal();
        // 갤러리에서 썸네일 제거 및 인덱스 업데이트
        const targetThumb = getThumbElements().find(thumb => thumb.dataset.path === currentImagePath);
        if (targetThumb && targetThumb.parentNode) {
            targetThumb.parentNode.removeChild(targetThumb);
        }
        const removedIndex = results.findIndex(item => item.file === currentImagePath);
        if (removedIndex >= 0) {
            results.splice(removedIndex, 1);
            refreshThumbIndices();
        }
    } else {
        showToast("❌ 오류: " + data.error);
    }
}

function showToast(message, type = "success") {
    if (window.AppUtils && typeof window.AppUtils.showToast === "function") {
        window.AppUtils.showToast(message, type);
        return;
    }
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    const kind = type === "warning" || type === "error" || type === "info" ? type : "success";
    toast.className = `toast toast-${kind}`;
    toast.textContent = message;

    container.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("is-visible"));
    setTimeout(() => {
        toast.classList.remove("is-visible");
        toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    }, 3000);
}

function initDbAdminUI() {
    const card = document.getElementById("db-admin-card");
    if (!card) return;

    const tableList = document.getElementById("db-table-list");
    const tableFilter = document.getElementById("db-table-filter");
    const selectedTableEl = document.getElementById("db-selected-table");
    const schemaBody = document.querySelector("#db-schema-table tbody");
    const schemaEmpty = document.getElementById("db-schema-empty");
    const indexList = document.getElementById("db-index-list");
    const queryInput = document.getElementById("db-admin-query");
    const pageSizeInput = document.getElementById("db-admin-page-size");
    const orderBySelect = document.getElementById("db-admin-order-by");
    const orderDescToggle = document.getElementById("db-admin-order-desc");
    const compactToggle = document.getElementById("db-admin-compact");
    const pageInfo = document.getElementById("db-admin-page-info");
    const pagePrevBtn = document.getElementById("db-admin-page-prev");
    const pageNextBtn = document.getElementById("db-admin-page-next");
    const rowsTable = document.getElementById("db-rows-table");
    const rowsHead = rowsTable?.querySelector("thead");
    const rowsBody = rowsTable?.querySelector("tbody");
    const rowsEmpty = document.getElementById("db-rows-empty");
    const resultSummary = document.getElementById("db-admin-result-summary");
    const selectedCountEl = document.getElementById("db-admin-selected-count");
    const compactInfoEl = document.getElementById("db-admin-compact-info");
    const expertPanel = document.getElementById("db-admin-expert-panel");
    const expertStatus = document.getElementById("db-admin-expert-status");
    const deleteSelectedBtn = document.getElementById("db-admin-delete-selected");
    const truncateBtn = document.getElementById("db-admin-truncate");
    const assetFileInput = document.getElementById("db-admin-asset-file");
    const deleteFileToggle = document.getElementById("db-admin-delete-file");
    const deleteThumbToggle = document.getElementById("db-admin-delete-thumb");
    const assetDryRunBtn = document.getElementById("db-admin-asset-dry-run");
    const assetExecuteBtn = document.getElementById("db-admin-asset-execute");
    const sqlInput = document.getElementById("db-admin-sql-input");
    const sqlRunBtn = document.getElementById("db-admin-sql-run");
    const sqlClearBtn = document.getElementById("db-admin-sql-clear");
    const sqlStatusEl = document.getElementById("db-admin-sql-status");
    const sqlSummaryEl = document.getElementById("db-admin-sql-summary");
    const sqlTable = document.getElementById("db-admin-sql-table");
    const sqlHead = sqlTable?.querySelector("thead");
    const sqlBody = sqlTable?.querySelector("tbody");
    const sqlEmpty = document.getElementById("db-admin-sql-empty");

    const pageSizeDefault = Number.parseInt(card.dataset.pageSizeDefault || "50", 10) || 50;
    const pageSizeMax = Number.parseInt(card.dataset.pageSizeMax || "200", 10) || 200;
    const textTruncateLimit = Number.parseInt(card.dataset.textTruncateLimit || "200", 10) || 200;
    const writeEnabled = card.dataset.enableWrite === "true";

    let allTables = [];
    let filteredTables = [];
    let selectedTable = null;
    let schema = null;
    let rowsData = [];
    let primaryKeys = [];
    let hasRowid = false;
    let totalRows = 0;
    let page = 1;
    let pageSize = pageSizeDefault;

    const fetchJson = async (url, options = {}) => {
        const res = await fetch(url, {
            headers: { Accept: "application/json", ...options.headers },
            ...options,
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || payload?.ok === false) {
            const message = payload?.error || `요청 실패 (${res.status})`;
            throw new Error(message);
        }
        return payload;
    };

    const updateExpertState = () => {
        if (!writeEnabled) {
            if (expertPanel) {
                expertPanel.classList.add("disabled");
            }
            if (expertStatus) {
                expertStatus.textContent = "설정에서 쓰기가 비활성화됨";
            }
            if (deleteSelectedBtn) deleteSelectedBtn.disabled = true;
            if (truncateBtn) truncateBtn.disabled = true;
            if (assetDryRunBtn) assetDryRunBtn.disabled = true;
            if (assetExecuteBtn) assetExecuteBtn.disabled = true;
            return false;
        }
        if (expertPanel) {
            expertPanel.classList.remove("disabled");
        }
        if (expertStatus) {
            expertStatus.textContent = "항상 활성";
        }
        return true;
    };

    const refreshActionStates = () => {
        const expertReady = updateExpertState();
        const hasSelection = rowsBody?.querySelectorAll("input.db-row-select:checked").length > 0;
        if (deleteSelectedBtn) deleteSelectedBtn.disabled = !(expertReady && hasSelection);
        if (truncateBtn) truncateBtn.disabled = !(expertReady && selectedTable && schema?.can_truncate);
        const canAsset = expertReady && (assetFileInput?.value || "").trim().length > 0;
        if (assetDryRunBtn) assetDryRunBtn.disabled = !canAsset;
        if (assetExecuteBtn) assetExecuteBtn.disabled = !canAsset;
        const canSql = expertReady && (sqlInput?.value || "").trim().length > 0;
        if (sqlRunBtn) sqlRunBtn.disabled = !canSql;
        updateSummary();
    };

    const clearSqlResult = () => {
        if (sqlHead) sqlHead.innerHTML = "";
        if (sqlBody) sqlBody.innerHTML = "";
        if (sqlEmpty) sqlEmpty.textContent = "실행 결과가 없습니다.";
        if (sqlSummaryEl) sqlSummaryEl.textContent = "-";
        if (sqlStatusEl) sqlStatusEl.textContent = "대기";
    };

    const renderSqlResult = (result) => {
        if (!sqlHead || !sqlBody) return;
        sqlHead.innerHTML = "";
        sqlBody.innerHTML = "";
        const columns = result?.columns || [];
        const rows = result?.rows || [];
        if (!columns.length) {
            if (sqlSummaryEl) {
                const affected = Number(result?.affected_rows ?? 0);
                const label = Number.isFinite(affected) && affected >= 0 ? String(affected) : "-";
                sqlSummaryEl.textContent = `처리된 행: ${label}`;
            }
            if (sqlEmpty) sqlEmpty.textContent = "조회 결과가 없습니다.";
            return;
        }
        const headerRow = document.createElement("tr");
        columns.forEach((name) => {
            const th = document.createElement("th");
            th.textContent = name;
            headerRow.appendChild(th);
        });
        sqlHead.appendChild(headerRow);
        rows.forEach((row) => {
            const tr = document.createElement("tr");
            row.forEach((value) => {
                const td = document.createElement("td");
                td.textContent = value === null || value === undefined ? "-" : String(value);
                tr.appendChild(td);
            });
            sqlBody.appendChild(tr);
        });
        if (sqlSummaryEl) {
            const limit = Number(result?.row_limit ?? rows.length);
            sqlSummaryEl.textContent = `결과 ${rows.length}건 (최대 ${limit}건 표시)`;
        }
        if (sqlEmpty) sqlEmpty.textContent = rows.length ? "" : "조회 결과가 없습니다.";
    };

    const renderTableList = () => {
        if (!tableList) return;
        tableList.innerHTML = "";
        if (!filteredTables.length) {
            const empty = document.createElement("li");
            empty.className = "db-admin-empty";
            empty.textContent = "테이블이 없습니다.";
            tableList.appendChild(empty);
            return;
        }
        filteredTables.forEach((table) => {
            const item = document.createElement("li");
            item.textContent = `${table.name} (${table.row_count ?? "?"})`;
            if (table.name === selectedTable) item.classList.add("active");
            item.addEventListener("click", () => selectTable(table.name));
            tableList.appendChild(item);
        });
    };

    const applyTableFilter = () => {
        const keyword = (tableFilter?.value || "").trim().toLowerCase();
        if (!keyword) {
            filteredTables = [...allTables];
        } else {
            filteredTables = allTables.filter((item) => item.name?.toLowerCase().includes(keyword));
        }
        renderTableList();
    };

    const renderSchema = () => {
        if (!schemaBody || !schema) return;
        schemaBody.innerHTML = "";
        const columns = schema.columns || [];
        if (!columns.length) {
            if (schemaEmpty) schemaEmpty.textContent = "스키마 정보가 없습니다.";
        } else if (schemaEmpty) {
            schemaEmpty.textContent = "";
        }
        columns.forEach((col) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${col.name}</td>
                <td>${col.type || "-"}</td>
                <td>${col.pk ? "✔" : "-"}</td>
                <td>${col.notnull ? "✔" : "-"}</td>
                <td>${col.default ?? "-"}</td>
            `;
            schemaBody.appendChild(row);
        });
        if (indexList) {
            indexList.innerHTML = "";
            const indexes = schema.indexes || [];
            if (!indexes.length) {
                const li = document.createElement("li");
                li.textContent = "없음";
                indexList.appendChild(li);
            } else {
                indexes.forEach((idx) => {
                    const li = document.createElement("li");
                    const colLabel = (idx.columns || []).join(", ");
                    li.textContent = `${idx.name}${idx.unique ? " (UNIQUE)" : ""} · ${colLabel || "-"}`;
                    indexList.appendChild(li);
                });
            }
        }

        if (orderBySelect) {
            orderBySelect.innerHTML = '<option value="">자동</option>';
            const options = [...(schema.columns || [])].map((col) => col.name);
            if (schema.has_rowid) {
                options.unshift("__rowid__");
            }
            options.forEach((name) => {
                const option = document.createElement("option");
                option.value = name === "__rowid__" ? "rowid" : name;
                option.textContent = name;
                orderBySelect.appendChild(option);
            });
        }
    };

    const renderRows = () => {
        if (!rowsHead || !rowsBody) return;
        rowsHead.innerHTML = "";
        rowsBody.innerHTML = "";
        rowsData = rowsData || [];
        const headerRow = document.createElement("tr");
        const expertReady = updateExpertState();
        if (expertReady && writeEnabled) {
            const th = document.createElement("th");
            th.textContent = "";
            headerRow.appendChild(th);
        }
        (schema?.columns || []).forEach((col) => {
            const th = document.createElement("th");
            th.textContent = col.name;
            headerRow.appendChild(th);
        });
        if (schema?.has_rowid) {
            const th = document.createElement("th");
            th.textContent = "__rowid__";
            headerRow.appendChild(th);
        }
        rowsHead.appendChild(headerRow);

        if (!rowsData.length) {
            if (rowsEmpty) rowsEmpty.textContent = "데이터가 없습니다.";
            refreshActionStates();
            return;
        }
        rowsData.forEach((row, idx) => {
            const tr = document.createElement("tr");
            if (expertReady && writeEnabled) {
                const td = document.createElement("td");
                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.className = "db-row-select";
                checkbox.dataset.index = String(idx);
                checkbox.addEventListener("change", refreshActionStates);
                td.appendChild(checkbox);
                tr.appendChild(td);
            }
            (schema?.columns || []).forEach((col) => {
                const td = document.createElement("td");
                const value = row[col.name];
                td.textContent = value === null || value === undefined ? "-" : String(value);
                tr.appendChild(td);
            });
            if (schema?.has_rowid) {
                const td = document.createElement("td");
                td.textContent = row.__rowid__ ?? "-";
                tr.appendChild(td);
            }
            rowsBody.appendChild(tr);
        });
        refreshActionStates();
    };

    const updateSummary = () => {
        if (!resultSummary) return;
        if (!selectedTable) {
            resultSummary.textContent = "테이블을 선택하세요.";
            return;
        }
        if (totalRows === 0) {
            resultSummary.textContent = `${selectedTable} · 0건`;
        } else {
            const start = (page - 1) * pageSize + 1;
            const end = Math.min(page * pageSize, totalRows);
            resultSummary.textContent = `${selectedTable} · ${totalRows}건 (표시 ${start}-${end})`;
        }
        if (selectedCountEl) {
            const selectedCount = rowsBody?.querySelectorAll("input.db-row-select:checked").length || 0;
            selectedCountEl.textContent = selectedCount ? `선택 ${selectedCount}건` : "";
        }
    };

    const updatePagination = () => {
        if (pageInfo) {
            pageInfo.textContent = `${page} / ${Math.max(1, Math.ceil(totalRows / pageSize))}`;
        }
        if (pagePrevBtn) pagePrevBtn.disabled = page <= 1;
        if (pageNextBtn) pageNextBtn.disabled = page * pageSize >= totalRows;
        updateSummary();
    };

    const loadTables = async () => {
        try {
            const data = await fetchJson("/api/db/tables");
            allTables = Array.isArray(data.tables) ? data.tables : [];
            filteredTables = [...allTables];
            renderTableList();
        } catch (err) {
            if (tableList) {
                tableList.innerHTML = `<li class="db-admin-empty">테이블 로딩 실패: ${err?.message || err}</li>`;
            }
        }
    };

    const loadSchema = async () => {
        if (!selectedTable) return;
        try {
            const data = await fetchJson(`/api/db/table/${encodeURIComponent(selectedTable)}/schema`);
            schema = data.schema || null;
            primaryKeys = schema?.primary_keys || [];
            hasRowid = schema?.has_rowid || false;
            renderSchema();
        } catch (err) {
            schema = null;
            if (schemaEmpty) schemaEmpty.textContent = err?.message || "스키마 로딩 실패";
        }
    };

    const loadRows = async () => {
        if (!selectedTable) return;
        const params = new URLSearchParams();
        params.set("page", String(page));
        params.set("page_size", String(pageSize));
        if (queryInput?.value) params.set("q", queryInput.value.trim());
        if (orderBySelect?.value) params.set("order_by", orderBySelect.value);
        if (orderDescToggle?.checked === false) params.set("desc", "0");
        if (compactToggle?.checked === false) {
            params.set("compact", "0");
        } else {
            params.set("compact", "1");
        }
        try {
            const data = await fetchJson(`/api/db/table/${encodeURIComponent(selectedTable)}/rows?${params.toString()}`);
            rowsData = Array.isArray(data.rows) ? data.rows : [];
            totalRows = data.total || 0;
            renderRows();
            updatePagination();
            if (rowsEmpty) rowsEmpty.textContent = rowsData.length ? "" : "데이터가 없습니다.";
            if (compactInfoEl) {
                if (data.compact) {
                    const limit = data.text_truncate_limit || textTruncateLimit;
                    compactInfoEl.textContent = `긴 텍스트는 ${limit}자까지만 표시됩니다.`;
                } else {
                    compactInfoEl.textContent = "";
                }
            }
        } catch (err) {
            rowsData = [];
            totalRows = 0;
            renderRows();
            updatePagination();
            if (rowsEmpty) rowsEmpty.textContent = err?.message || "데이터 로딩 실패";
            if (compactInfoEl) compactInfoEl.textContent = "";
        }
    };

    const selectTable = async (tableName) => {
        selectedTable = tableName;
        page = 1;
        if (selectedTableEl) selectedTableEl.textContent = tableName;
        await loadSchema();
        await loadRows();
        refreshActionStates();
    };

    const collectSelectedRows = () => {
        const selected = [];
        rowsBody?.querySelectorAll("input.db-row-select:checked").forEach((input) => {
            const idx = Number.parseInt(input.dataset.index || "-1", 10);
            if (Number.isFinite(idx) && rowsData[idx]) {
                selected.push(rowsData[idx]);
            }
        });
        return selected;
    };

    const submitDeleteSelected = async () => {
        if (!selectedTable) return;
        const selectedRows = collectSelectedRows();
        if (!selectedRows.length) {
            showToast("선택된 레코드가 없습니다.", "warning");
            return;
        }
        if (!confirm("선택한 레코드를 삭제합니다. 진행할까요?")) return;
        const payload = {
            table: selectedTable,
            mode: "execute",
            confirm: true,
        };
        if (primaryKeys.length) {
            if (primaryKeys.length === 1) {
                payload.pks = selectedRows.map((row) => row[primaryKeys[0]]);
            } else {
                payload.pks = selectedRows.map((row) => {
                    const entry = {};
                    primaryKeys.forEach((key) => {
                        entry[key] = row[key];
                    });
                    return entry;
                });
            }
        } else if (hasRowid) {
            payload.rowids = selectedRows.map((row) => row.__rowid__);
        }
        try {
            const res = await fetch("/data/admin/delete-rows", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data?.error) {
                throw new Error(data?.error || `삭제 실패 (${res.status})`);
            }
            showToast("삭제 작업을 시작했습니다.", "success");
            await loadRows();
        } catch (err) {
            showToast(err?.message || "삭제 요청 실패", "error");
        }
    };

    const submitTruncate = async () => {
        if (!selectedTable) return;
        if (!confirm(`테이블 ${selectedTable} 을(를) 비웁니다. 진행할까요?`)) return;
        try {
            const res = await fetch("/data/admin/truncate", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify({ table: selectedTable, mode: "execute", confirm: true }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data?.error) {
                throw new Error(data?.error || `요청 실패 (${res.status})`);
            }
            showToast("테이블 비우기 작업을 시작했습니다.", "success");
            await loadRows();
        } catch (err) {
            showToast(err?.message || "요청 실패", "error");
        }
    };

    const submitAssetDelete = async (mode) => {
        const fileValue = (assetFileInput?.value || "").trim();
        if (!fileValue) {
            showToast("파일 경로를 입력하세요.", "warning");
            return;
        }
        if (mode === "execute" && !confirm("자산 안전 삭제를 실행합니다. 진행할까요?")) return;
        try {
            const res = await fetch("/data/admin/asset-delete", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify({
                    file: fileValue,
                    mode,
                    confirm: mode === "execute",
                    delete_file: deleteFileToggle?.checked || false,
                    delete_thumb: deleteThumbToggle?.checked || false,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data?.error) {
                throw new Error(data?.error || `요청 실패 (${res.status})`);
            }
            showToast(mode === "execute" ? "안전 삭제 작업을 시작했습니다." : "드라이런을 시작했습니다.", "success");
        } catch (err) {
            showToast(err?.message || "요청 실패", "error");
        }
    };

    const submitSql = async () => {
        const sql = (sqlInput?.value || "").trim();
        if (!sql) {
            showToast("SQL을 입력하세요.", "warning");
            return;
        }
        if (sqlStatusEl) sqlStatusEl.textContent = "실행 중...";
        if (sqlRunBtn) sqlRunBtn.disabled = true;
        try {
            const res = await fetch("/api/db/sql", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify({ sql, row_limit: 200 }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data?.ok === false) {
                throw new Error(data?.error || `요청 실패 (${res.status})`);
            }
            renderSqlResult(data.result || {});
            if (sqlStatusEl) sqlStatusEl.textContent = "완료";
            showToast("SQL 실행 완료", "success");
        } catch (err) {
            if (sqlStatusEl) sqlStatusEl.textContent = "실패";
            showToast(err?.message || "SQL 실행 실패", "error");
        } finally {
            refreshActionStates();
        }
    };

    tableFilter?.addEventListener("input", applyTableFilter);
    queryInput?.addEventListener("change", () => {
        page = 1;
        loadRows();
    });
    pageSizeInput?.addEventListener("change", () => {
        const value = Number.parseInt(pageSizeInput.value || String(pageSizeDefault), 10);
        pageSize = Math.max(1, Math.min(value, pageSizeMax));
        page = 1;
        loadRows();
    });
    orderBySelect?.addEventListener("change", () => {
        page = 1;
        loadRows();
    });
    orderDescToggle?.addEventListener("change", () => {
        page = 1;
        loadRows();
    });
    compactToggle?.addEventListener("change", () => {
        page = 1;
        loadRows();
    });
    pagePrevBtn?.addEventListener("click", () => {
        if (page > 1) {
            page -= 1;
            loadRows();
        }
    });
    pageNextBtn?.addEventListener("click", () => {
        const maxPage = Math.max(1, Math.ceil(totalRows / pageSize));
        if (page < maxPage) {
            page += 1;
            loadRows();
        }
    });
    deleteSelectedBtn?.addEventListener("click", submitDeleteSelected);
    truncateBtn?.addEventListener("click", submitTruncate);
    assetFileInput?.addEventListener("input", refreshActionStates);
    assetDryRunBtn?.addEventListener("click", () => submitAssetDelete("dry"));
    assetExecuteBtn?.addEventListener("click", () => submitAssetDelete("execute"));
    sqlInput?.addEventListener("input", refreshActionStates);
    sqlRunBtn?.addEventListener("click", submitSql);
    sqlClearBtn?.addEventListener("click", clearSqlResult);

    pageSizeInput.value = String(pageSize);
    updateExpertState();
    clearSqlResult();
    loadTables();
}

function initMonitoringShellUI() {
    const root = document.getElementById("monitoring-page");
    if (!root) return;

    // 🪟 활동 피드(요약) 카드를 제거하고, 그 자리에 모니터링 로그 카드를 배치한다.
    // (버전별로 DOM 구조/ID가 조금씩 달라질 수 있어 텍스트 기반 탐색도 함께 사용)
    const locateActivityCard = () => {
        const byId = document.getElementById("overviewActivityFeed")?.closest(".monitoring-card");
        if (byId) return byId;
        const cards = Array.from(root.querySelectorAll(".monitoring-card"));
        return cards.find((card) => {
            const title = (card.querySelector("h2")?.textContent || "").trim();
            return title.includes("활동 피드");
        });
    };

    const activityCard = locateActivityCard();
    const logCard = document.getElementById("monitoring-log-section")?.closest(".monitoring-card") || document.getElementById("monitoring-log-section");
    if (activityCard) {
        if (logCard && activityCard.parentElement) {
            activityCard.parentElement.insertBefore(logCard, activityCard);
        }
        activityCard.remove();
    }

    monitoringShellState.tabOverviewBtn = document.getElementById("tabOverviewBtn");
    monitoringShellState.tabAdminBtn = document.getElementById("tabAdminBtn");
    monitoringShellState.tabOverviewPanel = document.getElementById("tab-overview");
    monitoringShellState.tabAdminPanel = document.getElementById("tab-admin");
    initTaskStatusChips();
    monitoringShellState.logSection = document.getElementById("monitoring-log-section");
    monitoringShellState.activityFeedEl = document.getElementById("overviewActivityFeed");
    monitoringShellState.activityEmptyEl = document.getElementById("overviewActivityEmpty");
    monitoringShellState.activitySummaryEl = document.getElementById("overviewActivitySummary");

    const setTab = (tabName) => {
        monitoringShellState.currentTab = tabName;
        const isOverview = tabName === "overview";
        if (monitoringShellState.tabOverviewPanel) {
            monitoringShellState.tabOverviewPanel.hidden = !isOverview;
        }
        if (monitoringShellState.tabAdminPanel) {
            monitoringShellState.tabAdminPanel.hidden = isOverview;
        }
        if (monitoringShellState.tabOverviewBtn) {
            monitoringShellState.tabOverviewBtn.classList.toggle("active", isOverview);
            monitoringShellState.tabOverviewBtn.setAttribute("aria-selected", String(isOverview));
        }
        if (monitoringShellState.tabAdminBtn) {
            monitoringShellState.tabAdminBtn.classList.toggle("active", !isOverview);
            monitoringShellState.tabAdminBtn.setAttribute("aria-selected", String(!isOverview));
        }
        if (!isOverview && monitoringShellState.tabAdminPanel && !monitoringShellState.dbAdminInitialized) {
            initDbAdminUI();
            monitoringShellState.dbAdminInitialized = true;
        }
    };

    monitoringShellState.tabOverviewBtn?.addEventListener("click", () => setTab("overview"));
    monitoringShellState.tabAdminBtn?.addEventListener("click", () => setTab("admin"));

    const logViewAllBtn = document.getElementById("viewAllLogsBtn");
    if (logViewAllBtn) {
        logViewAllBtn.addEventListener("click", () => {
            if (monitoringShellState.logSection) {
                monitoringShellState.logSection.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    }

    setTab("overview");
    updateStatusStrip();
    setInterval(updateStatusStrip, 15000);
}

async function updateStatusStrip() {
    const now = new Date();
    if (monitoringShellState.lastUpdatedChip) {
        monitoringShellState.lastUpdatedChip.textContent = `Updated: ${now.toLocaleTimeString("ko-KR", { hour12: false })}`;
    }

    if (monitoringShellState.refreshStatusChip) {
        try {
            const refreshState = typeof fetchRefreshStatus === "function" ? await fetchRefreshStatus() : null;
            if (refreshState) {
                const progress = Number(refreshState?.progress ?? 0);
                const status = refreshState?.status || "idle";
                const progressLabel = status === "running" ? ` (${Math.round(progress)}%)` : "";
                monitoringShellState.refreshStatusChip.textContent = `Refresh: ${status}${progressLabel}`;
            } else {
                monitoringShellState.refreshStatusChip.textContent = "Refresh: ...";
            }
        } catch (err) {
            monitoringShellState.refreshStatusChip.textContent = "Refresh: ...";
        }
    }

    if (monitoringShellState.dataTaskStatusChip) {
        try {
            const res = await fetch("/data/status", { headers: { Accept: "application/json" } });
            const payload = await res.json();
            const activeTaskName = payload?.active_task || "none";
            const taskState = resolveDataTaskState(payload);
            if (taskState) {
                const statusLabel = taskState.status || "idle";
                const progress = Number(taskState.progress ?? 0);
                const progressLabel = taskState.status === "running" ? ` (${Math.round(progress)}%)` : "";
                monitoringShellState.dataTaskStatusChip.textContent = `Task: ${activeTaskName} ${statusLabel}${progressLabel}`;
            } else {
                monitoringShellState.dataTaskStatusChip.textContent = "Task: none";
            }
        } catch (err) {
            monitoringShellState.dataTaskStatusChip.textContent = "Task: ...";
        }
    }
}

function initMonitoringPage() {
    const root = document.getElementById("monitoring-page");
    if (!root) return;

    setupDataTaskUI();
    initMonitoringShellUI();

    const statusEl = document.getElementById("monitoring-status");
    const tableSummaryEl = document.getElementById("monitoring-table-summary");
    const tableBody = document.querySelector("#monitoring-table tbody");
    const emptyEl = document.getElementById("monitoring-empty");
    const logContainer = document.getElementById("monitoring-log");
    const logEmpty = document.getElementById("monitoring-log-empty");
    const logSummary = document.getElementById("monitoring-log-summary");
    const kpiTodayImagesEl = document.getElementById("kpi-today-images");
    const kpiLast24ImagesEl = document.getElementById("kpi-last24-images");
    const kpiIssuesCountEl = document.getElementById("kpi-issues-count");
    const kpiVideosCountEl = document.getElementById("kpi-videos-count");
    const kpiDbSizeEl = document.getElementById("kpi-db-size");
    const kpiDbPathEl = document.getElementById("kpi-db-path");
    const kpiTotalRecordsEl = document.getElementById("kpi-total-records");
    const kpiTableCountEl = document.getElementById("kpi-table-count");
    const kpiLastModifiedEl = document.getElementById("kpi-last-modified");

    const formatter = new Intl.NumberFormat("ko-KR");
    let pollTimer = null;
    let retryTimer = null;
    let lastFingerprint = "";
    const logEntries = [];
    const seenLogIds = new Set();
    let lastServerLogId = 0;
    let clientLogCounter = 0;
    const logLimit = 50;
    const activityLimit = 12;

    const renderActivityFeed = () => {
        const feedEl = monitoringShellState.activityFeedEl;
        if (!feedEl) return;
        const priority = { error: 0, warn: 1, success: 2, info: 3 };
        const ordered = logEntries
            .map((entry, idx) => ({ entry, idx }))
            .sort((a, b) => {
                const aPriority = priority[a.entry.level] ?? 4;
                const bPriority = priority[b.entry.level] ?? 4;
                if (aPriority !== bPriority) return aPriority - bPriority;
                return b.idx - a.idx;
            })
            .slice(0, activityLimit)
            .map(item => item.entry);

        feedEl.innerHTML = "";
        if (!ordered.length) {
            monitoringShellState.activityEmptyEl?.classList.remove("hidden");
            if (monitoringShellState.activitySummaryEl) {
                monitoringShellState.activitySummaryEl.textContent = "최근 이벤트 0건";
            }
            return;
        }

        monitoringShellState.activityEmptyEl?.classList.add("hidden");
        ordered.forEach((entry) => {
            const li = document.createElement("li");
            li.className = `activity-item ${entry.level}`;
            const level = document.createElement("span");
            level.className = "activity-level";
            level.textContent = entry.level || "info";
            const content = document.createElement("div");
            content.className = "activity-content";
            const time = document.createElement("div");
            time.className = "activity-time";
            time.textContent = entry.timeLabel;
            const message = document.createElement("div");
            message.className = "activity-message";
            message.textContent = entry.message;
            content.appendChild(time);
            content.appendChild(message);
            li.appendChild(level);
            li.appendChild(content);
            feedEl.appendChild(li);
        });
        if (monitoringShellState.activitySummaryEl) {
            monitoringShellState.activitySummaryEl.textContent = `최근 이벤트 ${logEntries.length}건`;
        }
    };

    const appendLog = (message, level = "info", options = {}) => {
        const logId = Number.isFinite(options?.id) ? options.id : null;
        if (logId && seenLogIds.has(logId)) return;
        const now = new Date();
        const timeLabel = options?.timeLabel || now.toLocaleTimeString("ko-KR");
        const sourceLabel = options?.source ? `[${options.source}] ` : "";
        const entryId = logId || `client-${++clientLogCounter}`;
        logEntries.push({ message: `${sourceLabel}${message}`, level, timeLabel, id: entryId });
        if (logId) {
            seenLogIds.add(logId);
            lastServerLogId = Math.max(lastServerLogId, logId);
        }
        if (logEntries.length > logLimit) logEntries.shift();
        if (!logContainer) return;
        logContainer.innerHTML = "";
        logEntries.forEach((entry) => {
            const row = document.createElement("div");
            row.className = `monitoring-log-entry ${entry.level}`;
            const timeEl = document.createElement("span");
            timeEl.className = "monitoring-log-time";
            timeEl.textContent = entry.timeLabel;
            const messageEl = document.createElement("span");
            messageEl.className = "monitoring-log-message";
            messageEl.textContent = entry.message;
            row.appendChild(timeEl);
            row.appendChild(messageEl);
            logContainer.appendChild(row);
        });
        if (logEmpty) logEmpty.style.display = logEntries.length ? "none" : "block";
        if (logSummary) logSummary.textContent = `최근 이벤트 ${logEntries.length}건`;
        logContainer.scrollTop = logContainer.scrollHeight;
        renderActivityFeed();
    };

    const mergeServerLogs = (serverLogs = []) => {
        if (!Array.isArray(serverLogs) || !serverLogs.length) return;
        serverLogs.forEach((entry) => {
            const logId = Number.isFinite(entry?.id) ? entry.id : null;
            if (logId && logId <= lastServerLogId) return;
            const message = entry?.message || "서버 로그 수신";
            const level = entry?.level || "info";
            let timeLabel;
            if (entry?.time) {
                const parsed = new Date(entry.time);
                if (!Number.isNaN(parsed.getTime())) {
                    timeLabel = parsed.toLocaleTimeString("ko-KR");
                }
            }
            appendLog(message, level, { timeLabel, source: "서버", id: logId });
        });
    };

    const formatBytes = (bytes) => {
        if (!Number.isFinite(bytes)) return "-";
        if (bytes < 1024) return `${formatter.format(bytes)} B`;
        const units = ["KB", "MB", "GB", "TB"];
        let value = bytes / 1024;
        let unitIndex = 0;
        while (value >= 1024 && unitIndex < units.length - 1) {
            value /= 1024;
            unitIndex += 1;
        }
        return `${value.toFixed(2)} ${units[unitIndex]}`;
    };

    const formatDateTime = (value) => {
        if (!value) return "-";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return date.toLocaleString("ko-KR");
    };

    const setKpiValue = (el, value, formatterFn) => {
        if (!el) return;
        if (value === null || value === undefined || Number.isNaN(value)) {
            el.textContent = "-";
            return;
        }
        el.textContent = formatterFn ? formatterFn(value) : String(value);
    };

    const renderTables = (tables = []) => {
        tableBody.innerHTML = "";
        if (!tables.length) {
            emptyEl?.classList.remove("hidden");
            if (emptyEl) {
                emptyEl.textContent = "표시할 테이블 정보가 없습니다.";
            }
            tableSummaryEl.textContent = "테이블 정보 없음";
            return;
        }
        emptyEl?.classList.add("hidden");
        const totalRecords = tables.reduce((sum, item) => {
            return sum + (Number.isFinite(item.row_count) ? item.row_count : 0);
        }, 0);
        tableSummaryEl.textContent = `총 ${tables.length}개 테이블 · ${formatter.format(totalRecords)}건`;
        tables.forEach((item) => {
            const row = document.createElement("tr");
            const nameCell = document.createElement("td");
            const countCell = document.createElement("td");
            nameCell.textContent = item.name || "-";
            countCell.textContent = Number.isFinite(item.row_count) ? formatter.format(item.row_count) : "알 수 없음";
            row.appendChild(nameCell);
            row.appendChild(countCell);
            tableBody.appendChild(row);
        });
    };

    const applySummary = (summary) => {
        const tables = Array.isArray(summary?.tables) ? summary.tables : [];
        const totalRecords = Number.isFinite(summary?.total_records)
            ? summary.total_records
            : tables.reduce((sum, item) => {
                return sum + (Number.isFinite(item.row_count) ? item.row_count : 0);
            }, 0);
        renderTables(tables);
        setKpiValue(kpiDbSizeEl, summary?.db_size_bytes ?? null, formatBytes);
        setKpiValue(kpiDbPathEl, summary?.db_path || "-", (value) => String(value));
        setKpiValue(kpiTotalRecordsEl, totalRecords, (value) => formatter.format(value));
        setKpiValue(kpiTableCountEl, tables.length, (value) => formatter.format(value));
        setKpiValue(kpiLastModifiedEl, summary?.updated_at, formatDateTime);
        setKpiValue(kpiTodayImagesEl, summary?.today_images_count ?? null, (value) => formatter.format(value));
        setKpiValue(kpiLast24ImagesEl, summary?.last24_images_count ?? null, (value) => formatter.format(value));
        setKpiValue(kpiIssuesCountEl, summary?.issues_count ?? null, (value) => formatter.format(value));
        setKpiValue(kpiVideosCountEl, summary?.videos_count ?? null, (value) => formatter.format(value));
    };

    const buildFingerprint = (summary) => {
        if (!summary || typeof summary !== "object") return "";
        const tables = Array.isArray(summary.tables) ? summary.tables.length : 0;
        const updatedAt = summary.updated_at || "";
        const totalRecords = Number.isFinite(summary.total_records) ? summary.total_records : "";
        const dbSize = Number.isFinite(summary.db_size_bytes) ? summary.db_size_bytes : "";
        return `${updatedAt}|${totalRecords}|${dbSize}|${tables}`;
    };

    const applyFailureState = (message) => {
        if (statusEl) statusEl.textContent = `DB: ${message || "로드 실패"}`;
        if (monitoringShellState.lastUpdatedChip) {
            monitoringShellState.lastUpdatedChip.textContent = "Updated: 실패";
        }
        setKpiValue(kpiDbSizeEl, "로드 실패");
        setKpiValue(kpiDbPathEl, "로드 실패");
        setKpiValue(kpiTotalRecordsEl, "로드 실패");
        setKpiValue(kpiTableCountEl, "로드 실패");
        setKpiValue(kpiLastModifiedEl, "로드 실패");
        if (tableSummaryEl) tableSummaryEl.textContent = "로드 실패";
        if (tableBody) tableBody.innerHTML = "";
        if (emptyEl) {
            emptyEl.textContent = "로드 실패";
            emptyEl.classList.remove("hidden");
        }
    };

    const scheduleRetry = (delayMs) => {
        if (retryTimer) return;
        appendLog(`재시도 예약: ${Math.round(delayMs / 1000)}초 후`, "warn");
        retryTimer = window.setTimeout(() => {
            retryTimer = null;
            loadSummary();
            if (!pollTimer) {
                pollTimer = window.setInterval(loadSummary, pollInterval);
            }
        }, delayMs);
    };

    const resolveSummaryPayload = (payload) => {
        if (payload && typeof payload === "object" && "summary" in payload) {
            return payload.summary;
        }
        return payload;
    };

    const loadSummary = async () => {
        if (statusEl) statusEl.textContent = "DB 상태를 불러오는 중…";
        appendLog("모니터링 API 요청 시작: /api/monitoring/summary", "info");
        try {
            const res = await fetch("/api/monitoring/summary");
            const data = await res.json().catch(() => ({}));
            mergeServerLogs(data?.monitor_logs);
            if (!res.ok || data?.ok === false) {
                const errorMessage = data?.error || "모니터링 정보를 불러오지 못했습니다.";
                throw new Error(errorMessage);
            }
            const summary = resolveSummaryPayload(data);
            const now = new Date();
            const fingerprint = buildFingerprint(summary);
            mergeServerLogs(summary?.monitor_logs);
            if (!lastFingerprint || fingerprint !== lastFingerprint) {
                applySummary(summary);
                lastFingerprint = fingerprint;
                appendLog("새 데이터 반영 완료", "success");
            } else {
                appendLog("변경 없음 · 상태 확인 완료", "info");
            }
            if (monitoringShellState.lastUpdatedChip) {
                monitoringShellState.lastUpdatedChip.textContent = `Updated: ${now.toLocaleTimeString("ko-KR")}`;
            }
            if (statusEl) statusEl.textContent = `DB: ${summary?.exists ? "정상" : "DB 파일 없음"}`;
            if (retryTimer) {
                window.clearTimeout(retryTimer);
                retryTimer = null;
            }
        } catch (err) {
            console.error(err);
            applyFailureState("로드 실패");
            appendLog(`로드 실패: ${err?.message || "알 수 없는 오류"}`, "error");
            if (pollTimer) {
                window.clearInterval(pollTimer);
                pollTimer = null;
            }
            scheduleRetry(pollInterval * 3);
        }
    };

    const interval = Number.parseInt(root.dataset.pollInterval || "15000", 10);
    const pollInterval = Number.isFinite(interval) && interval > 0 ? interval : 15000;

    appendLog("모니터링 페이지 초기화 완료", "info");
    loadSummary();
    pollTimer = window.setInterval(loadSummary, pollInterval);

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            if (pollTimer) {
                window.clearInterval(pollTimer);
                pollTimer = null;
            }
            if (retryTimer) {
                window.clearTimeout(retryTimer);
                retryTimer = null;
            }
            appendLog("탭 비활성화: 자동 갱신 중지", "warn");
            return;
        }
        if (!pollTimer) {
            loadSummary();
            pollTimer = window.setInterval(loadSummary, pollInterval);
            appendLog("탭 활성화: 자동 갱신 재개", "info");
        }
    });
}

function initStatsPage() {
    const root = document.getElementById("stats-page");
    if (!root) return;

    const daysInput = document.getElementById("stats-days");
    const applyBtn = document.getElementById("stats-apply");
    const clearBtn = document.getElementById("stats-clear");
    const statusEl = document.getElementById("stats-status");
    const modelSort = document.getElementById("model-sort");
    const loraSort = document.getElementById("lora-sort");

    const modelTableBody = document.querySelector("#model-stats tbody");
    const loraTableBody = document.querySelector("#lora-stats tbody");
    const modelSummary = document.getElementById("model-summary");
    const loraSummary = document.getElementById("lora-summary");
    const modelEmpty = document.getElementById("model-empty");
    const loraEmpty = document.getElementById("lora-empty");

    const formatter = new Intl.NumberFormat("ko-KR");
    let modelItems = [];
    let loraItems = [];

    const parseDaysInput = (value) => {
        const num = Number.parseInt(value, 10);
        return Number.isFinite(num) && num > 0 ? num : null;
    };

    const sortItems = (items, sortValue) => {
        const [field, dir] = sortValue.split("_");
        const sorted = [...items].sort((a, b) => {
            if (field === "count") {
                const diff = (a.count || 0) - (b.count || 0);
                if (diff !== 0) return diff;
                return String(a.name || "").localeCompare(String(b.name || ""), "ko-KR", { sensitivity: "base" });
            }
            return String(a.name || "").localeCompare(String(b.name || ""), "ko-KR", { sensitivity: "base" });
        });
        return dir === "desc" ? sorted.reverse() : sorted;
    };

    const renderTable = (items, tableBody, summaryEl, emptyEl, sortValue, label) => {
        const sortedItems = sortItems(items, sortValue);
        tableBody.innerHTML = "";
        if (sortedItems.length === 0) {
            emptyEl?.classList.remove("hidden");
            summaryEl.textContent = `${label} 데이터 없음`;
            return;
        }
        emptyEl?.classList.add("hidden");
        const totalCount = sortedItems.reduce((sum, item) => sum + (item.count || 0), 0);
        summaryEl.textContent = `${label} ${sortedItems.length}종 · 총 ${formatter.format(totalCount)}회`;
        sortedItems.forEach((item) => {
            const row = document.createElement("tr");
            const nameCell = document.createElement("td");
            const countCell = document.createElement("td");
            nameCell.textContent = item.name || "-";
            countCell.textContent = formatter.format(item.count || 0);
            row.appendChild(nameCell);
            row.appendChild(countCell);
            tableBody.appendChild(row);
        });
    };

    const refreshTables = () => {
        renderTable(modelItems, modelTableBody, modelSummary, modelEmpty, modelSort?.value || "count_desc", "모델");
        renderTable(loraItems, loraTableBody, loraSummary, loraEmpty, loraSort?.value || "count_desc", "LoRA");
    };

    const loadStats = async () => {
        const days = parseDaysInput(daysInput?.value);
        const query = days ? `?days=${encodeURIComponent(days)}` : "";
        if (statusEl) statusEl.textContent = days ? `최근 ${days}일 데이터를 불러오는 중…` : "전체 데이터를 불러오는 중…";
        try {
            const [modelsRes, lorasRes] = await Promise.all([
                fetch(`/api/stats/models${query}`),
                fetch(`/api/stats/loras${query}`),
            ]);
            if (!modelsRes.ok || !lorasRes.ok) {
                throw new Error("통계 데이터를 불러오지 못했습니다.");
            }
            const modelsData = await modelsRes.json();
            const lorasData = await lorasRes.json();
            modelItems = Array.isArray(modelsData?.items) ? modelsData.items : [];
            loraItems = Array.isArray(lorasData?.items) ? lorasData.items : [];
            refreshTables();
            if (statusEl) {
                statusEl.textContent = days
                    ? `최근 ${days}일 기준 · 모델 ${modelItems.length}종 / LoRA ${loraItems.length}종`
                    : `전체 기준 · 모델 ${modelItems.length}종 / LoRA ${loraItems.length}종`;
            }
        } catch (err) {
            console.error(err);
            if (statusEl) statusEl.textContent = "통계 데이터를 불러오는 중 오류가 발생했습니다.";
        }
    };

    applyBtn?.addEventListener("click", loadStats);
    clearBtn?.addEventListener("click", () => {
        if (daysInput) daysInput.value = "";
        loadStats();
    });
    modelSort?.addEventListener("change", refreshTables);
    loraSort?.addEventListener("change", refreshTables);

    loadStats();
}



function initGalleryUpdateButton() {
    const btn = document.getElementById("btn-gallery-update");
    if (!btn) return;

    const restartHint = document.getElementById("update-restart-required");

    const setBusy = (busy) => {
        btn.disabled = !!busy;
        btn.style.opacity = busy ? "0.7" : "1";
        btn.style.cursor = busy ? "not-allowed" : "pointer";
        btn.textContent = busy ? "⬇️ 업데이트 중..." : "⬇️ 갤러리 업데이트";
    };

    btn.addEventListener("click", async () => {
        const ok = confirm(
            "GitHub에서 MyGallery 최신 코드를 받아옵니다.\n\n" +
            "- 기본 동작: rebase + autostash (필요 시 stash)\n" +
            "- 완료 후 서버 재시작이 필요할 수 있습니다.\n\n" +
            "진행할까요?"
        );
        if (!ok) return;

        setBusy(true);
        try {
            const res = await fetch("/api/repo/update/mygallery", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ rebase: true, stash: true }),
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok || !data.ok) {
                const msg = data?.error || `업데이트 실패 (HTTP ${res.status})`;
                showToast("❌ " + msg, "error");
                return;
            }

            if (data.updated) {
                showToast("✅ 업데이트 완료. 재시작이 필요합니다.", "warning");
                if (restartHint) restartHint.style.display = "block";
            } else {
                showToast("✅ 이미 최신 버전입니다.", "success");
            }

            if (Array.isArray(data.warnings) && data.warnings.length) {
                showToast("⚠️ " + data.warnings.join(" / "), "warning");
            }
        } catch (err) {
            console.error(err);
            showToast("❌ 업데이트 중 예외가 발생했습니다: " + (err?.message || err), "error");
        } finally {
            setBusy(false);
        }
    });
}
const initAppPages = () => {
    initStatsPage();
    initMonitoringPage();
    initGalleryUpdateButton();
    initBooruTagUI();
    initModalCopyHeaders();
    initRelatedPanel();
    initProfileMenu();
};

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAppPages);
} else {
    initAppPages();
}
document.addEventListener("DOMContentLoaded", function () {
  try {
    // Keep gallery title stable in Lite.
    var h1 = document.querySelector('h1');
    if (h1) {
      h1.textContent = '마이갤러리';
    }
  } catch (e) {
    console.error('MyGallery title injection failed:', e);
  }
});
