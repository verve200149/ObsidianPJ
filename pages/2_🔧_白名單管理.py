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
    <div class="compact-title">🔧 KYC 白名單管理 (暫時回歸本地儲存)</div>
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
        except Exception as e:
            st.error(f"解析 JSON 失敗: {e}")
            return []
    return []

# --- 2. 佈局 ---
df = pd.DataFrame(load_json_data())
if df.empty:
    df = pd.DataFrame(columns=["imo", "name", "callSign"])

# --- 3. 渲染 ---
st.info("💡 目前已移除 GitHub 同步功能，僅測試網頁是否能正常啟動。")
edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

if st.button("💾 儲存至本地 (測試)"):
    try:
        out_data = edited_df.replace("", pd.NA).dropna(how="all").to_dict(orient="records")
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=4)
        st.success("✅ 儲存成功！")
    except Exception as e:
        st.error(f"儲存失敗: {e}")
