import streamlit as st
import pandas as pd
import os
import json
from github import Github  # 導入 GitHub API 套件

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
    <div class="compact-title">🔧 KYC 白名單管理 (雲端同步版)</div>
    """, unsafe_allow_html=True)

# --- 1. 路徑設定與資料載入 (讀取依然從本地讀取最快) ---
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
JSON_PATH = os.path.join(ROOT_DIR, "Kingdee_Export_UTF8.json")

if not os.path.exists(JSON_PATH) and os.path.exists("Kingdee_Export_UTF8.json"):
    JSON_PATH = "Kingdee_Export_UTF8.json"

def load_json_data():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
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
        st.warning(f"⚠️ 找不到本地 `{JSON_PATH}`，儲存時將直接在 GitHub 建立新檔。")
        return []

# --- 2. 佈局佔位符 ---
top_bar = st.container()
table_container = st.container()

with top_bar:
    c1, c2 = st.columns([3, 1])
    with c1:
        search_term = st.text_input("🔍 搜尋 IMO、船名或呼號...", placeholder="輸入關鍵字篩選資料，篩選後修改仍可安全同步至 GitHub！")
    with c2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        save_placeholder = st.empty()

# --- 3. 資料準備與過濾 ---
raw_data = load_json_data()
df = pd.DataFrame(raw_data)

if df.empty:
    df = pd.DataFrame(columns=["imo", "name", "callSign"])

df = df.fillna("").astype(str)

imo_col = next((col for col in df.columns if col.lower() == 'imo'), 'imo')
if imo_col not in df.columns:
    df[imo_col] = ""

if search_term:
    search_mask = df.apply(lambda x: x.str.contains(search_term, case=False, na=False)).any(axis=1)
    display_df = df[search_mask].copy()
else:
    display_df = df.copy()

blank_row = {col: "" for col in display_df.columns}
blank_df = pd.DataFrame([blank_row])
display_df = pd.concat([blank_df, display_df], ignore_index=True)

# --- 4. 渲染互動表格 ---
with table_container:
    st.info("💡 **操作提示：** 直接在第一行 **空白列** 輸入資料即可快速新增；或勾選左側方塊按 `Delete` 刪除資料。")
    
    edited_df = st.data_editor(
        display_df,
        num_rows="dynamic",
        hide_index=False,
        use_container_width=True,
        height=600
    )

# --- 5. 堅不可摧的 GitHub 雲端儲存邏輯 ---
if save_placeholder.button("☁️ 儲存並同步至 GitHub", type="primary", use_container_width=True):
    # 檢查是否設定了 Secrets
    if "GITHUB_TOKEN" not in st.secrets or "GITHUB_REPO" not in st.secrets:
        st.error("❌ 尚未在 Streamlit Secrets 中設定 `GITHUB_TOKEN` 或 `GITHUB_REPO`！請至後台設定。")
        st.stop()
        
    try:
        # A. 處理資料比對與合併
        df[imo_col] = df[imo_col].str.strip()
        display_df[imo_col] = display_df[imo_col].str.strip()
        edited_df[imo_col] = edited_df[imo_col].astype(str).str.strip()

        original_imos = set(display_df[imo_col].unique()) - {"", "nan"}
        edited_imos = set(edited_df[imo_col].unique()) - {"", "nan"}
        deleted_imos = original_imos - edited_imos
        
        df = df[~df[imo_col].isin(deleted_imos)]

        edited_records = edited_df.replace("", pd.NA).dropna(subset=[imo_col]).to_dict(orient="records")
        
        new_entries = []
        for row in edited_records:
            imo_val = str(row[imo_col]).strip()
            if not imo_val or imo_val.lower() == "nan": 
                continue
            
            if imo_val in df[imo_col].values:
                idx = df[df[imo_col] == imo_val].index[0]
                for k, v in row.items():
                    if pd.notna(v):
                        df.at[idx, k] = str(v).strip()
            else:
                clean_row = {k: str(v).strip() for k, v in row.items() if pd.notna(v)}
                new_entries.append(clean_row)

        if new_entries:
            new_df = pd.DataFrame(new_entries)
            df = pd.concat([new_df, df], ignore_index=True)

        # B. 將 DataFrame 轉為準備推上 GitHub 的 JSON 字串
        out_data = df.fillna("").to_dict(orient="records")
        json_string = json.dumps(out_data, ensure_ascii=False, indent=4)

        # C. 呼叫 GitHub API 進行檔案覆寫
        with st.spinner("🚀 正在將資料推送至 GitHub..."):
            g = Github(st.secrets["GITHUB_TOKEN"])
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file_path_in_repo = "Kingdee_Export_UTF8.json"
            
            try:
                # 嘗試取得舊檔案以獲取 SHA (這是 API 覆寫檔案所必須的)
                contents = repo.get_contents(file_path_in_repo)
                repo.update_file(
                    contents.path, 
                    "Update Kingdee JSON via Streamlit Cloud", 
                    json_string, 
                    contents.sha
                )
            except Exception:
                # 如果檔案不存在，則新建
                repo.create_file(
                    file_path_in_repo, 
                    "Create Kingdee JSON via Streamlit Cloud", 
                    json_string
                )

        st.success(f"✅ 成功儲存 {len(out_data)} 筆資料，並已同步更新至 GitHub！")
        st.balloons()
        st.rerun()

    except Exception as e:
        st.error(f"GitHub 同步失敗: {e}")
