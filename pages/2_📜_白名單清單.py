import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(layout="wide", page_title="白名單清單", page_icon="📜")

# CSS 樣式增強：讓標題與控制面板更具一致性
st.markdown("""
    <style>
    .compact-title {
        font-size: 1.8rem;
        font-weight: 800;
        margin: 0 0 1rem 0;
        color: #4A90E2; /* 柔和且醒目的藍色 */
    }
    .control-panel {
        background-color: #1E1E1E;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 1rem;
        border: 1px solid #333;
    }
    /* 強制按鈕與輸入框垂直對齊 */
    div[data-testid="stDownloadButton"] > button {
        height: 42px; 
        margin-top: 0px;
    }
    div[data-testid="stTextInput"] input {
        height: 42px;
    }
    </style>
    <div class="compact-title">📜 金蝶白名單管理</div>
    """, unsafe_allow_html=True)

FILE_PATH = "Kingdee_Export_UTF8.json"

# ==========================================
# 1. 載入資料 (Session State 管理)
# ==========================================
if "whitelist_df" not in st.session_state:
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                st.session_state["whitelist_df"] = pd.DataFrame(data)
        except Exception as e:
            st.error(f"⚠️ 無法讀取 {FILE_PATH}: {e}")
            st.session_state["whitelist_df"] = pd.DataFrame(columns=["imo", "callSign"])
    else:
        st.session_state["whitelist_df"] = pd.DataFrame(columns=["imo", "callSign"])

# ==========================================
# 2. 控制欄位區 (對齊搜尋與匯出按鈕)
# ==========================================
st.markdown("#### 🔍 全局搜尋與操作")
col_search, col_export = st.columns([4, 1])

with col_search:
    # 隱藏預設 label，讓輸入框跟旁邊的按鈕可以在同一水平線上完美對齊
    search_term = st.text_input(
        "search", 
        label_visibility="collapsed", 
        placeholder="輸入 IMO、呼號 或 名稱 關鍵字進行搜尋與高亮..."
    )

with col_export:
    json_data = st.session_state["whitelist_df"].to_dict(orient="records")
    st.download_button(
        label="💾 匯出全部資料",
        data=json.dumps(json_data, ensure_ascii=False, indent=4).encode("utf-8-sig"),
        file_name="Kingdee_Export_UTF8.json",
        mime="application/json",
        type="primary",
        use_container_width=True # 讓按鈕寬度延展，視覺更飽滿
    )

# ==========================================
# 3. 處理搜尋邏輯與高亮 (Highlight)
# ==========================================
df = st.session_state["whitelist_df"]

def highlight_keyword(val):
    """自訂高亮特效：如果儲存格內容包含關鍵字，背景變亮黃色"""
    if search_term and str(search_term).lower() in str(val).lower():
        return "background-color: #9C6500; color: #FFFFFF; font-weight: bold;"
    return ""

if search_term:
    # 進行全欄位過濾
    mask = df.apply(lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1)
    filtered_df = df[mask]
    
    # 提示使用者目前為搜尋模式
    st.warning(f"👁️ 顯示搜尋結果：共 {len(filtered_df)} 筆。 (⚠️ **搜尋模式下無法儲存或新增資料**，請清空搜尋框以恢復編輯)")
    
    # 套用高亮樣式
    styler_method = getattr(filtered_df.style, "map", getattr(filtered_df.style, "applymap", None))
    display_data = styler_method(highlight_keyword) if styler_method else filtered_df
    
    # 搜尋模式下鎖定新增資料 (避免 Streamlit Styler 衝突)
    editor_num_rows = "fixed"
else:
    filtered_df = df
    display_data = df
    editor_num_rows = "dynamic" # 恢復可新增資料模式

# ==========================================
# 4. 互動式表格 (Data Editor)
# ==========================================
st.markdown("---")

# 渲染表格
edited_df = st.data_editor(
    display_data,
    use_container_width=True,
    num_rows=editor_num_rows,
    key="whitelist_editor",
    column_order=["imo", "callSign"] + [c for c in df.columns if c not in ["imo", "callSign"]],
    column_config={
        "imo": st.column_config.TextColumn("IMO (第一優先)", required=True, width="medium"),
        "callSign": st.column_config.TextColumn("呼號", width="medium"),
    }
)

# ==========================================
# 5. 自動同步變更回主清單
# ==========================================
# 只有在「未搜尋」的狀態下，才允許把表格的修改同步儲存到 session_state 中
if not search_term:
    if not edited_df.equals(st.session_state["whitelist_df"]):
        st.session_state["whitelist_df"] = edited_df
        st.rerun()
