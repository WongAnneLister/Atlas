"use strict";

const state = {
  limits: { max_tokens: 512, overlap_tokens: 64, product_whole_max_tokens: 4096, hard_max_tokens: 4096 },
  snapshots: [],
  defaultSnapshotId: null,
  snapshotId: null,
  docs: [],
  docTypeFilter: "all",
  docSearch: "",
  currentDocId: null,
  detail: null,
  sectionFilter: null,
  chunkFilter: "all",
  chunkSearch: "",
  activeChunkId: null,
};

const el = {
  snapshotSelect: document.getElementById("snapshot-select"),
  snapshotStats: document.getElementById("snapshot-stats"),
  themeToggle: document.getElementById("theme-toggle"),
  themeIcon: document.getElementById("theme-icon"),
  docCount: document.getElementById("doc-count"),
  docSearch: document.getElementById("doc-search"),
  docTypeFilters: document.getElementById("doc-type-filters"),
  docList: document.getElementById("doc-list"),
  docTitle: document.getElementById("doc-title"),
  docMeta: document.getElementById("doc-meta"),
  sectionsContainer: document.getElementById("sections-container"),
  chunkVisibleCount: document.getElementById("chunk-visible-count"),
  chunkTotalCount: document.getElementById("chunk-total-count"),
  prevChunk: document.getElementById("prev-chunk"),
  nextChunk: document.getElementById("next-chunk"),
  chunkSearch: document.getElementById("chunk-search"),
  chunkFilters: document.getElementById("chunk-filters"),
  limitMaxLabel: document.getElementById("limit-max-label"),
  limitHardLabel: document.getElementById("limit-hard-label"),
  sectionFilterBanner: document.getElementById("section-filter-banner"),
  sectionFilterName: document.getElementById("section-filter-name"),
  clearSectionFilter: document.getElementById("clear-section-filter"),
  chunksList: document.getElementById("chunks-list"),
  toast: document.getElementById("toast"),
};

let toastTimer = null;

function showToast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.toast.hidden = true;
  }, 1800);
}

function tokenLevel(tokens) {
  if (tokens > state.limits.hard_max_tokens) return "danger";
  if (tokens > state.limits.max_tokens) return "warn";
  return "ok";
}

function formatSnapshotLabel(snap, isDefault) {
  const tag = isDefault ? "当前 · " : snap.over_hard_cap > 0 ? "旧版 · " : "";
  const base = snap.kind === "build"
    ? snap.snapshot_id.slice(6, 14)
    : snap.snapshot_id.replace(/^file:/, "").replace(/\.jsonl$/, "");
  return `${tag}${base} (${snap.chunk_count} 块 · max ${snap.max_tokens})`;
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      if (err && err.detail) msg = err.detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(msg);
  }
  return res.json();
}

function renderSnapshotStats(snap) {
  el.snapshotStats.replaceChildren();
  if (!snap) return;

  const items = [
    { label: "文档", val: snap.doc_count, cls: "" },
    { label: "块", val: snap.chunk_count, cls: "" },
    { label: "最大", val: `${snap.max_tokens} tok`, cls: tokenLevel(snap.max_tokens) === "ok" ? "" : tokenLevel(snap.max_tokens) },
  ];
  if (snap.over_hard_cap > 0) {
    items.push({ label: `超 ${state.limits.hard_max_tokens} 硬上限`, val: `${snap.over_hard_cap} 块`, cls: "danger" });
  }

  for (const item of items) {
    const span = document.createElement("span");
    span.className = item.cls ? `stat-item ${item.cls}` : "stat-item";
    span.append(`${item.label} `);
    const strong = document.createElement("strong");
    strong.textContent = String(item.val);
    span.append(strong);
    el.snapshotStats.append(span);
  }
}

