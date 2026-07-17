import streamlit as st
import pandas as pd
import os, yaml, re, io, json
from datetime import datetime

st.set_page_config(layout="wide", page_title="訂單整理", page_icon="📦")

st.markdown("""
    <style>
    .compact-title {
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0 0 0.4rem 0;
        line-height: 1.2;
        white-space: nowrap;
    }
    @media (max-width: 640px) {
        .compact-title { font-size: 1.25rem; }
    }
    .email-pane {
        background-color: #ffffff; /* 確保郵件背景為白色 */
        color: #333333;
        padding: 20px;
        border-radius: 8px;
        /* 移除外框與陰影，因為外層的 container 已經有 border=True 了 */
    }
    .email-subject { font-size: 1.2em; font-weight: bold; color: #202124; margin-bottom: 8px; }
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

    # 載入 Kingdee 白名單 (Dict)
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

                # 處理寄件者
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

                # IMO 擷取邏輯
                contact_val = str(fm.get("contact", "-") or "-")
                imo_matches = re.findall(r"IMO.*?(\d{7})", contact_val, re.IGNORECASE)

                if not imo_matches:
                    imo_matches = [""]

                # 迴圈處理 IMO 並判定「呼號」
                for imo_num in imo_matches:
                    if not imo_num:
                        callsign_status = "無IMO"
                    elif imo_num in valid_imos_dict:
                        # 吻合時帶出對應的 callSign
                        callsign_status = valid_imos_dict[imo_num]
                    else:
                        # 不吻合時填上 KYC
                        callsign_status = "KYC"

                    rows.append({
                        "日期": parsed_date,
                        "寄件者": sender_clean,
                        "主旨": fm.get("subject", "-") or "-",
                        "數量": fm.get("quantity", "-") or "-",
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
    clean_df = export_df.drop(columns=["原始內文"], errors="ignore").copy()

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
    """只有在不吻合 (KYC) 的時候背景才標紅"""
    if val == "KYC":
        return "background-color: #A31D1D; color: white;" 
    return ""


df, parse_errors = load_cn_data()

if parse_errors:
    with st.sidebar.expander(f"⚠️ 解析失敗的信件 ({len(parse_errors)} 筆)"):
        for fpath, err in parse_errors:
            st.write(f"`{fpath}`")
            st.caption(err)

if df.empty:
    st.info("目前 `data_CN/` 資料夾內沒有可解析的資料。")
else:
    # 頂部控制區塊 (日期範圍 與 下載按鈕 排在同一列)
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 1, 3])
    with ctrl_col1:
        valid_dates = df["日期"].dropna()
        m_date = valid_dates.min().date() if not valid_dates.empty else datetime.today().date()
        x_date = valid_dates.max().date() if not valid_dates.empty else datetime.today().date()
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date), label_visibility="collapsed")
    
    mask = pd.Series([True] * len(df))
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        start_dt = pd.to_datetime(sel_range[0])
        end_dt = pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
        mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

    display_df = df[mask].sort_values(by="日期", ascending=False).reset_index(drop=True)

    with ctrl_col2:
        st.download_button(
            f"🗂️ 匯出 {len(display_df)} 筆",
            build_cn_excel(display_df),
            "cn_orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # 調整欄位順序：聯繫方式 在 IMO 前面，並將「警示」替換為「呼號」
    col_order = ["放行狀態", "日期", "寄件者", "主旨", "數量", "聯繫方式", "IMO", "呼號", "原始內文"]
    display_df = display_df[[c for c in col_order if c in display_df.columns]]

    show_df = display_df.drop(columns=["原始內文"])
    styler_method = getattr(show_df.style, "map", getattr(show_df.style, "applymap", None))
    styled_df = styler_method(style_alerts, subset=["呼號"]) if styler_method else show_df

    # --- 動態判斷表格高度 ---
    # 透過 st.session_state 提前取得表格目前的選取狀態
    table_key = "order_dataframe"
    current_selection = st.session_state.get(table_key, {}).get("selection", {}).get("rows", [])
    
    # 如果有選取資料，表格高度為 350；如果未選取，表格高度展開為 750
    df_height = 350 if len(current_selection) > 0 else 1000

    # --- 渲染 DataFrame ---
    event = st.dataframe(
        styled_df,
        key=table_key,  # 加入 key 以便讀取 session_state
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=df_height,
        column_config={
            "日期": st.column_config.DatetimeColumn("時間", format="YYYY/MM/DD HH:mm"),
            "主旨": st.column_config.TextColumn("主旨", width="medium"),
            "數量": st.column_config.TextColumn("數量", width="small"),
            "IMO": st.column_config.TextColumn("IMO", width="small"),
            "聯繫方式": st.column_config.TextColumn("聯繫方式", width="large"),
            "放行狀態": st.column_config.TextColumn("放行狀態", width="small"),
            "呼號": st.column_config.TextColumn("呼號", width="small"),
        }
    )

    # --- 下半部：僅在有選取時才出現的固定高度獨立捲動容器 ---
    sel_rows = event.get("selection", {}).get("rows", [])
    
    if sel_rows:
        # 使用 st.container(height=...) 建立固定高度的獨立滾動區塊
        detail_container = st.container(height=400, border=True)
        
        with detail_container:
            row = display_df.iloc[sel_rows[0]]
            time_str = row["日期"].strftime("%Y-%m-%d %H:%M") if pd.notnull(row["日期"]) else "未知時間"
            
            # 如果呼號是 KYC，加上醒目提示
            callsign_display = f"<span style='color:#A31D1D; font-weight:bold;'>{row['呼號']}</span>" if row['呼號'] == 'KYC' else row['呼號']
            
            st.markdown(f'''
            <div class="email-pane">
                <div class="email-subject">{row['主旨']}</div>
                <div class="email-meta">
                    ✉️ <b>{row['寄件者']}</b> &nbsp; | &nbsp; 📅 {time_str} &nbsp; | &nbsp; 📂 {row['放行狀態']} &nbsp; | &nbsp; ⚠️ 呼號: {callsign_display}
                </div>
                <div class="email-body">{row["原始內文"]}</div>
            </div>
            ''', unsafe_allow_html=True)
