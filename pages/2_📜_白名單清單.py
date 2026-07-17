import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(layout="wide", page_title="白名單清單", page_icon="📜")

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
    </style>
    <div class="compact-title">📜 金蝶白名單管理</div>
    """, unsafe_allow_html=True)

# 定義檔案路徑 (對應到主程式根目錄)
FILE_PATH = "Kingdee_Export_UTF8.json"

# ==========================================
# 1. 讀取 JSON 資料並存入 Session State
# ==========================================
def load_json_data():
    """讀取 JSON 檔案，確保使用 utf-8-sig 處理 BOM"""
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                return data
        except Exception as e:
            st.error(f"⚠️ 無法讀取 {FILE_PATH}: {e}")
            return []
    else:
        st.warning(f"⚠️ 找不到檔案 {FILE_PATH}，將建立全新的空白清單。")
        return []

# 確保資料只在第一次進入時讀取，之後的修改保留在 Session State 中
if "whitelist_df" not in st.session_state:
    raw_data = load_json_data()
    # 轉成 DataFrame
    st.session_state["whitelist_df"] = pd.DataFrame(raw_data)

st.info("💡 **操作提示**：\n"
        "1. **修改**：直接對著表格欄位「雙擊滑鼠」即可編輯內容。\n"
        "2. **新增**：捲動到表格最下方，點擊灰色的空白列即可新增一筆。\n"
        "3. **刪除**：勾選表格最左側的核取方塊，並按下鍵盤的 `Delete` 鍵。")

# ==========================================
# 2. 顯示互動式 Data Editor
# ==========================================
# 讓使用者可以自由編輯，num_rows="dynamic" 允許新增與刪除列
edited_df = st.data_editor(
    st.session_state["whitelist_df"],
    use_container_width=True,
    num_rows="dynamic",
    height=600,
    key="whitelist_editor",
    # 設定特定欄位的顯示格式，避免 IMO 被當作數字加上千分號 (例如 1,234,567)
    column_config={
        "imo": st.column_config.TextColumn("IMO (國際海事組織編號)", required=True),
        "callSign": st.column_config.TextColumn("呼號 (Call Sign)"),
        "callsign": st.column_config.TextColumn("呼號 (小寫)"), # 預防 JSON 內有大小寫混雜的狀況
    }
)

# ==========================================
# 3. 將編輯後的資料轉回 JSON 並提供下載
# ==========================================
# 整理資料：把 NaN 填補為空字串，避免輸出成 null
export_df = edited_df.fillna("")

# 將 DataFrame 轉回 List of Dictionaries
export_data = export_df.to_dict(orient="records")

# 轉換成格式化的 JSON 字串 (ensure_ascii=False 確保中文正常顯示)
json_str = json.dumps(export_data, ensure_ascii=False, indent=4)

st.markdown("---")
col1, col2 = st.columns([1, 4])

with col1:
    # 下載按鈕：打包成 utf-8-sig 編碼，維持與原系統相容
    st.download_button(
        label="💾 匯出更新後的 JSON",
        data=json_str.encode("utf-8-sig"),
        file_name="Kingdee_Export_UTF8.json",
        mime="application/json",
        type="primary",
        help="下載後，請直接覆蓋專案根目錄的 Kingdee_Export_UTF8.json 並 Commit 到 GitHub！"
    )
    
with col2:
    st.caption(f"目前共 {len(export_df)} 筆白名單資料準備匯出。")