function filteredDocs() {
  const q = state.docSearch.trim().toLowerCase();
  return state.docs.filter((d) => {
    if (state.docTypeFilter !== "all" && d.doc_type !== state.docTypeFilter) return false;
    if (q && !d.title.toLowerCase().includes(q) && !d.doc_id.toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderDocList() {
  const docs = filteredDocs();
  el.docCount.textContent = String(docs.length);
  el.docList.replaceChildren();

  if (docs.length === 0) {
    const li = document.createElement("li");
    li.className = "empty-state";
    li.textContent = state.docs.length === 0 ? "未找到本地文档，请先运行 make data && make ingest。" : "无匹配文档";
    el.docList.append(li);
    return;
  }

  for (const d of docs) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = d.doc_id === state.currentDocId ? "doc-item active" : "doc-item";

    const top = document.createElement("div");
    top.className = "doc-item-top";
    const name = document.createElement("span");
    name.className = "doc-item-name";
    name.textContent = d.title;
    const count = document.createElement("span");
    count.className = "doc-item-chunks";
    count.textContent = `${d.chunk_count} 块`;
    top.append(name, count);

    const sub = document.createElement("div");
    sub.className = "doc-item-sub";
    const typeLabel = document.createElement("span");
    typeLabel.textContent = `${d.doc_type === "catalog" ? "Catalog" : "Policy"} · ${d.section_count} 节`;
    const maxTok = document.createElement("span");
    const lvl = tokenLevel(d.max_chunk_tokens);
    maxTok.className = lvl === "ok" ? "doc-tok-tag" : `doc-tok-tag ${lvl}`;
    maxTok.textContent = `max ${d.max_chunk_tokens}`;
    sub.append(typeLabel, maxTok);

    btn.append(top, sub);
    btn.addEventListener("click", () => selectDoc(d.doc_id));
    li.append(btn);
    el.docList.append(li);
  }
}

function visibleChunks() {
  if (!state.detail) return [];
  const q = state.chunkSearch.trim().toLowerCase();
  return state.detail.chunks.filter((c) => {
    if (state.sectionFilter && c.section_id !== state.sectionFilter) return false;
    if (state.chunkFilter === "over_max" && c.n_tokens <= state.limits.max_tokens) return false;
    if (state.chunkFilter === "over_hard" && c.n_tokens <= state.limits.hard_max_tokens) return false;
    if (state.chunkFilter === "headed" && !c.header_prefix) return false;
    if (state.chunkFilter === "overlap" && c.overlap_prev_start === null && c.overlap_next_start === null) return false;
    if (q) {
      const hay = `${c.text}\n${c.chunk_id}\n${c.section_id}\n${c.heading_path}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function buildHighlightedProse(prose, chunk) {
  const frag = document.createDocumentFragment();
  if (!chunk || chunk.span_start === null || chunk.span_end === null) {
    frag.append(document.createTextNode(prose));
    return frag;
  }

  const len = prose.length;
  const s = Math.max(0, Math.min(len, chunk.span_start));
  const e = Math.max(s, Math.min(len, chunk.span_end));
  const hasPrev = chunk.overlap_prev_start !== null && chunk.overlap_prev_end !== null && chunk.overlap_prev_end > chunk.overlap_prev_start;
  const hasNext = chunk.overlap_next_start !== null && chunk.overlap_next_end !== null && chunk.overlap_next_end > chunk.overlap_next_start;
  const ps = hasPrev ? Math.max(s, Math.min(e, chunk.overlap_prev_start)) : -1;
  const pe = hasPrev ? Math.max(s, Math.min(e, chunk.overlap_prev_end)) : -1;
  const ns = hasNext ? Math.max(s, Math.min(e, chunk.overlap_next_start)) : -1;
  const ne = hasNext ? Math.max(s, Math.min(e, chunk.overlap_next_end)) : -1;

  const pointSet = new Set([0, len, s, e]);
  if (hasPrev) {
    pointSet.add(ps);
    pointSet.add(pe);
  }
  if (hasNext) {
    pointSet.add(ns);
    pointSet.add(ne);
  }
  const points = Array.from(pointSet).sort((a, b) => a - b);

  let firstMark = true;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (b <= a) continue;
    const slice = prose.slice(a, b);
    const inBody = a >= s && b <= e;
    const inPrev = hasPrev && a >= ps && b <= pe;
    const inNext = hasNext && a >= ns && b <= ne;

    if (!inBody) {
      frag.append(document.createTextNode(slice));
      continue;
    }

    const mark = document.createElement("mark");
    if (inPrev && inNext) {
      mark.className = "hl-both";
      mark.title = "同时与上一块和下一块重叠";
    } else if (inPrev) {
      mark.className = "hl-prev";
      mark.title = "与上一块重叠区 (Prev Overlap)";
    } else if (inNext) {
      mark.className = "hl-next";
      mark.title = "与下一块重叠区 (Next Overlap)";
    } else {
      mark.className = "hl-body";
      mark.title = "当前选中块正文";
    }
    if (firstMark) {
      mark.dataset.scrollTarget = "true";
      firstMark = false;
    }
    mark.textContent = slice;
    frag.append(mark);
  }
  return frag;
}

function renderDocumentSource(scrollToHighlight = false) {
  el.sectionsContainer.replaceChildren();
  const detail = state.detail;
  if (!detail) {
    el.docTitle.textContent = "选择左侧文档";
    el.docMeta.replaceChildren();
    return;
  }

  el.docTitle.textContent = detail.title;
  el.docMeta.replaceChildren();
  const metaBits = [
    `${detail.sections.length} 章节`,
    `${detail.chunks.length} 切块`,
  ];
  if (detail.source_datasets.length) metaBits.push(detail.source_datasets.join(" / "));
  if (detail.built_at) metaBits.push(detail.built_at);
  el.docMeta.textContent = metaBits.join(" · ");

  const activeChunk = detail.chunks.find((c) => c.chunk_id === state.activeChunkId) || null;
  const article = document.createElement("div");
  article.className = "source-article";

  for (const sec of detail.sections) {
    const isTarget = activeChunk && activeChunk.section_id === sec.section_id;
    const isFiltered = state.sectionFilter === sec.section_id;
    const block = document.createElement("section");
    block.className = isTarget ? "section-block active-section" : "section-block";
    block.dataset.sectionId = sec.section_id;

    const head = document.createElement("div");
    head.className = "section-head";

    const headLeft = document.createElement("div");
    headLeft.className = "section-head-left";

    const h3 = document.createElement("h2");
    h3.className = "section-heading";
    h3.textContent = sec.heading;
    h3.title = sec.section_id;

    const sub = document.createElement("div");
    sub.className = "section-meta-sub";
    const subParts = [`${sec.chunk_count} 块`];
    if (sec.max_chunk_tokens > 0) subParts.push(`max ${sec.max_chunk_tokens} tok`);
    if (sec.product_category) subParts.push(sec.product_category);
    if (sec.effective_from || sec.effective_to) {
      subParts.push(`${sec.effective_from || "…"} ~ ${sec.effective_to || "现行"}`);
    }
    sub.textContent = subParts.join(" · ");
    headLeft.append(h3, sub);

    const filterBtn = document.createElement("button");
    filterBtn.type = "button";
    filterBtn.className = isFiltered ? "section-filter-trigger active" : "section-filter-trigger";
    filterBtn.textContent = isFiltered ? "已筛选本节" : "只看本节";
    filterBtn.title = `section_id: ${sec.section_id}`;
    filterBtn.addEventListener("click", () => {
      state.sectionFilter = state.sectionFilter === sec.section_id ? null : sec.section_id;
      if (state.sectionFilter) {
        const firstInSec = detail.chunks.find((c) => c.section_id === state.sectionFilter);
        if (firstInSec) state.activeChunkId = firstInSec.chunk_id;
      }
      renderDocumentSource(false);
      renderChunksPane(true);
    });

    head.append(headLeft, filterBtn);

    const proseEl = document.createElement("div");
    proseEl.className = sec.prose ? "section-prose" : "section-prose empty";
    if (sec.prose) {
      proseEl.append(buildHighlightedProse(sec.prose, isTarget ? activeChunk : null));
    } else {
      proseEl.textContent = "（该章节不在当前本地 .md 原文中，可能来自历史快照）";
    }

    block.append(head, proseEl);
    article.append(block);
  }

  el.sectionsContainer.append(article);

  if (scrollToHighlight) {
    const target = el.sectionsContainer.querySelector('mark[data-scroll-target="true"]')
      || el.sectionsContainer.querySelector(".section-block.active-section");
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
}

function renderChunksPane(scrollActiveCard = false) {
  const total = state.detail ? state.detail.chunks.length : 0;
  const visible = visibleChunks();
  el.chunkTotalCount.textContent = String(total);
  el.chunkVisibleCount.textContent = String(visible.length);

  if (state.sectionFilter) {
    const secObj = state.detail?.sections.find((s) => s.section_id === state.sectionFilter);
    el.sectionFilterBanner.hidden = false;
    el.sectionFilterName.textContent = secObj ? secObj.heading : state.sectionFilter;
    el.sectionFilterName.title = state.sectionFilter;
  } else {
    el.sectionFilterBanner.hidden = true;
  }

  const activeIdx = visible.findIndex((c) => c.chunk_id === state.activeChunkId);
  el.prevChunk.disabled = visible.length === 0 || activeIdx <= 0;
  el.nextChunk.disabled = visible.length === 0 || activeIdx >= visible.length - 1;

  el.chunksList.replaceChildren();

  if (visible.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前筛选条件下没有切块";
    el.chunksList.append(empty);
    return;
  }

  for (const c of visible) {
    const isActive = c.chunk_id === state.activeChunkId;
    const card = document.createElement("article");
    card.className = isActive ? "chunk-card active" : "chunk-card";
    card.dataset.chunkId = c.chunk_id;

    const head = document.createElement("div");
    head.className = "chunk-head";

    const left = document.createElement("div");
    left.className = "chunk-head-left";

    const num = document.createElement("span");
    num.className = "chunk-num";
    num.textContent = `#${c.global_index}`;

    const tok = document.createElement("span");
    tok.className = `chunk-tok ${tokenLevel(c.n_tokens)}`;
    tok.textContent = `${c.n_tokens} tok`;
    left.append(num, tok);

    if (c.header_prefix) {
      const tag = document.createElement("span");
      tag.className = "mini-tag headed";
      tag.textContent = "带标题";
      left.append(tag);
    }
    if (c.overlap_prev_start !== null) {
      const tag = document.createElement("span");
      tag.className = "mini-tag overlap";
      tag.textContent = "重叠";
      left.append(tag);
    }

    const idBtn = document.createElement("button");
    idBtn.type = "button";
    idBtn.className = "copy-id mono";
    idBtn.textContent = c.chunk_id.slice(0, 8);
    idBtn.title = `复制完整 chunk_id: ${c.chunk_id}`;
    idBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(c.chunk_id).then(() => showToast(`已复制 ${c.chunk_id.slice(0, 12)}…`));
      }
    });

    head.append(left, idBtn);
    card.append(head);

    if (state.detail && state.detail.sections.length > 1) {
      const sub = document.createElement("div");
      sub.className = "chunk-sub";
      sub.textContent = `${c.heading_path || c.section_id} · 节内 #${c.section_index}`;
      card.append(sub);
    }

    if (c.header_prefix) {
      const pref = document.createElement("div");
      pref.className = "chunk-prefix";
      const lbl = document.createElement("strong");
      lbl.textContent = "拼接前缀 · ";
      pref.append(lbl, document.createTextNode(c.header_prefix));
      card.append(pref);
    }

    const body = document.createElement("p");
    body.className = "chunk-body";
    body.textContent = c.body_text;
    card.append(body);

    if (isActive) {
      const foot = document.createElement("div");
      foot.className = "chunk-foot";

      const row = document.createElement("div");
      row.className = "chunk-foot-row";
      const spanEl = document.createElement("span");
      spanEl.className = "mono";
      if (c.span_start !== null && c.span_end !== null) {
        const prevLen = c.overlap_prev_start !== null ? c.overlap_prev_end - c.overlap_prev_start : 0;
        const nextLen = c.overlap_next_start !== null ? c.overlap_next_end - c.overlap_next_start : 0;
        spanEl.textContent = `原文 [${c.span_start}..${c.span_end}] · 上重叠 ${prevLen} · 下重叠 ${nextLen}`;
      } else {
        spanEl.textContent = "未在当前原文中定位到完全匹配区间";
      }
      const pct = Math.min(100, Math.round((c.n_tokens / state.limits.hard_max_tokens) * 100));
      const capEl = document.createElement("span");
      capEl.textContent = `${pct}% 硬上限`;
      row.append(spanEl, capEl);

      const meter = document.createElement("div");
      meter.className = "meter";
      const fill = document.createElement("div");
      const lvl = tokenLevel(c.n_tokens);
      fill.className = lvl === "ok" ? "meter-fill" : `meter-fill ${lvl}`;
      fill.style.width = `${Math.max(2, pct)}%`;
      meter.append(fill);

      foot.append(row, meter);
      card.append(foot);
    }

    card.addEventListener("click", () => selectChunk(c.chunk_id, true, false));
    el.chunksList.append(card);
  }

  if (scrollActiveCard) {
    const activeEl = el.chunksList.querySelector(".chunk-card.active");
    if (activeEl) {
      activeEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

function selectChunk(chunkId, scrollSource = true, scrollCard = false) {
  state.activeChunkId = chunkId;
  renderDocumentSource(scrollSource);
  renderChunksPane(scrollCard);
}

function stepChunk(delta) {
  const visible = visibleChunks();
  if (!visible.length) return;
  const idx = visible.findIndex((c) => c.chunk_id === state.activeChunkId);
  const next = idx === -1 ? 0 : Math.max(0, Math.min(visible.length - 1, idx + delta));
  selectChunk(visible[next].chunk_id, true, true);
}

async function selectDoc(docId) {
  state.currentDocId = docId;
  state.sectionFilter = null;
  state.activeChunkId = null;
  renderDocList();

  const loading = document.createElement("div");
  loading.className = "empty-state";
  loading.textContent = "加载中…";
  el.sectionsContainer.replaceChildren(loading);
  el.chunksList.replaceChildren();

  try {
    const q = state.snapshotId ? `?snapshot=${encodeURIComponent(state.snapshotId)}` : "";
    const detail = await fetchJson(`/api/chunks/docs/${encodeURIComponent(docId)}${q}`);
    state.detail = detail;
    state.activeChunkId = detail.chunks.length ? detail.chunks[0].chunk_id : null;
    renderDocumentSource(false);
    renderChunksPane(false);
  } catch (err) {
    const msg = document.createElement("div");
    msg.className = "empty-state";
    msg.textContent = `加载失败：${err.message}`;
    el.sectionsContainer.replaceChildren(msg);
  }
}

async function loadSnapshot(snapshotId) {
  state.snapshotId = snapshotId;
  const prevDoc = state.currentDocId;
  try {
    const q = snapshotId ? `?snapshot=${encodeURIComponent(snapshotId)}` : "";
    const data = await fetchJson(`/api/chunks/docs${q}`);
    state.limits = data.limits;
    el.limitMaxLabel.textContent = String(data.limits.max_tokens);
    el.limitHardLabel.textContent = String(data.limits.hard_max_tokens);
    renderSnapshotStats(data.snapshot);
    state.docs = data.docs;
    renderDocList();

    const targetDoc =
      data.docs.find((d) => d.doc_id === prevDoc)?.doc_id
      || data.docs.find((d) => d.doc_id === "catalog_air_fryers")?.doc_id
      || (data.docs[0] ? data.docs[0].doc_id : null);

    if (targetDoc) {
      await selectDoc(targetDoc);
    } else {
      state.detail = null;
      renderDocumentSource(false);
      renderChunksPane(false);
    }
  } catch (err) {
    showToast(`加载快照失败：${err.message}`);
  }
}

async function init() {
  try {
    const data = await fetchJson("/api/chunks/snapshots");
    state.limits = data.limits;
    state.snapshots = data.snapshots;
    state.defaultSnapshotId = data.default_snapshot_id;
    el.limitMaxLabel.textContent = String(data.limits.max_tokens);
    el.limitHardLabel.textContent = String(data.limits.hard_max_tokens);

    el.snapshotSelect.replaceChildren();
    if (!data.snapshots.length) {
      const opt = document.createElement("option");
      opt.textContent = "未找到本地切块快照";
      el.snapshotSelect.append(opt);
      el.snapshotSelect.disabled = true;
      renderDocList();
      return;
    }

    for (const s of data.snapshots) {
      const opt = document.createElement("option");
      opt.value = s.snapshot_id;
      opt.textContent = formatSnapshotLabel(s, s.snapshot_id === data.default_snapshot_id);
      el.snapshotSelect.append(opt);
    }
    el.snapshotSelect.value = data.default_snapshot_id || data.snapshots[0].snapshot_id;
    await loadSnapshot(el.snapshotSelect.value);
  } catch (err) {
    const div = document.createElement("div");
    div.className = "empty-state";
    div.textContent = `无法读取切块接口：${err.message}`;
    el.sectionsContainer.replaceChildren(div);
  }
}

el.snapshotSelect.addEventListener("change", () => loadSnapshot(el.snapshotSelect.value));

el.docSearch.addEventListener("input", () => {
  state.docSearch = el.docSearch.value;
  renderDocList();
});

el.docTypeFilters.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-filter]");
  if (!btn) return;
  state.docTypeFilter = btn.dataset.filter;
  for (const b of el.docTypeFilters.querySelectorAll("button")) {
    b.classList.toggle("active", b === btn);
  }
  renderDocList();
});

el.chunkSearch.addEventListener("input", () => {
  state.chunkSearch = el.chunkSearch.value;
  renderChunksPane(false);
});

el.chunkFilters.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-filter]");
  if (!btn) return;
  state.chunkFilter = btn.dataset.filter;
  for (const b of el.chunkFilters.querySelectorAll("button")) {
    b.classList.toggle("active", b === btn);
  }
  renderChunksPane(false);
});

el.clearSectionFilter.addEventListener("click", () => {
  state.sectionFilter = null;
  renderDocumentSource(false);
  renderChunksPane(false);
});

el.prevChunk.addEventListener("click", () => stepChunk(-1));
el.nextChunk.addEventListener("click", () => stepChunk(1));

document.addEventListener("keydown", (ev) => {
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (ev.key === "ArrowDown" || ev.key === "j") {
    ev.preventDefault();
    stepChunk(1);
  } else if (ev.key === "ArrowUp" || ev.key === "k") {
    ev.preventDefault();
    stepChunk(-1);
  }
});

el.themeToggle.addEventListener("click", () => {
  const root = document.documentElement;
  const next = root.dataset.theme === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  el.themeIcon.textContent = next === "dark" ? "☀" : "☾";
});

init();
