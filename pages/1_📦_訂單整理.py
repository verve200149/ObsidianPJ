import streamlit as st
import pandas as pd
import os, yaml, re, io, json, uuid
from datetime import datetime

st.set_page_config(layout="wide", page_title="訂單整理", page_icon="📦")

# 初始化 Session State
if "deleted_uids" not in st.session_state:
    st.session_state["deleted_uids"] = set()
if "df_key_counter" not in st.session_state:
    st.session_state["df_key_counter"] = 0

st.markdown("""
    <style>
    .compact-title {
        font-size: 1.8rem;
        font-weight: 800;
        margin: 0 0 0.4rem 0;
        line-height: 1.2;
        white-space: nowrap;
    }
    @media (max-width: 640px) {
        .compact-title { font-size: 1.25rem; }
    }
    
    /* === 🚀 魔法區：強制懸浮刪除按鈕 === */
    /* 我們將刪除按鈕設為 primary，並強制絕對定位到右上角 */
    button[kind="primary"] {
        position: absolute !important;
        right: 15px !important;
        top: 15px !important;
        z-index: 999 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2) !important;
    }

    .email-pane {
        background-color: #ffffff;
        color: #333333;
        padding: 20px;
        border-radius: 8px;
        /* 向上推移，吃掉按鈕原本佔據的空白行距，讓畫面完美貼齊 */
        margin-top: -45px; 
    }
    .email-subject { 
        font-size: 1.2em; 
        font-weight: bold; 
        color: #202124; 
        margin-bottom: 8px; 
        /* 預留右邊距，避免長標題被右上角的浮動按鈕遮擋 */
        padding-right: 90px; 
    }
    .email-meta { font-size: 0.95em; color: #5f6368; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #eaeaea; }
    .email-body {
        white-space: pre-wrap;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 14px;
        line-height: 1.6;
        color: #444444;
    }
    </style>
    <div class="compact-title">📦 訂單整理</div>
    """, unsafe_allow_html=True)


@st.cache_data(ttl=600)
def load_whitelist_dict():
    """讀取 Kingdee 輸出的 JSON 作為白名單比對，回傳 Dict {imo: callSign}。"""
    if os.path.exists("Kingdee_Export_UTF8.json"):
        try:
            with open("Kingdee_Export_UTF8.json", "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                return {
                    str(item.get("imo", "")).strip(): str(item.get("callSign", item.get("callsign", ""))).strip()
                    for item in data if str(item.get("imo", "")).strip()
                }
        except Exception as e:
            st.sidebar.warning(f"⚠️ 無法讀取 Kingdee_Export_UTF8.json: {e}")
    return {}


def parse_metadata_robust(header_text: str) -> dict:
    """雙軌解析機制：優先使用標準 yaml 解析，失敗則轉為正則提取"""
    try:
        data = yaml.safe_load(header_text)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass

    data = {}
    fields = ["date", "sender", "subject", "quantity", "contact", "release_status", "status"]
    for field in fields:
        pattern = rf"{field}:\s*\"?(.*?)\"?(?=\s*(?:{'|'.join(fields)}):|$)"
        match = re.search(pattern, header_text, re.DOTALL)
        if match:
            val = match.group(1).strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            data[field] = val
    return data


@st.cache_data(ttl=60)
def load_cn_data():
    """讀取 data_CN/ 底下的 .md 檔案，支援單一信件內包含多個 IMO 的拆解"""
    rows = []
    parse_errors = []
    base_dir = "data_CN"

    valid_imos_dict = load_whitelist_dict()

    if not os.path.isdir(base_dir):
        return pd.DataFrame(), parse_errors

    for root, _, files in os.walk(base_dir):
        for file in files:
            if not file.endswith(".md"):
                continue
            fpath = os.path.join(root, file)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    raw_text = f.read()

                if not raw_text.startswith("---"):
                    parse_errors.append((fpath, "找不到 YAML frontmatter (檔案未以 --- 開頭)"))
                    continue

                parts = raw_text.split("---")
                if len(parts) < 3:
                    parse_errors.append((fpath, "YAML frontmatter 格式不完整 (--- 數量不足)"))
                    continue

                fm = parse_metadata_robust(parts[1])
                if not fm:
                    parse_errors.append((fpath, "YAML 區塊解析結果為空"))
                    continue

                body = "---".join(parts[2:]).strip()

                date_val = fm.get("date")
                parsed_date = pd.NaT
                if date_val:
                    try:
                        parsed_date = pd.to_datetime(date_val)
                    except Exception:
                        pass

                sender_val = str(fm.get("sender", "-") or "-").strip()
                if len(sender_val.split()) == 1 and "@" in sender_val:
                    sender_clean = sender_val.split("@")[0].replace("<", "").replace(">", "")
                elif "@" in sender_val:
                    name_parts = [p for p in sender_val.split() if "@" not in p]
                    if name_parts:
                        sender_clean = " ".join(name_parts).replace('"', '').replace("'", "")
                    else:
                        sender_clean = sender_val.split("@")[0].replace("<", "").strip()
                else:
                    sender_clean = sender_val

                contact_val = str(fm.get("contact", "-") or "-")
                imo_matches = re.findall(r"IMO.*?(\d{7})", contact_val, re.IGNORECASE)

                if not imo_matches:
                    imo_matches = [""]

                for imo_num in imo_matches:
                    if not imo_num:
                        callsign_status = "無IMO"
                    elif imo_num in valid_imos_dict:
                        callsign_status = valid_imos_dict[imo_num]
                    else:
                        callsign_status = "KYC"

                    rows.append({
                        "_uid": str(uuid.uuid4()), # 給予每筆資料唯一碼，方便刪除追蹤
                        "日期": parsed_date,
                        "寄件者": sender_clean,
                        "主旨": fm.get("subject", "-") or "-",
                        "數量": fm.get("quantity", "-") or "-",
                        "處理": "",  # 暫時留空，供後續人工填寫處理狀態
                        "IMO": imo_num,
                        "聯繫方式": contact_val,
                        "放行狀態": fm.get("release_status", "-") or "-",
                        "呼號": callsign_status,
                        "原始內文": body,
                    })
            except Exception as e:
                parse_errors.append((fpath, f"{type(e).__name__}: {e}"))
                continue

    return pd.DataFrame(rows), parse_errors


