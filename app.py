import streamlit as st
import pandas as pd
import os, yaml, json, re, io
from datetime import datetime

# ==========================================
# 1. 頁面與樣式設定 (保持極簡與乾淨)
# ==========================================
st.set_page_config(layout="wide", page_title="船隊調度管理系統", page_icon="🚢")

st.markdown("""
    <style>
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #1a73e8; font-weight: 600; }
    .email-pane { 
        background-color: #ffffff; color: #333333; padding: 25px; 
        border-radius: 8px; border: 1px solid #e0e0e0;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        height: 600px; overflow-y: auto;
    }
    .email-header { border-bottom: 1px solid #eeeeee; padding-bottom: 12px; margin-bottom: 20px; }
    .email-subject { font-size: 1.3em; font-weight: bold; color: #202124; margin-bottom: 8px; }
    .email-meta { font-size: 0.9em; color: #5f6368; }
    .email-body { white-space: pre-wrap; font-family: 'Consolas', monospace; font-size: 14px; line-height: 1.6; color: #444444; }
    </style>
""", unsafe_allow_html=True)


# ==========================================
# 2. 資料讀取與解析 (加入快取，避免每次點擊都重新掃描檔案)
# ==========================================
def load_update_log():
    if os.path.exists('update_log.json'):
        try:
            with open('update_log.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return None

@st.cache_data(ttl=600)
def load_ship_map():
    if os.path.exists('Kingdee_Export_UTF8.json'):
        try:
            with open('Kingdee_Export_UTF8.json', 'r', encoding='utf-8-sig') as f:
                return {str(item.get('imo', '')).strip(): item for item in json.load(f)}
        except: pass
    return {}

def clean_mail_field(raw):
    if not raw: return ""
    return re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', str(raw)).strip()

def parse_ship_entries(target):
    if not target or str(target).strip() == "(本次無資料)":
        return [{"fv": "(本次無資料)", "imo": "-"}]
    segments = [s.strip() for s in str(target).split('|') if s.strip()]
    res = []
    for seg in segments:
        fv = re.search(r'FV:(.*?)丨', seg) or re.search(r'FV:(.*)$', seg)
        imo = re.search(r'IMO:(\d+)', seg)
        res.append({
            "fv": fv.group(1).strip() if fv else "-", 
            "imo": imo.group(1).strip() if imo else "-"
        })
    return res

# 【關鍵修正】：必須加上 @st.cache_data，否則點擊表格都會導致全站重讀，拖垮伺服器造成斷線
@st.cache_data(ttl=120) 
def load_all_data():
    ship_map = load_ship_map()
    rows = []
    EXCLUDE_FILES = {'checklist.md', 'schedule操作介面.md'}
    
    for root, _, files in os.walk('.'):
        if any(ex in root for ex in ['.git', '.obsidian']): continue
        for file in files:
            if not (file.endswith('.md') and file not in EXCLUDE_FILES): continue
            
            fpath = os.path.join(root, file)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    raw_text = f.read()

                if not raw_text.startswith('---'): continue
                parts = raw_text.split('---')
                if len(parts) < 3: continue

                fm = yaml.safe_load(parts[1])
                if not fm: continue

                body = '---'.join(parts[2:]).strip()
                ships = parse_ship_entries(fm.get('target', ''))
                
                for s in ships:
                    s_info = ship_map.get(s['imo'], {})
                    is_kyc_fail = (s['imo'] != "-" and s['imo'] not in ship_map)
                    rows.append({
                        "油輪": clean_mail_field(fm.get('ships', '')).split('@')[0] or '-',
                        "日期": pd.to_datetime(fm.get('date')) if fm.get('date') else pd.NaT,
                        "位置": fm.get('Position', '-') or '-',
                        "船名": s_info.get('name', s['fv']),
                        "狀態": "KYC未通過" if is_kyc_fail else str(fm.get('category', 'PENDING')).upper(),
                        "ETA": fm.get('ETA', '-') or '-',
                        "IMO": s['imo'],
                        "呼號": s_info.get('callSign', "-"),
                        "主旨": fm.get('subject', '-'),
                        "原始內文": body
                    })
            except:
                continue
    return pd.DataFrame(rows)


# ==========================================
# 3. 網頁 UI 渲染 (原生 Streamlit 佈局)
# ==========================================
st.title("🚢 船隊實時調度報表")

# 重新整理按鈕 (清除快取)
if st.button("🔄 重新載入最新資料 (清除快取)"):
    load_all_data.clear()
    st.rerun()

# 載入資料 (這現在是非常快速的，因為有快取)
df = load_all_data()

if df.empty:
    st.warning("⚠️ 找不到任何資料。請確認 Markdown 檔案是否存在。")
    st.stop()

# --- 頂部篩選器 ---
c1, c2, c3 = st.columns([1, 1, 1.5])
with c1:
    tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
    sel_tanker = st.selectbox("🚢 篩選油輪", tankers)
with c2:
    sel_status = st.selectbox("📂 篩選狀態", ["全部", "APPROVED", "COMPLETED", "CANCELLED", "PENDING", "KYC未通過"])
with c3:
    valid_dates = df["日期"].dropna()
    m_date = valid_dates.min().date() if not valid_dates.empty else datetime.today().date()
    x_date = valid_dates.max().date() if not valid_dates.empty else datetime.today().date()
    sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date))

