import streamlit as st
import pandas as pd
import os, yaml, json, re
from datetime import datetime

st.set_page_config(layout="wide", page_title="船隊調度管理系統")

# 自定義 CSS (增加 Log 區樣式)
st.markdown("""
    <style>
    .log-container {
        background-color: #0e1117;
        padding: 10px 15px;
        border-radius: 5px;
        border-left: 5px solid #2196F3;
        margin-bottom: 20px;
        font-family: monospace;
        font-size: 13px;
    }
    .email-body { background-color: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 8px; white-space: pre-wrap; font-family: monospace; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 讀取 Update Log ---
def load_update_log():
    if os.path.exists('update_log.json'):
        with open('update_log.json', 'r', encoding='utf-8') as f:
            return json.load(f)
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

# --- 3. 解析郵件邏輯 ---
def parse_ship_entries(target):
    if not target or str(target).strip() == "(本次無資料)": return [{"fv": "-", "imo": "-"}]
    segments = [s.strip() for s in str(target).split('|') if s.strip()]
    res = []
    for seg in segments:
        fv = re.search(r'FV:(.*?)丨', seg)
        if not fv: fv = re.search(r'FV:(.*)$', seg)
        imo = re.search(r'IMO:(\d+)', seg)
        res.append({"fv": fv.group(1).strip() if fv else "-", "imo": imo.group(1).strip() if imo else "-"})
    return res

@st.cache_data(ttl=60)
def load_all_data():
    rows = []
    for root, _, files in os.walk('.'):
        if any(ex in root for ex in ['.git', '.obsidian']): continue
        for file in files:
            if file.endswith('.md') and file != 'checklist.md':
                try:
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                        raw_text = f.read()
                        if raw_text.startswith('---'):
                            parts = raw_text.split('---')
                            fm = yaml.safe_load(parts[1])
                            body = parts[2].strip()
                            ships = parse_ship_entries(fm.get('target', ''))
                            for s in ships:
                                s_info = ship_map.get(s['imo'], {})
                                is_kyc_fail = (s['imo'] != "-" and s['imo'] not in ship_map)
                                rows.append({
                                    "油輪": str(fm.get('ships', '')).split('@')[0],
                                    "日期": pd.to_datetime(fm.get('date')).date() if fm.get('date') else None,
                                    "位置": fm.get('Position', '-'),
                                    "船名": s_info.get('name', s['fv']),
                                    "狀態": "KYC未通過" if is_kyc_fail else str(fm.get('category', 'PENDING')).upper(),
                                    "ETA": fm.get('ETA', '-'),
                                    "IMO": s['imo'],
                                    "呼號": s_info.get('callSign', "-"),
                                    "主旨": fm.get('subject', '-'),
                                    "原始內文": body
                                })
                except: continue
    return pd.DataFrame(rows)

# --- 介面渲染 ---
st.title("🚢 船隊實時調度報表")

# 🚀 顯示 Log 區
log = load_update_log()
if log:
    st.markdown(f"""
    <div class="log-container">
        📡 系統日誌：<br>
        • 最後更新時間：{log.get('update_time')}<br>
        • 最新郵件編號：ID {log.get('last_id')}<br>
        • 資料庫總筆數：{log.get('total_files')} 封郵件
    </div>
    """, unsafe_allow_html=True)

df = load_all_data()

if not df.empty:
    c1, c2, c3 = st.columns([1, 1, 1.5])
    with c1:
        tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        sel_tanker = st.selectbox("🚢 油輪", tankers)
    with c2:
        sel_status = st.selectbox("📂 狀態", ["全部", "APPROVED", "COMPLETED", "CANCELLED", "KYC未通過"])
    with c3:
        m_date, x_date = df["日期"].min(), df["日期"].max()
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date))

    mask = pd.Series([True] * len(df))
    if sel_tanker != "全部": mask &= (df["油輪"] == sel_tanker)
    if sel_status != "全部": mask &= (df["狀態"] == sel_status)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        mask &= (df["日期"] >= sel_range[0]) & (df["日期"] <= sel_range[1])

    display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False])

    st.info("💡 點擊下方表格行，即可在底部查看原始郵件全文。")
    event = st.dataframe(
        display_df.drop(columns=["原始內文"]), 
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
        column_config={"日期": st.column_config.DateColumn("日期", format="MM/DD"), "主旨": st.column_config.TextColumn("主旨", width="large")}
    )

    indices = event.get("selection", {}).get("rows", [])
    if indices:
        sel = display_df.iloc[indices[0]]
        st.markdown("---")
        st.subheader(f"✉️ 原始郵件詳情")
        st.markdown(f'<div class="email-body">{sel["原始內文"]}</div>', unsafe_allow_html=True)
    
    st.download_button(f"📊 下載 CSV ({len(display_df)} 筆)", display_df.to_csv(index=False).encode('utf-8-sig'), "report.csv", "text/csv")

if st.sidebar.button("🔄 立即刷新資料"):
    st.cache_data.clear()
    st.rerun()
