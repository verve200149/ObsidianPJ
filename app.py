import streamlit as st
import pandas as pd
import os
import yaml
import json
import re
from datetime import datetime

st.set_page_config(layout="wide", page_title="船隊調度管理系統")

# --- 1. 讀取 Kingdee JSON ---
@st.cache_data
def load_ship_map():
    if os.path.exists('Kingdee_Export_UTF8.json'):
        try:
            with open('Kingdee_Export_UTF8.json', 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                return {str(item.get('imo', '')).strip(): item for item in data}
        except: return {}
    return {}

ship_map = load_ship_map()

# --- 2. 解析資料夾內的 Markdown ---
@st.cache_data
def load_data():
    rows = []
    data_folder = 'data_John' 
    if not os.path.exists(data_folder):
        return pd.DataFrame()

    for root, dirs, files in os.walk(data_folder):
        for file in files:
            if file.endswith('.md'):
                with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                    try:
                        content = f.read()
                        if content.startswith('---'):
                            parts = content.split('---')
                            fm = yaml.safe_load(parts[1])
                            
                            target = fm.get('target', '')
                            imo = re.search(r'IMO:(\d+)', target).group(1) if re.search(r'IMO:(\d+)', target) else "-"
                            mail_ship_name = re.search(r'FV:(.*?)丨', target).group(1).strip() if "FV:" in target else "-"
                            mail_call = re.search(r'Call:(.*)$', target).group(1).strip() if "Call:" in target else "-"
                            
                            is_kyc_valid = imo != "-" and imo in ship_map
                            ship_info = ship_map.get(imo, {})
                            final_name = ship_info.get('name', mail_ship_name)
                            final_call = ship_info.get('callSign', mail_call)
                            
                            cat = str(fm.get('category', 'PENDING')).upper()
                            status = "KYC未通過" if imo != "-" and not is_kyc_valid else cat
                            
                            rows.append({
                                "油輪": fm.get('ships', '').split('@')[0],
                                "日期": fm.get('date', '-'),
                                "位置": fm.get('Position', '-'),
                                "船名": final_name,
                                "狀態": status,
                                "ETA": fm.get('ETA', '-'),
                                "IMO": imo,
                                "呼號": final_call,
                                "主旨": fm.get('subject', '-')
                            })
                    except: continue
    return pd.DataFrame(rows)

df = load_data()

# --- 3. 網頁 UI ---
st.title("🚢 船隊實時調度報表")

if df.empty:
    st.info("💡 目前資料夾內無資料，請上傳 data_John 資料夾至 GitHub。")
else:
    col1, col2 = st.columns(2)
    with col1:
        tanker_list = ["全部"] + sorted(df["油輪"].unique().tolist())
        selected_tanker = st.selectbox("🚢 選擇油輪", tanker_list)
    with col2:
        status_list = ["全部", "APPROVED", "COMPLETED", "CANCELLED", "KYC未通過"]
        selected_status = st.selectbox("📂 狀態類別", status_list)

    mask = pd.Series([True] * len(df))
    if selected_tanker != "全部": mask &= (df["油輪"] == selected_tanker)
    if selected_status != "全部": mask &= (df["狀態"] == selected_status)
    
    display_df = df[mask].sort_values(by="日期", ascending=False)

    def color_status(val):
        colors = {'APPROVED': '#4CAF50', 'COMPLETED': '#2196F3', 'KYC未通過': '#f44336', 'CANCELLED': '#9e9e9e'}
        return f'color: {colors.get(val, "white")}; font-weight: bold'

    st.dataframe(display_df.style.map(color_status, subset=['狀態']), use_container_width=True, hide_index=True)

    csv = display_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(label="📊 下載篩選結果 CSV", data=csv, file_name=f'ship_report.csv', mime='text/csv')
