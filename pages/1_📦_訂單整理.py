import streamlit as st
import pandas as pd
import os, yaml, re, io
from datetime import datetime

st.set_page_config(layout="wide", page_title="訂單整理", page_icon="📦")

st.markdown("""
    <style>
    .compact-title {
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0 0 0.4rem 0;
        line-height: 1.2;
        white-space: nowrap;
    }
    @media (max-width: 640px) {
        .compact-title { font-size: 1.25rem; }
    }
    .email-pane {
        background-color: #ffffff;
        color: #333333;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        margin-top: 0.5rem;
    }
    .email-subject { font-size: 1.15em; font-weight: bold; color: #202124; margin-bottom: 8px; }
    .email-meta { font-size: 0.9em; color: #5f6368; margin-bottom: 12px; }
    .email-body {
        white-space: pre-wrap;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 14px;
        line-height: 1.6;
        color: #444444;
    }
    </style>
    <div class="compact-title">📦 訂單整理</div>
    """, unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_cn_data():
    """讀取 data_CN/ 底下的 .md 檔案 (CNORDER 信箱格式：數量/聯繫方式/放行狀態)。"""
    rows = []
    parse_errors = []
    base_dir = "data_CN"

    if not os.path.isdir(base_dir):
        return pd.DataFrame(), parse_errors

    for root, _, files in os.walk(base_dir):
        for file in files:
            if not file.endswith(".md"):
                continue
            fpath = os.path.join(root, file)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    raw_text = f.read()

                if not raw_text.startswith("---"):
                    parse_errors.append((fpath, "找不到 YAML frontmatter (檔案未以 --- 開頭)"))
                    continue

                parts = raw_text.split("---")
                if len(parts) < 3:
                    parse_errors.append((fpath, "YAML frontmatter 格式不完整 (--- 數量不足)"))
                    continue

                fm = yaml.safe_load(parts[1])
                if not fm:
                    parse_errors.append((fpath, "YAML 解析結果為空"))
                    continue

                # 內文可能自己就含有 '---'，用 join 把後面全部接回來避免被截斷
                body = "---".join(parts[2:]).strip()

                rows.append({
                    "日期": pd.to_datetime(fm.get("date")) if fm.get("date") else pd.NaT,
                    "寄件者": fm.get("sender", "-") or "-",
                    "主旨": fm.get("subject", "-") or "-",
                    "數量": fm.get("quantity", "-") or "-",
                    "聯繫方式": fm.get("contact", "-") or "-",
                    "放行狀態": fm.get("release_status", "-") or "-",
                    "原始內文": body,
                })
            except Exception as e:
                parse_errors.append((fpath, f"{type(e).__name__}: {e}"))
                continue

    return pd.DataFrame(rows), parse_errors


@st.cache_data(ttl=60)
def build_cn_excel(export_df: pd.DataFrame) -> bytes:
    """依目前篩選範圍匯出成一份 Excel。"""
    output = io.BytesIO()
    clean_df = export_df.drop(columns=["原始內文"], errors="ignore")

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        clean_df.to_excel(writer, sheet_name="訂單整理", index=False)
        ws = writer.sheets["訂單整理"]
        for col_idx, col in enumerate(clean_df.columns, start=1):
            values = clean_df[col].astype(str).tolist()
            max_len = max([len(str(col))] + [len(v) for v in values]) if values else len(str(col))
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)
        ws.freeze_panes = "A2"

    return output.getvalue()


df, parse_errors = load_cn_data()

if parse_errors:
    with st.sidebar.expander(f"⚠️ 解析失敗的信件 ({len(parse_errors)} 筆)"):
        for fpath, err in parse_errors:
            st.write(f"`{fpath}`")
            st.caption(err)

if df.empty:
    st.info("目前 `data_CN/` 資料夾內沒有可解析的資料。")
else:
    # 篩選：只有日期範圍
    valid_dates = df["日期"].dropna()
    m_date = valid_dates.min().date() if not valid_dates.empty else datetime.today().date()
    x_date = valid_dates.max().date() if not valid_dates.empty else datetime.today().date()
    sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date))

    mask = pd.Series([True] * len(df))
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        start_dt = pd.to_datetime(sel_range[0])
        end_dt = pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
        mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

    display_df = df[mask].sort_values(by="日期", ascending=False).reset_index(drop=True)

    st.caption(f"共 {len(display_df)} 筆資料")

    event = st.dataframe(
        display_df.drop(columns=["原始內文"]),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=550,
        column_config={
            "日期": st.column_config.DatetimeColumn("時間", format="MM/DD HH:mm"),
            "主旨": st.column_config.TextColumn("主旨", width="medium"),
            "聯繫方式": st.column_config.TextColumn("聯繫方式", width="large"),
        }
    )

    # 點擊某一列時，在下方顯示完整內文
    sel_rows = event.get("selection", {}).get("rows", [])
    if sel_rows:
        row = display_df.iloc[sel_rows[0]]
        time_str = row["日期"].strftime("%Y-%m-%d %H:%M") if pd.notnull(row["日期"]) else "未知時間"
        st.markdown(f'''
        <div class="email-pane">
            <div class="email-subject">{row['主旨']}</div>
            <div class="email-meta">
                ✉️ <b>{row['寄件者']}</b> &nbsp; | &nbsp; 📅 {time_str} &nbsp; | &nbsp; 📂 {row['放行狀態']}
            </div>
            <div class="email-body">{row["原始內文"]}</div>
        </div>
        ''', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    exp_c1, exp_c2 = st.columns(2)
    with exp_c1:
        st.download_button(
            f"📊 匯出 CSV ({len(display_df)} 筆)",
            display_df.to_csv(index=False).encode("utf-8-sig"),
            "cn_orders.csv",
            "text/csv"
        )
    with exp_c2:
        st.download_button(
            f"🗂️ 匯出 Excel ({len(display_df)} 筆)",
            build_cn_excel(display_df),
            "cn_orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