@st.cache_data(ttl=60)
def build_cn_excel(export_df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    # 匯出時排除原始內文與內部使用的 _uid
    clean_df = export_df.drop(columns=["原始內文", "_uid"], errors="ignore").copy()

    if "日期" in clean_df.columns:
        clean_df["日期"] = clean_df["日期"].dt.date

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        clean_df.to_excel(writer, sheet_name="訂單整理", index=False)
        ws = writer.sheets["訂單整理"]
        for col_idx, col in enumerate(clean_df.columns, start=1):
            values = clean_df[col].astype(str).tolist()
            max_len = max([len(str(col))] + [len(v) for v in values]) if values else len(str(col))
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)
        ws.freeze_panes = "A2"

    return output.getvalue()


def style_alerts(val):
    if val == "KYC":
        return "background-color: #A31D1D; color: white;" 
    return ""


df_raw, parse_errors = load_cn_data()

if parse_errors:
    with st.sidebar.expander(f"⚠️ 解析失敗的信件 ({len(parse_errors)} 筆)"):
        for fpath, err in parse_errors:
            st.write(f"`{fpath}`")
            st.caption(err)

# 1. 篩選掉已經在前端被標記刪除的資料，★ 並透過 reset_index(drop=True) 重製乾淨的索引，避免 IndexingError
if not df_raw.empty:
    df = df_raw[~df_raw["_uid"].isin(st.session_state["deleted_uids"])].reset_index(drop=True)
else:
    df = df_raw.copy()

if df.empty:
    if not df_raw.empty:
        st.info("資料已全數隱藏/刪除。您可以重新整理頁面來恢復。")
    else:
        st.info("目前 `data_CN/` 資料夾內沒有可解析的資料。")