# --- 資料過濾 ---
mask = pd.Series([True] * len(df))
if sel_tanker != "全部": mask &= (df["油輪"] == sel_tanker)
if sel_status != "全部": mask &= (df["狀態"] == sel_status)
if isinstance(sel_range, tuple) and len(sel_range) == 2:
    start_dt = pd.to_datetime(sel_range[0])
    end_dt = pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
    mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False]).reset_index(drop=True)


# --- 核心：原生表格與預覽分欄 ---
# 【關鍵修正】：移除 JS 注入，直接使用穩定的原生 st.columns
col_table, col_preview = st.columns([1.2, 1]) 

with col_table:
    st.info("💡 點擊下方表格內的信件即可在右側預覽 (支援多選)。")
    event = st.dataframe(
        display_df.drop(columns=["原始內文"]), 
        use_container_width=True, 
        hide_index=True, 
        on_select="rerun", 
        selection_mode="multi-row",
        height=600,
        column_config={
            "日期": st.column_config.DatetimeColumn("時間", format="MM/DD HH:mm"), 
            "主旨": st.column_config.TextColumn("主旨", width="medium")
        }
    )
    
    st.download_button(
        f"📊 匯出目前篩選 ({len(display_df)} 筆)", 
        display_df.to_csv(index=False).encode('utf-8-sig'), 
        "ship_report.csv", 
        "text/csv"
    )

with col_preview:
    # 取得使用者勾選的行號 (List of index)
    selected_indices = event.selection.rows
    
    if len(selected_indices) == 0:
        st.markdown('<div style="margin-top: 100px; text-align: center; color: #888;">👈 請點選左側表格中的郵件以查看內文</div>', unsafe_allow_html=True)
    else:
        # 只顯示最後勾選的最多 2 筆，避免畫面過長
        for idx in selected_indices[-2:]:
            row = display_df.iloc[idx]
            time_str = row['日期'].strftime('%Y-%m-%d %H:%M') if pd.notnull(row['日期']) else '未知時間'
            
            st.markdown(f'''
            <div class="email-pane" style="height: auto; max-height: 600px; margin-bottom: 20px;">
                <div class="email-header">
                    <div class="email-subject">{row['主旨']}</div>
                    <div class="email-meta">
                        🚢 <b>{row['油輪']}</b> &nbsp; | &nbsp; 📅 {time_str} &nbsp; | &nbsp; 📂 {row['狀態']}
                    </div>
                </div>
                <div class="email-body">{row["原始內文"]}</div>
            </div>
            ''', unsafe_allow_html=True)
