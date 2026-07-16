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

# --- 1. 路徑設定與資料載入 ---
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
JSON_PATH = os.path.join(ROOT_DIR, "Kingdee_Export_UTF8.json")

if not os.path.exists(JSON_PATH) and os.path.exists("Kingdee_Export_UTF8.json"):
    JSON_PATH = "Kingdee_Export_UTF8.json"

def load_json_data():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            # 處理可能存在的巢狀結構
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
        st.warning(f"⚠️ 找不到 `{JSON_PATH}`，儲存時將自動建立。")
        return []

# --- 2. 佈局佔位符 (讓按鈕與搜尋列頂置) ---
top_bar = st.container()
table_container = st.container()

with top_bar:
    c1, c2 = st.columns([3, 1])
    with c1:
        search_term = st.text_input("🔍 搜尋 IMO、船名或呼號...", placeholder="輸入關鍵字篩選資料，篩選後修改仍可安全儲存！")
    with c2:
        # 使用 CSS 讓按鈕與左側輸入框對齊
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        save_placeholder = st.empty()

# --- 3. 資料處理與過濾 ---
raw_data = load_json_data()
df = pd.DataFrame(raw_data)

if df.empty:
    df = pd.DataFrame(columns=["imo", "name", "callSign"])

# 給原始資料一個唯一的隱藏 ID，用來追蹤過濾後的修改與刪除
df['_row_id'] = range(len(df))

# 執行搜尋過濾
if search_term:
    # 忽略隱藏的 _row_id，搜尋所有欄位
    search_mask = df.drop(columns=['_row_id']).astype(str).apply(
        lambda x: x.str.contains(search_term, case=False, na=False)
    ).any(axis=1)
    display_df = df[search_mask].copy()
else:
    display_df = df.copy()

# 【魔法在此】在表格最頂端，強塞一個「空白列」，供使用者快速新增
blank_row = {col: "" for col in display_df.columns}
blank_row['_row_id'] = -1  # 給予特殊標記 -1 代表這是一筆「待新增」的空資料
display_df = pd.concat([pd.DataFrame([blank_row]), display_df], ignore_index=True)

# --- 4. 渲染互動表格 ---
with table_container:
    st.info("💡 **操作提示：** 直接在第一行 **空白列** 輸入資料即可快速新增；或勾選左側方塊按 `Delete` 刪除資料。")
    
    edited_df = st.data_editor(
        display_df,
        num_rows="dynamic",
        hide_index=False,
        use_container_width=True,
        height=600,
        column_config={
            "_row_id": None  # 將系統追蹤用的 ID 對使用者隱藏
        }
    )

# --- 5. 頂部儲存按鈕邏輯 ---
if save_placeholder.button("💾 儲存並覆寫 JSON", type="primary", use_container_width=True):
    try:
        new_full = df.copy()

        # A. 處理刪除 (存在於展示清單中，但被使用者刪掉的資料)
        original_displayed_ids = set(display_df[display_df['_row_id'] != -1]['_row_id'])
        edited_ids = set(edited_df[edited_df['_row_id'] != -1]['_row_id'].dropna())
        deleted_ids = original_displayed_ids - edited_ids
        new_full = new_full[~new_full['_row_id'].isin(deleted_ids)]

        # B. 處理修改 (更新原本存在的資料)
        edited_existing = edited_df[(edited_df['_row_id'] != -1) & (edited_df['_row_id'].notna())]
        cols_to_update = [c for c in edited_df.columns if c != '_row_id']
        for _, row in edited_existing.iterrows():
            rid = row['_row_id']
            new_full.loc[new_full['_row_id'] == rid, cols_to_update] = row[cols_to_update]

        # C. 處理新增 (包含最上方的空白列被填寫，或是使用者在最下方按 + 新增的列)
        new_rows = edited_df[(edited_df['_row_id'] == -1) | (edited_df['_row_id'].isna())].copy()
        new_rows = new_rows.drop(columns=['_row_id'], errors='ignore')
        # 把整行都是空白的廢列清掉
        new_rows = new_rows.replace("", pd.NA).dropna(how="all")

        # 合併新資料到總表的最上方 (讓使用者下次開啟直接看到)
        new_full = new_full.drop(columns=['_row_id'], errors='ignore')
        if not new_rows.empty:
            new_full = pd.concat([new_rows, new_full], ignore_index=True)

        # D. 最終清洗：確保 IMO 不能是空的
        imo_col = "IMO" if "IMO" in new_full.columns else "imo"
        if imo_col not in new_full.columns:
            imo_col = "imo" # 容錯機制
            
        new_full = new_full[new_full[imo_col].notna()]
        new_full = new_full[new_full[imo_col].astype(str).str.strip() != ""]

        # E. 寫入 JSON 檔案
        out_data = new_full.fillna("").to_dict(orient="records")
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=4)

        st.success(f"✅ 成功儲存 {len(out_data)} 筆資料！")
        st.rerun()  # 畫面重整

    except Exception as e:
        st.error(f"儲存失敗: {e}")
