import streamlit as st
import pandas as pd
import os, yaml, json, re
from datetime import datetime

# 1. 頁面基礎配置 (優化手機顯示)
st.set_page_config(
    layout="wide", 
    page_title="船隊調度管理系統",
    initial_sidebar_state="collapsed"
)

# 自定義 CSS：強制表格主旨不換行並優化手機端邊距
st.markdown("""
    <style>
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    </style>
    """, unsafe_allow_html=True)  # <--- 這裡原本寫錯了，請改成 unsafe_allow_html

# --- 2. 數據加載 (維持原有邏輯但增加快取穩定性) ---
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
    if not segments: return [{"fv": "-", "imo": "-"}]
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
                        content = f.read()
                        if content.startswith('---'):
                            fm = yaml.safe_load(content.split('---')[1])
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
                                    "主旨": fm.get('subject', '-')
                                })
                    except: continue
    return pd.DataFrame(rows)

df = load_all_data()

# --- 3. 介面與篩選器 (響應式佈局) ---
st.title("油輪即時預報查詢")

if df.empty:
    st.warning("⚠️ 尚無資料")
else:
    # 篩選器佈局：在手機端會自動換行
    c1, c2, c3 = st.columns([1, 1, 1.5])
    with c1:
        tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        sel_tanker = st.selectbox("🚢 油輪", tankers)
    with c2:
        sel_status = st.selectbox("📂 狀態", ["全部", "APPROVED", "COMPLETED", "CANCELLED", "KYC未通過"])
    with c3:
        m_date, x_date = df["日期"].min(), df["日期"].max()
        # 日期選擇器處理
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date), min_value=m_date, max_value=x_date)

    # 執行篩選
    mask = pd.Series([True] * len(df))
    if sel_tanker != "全部": mask &= (df["油輪"] == sel_tanker)
    if sel_status != "全部": mask &= (df["狀態"] == sel_status)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        mask &= (df["日期"] >= sel_range[0]) & (df["日期"] <= sel_range[1])

    display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False])

    # --- 4. 🚀 重點：固定欄位寬度配置 ---
    # 使用 st.column_config 來精確控制比例
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "油輪": st.column_config.TextColumn("油輪", width="small"),
            "日期": st.column_config.DateColumn("日期", width="small", format="MM/DD"),
            "位置": st.column_config.TextColumn("位置", width="medium"),
            "船名": st.column_config.TextColumn("船名", width="medium"),
            "狀態": st.column_config.TextColumn("狀態", width="small"),
            "ETA": st.column_config.TextColumn("ETA", width="small"),
            "IMO": st.column_config.TextColumn("IMO", width="small"),
            "呼號": st.column_config.TextColumn("呼號", width="small"),
            "主旨": st.column_config.TextColumn("主旨 (點擊展開)", width="large"),
        }
    )

    # 下載區域
    csv = display_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(f"📊 下載 CSV ({len(display_df)} 筆)", csv, "report.csv", "text/csv")

# 側邊選單
with st.sidebar:
    st.write(f"最後更新: {datetime.now().strftime('%H:%M:%S')}")
    if st.button("🔄 刷新資料"):
        st.cache_data.clear()
        st.rerun()
