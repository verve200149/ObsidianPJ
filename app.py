import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os, yaml, json, re, io
from datetime import datetime

# 建議將網頁預設為寬螢幕佈局
st.set_page_config(layout="wide", page_title="船隊調度管理系統", page_icon="🚢")

# 自定義 CSS (打造清爽的郵箱風格 UI + 手機版篩選器強制同行優化)
st.markdown("""
    <style>
    /* 調整指標數字大小與顏色 (商務藍) */
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #1a73e8; font-weight: 600; }
    
    /* 隱藏預設的 DataFrame index */
    .row_heading.level0 {display:none}
    .blank {display:none}
    
    /* 右側郵件閱讀器的精美樣式 */
    .email-pane { 
        background-color: #ffffff; 
        color: #333333; 
        padding: 25px; 
        border-radius: 8px; 
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        height: 500px;
        box-sizing: border-box;
        overflow-y: auto;
    }
    .email-header {
        border-bottom: 1px solid #eeeeee;
        padding-bottom: 12px;
        margin-bottom: 20px;
    }
    .email-subject { 
        font-size: 1.3em; 
        font-weight: bold; 
        color: #202124; 
        margin-bottom: 8px;
    }
    .email-meta {
        font-size: 0.9em; 
        color: #5f6368; 
    }
    .email-body {
        white-space: pre-wrap; 
        font-family: 'Consolas', 'Courier New', monospace; 
        font-size: 14px;
        line-height: 1.6;
        color: #444444;
    }

    /* 手機版篩選器元件內縮與緊湊化，防止同行時內容爆出去 */
    @media (max-width: 640px) {
        div[id="mobile-filter-container"] label {
            font-size: 0.75rem !important; /* 縮小上方標題如 「🚢 篩選油輪」 */
        }
        div[id="mobile-filter-container"] div[data-testid="stMarkdownContainer"] p {
            font-size: 0.75rem !important;
        }
        div[id="mobile-filter-container"] div[data-baseweb="select"] {
            font-size: 0.75rem !important; /* 縮小下拉選單內文字 */
        }
        div[id="mobile-filter-container"] input {
            font-size: 0.7rem !important;  /* 縮小日期輸入框文字 */
            padding: 2px 4px !important;
        }
        /* 讓下拉選單與日期高度更緊湊 */
        div[id="mobile-filter-container"] div[data-baseweb="base-input"] {
            min-height: 30px !important;
            height: 30px !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 讀取 Update Log ---
def load_update_log():
    if os.path.exists('update_log.json'):
        try:
            with open('update_log.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
    return None

# --- 2. 讀取 Kingdee JSON ---
@st.cache_data(ttl=600)
def load_ship_map():
    if os.path.exists('Kingdee_Export_UTF8.json'):
        try:
            with open('Kingdee_Export_UTF8.json', 'r', encoding='utf-8-sig') as f:
                return {str(item.get('imo', '')).strip(): item for item in json.load(f)}
        except: return {}
    return {}

ship_map = load_ship_map()

# --- 3. 解析工具 ---
def clean_mail_field(raw):
    """把 Obsidian 常見的 Markdown 連結格式 [顯示文字](mailto:xxx) 還原成純文字，
    避免直接 split('@') 時抓到帶有中括號的錯誤字串。"""
    if not raw:
        return ""
    raw = str(raw)
    raw = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', raw)
    return raw.strip()

def parse_ship_entries(target):
    """解析 target 欄位。若本次沒有實際船隻資料 (本次無資料)，
    仍回傳一筆佔位資料，讓這封信在前端能被分類、被看見，
    而不是直接消失。"""
    if not target or str(target).strip() == "(本次無資料)":
        return [{"fv": "(本次無資料)", "imo": "-"}]
    segments = [s.strip() for s in str(target).split('|') if s.strip()]
    res = []
    for seg in segments:
        fv = re.search(r'FV:(.*?)丨', seg)
        if not fv: fv = re.search(r'FV:(.*)$', seg)
        imo = re.search(r'IMO:(\d+)', seg)
        res.append({"fv": fv.group(1).strip() if fv else "-", "imo": imo.group(1).strip() if imo else "-"})
    return res

@st.cache_data(ttl=60)
def build_tanker_excel(full_df: pd.DataFrame) -> bytes:  # 💥 修正 SyntaxError
    """把「全部資料」(不受網頁篩選條件影響) 依油輪分頁匯出成一份 Excel，
    每個分頁就是一艘油輪的完整資料範圍，分頁名稱直接用油輪代碼命名。"""
    output = io.BytesIO()
    export_df = full_df.drop(columns=["原始內文"], errors="ignore")

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        tankers = sorted([t for t in export_df["油輪"].unique() if t and t != "-"])
        used_names = set()

        for tanker in tankers:
            sheet_df = export_df[export_df["油輪"] == tanker].sort_values(
                by=["日期", "主旨"], ascending=[False, False]
            )

            safe_name = re.sub(r'[\\/*?:\[\]]', '_', str(tanker))[:31] or "sheet"
            base_name, n = safe_name, 1
            while safe_name in used_names:
                suffix = f"_{n}"
                safe_name = base_name[: 31 - len(suffix)] + suffix
                n += 1
            used_names.add(safe_name)

            sheet_df.to_excel(writer, sheet_name=safe_name, index=False)

            ws = writer.sheets[safe_name]
            for col_idx, col in enumerate(sheet_df.columns, start=1):
                values = sheet_df[col].astype(str).tolist()
                max_len = max([len(str(col))] + [len(v) for v in values]) if values else len(str(col))
                ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 50)
            ws.freeze_panes = "A2"

        if not tankers:
            # 💥 修正 SyntaxError
            pd.DataFrame().to_excel(writer, sheet_name="無資料", index=False)

    return output.getvalue()

@st.cache_data(ttl=60)
def load_all_data():
    rows = []
    parse_errors = []
    DATA_DIR = 'data_John'
    if not os.path.exists(DATA_DIR):
        return pd.DataFrame(rows), parse_errors # 💥 修正 SyntaxError
        
    EXCLUDE_FILES = {'checklist.md', 'schedule操作介面.md'}
    for root, _, files in os.walk(DATA_DIR):
        if any(ex in root for ex in ['.git', '.obsidian']): continue
        for file in files:
            if not (file.endswith('.md') and file not in EXCLUDE_FILES):
                continue
            fpath = os.path.join(root, file)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    raw_text = f.read()

                if not raw_text.startswith('---'):
                    parse_errors.append((fpath, "找不到 YAML frontmatter (檔案未以 --- 開頭)"))
                    continue

                parts = raw_text.split('---')
                if len(parts) < 3:
                    parse_errors.append((fpath, "YAML frontmatter 格式不完整 (--- 數量不足)"))
                    continue

                fm = yaml.safe_load(parts[1])
                if not fm:
                    parse_errors.append((fpath, "YAML 解析結果為空"))
                    continue

                body = '---'.join(parts[2:]).strip()
                ships = parse_ship_entries(fm.get('target', ''))
                for s in ships:
                    s_info = ship_map.get(s['imo'], {})
                    is_kyc_fail = (s['imo'] != "-" and s['imo'] not in ship_map)
                    rows.append({
                        "油輪": clean_mail_field(fm.get('ships', '')).split('@')[0] or '-',
                        "日期": pd.to_datetime(fm.get('date')) if fm.get('date') else pd.NaT, # 內部維持叫「日期」
                        "位置": fm.get('Position', '-') or '-',
                        "船名": s_info.get('name', s['fv']),
                        "狀態": "KYC未通過" if is_kyc_fail else str(fm.get('category', 'PENDING')).upper(),
                        "ETA": fm.get('ETA', '-') or '-',
                        "IMO": s['imo'],
                        "呼號": s_info.get('callSign', "-"),
                        "主旨": fm.get('subject', '-'),
                        "原始內文": body
                    })
            except Exception as e:
                parse_errors.append((fpath, f"{type(e).__name__}: {e}"))
                continue
    # 💥 修正 SyntaxError
    return pd.DataFrame(rows), parse_errors

# --- 4. 分割版面 (固定 3 欄結構) ---
def apply_split_layout(marker_id: str, n_selected: int):
    js = f"""
    <script>
    (function() {{
        function findTargetBlock(doc, marker) {{
            const allBlocks = Array.from(doc.querySelectorAll('[data-testid="stHorizontalBlock"]'));
            for (const b of allBlocks) {{
                if (marker.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) return b;
            }}
            return null;
        }}

        function setupHandle(doc, hBlock, id, left, right) {{
            const old = hBlock.querySelector('#' + id);
            if (old) old.remove();
            const h = doc.createElement('div');
            h.id = id;
            h.style.cssText = 'flex:0 0 8px;width:8px;cursor:col-resize;position:relative;z-index:999;display:flex;align-items:center;justify-content:center;';
            h.innerHTML = '<div style="width:2px;height:32px;background:#4a4a4a;border-radius:2px;pointer-events:none;"></div>';
            h.addEventListener('mouseenter', () => {{ h.firstChild.style.background = '#1a73e8'; }});
            h.addEventListener('mouseleave', () => {{ if (!h.dataset.dragging) h.firstChild.style.background = '#4a4a4a'; }});
            h.addEventListener('mousedown', (e) => {{
                h.dataset.dragging = '1';
                h.firstChild.style.background = '#1a73e8';
                doc.body.style.userSelect = 'none';
                e.preventDefault();
                const onMove = (ev) => {{
                    const lRect = left.getBoundingClientRect();
                    const rRect = right.getBoundingClientRect();
                    const combinedLeft = lRect.left;
                    const combinedWidth = rRect.right - lRect.left;
                    let newLeftWidth = ev.clientX - combinedLeft;
                    const minW = 80;
                    if (newLeftWidth < minW) newLeftWidth = minW;
                    if (newLeftWidth > combinedWidth - minW) newLeftWidth = combinedWidth - minW;
                    const pct = newLeftWidth / combinedWidth;
                    left.style.flex = pct + ' 1 0px';
                    right.style.flex = (1 - pct) + ' 1 0px';
                }};
                const onUp = () => {{
                    h.dataset.dragging = '';
                    h.firstChild.style.background = '#4a4a4a';
                    doc.body.style.userSelect = '';
                    doc.removeEventListener('mousemove', onMove);
                    doc.removeEventListener('mouseup', onUp);
                }};
                doc.addEventListener('mousemove', onMove);
                doc.addEventListener('mouseup', onUp);
            }});
            right.parentNode.insertBefore(h, right);
            return h;
        }}

        let attempts = 0;
        function init() {{
            attempts++;
            const doc = window.parent.document;
            const marker = doc.getElementById('{marker_id}');
            if (!marker) {{ if (attempts < 30) setTimeout(init, 80); return; }}
            const hBlock = findTargetBlock(doc, marker);
            if (!hBlock) {{ if (attempts < 30) setTimeout(init, 80); return; }}
            const cols = Array.from(hBlock.children).filter(c => c.getAttribute && c.getAttribute('data-testid') === 'stColumn');
            if (cols.length < 3) {{ if (attempts < 30) setTimeout(init, 80); return; }}

            hBlock.style.display = 'flex';
            hBlock.style.alignItems = 'stretch';
            const [c0, c1, c2] = cols;
            [c0, c1, c2].forEach(c => {{ c.style.overflow = 'hidden'; c.style.minWidth = '0'; c.style.transition = 'none'; }});

            const handle1 = setupHandle(doc, hBlock, 'split-handle-1', c0, c1);
            const handle2 = setupHandle(doc, hBlock, 'split-handle-2', c1, c2);

            const n = {n_selected};
            if (n === 0) {{
                c0.style.flex = '1 1 100%'; c0.style.display = '';
                c1.style.display = 'none';
                c2.style.display = 'none';
                handle1.style.display = 'none';
                handle2.style.display = 'none';
            }} else if (n === 1) {{
                c0.style.display = ''; c1.style.display = ''; c2.style.display = 'none';
                c0.style.flex = '1 1 0px'; c1.style.flex = '1 1 0px';
                handle1.style.display = 'flex';
                handle2.style.display = 'none';
            }} else {{
                c0.style.display = ''; c1.style.display = ''; c2.style.display = '';
                c0.style.flex = '1 1 0px'; c1.style.flex = '1 1 0px'; c2.style.flex = '1 1 0px';
                handle1.style.display = 'flex';
                handle2.style.display = 'flex';
            }}
        }}
        setTimeout(init, 60);
    }})();
    </script>
    """
    components.html(js, height=0, width=0)

# --- 5. 強制手機版篩選器維持同一行不拆行 ---
def apply_mobile_filter_layout():
    js = """
    <script>
    (function() {
        let attempts = 0;
        function fixFilter() {
            attempts++;
            const doc = window.parent.document;
            const container = doc.getElementById('mobile-filter-container');
            if (!container) {
                if (attempts < 30) setTimeout(fixFilter, 80);
                return;
            }
            
            const hBlock = container.querySelector('[data-testid="stHorizontalBlock"]');
            if (!hBlock) return;
            
            hBlock.style.setProperty('display', 'flex', 'important');
            hBlock.style.setProperty('flex-direction', 'row', 'important');
            hBlock.style.setProperty('flex-wrap', 'nowrap', 'important');
            hBlock.style.setProperty('gap', '8px', 'important');
            
            const cols = Array.from(hBlock.children).filter(c => c.getAttribute && c.getAttribute('data-testid') === 'stColumn');
            cols.forEach(col => {
                col.style.setProperty('flex', '1 1 0%', 'important');
                col.style.setProperty('min-width', '0', 'important');
                col.style.setProperty('width', 'auto', 'important'); 
            });
        }
        setTimeout(fixFilter, 50);
    })();
    </script>
    """
    components.html(js, height=0, width=0)

# --- 介面渲染 ---
st.markdown("""
    <div class="compact-title">🚢 船隊實時調度報表</div>
    """, unsafe_allow_html=True)

# 載入資料庫
df, parse_errors = load_all_data()

if parse_errors:
    with st.sidebar.expander(f"⚠️ 解析失敗的信件 ({len(parse_errors)} 筆)"):
        for fpath, err in parse_errors:
            st.write(f"`{fpath}`")
            st.caption(err)

# 數據看板 (Metrics)
log = load_update_log()
if log:
    update_time = log.get('update_time', '未知')
    total_files = log.get('total_files', 0)
    latest_date_str = log.get('latest_date_str', '未知')
    latest_emails = log.get('latest_emails', 0)
    latest_imos = log.get('latest_imos', 0)
    latest_nodata = log.get('latest_nodata', 0)
    total_targets = latest_imos + latest_nodata

    with st.expander(f"📊 資料看板：總信件庫 {total_files} 封 ・ 最新 {latest_emails} 封 ・ 最後同步 {update_time}", expanded=False):
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("📁 總信件庫", f"{total_files} 封")
        col_m2.metric(f"📅 最新 ({latest_date_str})", f"{latest_emails} 封")
        col_m3.metric("🚢 最新解析郵件", f"{total_targets} 筆")
        col_m4.metric("⏱️ 最後同步時間", update_time)

if not df.empty:
    # 頂部篩選器
    st.markdown('<div id="mobile-filter-container">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        sel_tanker = st.selectbox("🚢 篩選油輪", tankers)
    with c2:
        dynamic_statuses = ["全部"] + sorted(list(df["狀態"].unique()))
        sel_status = st.selectbox("📂 篩選狀態", dynamic_statuses)
    with c3:
        valid_dates = df["日期"].dropna()
        m_date = valid_dates.min().date() if not valid_dates.empty else datetime.today().date()
        x_date = valid_dates.max().date() if not valid_dates.empty else datetime.today().date()
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date))
    st.markdown('</div>', unsafe_allow_html=True)

    apply_mobile_filter_layout()

    # 資料過濾邏輯
    mask = pd.Series([True] * len(df))
    if sel_tanker != "全部": mask &= (df["油輪"] == sel_tanker)
    if sel_status != "全部": mask &= (df["狀態"] == sel_status)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        start_dt = pd.to_datetime(sel_range[0])
        end_dt = pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
        mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

    display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False]).reset_index(drop=True)

    st.info("💡 點擊左側表格內的任意郵件，即可在分割預覽完整內容。")

    DF_KEY = "email_table"
    if "sel_seq" not in st.session_state:
        st.session_state.sel_seq = {}   
    if "sel_counter" not in st.session_state:
        st.session_state.sel_counter = 0

    _hint_rows = st.session_state.get(DF_KEY, {}).get("selection", {}).get("rows", [])
    guess_has_selection = len(st.session_state.sel_seq) > 0 or len(_hint_rows) > 0

    if not guess_has_selection:
        marker_id = None
        col_list = st.container()
        preview_cols = []
    else:
        marker_id = "split-marker"
        st.markdown(f'<div id="{marker_id}"></div>', unsafe_allow_html=True)
        col_list, col_preview1, col_preview2 = st.columns([1, 1, 1], gap="small")
        preview_cols = [col_preview1, col_preview2]

    with col_list:
        # =========================================================
        # 💡 【動態表格設定區】未來你要改標題或順序，只要在這裡改！
        # =========================================================
        # 1. 指定顯示順序 (注意：請填寫 Pandas 內部的原始欄位名稱)
        DISPLAY_COLUMNS = ["油輪", "日期", "狀態", "船名", "IMO", "呼號", "ETA", "位置", "主旨"]

      # 2a. 狀態顏色邏輯 (背景 30% 不透明度，字體加粗、不變淡且縮小至 12px)
        def style_status(val):
            val_upper = str(val).upper().strip()
            # font-size: 12px 讓字體變小，同時維持原本的高對比度文字顏色
            if "APPROVED" in val_upper: 
                return "background-color: rgba(250, 225, 50, 0.3); color: #554400; font-weight: bold; font-size: 10px;"
            elif "COMPLETED" in val_upper: 
                return "background-color: rgba(255, 128, 128, 0.3); color: #801a1a; font-weight: bold; font-size: 10px;"
            elif "CANCELLED" in val_upper or "KYC" in val_upper: 
                return "background-color: rgba(230, 120, 230, 0.3); color: #661166; font-weight: bold; font-size: 10px;"
            elif "PENDING" in val_upper: 
                return "background-color: rgba(255, 243, 205, 0.3); color: #664D03; font-weight: bold; font-size: 10px;"
            return ""

# 2b. 判斷並標示「有效配對」的 IMO 邏輯
        # 條件：同一油輪、同一IMO，存在「APPROVED」與「COMPLETED」，且 COMPLETED 晚於 APPROVED 並在 7 天內
        valid_dup_indices = set()
        
        # 排除無效 IMO 的資料來提升比對效率
        valid_imo_mask = ~display_df['IMO'].isin(['-', '', '(本次無資料)'])
        valid_df = display_df[valid_imo_mask]
        
        # 依照 油輪 與 IMO 分組進行檢查
        for (tanker, imo), group in valid_df.groupby(['油輪', 'IMO']):
            # 抓出該群組內的 APPROVED 與 COMPLETED 紀錄
            approved_rows = group[group['狀態'].str.contains('APPROVED', case=False, na=False)]
            completed_rows = group[group['狀態'].str.contains('COMPLETED', case=False, na=False)]
            
            # 只有當兩者都存在時，才進一步比對時間
            if not approved_rows.empty and not completed_rows.empty:
                for a_idx, a_row in approved_rows.iterrows():
                    for c_idx, c_row in completed_rows.iterrows():
                        a_time = a_row['日期']
                        c_time = c_row['日期']
                        
                        # 確保時間欄位不是空值
                        if pd.notnull(a_time) and pd.notnull(c_time):
                            time_diff = c_time - a_time
                            
                            # 判斷邏輯：COMPLETED 時間 > APPROVED 時間，且相差 <= 7 天
                            if pd.Timedelta(0) < time_diff <= pd.Timedelta(days=7):
                                # 條件符合，將這兩個紀錄的 Index 加入發光名單
                                valid_dup_indices.add(a_idx)
                                valid_dup_indices.add(c_idx)

        def style_duplicate_imo(s):
            # 針對被標記為有效配對的 IMO 欄位，套用橘色半透明背景 (50%) 與粗體
            return ['background-color: rgba(253, 126, 20, 0.1); font-weight: bold;' if i in valid_dup_indices else '' for i in s.index]

        # 3. 疊加套用樣式：先上狀態顏色，再針對 IMO 欄位上重複顏色
        styled_df = display_df[DISPLAY_COLUMNS].style.map(style_status, subset=["狀態"])
        styled_df = styled_df.apply(style_duplicate_imo, subset=["IMO"]) # 👈 在這疊加上去！
        
        event = st.dataframe(
            styled_df,  
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="multi-row",
            key=DF_KEY,
            height=500,
            column_config={
                # 前端動態改名：把原名為 "日期" 的欄位，在畫面上顯示成 "收信時間"
                "日期": st.column_config.DatetimeColumn("收信時間", format="MM/DD HH:mm"), 
                "狀態": st.column_config.TextColumn("狀態", width="small"),
                "主旨": st.column_config.TextColumn("郵件主旨", width="medium")
            }
        )
        # =========================================================
        
        st.markdown("<br>", unsafe_allow_html=True)
        exp_c1, exp_c2 = st.columns(2)
        with exp_c1:
            st.download_button(
                f"📊 匯出目前篩選 ({len(display_df)} 筆)", 
                display_df.to_csv(index=False).encode('utf-8-sig'), 
                "ship_report.csv", 
                "text/csv"
            )
        with exp_c2:
            st.download_button(
                f"🗂️ 匯出全部資料 (依油輪分頁，{df['油輪'].nunique()} 個分頁)",
                build_tanker_excel(df),
                "ship_report_by_tanker.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # === 更新序號並計算預覽項目 ===
    raw_rows = event.get("selection", {}).get("rows", [])
    raw_set = set(raw_rows)

    for r in list(st.session_state.sel_seq.keys()):
        if r not in raw_set:
            del st.session_state.sel_seq[r]

    for r in raw_rows:
        if r not in st.session_state.sel_seq:
            st.session_state.sel_counter += 1
            st.session_state.sel_seq[r] = st.session_state.sel_counter

    all_checked = sorted(st.session_state.sel_seq.keys(), key=lambda r: st.session_state.sel_seq[r])
    preview_order = all_checked[-2:] if len(all_checked) > 2 else all_checked
    n_selected = len(preview_order)

    if len(all_checked) > 2:
        st.warning(
            f"⚠️ 目前勾選了 {len(all_checked)} 筆，僅預覽最後選取的 2 筆。"
            "若要讓表格勾選狀態也只剩 2 筆，請手動取消較舊的勾選。"
        )

    if marker_id:
        apply_split_layout(marker_id, n_selected)

    def render_email_pane(container, row):
        time_str = row['日期'].strftime('%Y-%m-%d %H:%M') if pd.notnull(row['日期']) else '未知時間'
        with container:
            st.markdown(f'''
            <div class="email-pane">
                <div class="email-header">
                    <div class="email-subject">{row['主旨']}</div>
                    <div class="email-meta">
                        🚢 <b>{row['油輪']}</b> &nbsp; | &nbsp; 📅 {time_str} &nbsp; | &nbsp; 📂 {row['狀態']}
                    </div>
                </div>
                <div class="email-body">{row["原始內文"]}</div>
            </div>
            ''', unsafe_allow_html=True)

    for i, row_idx in enumerate(preview_order):
        if i < len(preview_cols) and row_idx < len(display_df):
            render_email_pane(preview_cols[i], display_df.iloc[row_idx])

    if (n_selected == 0) != (not guess_has_selection):
        st.rerun()
