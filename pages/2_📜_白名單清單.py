import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(layout="wide", page_title="白名單清單", page_icon="📜")

# CSS 樣式增強：讓標題與搜尋框更醒目
st.markdown("""
    <style>
    .compact-title {
        font-size: 1.8rem;
        font-weight: 800;
        margin: 0 0 1rem 0;
        color: #1E3A8A; /* 深藍色，醒目 */
    }
    .search-box {
        background-color: #F3F4F6;
        padding: 10px;
        border-radius: 10px;
        border: 1px solid #E5E7EB;
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
        with open(FILE_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            st.session_state["whitelist_df"] = pd.DataFrame(data)
    else:
        st.session_state["whitelist_df"] = pd.DataFrame(columns=["imo", "callSign"])

# ==========================================
# 2. 控制欄位區 (搜尋 + 匯出)
# ==========================================
col_search, col_export = st.columns([4, 1])

with col_search:
    search_term = st.text_input("🔍 全局搜尋 (搜尋 IMO 或 呼號)", "", help="輸入關鍵字即可過濾所有欄位")

with col_export:
    st.write("###") # 對齊按鈕
    # 這裡匯出的是整個 Master DataFrame (st.session_state["whitelist_df"])
    json_data = st.session_state["whitelist_df"].to_dict(orient="records")
    st.download_button(
        label="💾 匯出全部資料",
        data=json.dumps(json_data, ensure_ascii=False, indent=4).encode("utf-8-sig"),
        file_name="Kingdee_Export_UTF8.json",
        mime="application/json",
        type="primary"
    )

# ==========================================
# 3. 處理搜尋邏輯
# ==========================================
df = st.session_state["whitelist_df"]

if search_term:
    # 進行全欄位搜尋
    mask = df.apply(lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1)
    filtered_df = df[mask]
    st.warning(f"顯示搜尋結果：共 {len(filtered_df)} 筆")
else:
    filtered_df = df

# ==========================================
# 4. 互動式表格 (Data Editor)
# ==========================================
st.markdown("---")

# 這裡設定 column_order 確保 imo 永遠在第一行
edited_df = st.data_editor(
    filtered_df,
    use_container_width=True,
    num_rows="dynamic",
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
# 如果是在搜尋模式下，直接修改會導致「被過濾掉的資料消失」
# 所以我們這裡做個防呆：如果正在搜尋，不自動儲存，提示使用者
if search_term:
    st.info("⚠️ **搜尋模式下無法直接儲存變更**。請清除搜尋框後再進行新增或刪除，以確保資料完整。")
else:
    # 沒有搜尋時，自動同步變更
    if not edited_df.equals(st.session_state["whitelist_df"]):
        st.session_state["whitelist_df"] = edited_df
        st.rerun()
