import streamlit as st
import pandas as pd
import os
import json

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
    <div class="compact-title">🔧 KYC 白名單管理 (Kingdee)</div>
    """, unsafe_allow_html=True)

# -------------------------------------------------------------
# 1. 動態尋找根目錄的 JSON 檔案路徑
# 因為這個腳本放在 pages/ 底下，所以使用 dirname 往上推一層尋找根目錄
# -------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
JSON_PATH = os.path.join(ROOT_DIR, "Kingdee_Export_UTF8.json")

# 容錯：如果推一層找不到，退回檢查當前執行目錄
if not os.path.exists(JSON_PATH) and os.path.exists("Kingdee_Export_UTF8.json"):
    JSON_PATH = "Kingdee_Export_UTF8.json"

# -------------------------------------------------------------
# 2. 載入 JSON 資料的函式
# -------------------------------------------------------------
def load_json_data():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 處理 Kingdee 可能輸出的巢狀結構
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, list):
                        return v
                return [data]
            return data
        except Exception as e:
            st.error(f"解析 JSON 失敗: {e}")
            return []
    else:
        st.warning(f"⚠️ 目前找不到檔案: `{JSON_PATH}`。您可以直接在此新增資料，儲存時將自動建立該檔案。")
        return []

# -------------------------------------------------------------
# 3. 渲染互動式表格
# -------------------------------------------------------------
raw_data = load_json_data()
df = pd.DataFrame(raw_data)

# 如果檔案是空的，預設給個空欄位讓使用者方便開始填寫
if df.empty:
    df = pd.DataFrame(columns=["IMO", "其他欄位(可自訂)"])

st.info("💡 **操作提示：** \n"
        "- **修改**：直接在表格儲存格點擊兩下即可修改內容。\n"
        "- **新增**：滑到表格最底部的「空白列」直接輸入，即可新增資料。\n"
        "- **刪除**：勾選最左側的核取方塊，按下鍵盤 `Delete` 鍵即可刪除該列。")

# 使用 st.data_editor 讓 DataFrame 變成可直接編輯的 UI
edited_df = st.data_editor(
    df,
    num_rows="dynamic",        # 允許動態新增與刪除列
    use_container_width=True,
    height=600,
    hide_index=False           # 保留 index 方便核取刪除
)

st.markdown("<br>", unsafe_allow_html=True)

# -------------------------------------------------------------
# 4. 儲存變更並回寫 JSON
# -------------------------------------------------------------
if st.button("💾 儲存並覆寫 JSON 檔案", type="primary"):
    try:
        # 清除不小心多點出來的全空白列
        clean_df = edited_df.dropna(how="all")
        
        # 將 DataFrame 轉回 JSON 接受的字典列表格式
        new_data = clean_df.to_dict(orient="records")
        
        # 寫入檔案
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=4)
            
        st.success(f"✅ 成功儲存 {len(new_data)} 筆資料至 `{JSON_PATH}`！請切換分頁確認狀態。")
        st.balloons()  # 慶祝動畫
    except Exception as e:
        st.error(f"儲存失敗: {e}")
