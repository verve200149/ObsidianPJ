import streamlit as st
import pandas as pd
import os, yaml, json, re
from datetime import datetime

# 設定網頁標題與寬度
st.set_page_config(layout="wide", page_title="船隊調度管理系統")

# --- 1. 讀取 Kingdee JSON ---
@st.cache_data(ttl=600) # 快取 10 分鐘
def load_ship_map():
    json_filename = 'Kingdee_Export_UTF8.json'
    if os.path.exists(json_filename):
        try:
            with open(json_filename, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                return {str(item.get('imo', '')).strip(): item for item in data}
        except Exception as e:
            st.error(f"JSON 解析出錯: {e}")
            return {}
    return {}

ship_map = load_ship_map()

# --- 2. 解析郵件中的船隻資訊 (處理多船併報的情況) ---
def parse_ship_entries(target):
    if not target or str(target).strip() == "(本次無資料)":
        return [{"fv": "-", "imo": "-"}]
    
    # 根據 "|" 拆分多個船隻條目
    segments = [s.strip() for s in str(target).split('|') if s.strip()]
    if not segments:
        return [{"fv": "-", "imo": "-"}]
    
    res = []
    for seg in segments:
        fv = re.search(r'FV:(.*?)丨', seg)
        if not fv: fv = re.search(r'FV:(.*)$', seg)
        imo = re.search(r'IMO:(\d+)', seg)
        res.append({
            "fv": fv.group(1).strip() if fv else "-",
            "imo": imo.group(1).strip() if imo else "-"
        })
    return res

# --- 3. 遞迴讀取所有 Markdown 檔案 ---
@st.cache_data(ttl=300) # 每 5 分鐘自動刷新
def load_all_data():
    rows = []
    # 這裡會搜尋整個目錄，包括子資料夾
    search_path = 'data_John' 
    if not os.path.exists(search_path):
        # 如果 data_John 不存在，就從根目錄搜尋
        search_path = '.'

    for root, dirs, files in os.walk(search_path):
        # 排除系統與設定資料夾
        if any(ex in root for ex in ['.git', '.obsidian', '.trash']):
            continue
            
        for file in files:
            if file.endswith('.md') and file != 'checklist.md':
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        file_content = f.read()
                        if file_content.startswith('---'):
                            # 提取 YAML 區塊
                            parts = file_content.split('---')
                            if len(parts) < 3: continue
                            fm = yaml.safe_load(parts[1])
                            if not fm: continue
                            
                            # 取得日期 (轉換為 Python 日期物件)
                            raw_date = fm.get('date')
                            p_date = pd.to_datetime(raw_date).date() if raw_date else None
                            
                            # 解析 target 欄位 (可能包含多船)
                            ships_in_mail = parse_ship_entries(fm.get('target', ''))
                            
                            for s in ships_in_mail:
                                # 查詢 JSON 白名單
                                ship_info = ship_map.get(s['imo'], {})
                                final_name = ship_info.get('name', s['fv'])
                                final_call = ship_info.get('callSign', "-")
                                
                                # 狀態判定
                                is_kyc_fail = (s['imo'] != "-" and s['imo'] not in ship_map)
                                cat = str(fm.get('category', 'PENDING')).upper()
                                status = "KYC未通過" if is_kyc_fail else cat

                                rows.append({
                                    "油輪": str(fm.get('ships', '')).split('@')[0],
                                    "日期": p_date,
                                    "位置": fm.get('Position', '-'),
                                    "船名": final_name,
                                    "狀態": status,
                                    "ETA": fm.get('ETA', '-'),
                                    "IMO": s['imo'],
                                    "呼號": final_call,
                                    "主旨": fm.get('subject', '-')
                                })
                    except Exception:
                        continue
    return pd.DataFrame(rows)

df = load_all_data()

# --- 4. 網頁前端顯示 ---
st.title("🚢 船隊實時調度報表")

if df.empty:
    st.warning("⚠️ 掃描完畢，但沒發現有效的資料。請檢查 .md 檔案的 YAML 格式。")
else:
    # 頂部控制列
    col1, col2, col3 = st.columns([1, 1, 1.5])
    
    with col1:
        tanker_list = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        selected_tanker = st.selectbox("🚢 選擇油輪", tanker_list)
        
    with col2:
        status_list = ["全部", "APPROVED", "COMPLETED", "CANCELLED", "KYC未通過"]
        selected_status = st.selectbox("📂 狀態類別", status_list)
        
    with col3:
        # 日期範圍選擇
        min_d, max_d = df["日期"].min(), df["日期"].max()
        # 預設選取最近一週或全部
        date_range = st.date_input("📅 日期範圍", value=(min_d, max_d), min_value=min_d, max_value=max_d)

    # 執行篩選
    mask = pd.Series([True] * len(df))
    if selected_tanker != "全部":
        mask &= (df["油輪"] == selected_tanker)
    if selected_status != "全部":
        mask &= (df["狀態"] == selected_status)
    if isinstance(date_range, tuple) and len(date_range) == 2:
        mask &= (df["日期"] >= date_range[0]) & (df["日期"] <= date_range[1])

    # 排序：日期最新排在最前
    display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False])

    # 顯示筆數統計
    st.info(f"📊 目前篩選結果共有 **{len(display_df)}** 筆記錄")

    # 定義狀態顏色
    def color_status(val):
        colors = {'APPROVED': '#4CAF50', 'COMPLETED': '#2196F3', 'KYC未通過': '#f44336', 'CANCELLED': '#9e9e9e'}
        return f'color: {colors.get(val, "white")}; font-weight: bold'

    # 渲染表格
    st.dataframe(
        display_df.style.map(color_status, subset=['狀態']), 
        use_container_width=True, 
        hide_index=True
    )

    # 下載 CSV 功能
    csv_data = display_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📊 匯出目前的報表 (CSV)",
        data=csv_data,
        file_name=f'Vessel_Schedule_{datetime.now().strftime("%Y%m%d")}.csv',
        mime='text/csv'
    )

# 側邊欄額外功能
with st.sidebar:
    st.markdown("---")
    if st.button("🔄 強制刷新網頁資料"):
        st.cache_data.clear()
        st.rerun()
