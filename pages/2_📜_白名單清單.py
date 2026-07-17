import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(layout="wide", page_title="白名單清單", page_icon="📜")

# ==========================================
# 🎨 CSS 樣式增強 (高度精準對齊、視覺美化、工具列置頂)
# ==========================================
st.markdown("""
    <style>
    .compact-title {
        font-size: 2rem;
        font-weight: 900;
        margin: 0 0 1.5rem 0;
        color: #4A90E2; 
        text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
    }
    
    /* === 🚀 輸入框與按鈕精準對齊與美化 === */
    /* 隱藏 label 避免佔用多餘的高度空間 */
    div[data-testid="stTextInput"] label {
        display: none !important;
    }
    
    /* 統一設定高度與視覺風格，達成像素級對齊 */
    div[data-testid="stTextInput"] input {
        height: 46px !important;
        border-radius: 8px !important;
        border: 1px solid #555 !important;
        font-size: 1.05rem !important;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #4A90E2 !important;
        box-shadow: 0 0 0 2px rgba(74, 144, 226, 0.3) !important;
    }
    
    div[data-testid="stButton"] > button,
    div[data-testid="stDownloadButton"] > button {
        height: 46px !important;
        border-radius: 8px !important;
        font-weight: bold !important;
        font-size: 1.05rem !important;
        transition: all 0.2s ease-in-out !important;
    }
    div[data-testid="stButton"] > button:hover,
    div[data-testid="stDownloadButton"] > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.2) !important;
    }

    /* === 🚀 表格右上角原生工具列放大置頂 === */
    [data-testid="stElementToolbar"] {
        transform: scale(1.4);       
        transform-origin: top right; 
        opacity: 0.9 !important;     
        z-index: 99999 !important;   
    }
    [data-testid="stElementToolbar"]:hover {
        transform: scale(1.5);
        opacity: 1 !important;
        z-index: 99999 !important;   
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
# 2. 控制欄位區 (對齊搜尋、新增列 與 匯出按鈕)
# ==========================================
st.markdown("#### 🔍 全局搜尋與操作")
col_search, col_add, col_export = st.columns([5, 2, 2])

with col_search:
    # 隱藏預設 label，對齊按鈕
    search_term = st.text_input(
        "search", 
        label_visibility="collapsed", 
        placeholder="輸入 IMO、呼號 或 名稱 關鍵字進行搜尋與高亮 (請按 Enter) ..."
    )

with col_add:
    # 解決新增資料跳動問題：直接在最上方插入空白列
    if st.button("➕ 頂部新增空白列", use_container_width=True, help="點擊在表格最上方插入空白列，輸入時畫面不跳動"):
        # 建立一筆與目前欄位相同的空白列
        new_row = {c: "" for c in st.session_state["whitelist_df"].columns}
        new_df = pd.DataFrame([new_row])
        # 將空白列合併到最上方
        st.session_state["whitelist_df"] = pd.concat([new_df, st.session_state["whitelist_df"]], ignore_index=True)
        st.rerun()

with col_export:
    # 匯出前過濾掉「全空」的列，避免使用者按了新增列卻沒輸入資料，導致匯出無效的 JSON
    export_df = st.session_state["whitelist_df"].copy()
    is_not_empty = export_df.astype(str).apply(lambda x: x.str.strip().astype(bool)).any(axis=1)
    export_df = export_df[is_not_empty]
    
    json_data = export_df.to_dict(orient="records")
    st.download_button(
        label="📩 匯出全部資料",
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
