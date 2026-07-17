import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(layout="wide", page_title="白名單清單", page_icon="📜")

# ==========================================
# 🔐 密碼保護機制 (使用 if/else 避免 websocket cache miss 報錯)
# ==========================================
if "whitelist_authenticated" not in st.session_state:
    st.session_state["whitelist_authenticated"] = False

if not st.session_state["whitelist_authenticated"]:
    # ❌ 未解鎖：只顯示登入畫面
    st.markdown("<br><br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
            <div style='text-align: center;'>
                <h2 style='color: #4A90E2;'>🔒 白名單管理系統</h2>
                <p style='color: #888;'>此頁面受密碼保護，請輸入密碼解鎖</p>
            </div>
        """, unsafe_allow_html=True)
        
        # 移除了 placeholder 中的預設密碼提示
        pwd_input = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="請輸入密碼...")
        
        if st.button("🔓 確認解鎖", type="primary", use_container_width=True):
            if pwd_input == "0000":
                st.session_state["whitelist_authenticated"] = True
                st.rerun()  # 密碼正確，重新整理頁面進入 else 區塊
            else:
                st.error("❌ 密碼錯誤，請重新輸入！")

else:
    # 🔓 已解鎖：顯示完整主程式
    # ==========================================
    # 🎨 CSS 樣式增強 (高度精準對齊、視覺美化)
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
        div[data-testid="stTextInput"] label {
            display: none !important;
        }
        
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
            font-size: 1.1rem !important;
            transition: all 0.2s ease-in-out !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div[data-testid="stButton"] > button:hover,
        div[data-testid="stDownloadButton"] > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2) !important;
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
    col_search, col_add, col_export = st.columns([6, 2, 1])

    with col_search:
        search_term = st.text_input(
            "search", 
            label_visibility="collapsed", 
            placeholder="輸入 IMO、呼號 或 名稱 關鍵字進行搜尋與高亮 (請按 Enter) ..."
        )

    with col_add:
        if st.button("➕ 頂部新增空白列", use_container_width=True, help="點擊在表格最上方插入空白列，輸入時畫面不跳動"):
            new_row = {c: "" for c in st.session_state["whitelist_df"].columns}
            new_df = pd.DataFrame([new_row])
            st.session_state["whitelist_df"] = pd.concat([new_df, st.session_state["whitelist_df"]], ignore_index=True)
            st.rerun()

   with col_export:
    export_df = st.session_state["whitelist_df"].copy()
    is_not_empty = export_df.astype(str).apply(lambda x: x.str.strip().astype(bool)).any(axis=1)
    export_df = export_df[is_not_empty]
    
    json_data = export_df.to_dict(orient="records")
    st.download_button(
        label="📧", 
        data=json.dumps(json_data, ensure_ascii=False, indent=4).encode("utf-8-sig"),
        file_name="Kingdee_Export_UTF8.json",
        mime="application/json",
        use_container_width=True,
        help="匯出全部資料 (存檔為 Kingdee_Export_UTF8.json)"
    )

    # ==========================================
    # 3. 處理邏輯與高亮特效
    # ==========================================
    df = st.session_state["whitelist_df"]

    def highlight_keyword(val):
        if search_term and str(search_term).lower() in str(val).lower():
            return "background-color: #A31D1D; color: #FFFFFF; font-weight: bold;"
        return ""

    st.markdown("---")

    if search_term:
        # ---- 搜尋模式 (唯讀，支援完美高亮) ----
        mask = df.apply(lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1)
        filtered_df = df[mask]
        
        st.warning(f"👁️ 顯示搜尋結果：共 {len(filtered_df)} 筆。 (⚠️ **目前為搜尋唯讀模式**，請清空搜尋框以恢復編輯)")
        
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

        if not edited_df.equals(st.session_state["whitelist_df"]):
            st.session_state["whitelist_df"] = edited_df
            st.rerun()
