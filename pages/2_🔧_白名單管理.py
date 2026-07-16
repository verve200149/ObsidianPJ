import streamlit as st
import pandas as pd
import os
import json
import io

st.set_page_config(page_title="白名單管理", page_icon="🔧", layout="wide")

st.markdown("""
    <style>
    .compact-title {
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0 0 1rem 0;
        line-height: 1.2;
    }
    </style>
    <div class="compact-title">🔧 KYC 白名單管理 (本地編輯與下載版)</div>
    """, unsafe_allow_html=True)

# --- 1. 路徑設定與資料載入 ---
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
JSON_PATH = os.path.join(ROOT_DIR, "Kingdee_Export_UTF8.json")

def load_json_data():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []

# --- 2. 佈局 ---
raw_data = load_json_data()
df = pd.DataFrame(raw_data)
if df.empty:
    df = pd.DataFrame(columns=["imo", "name", "callSign"])

df = df.fillna("").astype(str)

# --- 3. 搜尋與編輯 ---
search_term = st.text_input("🔍 搜尋 IMO、船名或呼號...", placeholder="輸入關鍵字篩選資料")

if search_term:
    search_mask = df.apply(lambda x: x.str.contains(search_term, case=False, na=False)).any(axis=1)
    display_df = df[search_mask].copy()
else:
    display_df = df.copy()

# 顯示編輯器
st.info("💡 **提示：** 修改完成後，請點擊下方的「準備下載 JSON」按鈕，將檔案儲存回桌面，並覆蓋原本的 Kingdee_Export_UTF8.json。")
edited_df = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, height=500)

# --- 4. 準備下載功能 ---
if st.button("📥 準備下載更新後的 JSON", type="primary"):
    # 這裡我們只輸出這一次編輯過的資料，你可以將其下載後存回原資料夾
    json_str = edited_df.replace("", pd.NA).dropna(how="all").to_json(orient="records", force_ascii=False, indent=4)
    
    st.download_button(
        label="點我儲存到桌面",
        data=json_str,
        file_name="Kingdee_Export_UTF8.json",
        mime="application/json"
    )
    st.success("✅ 檔案已準備好，請點擊上方按鈕下載，並覆蓋原目錄下的檔案！")
