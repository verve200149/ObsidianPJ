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
        margin: 0 0 1rem 0;
        color: #4A90E2; 
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
    
    /* === 🚀 魔法區：放大表格右上角的原生工具列 === */
    [data-testid="stElementToolbar"] {
        transform: scale(1.4);       /* 調整這個數值來控制放大倍率，1.4 = 放大 40% */
        transform-origin: top right; /* 確保它錨定在右上角放大，不會跑版 */
        opacity: 0.9 !important;     /* 提高透明度，讓圖示更清晰顯眼 */
    }
    /* 如果你想讓滑鼠移過去時再稍微放大一點點，可以加上這段互動效果 */
    [data-testid="stElementToolbar"]:hover {
        transform: scale(1.5);
        opacity: 1 !important;
    }
    </style>
    <div class="compact-title">📜 白名單管理系統</div>
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
    # 隱藏預設 label，對齊按鈕
    search_term = st.text_input(
        "search", 
        label_visibility="collapsed", 
        placeholder="輸入 IMO、呼號 或 名稱 關鍵字進行搜尋與高亮 (輸入完畢請按 Enter) ..."
    )

with col_export:
    json_data = st.session_state["whitelist_df"].to_dict(orient="records")
    st.download_button(
        label="💾 匯出全部資料",
        data=json.dumps(json_data, ensure_ascii=False, indent=4).encode("utf-8-sig"),
        file_name="Kingdee_Export_UTF8.json",
        mime="application/json",
        type="primary",
        use_container_width=True 
    )

# ==========================================
# 3. 處理邏輯與高亮特效
# ==========================================
df = st.session_state["whitelist_df"]

def highlight_keyword(val):
    """自訂高亮特效：背景轉為深紅色，文字轉為白色"""
    if search_term and str(search_term).lower() in str(val).lower():
        return "background-color: #A31D1D; color: #FFFFFF; font-weight: bold;"
    return ""

st.markdown("---")

if search_term:
    # ---- 搜尋模式 (唯讀，支援完美高亮) ----
    mask = df.apply(lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1)
    filtered_df = df[mask]
    
    st.warning(f"👁️ 顯示搜尋結果：共 {len(filtered_df)} 筆。 (⚠️ **目前為搜尋唯讀模式**，請清空搜尋框以恢復編輯)")
    
    # 針對 DataFrame 套用 Styler
    styler_method = getattr(filtered_df.style, "map", getattr(filtered_df.style, "applymap", None))
    styled_df = styler_method(highlight_keyword) if styler_method else filtered_df
    
    # 使用 st.dataframe 取代 st.data_editor，確保 CSS 背景色完美渲染
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_order=["imo", "callSign"] + [c for c in df.columns if c not in ["imo", "callSign"]],
        column_config={
            "imo": st.column_config.TextColumn("IMO (第一優先)", width="medium"),
            "callSign": st.column_config.TextColumn("呼號", width="medium"),
        }
    )
else:
    # ---- 編輯模式 (無搜尋時顯示，可自由新增/修改/刪除) ----
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        key="whitelist_editor",
        hide_index=True,
        column_order=["imo", "callSign"] + [c for c in df.columns if c not in ["imo", "callSign"]],
        column_config={
            "imo": st.column_config.TextColumn("IMO (第一優先)", required=True, width="medium"),
            "callSign": st.column_config.TextColumn("呼號", width="medium"),
        }
    )

    # 自動同步變更回主清單
    if not edited_df.equals(st.session_state["whitelist_df"]):
        st.session_state["whitelist_df"] = edited_df
        st.rerun()