else:
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 3, 1])
    with ctrl_col1:
        valid_dates = df["日期"].dropna()
        m_date = valid_dates.min().date() if not valid_dates.empty else datetime.today().date()
        x_date = valid_dates.max().date() if not valid_dates.empty else datetime.today().date()
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date), label_visibility="collapsed")

    with ctrl_col2:
        search_kw = st.text_input(
            "🔍 關鍵字搜尋",
            placeholder="搜尋寄件者、主旨、數量、IMO、聯繫方式...（可用空白分隔多個關鍵字）",
            key="main_search_input",
            label_visibility="collapsed",
        )

    # ★ 改用 df.index 作為 Series 的 index，徹底根絕長度/對齊不一致的問題
    mask = pd.Series(True, index=df.index)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        start_dt = pd.to_datetime(sel_range[0])
        end_dt = pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
        mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

    # 🔍 多值空白搜尋：以空白分隔多個關鍵字，符合任一關鍵字的資料列都會被納入
    search_keywords = []
    if search_kw:
        search_cols = ["寄件者", "主旨", "數量", "IMO", "聯繫方式", "放行狀態", "呼號", "原始內文"]
        search_cols = [c for c in search_cols if c in df.columns]
        search_keywords = [k.strip() for k in search_kw.split() if k.strip()]
        missing_keywords = []
        combined_kw_mask = pd.Series(False, index=df.index)

        for kw in search_keywords:
            kw_mask = df[search_cols].astype(str).apply(lambda col: col.str.contains(kw, case=False, na=False, regex=False)).any(axis=1)
            if not kw_mask.any():
                missing_keywords.append(kw)
            else:
                combined_kw_mask |= kw_mask

        if missing_keywords:
            st.warning(f"⚠️ 提示：以下字串不在表格中： **{', '.join(missing_keywords)}**", icon="🚨")
        if combined_kw_mask.any():
            mask &= combined_kw_mask
        elif missing_keywords:
            mask &= False

    # 1. 篩選與排序
    display_df = df[mask].sort_values(by="日期", ascending=False).reset_index(drop=True)

    # 🚀 修改點：將調整欄位順序的邏輯移到匯出按鈕「之前」
    col_order = ["放行狀態", "日期", "寄件者", "主旨", "數量", "處理", "聯繫方式", "IMO", "呼號", "_uid", "原始內文"]
    display_df = display_df[[c for c in col_order if c in display_df.columns]]

    

      # 2. 此時的 display_df 已經跟前端顯示的排序一模一樣，再傳給 Excel 產生器
    # 🚀 匯出按鈕移到最右邊，並包在展開區塊裡，需要先手動展開才看得到下載按鈕，避免誤觸
    with ctrl_col3:
        with st.expander("🗂️ 匯出", expanded=False):
            st.download_button(
                f"匯出 {len(display_df)} 筆",
                build_cn_excel(display_df),
                "cn_orders.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # 3. 隱藏用不到的底層資料（後續交給 Streamlit 渲染表格）
    show_df = display_df.drop(columns=["原始內文", "_uid"], errors="ignore")

    def style_search_match(val):
        if search_kw and search_keywords:
            val_str = str(val).lower()
            for kw in search_keywords:
                if kw.lower() in val_str:
                    return "background-color: #ffeb3b; color: #000000; font-weight: bold;"
        return ""

    styler_method_name = "map" if hasattr(show_df.style, "map") else ("applymap" if hasattr(show_df.style, "applymap") else None)

    if styler_method_name:
        styled_df = getattr(show_df.style, styler_method_name)(style_alerts, subset=["呼號"])
        if search_kw:
            styled_df = getattr(styled_df, styler_method_name)(style_search_match)
    else:
        styled_df = show_df

    # 動態產生 table_key，每次刪除後 counter + 1，確保表格徹底刷新並清空選取狀態
    table_key = f"order_dataframe_{st.session_state['df_key_counter']}"
    current_selection = st.session_state.get(table_key, {}).get("selection", {}).get("rows", [])
    
    df_height = 350 if len(current_selection) > 0 else 1000

    event = st.dataframe(
        styled_df,
        key=table_key, 
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=df_height,
        column_config={
            "日期": st.column_config.DatetimeColumn("接收時間", format="MM/DD HH:mm"),
            "主旨": st.column_config.TextColumn("主旨", width="medium"),
            "數量": st.column_config.TextColumn("數量", width="small"),
            "處理": st.column_config.TextColumn("處理", width="small"),
            "IMO": st.column_config.TextColumn("IMO", width="small"),
            "聯繫方式": st.column_config.TextColumn("聯繫方式", width="medium"),
            "放行狀態": st.column_config.TextColumn("放行狀態", width="small"),
            "呼號": st.column_config.TextColumn("呼號", width="small"),
        }
    )

    sel_rows = event.get("selection", {}).get("rows", [])
    
    if sel_rows:
        if sel_rows[0] < len(display_df):
            detail_container = st.container(height=400, border=True)
            
            with detail_container:
                row = display_df.iloc[sel_rows[0]]
                time_str = row["日期"].strftime("%Y-%m-%d %H:%M") if pd.notnull(row["日期"]) else "未知時間"
                callsign_display = f"<span style='color:#A31D1D; font-weight:bold;'>{row['呼號']}</span>" if row['呼號'] == 'KYC' else row['呼號']
                
                # 將按鈕設定為 type="primary"，CSS 就會自動將它吸附到右上角！
                if st.button("🗑️ 刪除", type="primary", help="暫時隱藏此筆訂單，匯出時亦會剔除"):
                    st.session_state["deleted_uids"].add(row["_uid"])
                    st.session_state["df_key_counter"] += 1
                    st.rerun()

                # 滿版展開的郵件內容 (不用 st.columns 壓縮寬度)
                st.markdown(f'''
                <div class="email-pane">
                    <div class="email-subject">{row['主旨']}</div>
                    <div class="email-meta">
                        ✉️ <b>{row['寄件者']}</b> &nbsp; | &nbsp; 📅 {time_str} &nbsp; | &nbsp; 📂 {row['放行狀態']} &nbsp; | &nbsp; ⚠️ 呼號: {callsign_display}
                    </div>
                    <div class="email-body">{row["原始內文"]}</div>
                </div>
                ''', unsafe_allow_html=True)
