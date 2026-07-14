---
查詢狀態: approved
開始日期: 2026-07-13
結束日期: 2026-07-16
查詢類別:
查詢船隻: oceanace@gtmailplus.com
排序欄位: status
排序方向: desc
---

```dataviewjs
// ==========================================
// 1. 基礎設定與 CSS 注入
// ==========================================
let currentPage = dv.current();
if (!currentPage || !currentPage.file) {
    dv.paragraph("⏳ 系統載入中...");
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

// --- 建立控制面板 ---
let controlContainer = this.container.createEl("div");
controlContainer.style.cssText = "display: flex; gap: 12px; margin-bottom: 15px; align-items: center; flex-wrap: wrap; padding: 15px; background-color: var(--background-secondary); border-radius: 10px; border: 1px solid var(--background-modifier-border);";

let reportArea = this.container.createEl("div");
reportArea.style.cssText = "display: none; margin-bottom: 15px; padding: 15px; background-color: rgba(33, 150, 243, 0.1); border-left: 5px solid #2196F3; border-radius: 4px; font-size: 0.95em;";

// ==========================================
// 2. 獲取 Kingdee JSON 資料
// ==========================================
let shipMap = {};
const basePath = app.vault.adapter.getBasePath();
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
// 3. 更新按鈕 (不用插件，直接跑 Git 指令)
// ==========================================
let updateBtn = controlContainer.createEl('button', {text: "📥 更新郵件"}); 
updateBtn.style.cssText = "padding: 6px 15px; background: #2196F3; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;";

updateBtn.onclick = async () => { 
    // 1. 記錄執行前的檔案清單
    let beforePaths = dv.pages('"data_John"').file.path.array();
    
    updateBtn.innerText = "⏳ 抓取中..."; 
    updateBtn.style.backgroundColor = "#ff9800"; 
    
    const { exec } = require('child_process');
    
    // 第一步：執行爬蟲 AppleScript
    exec(`osascript "${basePath}/script.scpt"`, async (error) => { 
        if (error) { 
            new Notice('❌ 爬取失敗: ' + error.message); 
            updateBtn.innerText = "❌ 失敗"; 
        } else { 
            updateBtn.innerText = "🔍 彙整中..."; 
            await new Promise(r => setTimeout(r, 3000)); // 等待索引
            
            let newPages = dv.pages('"data_John"').where(p => !beforePaths.includes(p.file.path));

            // 第二步：彈窗詢問是否部署
            if (confirm(`抓取完畢！新增了 ${newPages.length} 筆。是否要同步到 GitHub 網頁？`)) {
                updateBtn.innerText = "📤 正在上傳...";
                
                // 直接執行 Git 指令串 (add + commit + push)
                // 注意：這裡假設您的終端機已經具備 GitHub 推送權限
                let gitCmd = `cd "${basePath}" && git add . && git commit -m "Auto update via button" && git push origin main`;
                
                exec(gitCmd, (gError, stdout, stderr) => {
                    if (gError) {
                        new Notice('❌ GitHub 同步失敗，請檢查權限');
                        console.error(gError);
                    } else {
                        new Notice('✅ 網頁同步成功！');
                    }
                });
            }

            // 顯示報告
            if (newPages.length > 0) {
                reportArea.innerHTML = `<b>📊 更新完成：新增 ${newPages.length} 筆郵件</b><br><hr>` + newPages.map(p => `📄 ${p.subject}`).join("<br>");
                reportArea.style.display = "block";
            }
            updateBtn.innerText = "✅ 完成"; 
            updateBtn.style.backgroundColor = "#4CAF50"; 
        } 
        setTimeout(() => { 
            updateBtn.innerText = "📥 更新郵件"; 
            updateBtn.style.backgroundColor = "#2196F3"; 
        }, 5000); 
    }); 
};

// ==========================================
// 4. 篩選器 UI (日期、類別、油輪)
// ==========================================

// 日期區間 (純手刻 popup 日曆，單一欄位、無外部依賴，不會被 CSP 擋)
controlContainer.createEl("span", {text: "📅 範圍：", attr: {style: "font-weight: bold; margin-left: 5px;"}});
let dateRangeInput = controlContainer.createEl("input", {type: "text"});
dateRangeInput.readOnly = true;
dateRangeInput.style.cssText = "padding: 5px; border-radius: 4px; border: 1px solid var(--background-modifier-border); width: 190px; text-align: center; cursor: pointer; background: var(--background-primary);";
dateRangeInput.value = (currentPage.開始日期 && currentPage.結束日期) ? `${currentPage.開始日期} ~ ${currentPage.結束日期}` : "點擊選擇日期區間";

let rangeStart = currentPage.開始日期 || null;
let rangeEnd = currentPage.結束日期 || null;
let pickingStart = null; // 暫存第一次點擊的日期，用來判斷是選起點還是終點

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
                // 第一次點擊：設為起點，清空舊區間
                pickingStart = iso;
                rangeStart = iso;
                rangeEnd = null;
            } else {
                // 第二次點擊：決定起訖 (自動排序)
                rangeEnd = iso > pickingStart ? iso : pickingStart;
                rangeStart = iso > pickingStart ? pickingStart : iso;
                pickingStart = null;
                dateRangeInput.value = `${rangeStart} ~ ${rangeEnd}`;
                await app.fileManager.processFrontMatter(file, fm => {
                    fm["開始日期"] = rangeStart;
                    fm["結束日期"] = rangeEnd;
                });
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
        // 每次打開都完全重新開始：清空選取狀態與範圍高亮，不沿用上次結果
        pickingStart = null;
        rangeStart = null;
        rangeEnd = null;
        let rect = dateRangeInput.getBoundingClientRect();
        popup.style.left = `${rect.left}px`;
        popup.style.top = `${rect.bottom + 4}px`;
        renderCalendar();
        popup.style.display = "block";
    } else {
        popup.style.display = "none";
    }
};
document.addEventListener("click", (e) => {
    if (!popup.contains(e.target) && e.target !== dateRangeInput) popup.style.display = "none";
});

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
// 5. 🚀 新增排序檢索 UI
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
    await app.fileManager.processFrontMatter(file, fm => {
        fm["排序欄位"] = sortFieldSelect.value;
        fm["排序方向"] = sortDirSelect.value;
    });
};
sortFieldSelect.onchange = updateSort;
sortDirSelect.onchange = updateSort;

// ==========================================
// 6. 資料處理與排序邏輯
// ==========================================

// 把 target 字串 (可能包含多艘船，用 " | " 分隔) 拆成多筆 {fv, imo}
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

// 先做「頁面層級」的篩選 (日期、油輪)，跟船隻數量無關
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

// 攤平：一封信有幾艘船，就展開成幾筆 entry，每筆各自查 JSON、各自判斷狀態
let allEntries = [];
for (let p of basePages) {
    let shipEntries = parseShipEntries(p.target);
    for (let s of shipEntries) {
        let isKycFail = (s.imo !== "-" && !shipMap[s.imo]);
        let statusText = isKycFail ? "KYC未通過" : (p.category ? p.category.toUpperCase() : "PENDING");
        allEntries.push({
            page: p,
            fv: s.fv,
            imo: s.imo,
            isKycFail,
            statusText
        });
    }
}

// 狀態篩選 (現在是針對每一艘船，而不是整封信)
let entries = allEntries.filter(en => {
    if (currentPage.查詢類別 && currentPage.查詢類別 !== "全部" && en.statusText !== currentPage.查詢類別) return false;
    return true;
});

// 執行排序
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

// 格式化日期顯示：優先用 Dataview 的 toFormat()（正確處理時間/時區），沒有的話 fallback 用字串切法
const formatDateDisplay = (d) => {
    if (!d) return "-";
    if (typeof d.toFormat === "function") {
        return d.toFormat("MM|dd");
    }
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

// 匯出按鈕
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