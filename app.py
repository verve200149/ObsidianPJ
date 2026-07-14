import streamlit as st
import pandas as pd
import os, yaml, json, re
from datetime import datetime

# 1. 頁面基礎配置
st.set_page_config(
    layout="wide", 
    page_title="船隊調度管理系統",
    initial_sidebar_state="collapsed"
)

# 自定義 CSS
st.markdown("""
    <style>
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .email-body { 
        background-color: #1e1e1e; 
        color: #d4d4d4; 
        padding: 20px; 
        border-radius: 10px; 
        border: 1px solid #333;
        font-family: monospace;
        white-space: pre-wrap;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 數據加載 (增加讀取內文邏輯) ---
@st.cache_data(ttl=600)
def load_ship_map():
    if os.path.exists('Kingdee_Export_UTF8.json'):
        try:
            with open('Kingdee_Export_UTF8.json', 'r', encoding='utf-8-sig') as f:
                return {str(item.get('imo', '')).strip(): item for item in json.load(f)}
        except: return {}
    return {}

ship_map = load_ship_map()

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

@st.cache_data(ttl=300)
def load_all_data():
    rows = []
    search_path = 'data_John' if os.path.exists('data_John') else '.'
    for root, _, files in os.walk(search_path):
        if any(ex in root for ex in ['.git', '.obsidian']): continue
        for file in files:
            if file.endswith('.md') and file != 'checklist.md':
                with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                    try:
                        raw_text = f.read()
                        if raw_text.startswith('---'):
                            parts = raw_text.split('---')
                            fm = yaml.safe_load(parts[1])
                            # 🚀 抓取郵件本文 (YAML 區塊之後的所有文字)
                            body = parts[2].strip() if len(parts) > 2 else "無內文內容"
                            
                            p_date = pd.to_datetime(fm.get('date')).date() if fm.get('date') else None
                            ships = parse_ship_entries(fm.get('target', ''))
                            for s in ships:
                                s_info = ship_map.get(s['imo'], {})
                                is_kyc_fail = (s['imo'] != "-" and s['imo'] not in ship_map)
                                rows.append({
                                    "油輪": str(fm.get('ships', '')).split('@')[0],
                                    "日期": p_date,
                                    "位置": fm.get('Position', '-'),
                                    "船名": s_info.get('name', s['fv']),
                                    "狀態": "KYC未通過" if is_kyc_fail else str(fm.get('category', 'PENDING')).upper(),
                                    "ETA": fm.get('ETA', '-'),
                                    "IMO": s['imo'],
                                    "呼號": s_info.get('callSign', "-"),
                                    "主旨": fm.get('subject', '-'),
                                    "原始內文": body # 存入完整內容
                                })
                    except: continue
    return pd.DataFrame(rows)

df = load_all_data()

# --- 3. 介面與篩選器 ---
st.title("🚢 船隊實時調度報表")

if df.empty:
    st.warning("⚠️ 尚無資料")
else:
    c1, c2, c3 = st.columns([1, 1, 1.5])
    with c1:
        tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        sel_tanker = st.selectbox("🚢 油輪", tankers)
    with c2:
        sel_status = st.selectbox("📂 狀態", ["全部", "APPROVED", "COMPLETED", "CANCELLED", "KYC未通過"])
    with c3:
        m_date, x_date = df["日期"].min(), df["日期"].max()
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date), min_value=m_date, max_value=x_date)

    mask = pd.Series([True] * len(df))
    if sel_tanker != "全部": mask &= (df["油輪"] == sel_tanker)
    if sel_status != "全部": mask &= (df["狀態"] == sel_status)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        mask &= (df["日期"] >= sel_range[0]) & (df["日期"] <= sel_range[1])

    display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False])

    # --- 4. 表格顯示 (開啟單選模式) ---
    st.info("💡 提示：點擊下方表格中的任意行，可在頁面底部查看該郵件的原始內文。")
    
    # 使用 selection 模式，讓使用者點擊某一行
    event = st.dataframe(
        display_df.drop(columns=["原始內文"]), # 表格不顯示大段文字，保持整潔
        use_container_width=True,
        hide_index=True,
        on_select="rerun", # 點擊後重新整理以顯示內文
        selection_mode="single_row",
        column_config={
            "日期": st.column_config.DateColumn("日期", width="small", format="MM/DD"),
            "主旨": st.column_config.TextColumn("主旨", width="large"),
        }
    )

    # --- 5. 顯示原始郵件內容 (當點擊發生時) ---
    selected_rows = event.get("selection", {}).get("rows", [])
    if selected_rows:
        index = selected_rows[0]
        selected_mail = display_df.iloc[index]
        
        st.markdown("---")
        st.subheader(f"✉️ 原始郵件詳情：{selected_mail['主旨']}")
        
        with st.expander("📄 點擊展開/收合 完整郵件本文", expanded=True):
            st.markdown(f'<div class="email-body">{selected_mail["原始內文"]}</div>', unsafe_allow_html=True)
    
    # 下載區域
    csv = display_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(f"📊 下載 CSV ({len(display_df)} 筆)", csv, "report.csv", "text/csv")

with st.sidebar:
    if st.button("🔄 刷新資料"):
        st.cache_data.clear()
        st.rerun()
