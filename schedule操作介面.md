```dataviewjs
// ==========================================
// 1. 基礎設定與 CSS 注入 (含載入重試機制)
// ==========================================
let currentPage = dv.current();
if (!currentPage || !currentPage.file) {
    let loadingPara = dv.paragraph("⏳ 系統載入中...（Dataview 索引建立中，稍候會自動重新整理）");
    let retryCount = 0;
    const tryReload = () => {
        retryCount++;
        let retryPage = dv.current();
        if (retryPage && retryPage.file) {
            dv.app.workspace.trigger("dataview:refresh-views");
        } else if (retryCount < 10) {
            setTimeout(tryReload, 800);
        } else {
            loadingPara.innerText = "⚠️ 索引一直沒建立完成。請試著在命令面板執行「Dataview: Rebuild current index / Force refresh」。";
        }
    };
    setTimeout(tryReload, 800);
    return;
}

let styleEl = document.getElementById("dv-custom-layout-style");
if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = "dv-custom-layout-style";
    styleEl.innerHTML = `
        .dv-table-fixed-line {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            max-width: 300px;
            display: block;
        }
        .status-kyc-fail { color: #f44336; font-weight: bold; }
        .status-approved { color: #4CAF50; font-weight: bold; }
        .status-completed { color: #2196F3; font-weight: bold; }
        .status-cancelled { color: #9e9e9e; font-weight: bold; }
        .status-other { color: var(--text-muted); }
    `;
    document.head.appendChild(styleEl);
}

let file = app.vault.getAbstractFileByPath(currentPage.file.path);
const fs = require('fs');
const { exec } = require('child_process');
const basePath = app.vault.adapter.getBasePath();

// --- 建立控制面板 ---
let controlContainer = this.container.createEl("div");
controlContainer.style.cssText = "display: flex; gap: 12px; margin-bottom: 15px; align-items: center; flex-wrap: wrap; padding: 15px; background-color: var(--background-secondary); border-radius: 10px; border: 1px solid var(--background-modifier-border);";

let reportArea = this.container.createEl("div");
reportArea.style.cssText = "display: none; margin-bottom: 15px; padding: 15px; background-color: rgba(33, 150, 243, 0.1); border-left: 5px solid #2196F3; border-radius: 4px; font-size: 0.95em;";

// ==========================================
// 2. 獲取 Kingdee JSON 資料
// ==========================================
let shipMap = {};
try {
    const jsonPath = fs.existsSync(`${basePath}/Kingdee_Export_UTF8.json`) ? `${basePath}/Kingdee_Export_UTF8.json` : `${basePath}/../Kingdee_Export_UTF8.json`;
    if (fs.existsSync(jsonPath)) {
        let content = fs.readFileSync(jsonPath, 'utf8').replace(/^\uFEFF/, '').replace(/,\s*\]$/, ']');
        JSON.parse(content).forEach(item => { 
            let imo = item.imo || item.IMO || item.Imo;
            if (imo) shipMap[String(imo).trim()] = item; 
        });
    }
} catch (e) {}

// ==========================================
// 3. 🚀 更新按鈕 (修正 Log 讀取與 GitHub 觸發)
// ==========================================
let updateBtn = controlContainer.createEl('button', {text: "📥 更新郵件"}); 
updateBtn.style.cssText = "padding: 6px 15px; background: #2196F3; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;";

updateBtn.onclick = async () => { 
    // 拍照：記錄更新前的檔案清單
    let beforePaths = dv.pages('"data_John"').file.path.array();
    
    updateBtn.innerText = "⏳ 抓取中..."; 
    updateBtn.style.backgroundColor = "#ff9800"; 
    reportArea.style.display = "none";
    
    exec(`osascript "${basePath}/script.scpt"`, async (error) => { 
        if (error) { 
            new Notice('❌ 爬取失敗: ' + error.message); 
            updateBtn.innerText = "❌ 失敗"; 
            setTimeout(() => { updateBtn.innerText = "📥 更新郵件"; updateBtn.style.backgroundColor = "#2196F3"; }, 5000);
            return;
        }

        updateBtn.innerText = "🔍 讀取紀錄...";
        await new Promise(r => setTimeout(r, 3500)); // 等待 Obsidian 建立新檔案索引

        // 🚀 修正點 1：正確的路徑 (根目錄)
        let logPath = `${basePath}/update_log.json`;
        let lastId = 0, updateTime = "-";
        try {
            if (fs.existsSync(logPath)) {
                let logContent = fs.readFileSync(logPath, 'utf8');
                let log = JSON.parse(logContent);
                lastId = log.last_id || 0;
                updateTime = log.update_time || "-";
            }
        } catch (e) {
            console.error("Log 讀取失敗", e);
            new Notice('⚠️ 讀不到 update_log.json，請確認 AppleScript 有正確執行。');
        }

        // 🚀 修正點 2：比對新舊清單，精準算出新增了幾筆
        let newPages = dv.pages('"data_John"').where(p => !beforePaths.includes(p.file.path));
        let newCount = newPages.length;

        // 顯示報告
        reportArea.innerHTML = `<b>📊 更新完成：新增 ${newCount} 筆郵件</b><br>系統最後更新時間：${updateTime}<br><hr>` +
            (newCount > 0 ? newPages.map(p => `📄 ${p.subject}`).join("<br>") : "（本次沒有新郵件）");
        reportArea.style.display = "block";

        // 🚀 修正點 3：無論有沒有新信，都詢問是否要同步 (防呆機制)
        let confirmMsg = newCount > 0 
            ? `抓取完畢！最新編號：${lastId}\n本次新增：${newCount} 筆。\n\n是否同步到 GitHub 網頁？` 
            : `抓取完畢！最新編號：${lastId}\n本次沒有新增郵件。\n\n是否仍要強制同步 GitHub？`;

        if (confirm(confirmMsg)) {
            updateBtn.innerText = "📤 正在上傳...";
            // 🚀 確保 push 資料夾與 log
            let gitCmd = `cd "${basePath}" && git add data_John update_log.json Kingdee_Export_UTF8.json .gitignore && git commit -m "Auto update via button (ID: ${lastId})" && git push origin main`;
            exec(gitCmd, (gError, stdout, stderr) => {
                if (gError) {
                    new Notice('❌ GitHub 同步失敗，請檢查權限');
                    console.error(gError, stderr);
                    updateBtn.innerText = "❌ 同步失敗";
                } else {
                    new Notice('✅ 網頁同步成功！');
                    updateBtn.innerText = "✅ 同步完成";
                }
            });
        } else {
            updateBtn.innerText = "✅ 完成"; 
        }

        updateBtn.style.backgroundColor = "#4CAF50"; 
        setTimeout(() => { updateBtn.innerText = "📥 更新郵件"; updateBtn.style.backgroundColor = "#2196F3"; }, 5000); 
    }); 
};

// ==========================================
// 4. 篩選器 UI (日期、類別、油輪)
// ==========================================

controlContainer.createEl("span", {text: "📅 範圍：", attr: {style: "font-weight: bold; margin-left: 5px;"}});
let dateRangeInput = controlContainer.createEl("input", {type: "text"});
dateRangeInput.readOnly = true;
dateRangeInput.style.cssText = "padding: 5px; border-radius: 4px; border: 1px solid var(--background-modifier-border); width: 190px; text-align: center; cursor: pointer; background: var(--background-primary);";
dateRangeInput.value = (currentPage.開始日期 && currentPage.結束日期) ? `${currentPage.開始日期} ~ ${currentPage.結束日期}` : "點擊選擇日期區間";

let rangeStart = currentPage.開始日期 || null;
let rangeEnd = currentPage.結束日期 || null;
let pickingStart = null; 

let popup = document.createElement("div");
popup.style.cssText = "position: absolute; z-index: 999; display: none; background: var(--background-primary); border: 1px solid var(--background-modifier-border); border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); padding: 10px; width: 240px;";
document.body.appendChild(popup);

let viewDate = rangeStart ? new Date(rangeStart) : new Date();
const pad2 = n => String(n).padStart(2, "0");
const toISO = d => `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`;

const renderCalendar = () => {
    popup.innerHTML = "";
    let header = document.createElement("div");
    header.style.cssText = "display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; font-weight:bold;";
    let prevBtn = document.createElement("span"); prevBtn.textContent = "◀"; prevBtn.style.cursor = "pointer";
    let nextBtn = document.createElement("span"); nextBtn.textContent = "▶"; nextBtn.style.cursor = "pointer";
    let label = document.createElement("span"); label.textContent = `${viewDate.getFullYear()} / ${pad2(viewDate.getMonth()+1)}`;
    prevBtn.onclick = (e) => { e.stopPropagation(); viewDate.setMonth(viewDate.getMonth() - 1); renderCalendar(); };
    nextBtn.onclick = (e) => { e.stopPropagation(); viewDate.setMonth(viewDate.getMonth() + 1); renderCalendar(); };
    header.append(prevBtn, label, nextBtn);
    popup.appendChild(header);

    let grid = document.createElement("div");
    grid.style.cssText = "display:grid; grid-template-columns:repeat(7,1fr); gap:2px; text-align:center; font-size:0.85em;";
    ["日","一","二","三","四","五","六"].forEach(w => {
        let el = document.createElement("div"); el.textContent = w; el.style.cssText = "font-weight:bold; color:var(--text-muted); padding:4px 0;";
        grid.appendChild(el);
    });

    let y = viewDate.getFullYear(), m = viewDate.getMonth();
    let firstDay = new Date(y, m, 1).getDay();
    let daysInMonth = new Date(y, m + 1, 0).getDate();

    for (let i = 0; i < firstDay; i++) grid.appendChild(document.createElement("div"));

    for (let d = 1; d <= daysInMonth; d++) {
        let cellDate = new Date(y, m, d);
        let iso = toISO(cellDate);
        let cell = document.createElement("div");
        cell.textContent = d;
        cell.style.cssText = "padding:4px 0; border-radius:4px; cursor:pointer;";

        let inRange = rangeStart && rangeEnd && iso >= rangeStart && iso <= rangeEnd;
        let isEdge = iso === rangeStart || iso === rangeEnd;
        if (isEdge) cell.style.cssText += "background:#2196F3; color:white; font-weight:bold;";
        else if (inRange) cell.style.cssText += "background:rgba(33,150,243,0.2);";

        cell.onmouseenter = () => { if (!isEdge && !inRange) cell.style.background = "var(--background-modifier-hover)"; };
        cell.onmouseleave = () => { if (!isEdge && !inRange) cell.style.background = ""; };

        cell.onclick = async (e) => {
            e.stopPropagation();
            if (!pickingStart) {
                pickingStart = iso; rangeStart = iso; rangeEnd = null;
            } else {
                rangeEnd = iso > pickingStart ? iso : pickingStart;
                rangeStart = iso > pickingStart ? pickingStart : iso;
                pickingStart = null;
                dateRangeInput.value = `${rangeStart} ~ ${rangeEnd}`;
                await app.fileManager.processFrontMatter(file, fm => { fm["開始日期"] = rangeStart; fm["結束日期"] = rangeEnd; });
                popup.style.display = "none";
            }
            renderCalendar();
        };
        grid.appendChild(cell);
    }
    popup.appendChild(grid);
};

dateRangeInput.onclick = (e) => {
    e.stopPropagation();
    if (popup.style.display === "none") {
        pickingStart = null; rangeStart = null; rangeEnd = null;
        let rect = dateRangeInput.getBoundingClientRect();
        popup.style.left = `${rect.left}px`; popup.style.top = `${rect.bottom + 4}px`;
        renderCalendar(); popup.style.display = "block";
    } else {
        popup.style.display = "none";
    }
};
document.addEventListener("click", (e) => { if (!popup.contains(e.target) && e.target !== dateRangeInput) popup.style.display = "none"; });

// 類別選單
controlContainer.createEl("span", {text: "📂 狀態：", attr: {style: "font-weight: bold; margin-left: 5px;"}});
let catSelect = controlContainer.createEl("select");
["全部", "APPROVED", "COMPLETED", "CANCELLED", "KYC未通過"].forEach(c => {
    let opt = catSelect.createEl("option", {value: c, text: c});
    if(c === (currentPage.查詢類別 || "全部")) opt.selected = true;
});
catSelect.onchange = async (e) => { await app.fileManager.processFrontMatter(file, fm => { fm["查詢類別"] = e.target.value === "全部" ? null : e.target.value; }); };

// 油輪選單
controlContainer.createEl("span", {text: "🚢 油輪：", attr: {style: "font-weight: bold; margin-left: 5px;"}});
let rawS = [...new Set(dv.pages('"data_John"').where(p => p.ships).map(p => p.ships))];
let shipSelect = controlContainer.createEl("select");
[{v: "全部", t: "全部"}, ...rawS.map(s => ({v: s, t: s.split('@')[0]}))].forEach(o => {
    let opt = shipSelect.createEl("option", {value: o.v, text: o.t});
    if(o.v === (currentPage.查詢船隻 || "全部")) opt.selected = true;
});
shipSelect.onchange = async (e) => { await app.fileManager.processFrontMatter(file, fm => { fm["查詢船隻"] = e.target.value === "全部" ? null : e.target.value; }); };

// ==========================================
// 5. 排序檢索 UI
// ==========================================
controlContainer.createEl("span", {text: "🔃 排序：", attr: {style: "font-weight: bold; margin-left: 5px;"}});
let sortFieldSelect = controlContainer.createEl("select");
let sortDirSelect = controlContainer.createEl("select");

[ {v: "date", t: "日期"}, {v: "status", t: "狀態"} ].forEach(o => {
    let opt = sortFieldSelect.createEl("option", {value: o.v, text: o.t});
    if(o.v === (currentPage.排序欄位 || "date")) opt.selected = true;
});

[ {v: "desc", t: "降序 (新→舊)"}, {v: "asc", t: "升序 (舊→新)"} ].forEach(o => {
    let opt = sortDirSelect.createEl("option", {value: o.v, text: o.t});
    if(o.v === (currentPage.排序方向 || "desc")) opt.selected = true;
});

const updateSort = async () => {
    await app.fileManager.processFrontMatter(file, fm => { fm["排序欄位"] = sortFieldSelect.value; fm["排序方向"] = sortDirSelect.value; });
};
sortFieldSelect.onchange = updateSort;
sortDirSelect.onchange = updateSort;

// ==========================================
// 6. 資料處理與排序邏輯
// ==========================================
const parseShipEntries = (target) => {
    if (!target || target === "(本次無資料)") return [{ fv: "-", imo: "-" }];
    let segments = target.split(/\s*\|\s*/).filter(s => s.trim() !== "");
    if (segments.length === 0) return [{ fv: "-", imo: "-" }];
    return segments.map(seg => {
        let fv = seg.match(/FV:(.*?)丨/)?.[1]?.trim() || seg.match(/FV:(.*)$/)?.[1]?.trim() || "-";
        let imo = seg.match(/IMO:(\d+)/)?.[1]?.trim() || "-";
        return { fv, imo };
    });
};

let basePages = dv.pages('"data_John"')
    .where(p => p.file.path !== currentPage.file.path)
    .where(p => {
        if (currentPage.開始日期 && currentPage.結束日期) {
            let pT = new Date(p.date).getTime();
            let sT = new Date(currentPage.開始日期).getTime();
            let eT = new Date(currentPage.結束日期).getTime();
            if (pT < sT || pT > eT) return false;
        }
        if (currentPage.查詢船隻 && currentPage.查詢船隻 !== "全部" && p.ships !== currentPage.查詢船隻) return false;
        return true;
    });

let allEntries = [];
for (let p of basePages) {
    let shipEntries = parseShipEntries(p.target);
    for (let s of shipEntries) {
        let isKycFail = (s.imo !== "-" && !shipMap[s.imo]);
        let statusText = isKycFail ? "KYC未通過" : (p.category ? p.category.toUpperCase() : "PENDING");
        allEntries.push({ page: p, fv: s.fv, imo: s.imo, isKycFail, statusText });
    }
}

let entries = allEntries.filter(en => {
    if (currentPage.查詢類別 && currentPage.查詢類別 !== "全部" && en.statusText !== currentPage.查詢類別) return false;
    return true;
});

let sField = currentPage.排序欄位 || "date";
let sDir = currentPage.排序方向 || "desc";
const statusRank = { "KYC未通過": 0, "APPROVED": 1, "COMPLETED": 2, "CANCELLED": 3 };

if (sField === "date") {
    entries.sort((a, b) => {
        let diff = new Date(a.page.date) - new Date(b.page.date);
        return sDir === "asc" ? diff : -diff;
    });
} else if (sField === "status") {
    entries.sort((a, b) => {
        let diff = (statusRank[a.statusText] ?? 4) - (statusRank[b.statusText] ?? 4);
        return sDir === "asc" ? diff : -diff;
    });
}

const formatDateDisplay = (d) => {
    if (!d) return "-";
    if (typeof d.toFormat === "function") return d.toFormat("MM|dd");
    let datePart = String(d).split("T")[0];
    let segments = datePart.split("-");
    return segments.length >= 3 ? `${segments[1]}|${segments[2]}` : segments.join("|");
};

// ==========================================
// 7. 表格渲染 (每艘船一列)
// ==========================================
let rows = [];
for (let en of entries) {
    let p = en.page;
    let finalShipName = (en.imo !== "-" && shipMap[en.imo]) ? (shipMap[en.imo].name || en.fv) : en.fv;
    let finalCallSign = (en.imo !== "-" && shipMap[en.imo]) ? (shipMap[en.imo].callSign || "-") : "-";

    let colorClass = "status-other";
    if (en.isKycFail) colorClass = "status-kyc-fail";
    else if (en.statusText === "APPROVED") colorClass = "status-approved";
    else if (en.statusText === "COMPLETED") colorClass = "status-completed";
    else if (en.statusText === "CANCELLED") colorClass = "status-cancelled";

    rows.push([
        p.ships ? p.ships.split('@')[0] : "-",
        formatDateDisplay(p.date),
        p.Position || "-",
        finalShipName,
        `<span class="${colorClass}">${en.statusText}</span>`,
        p.ETA || "-",
        en.imo,
        finalCallSign,
        `<span class="dv-table-fixed-line">${dv.fileLink(p.file.path, false, p.subject)}</span>`
    ]);
}

dv.table(["油輪", "日期", "位置", "船名", "狀態", "ETA", "IMO", "呼號", "主旨"], rows);

let exportBtn = controlContainer.createEl('button', {text: "📊 匯出"}); 
exportBtn.style.cssText = "margin-left: auto; padding: 5px 12px; background: #4CAF50; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;";
exportBtn.onclick = () => { 
    let csv = "\ufeff" + ["油輪", "日期", "位置", "船名", "狀態", "ETA", "IMO", "呼號"].join(",") + "\n";
    rows.forEach(r => { 
        let cleanRow = r.slice(0, 8).map(cell => `"${String(cell).replace(/<[^>]*>/g, "").replace(/,/g, "，")}"`);
        csv += cleanRow.join(",") + "\n"; 
    });
    let blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    let url = URL.createObjectURL(blob);
    let a = document.createElement("a"); a.href = url; a.download = `船隊報表_${new Date().toISOString().slice(0,10)}.csv`; a.click();
};
```