import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os, yaml, json, re, io
from datetime import datetime, timezone, timedelta

import folium
from folium.plugins import MarkerCluster
from folium.elements import MacroElement
from jinja2 import Template
from streamlit_folium import st_folium

# ==========================================
# 🛡️ 維護建議：
# 建議在部署的 requirements.txt 中綁定目前的 Streamlit 版本，
# 例如: streamlit==1.36.0，以避免未來官方更新 UI 結構時導致排版失效。
# ==========================================

# 建議將網頁預設為寬螢幕佈局
st.set_page_config(layout="wide", page_title="船隊調度管理系統", page_icon="🚢")

# ==========================================
# 🎨 自定義 CSS
# ==========================================
st.markdown("""
    <style>
    /* 調整指標數字大小與顏色 (商務藍) */
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #1a73e8; font-weight: 600; }
    
    /* 隱藏預設的 DataFrame index */
    .row_heading.level0 {display:none}
    .blank {display:none}
    
    /* 右側郵件閱讀器的精美樣式 (保留白底黑字以求最佳閱讀性) */
    .email-pane { 
        background-color: #ffffff; 
        color: #333333; 
        padding: 25px; 
        border-radius: 8px; 
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        height: 500px;
        box-sizing: border-box;
        overflow-y: auto;
    }
    .email-header {
        border-bottom: 1px solid #eeeeee;
        padding-bottom: 12px;
        margin-bottom: 20px;
    }
    .email-subject { 
        font-size: 1.3em; 
        font-weight: bold; 
        color: #202124; 
        margin-bottom: 8px;
    }
    .email-meta {
        font-size: 0.9em; 
        color: #5f6368; 
    }
    .email-body {
        white-space: pre-wrap; 
        font-family: 'Consolas', 'Courier New', monospace; 
        font-size: 14px;
        line-height: 1.6;
        color: #444444;
    }

    /* 手機版篩選器元件內縮與緊湊化 */
    @media (max-width: 640px) {
        div[id="mobile-filter-container"] label {
            font-size: 0.75rem !important; 
        }
        div[id="mobile-filter-container"] div[data-testid="stMarkdownContainer"] p {
            font-size: 0.75rem !important;
        }
        div[id="mobile-filter-container"] div[data-baseweb="select"] {
            font-size: 0.75rem !important; 
        }
        div[id="mobile-filter-container"] input {
            font-size: 0.7rem !important;  
            padding: 2px 4px !important;
        }
        div[id="mobile-filter-container"] div[data-baseweb="base-input"] {
            min-height: 30px !important;
            height: 30px !important;
        }
    }
    /* 全站區塊間距收緊，畫面更緊湊 */
    div[data-testid="stElementContainer"] { margin-bottom: 0.3rem; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 🗺️ 船隊地圖相關：常數與工具函式
# ==========================================
ARROW_HEADING = {
    '→': 90, '↗': 45, '↑': 0, '↖': 315,
    '←': 270, '↙': 225, '↓': 180, '↘': 135
}

SIGNAL_LIMIT_HOURS = 6
TAIPEI_TZ = timezone(timedelta(hours=8))

VMS_SPREADSHEET_ID = "1wwFluz-H4-r7HRKya1AUZ_2KyZ6bVow_2v-TBqXj46c"
VMS_VESSELDATA_GID = "1420495034"  


def _parse_custom_date(s):
    m = re.match(r'^(\d{4})(\d{2})(\d{2}) (\d{2}):(\d{2})$', str(s or "").strip())
    if not m: return None
    y, mo, d, h, mi = map(int, m.groups())
    try: return datetime(y, mo, d, h, mi, tzinfo=TAIPEI_TZ)
    except ValueError: return None


def _parse_position(raw):
    parts = str(raw or "").split(',')
    if len(parts) < 2: return None
    try: return {"lat": float(parts[0].strip()), "lon": float(parts[1].strip())}
    except ValueError: return None


def _parse_speed_field(raw):
    s = str(raw or "").strip()
    arrow = s[:1]
    heading = ARROW_HEADING.get(arrow, 0)
    digits = re.sub(r'[^\d.]', '', s)
    speed = float(digits) if digits else 0.0
    return {"speed": speed, "heading": heading}


def _find_column(columns, candidates):
    normalized = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand in normalized: return normalized[cand]
    for col_lower, col_orig in normalized.items():
        for cand in candidates:
            if cand in col_lower: return col_orig
    return None


@st.cache_data(ttl=300, show_spinner=False)
def load_vessel_positions():
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{VMS_SPREADSHEET_ID}"
        f"/export?format=csv&gid={VMS_VESSELDATA_GID}"
    )
    try:
        raw = pd.read_csv(csv_url)
    except Exception as e:
        st.sidebar.error(f"⚠️ 無法讀取船位資料（VesselData）：{e}")
        return pd.DataFrame()

    col_name = _find_column(raw.columns, ["vessel name", "vessel", "name"])
    col_last_signal = _find_column(raw.columns, ["last signal", "signal"])
    col_location = _find_column(raw.columns, ["location", "position"])
    col_speed = _find_column(raw.columns, ["speed/direction", "speed", "direction"])
    col_validity = _find_column(raw.columns, ["validity"])
    col_remark = _find_column(raw.columns, ["remark"])
    col_email = _find_column(raw.columns, ["email", "e-mail", "mail"])

    if col_name is None or col_last_signal is None:
        return pd.DataFrame()

    now = datetime.now(TAIPEI_TZ)
    rows = []
    for _, r in raw.iterrows():
        vessel_name = str(r[col_name]).strip() if pd.notna(r[col_name]) else ""
        if not vessel_name: continue

        last_signal = _parse_custom_date(r[col_last_signal])
        if not last_signal: continue

        pos = _parse_position(r[col_location]) if col_location and pd.notna(r[col_location]) else None
        speed_info = _parse_speed_field(r[col_speed]) if col_speed and pd.notna(r[col_speed]) else {"speed": 0, "heading": 0}
        validity = str(r[col_validity]) if col_validity and pd.notna(r[col_validity]) else "0/6"
        valid_count = int(validity.split('/')[0]) if '/' in validity and validity.split('/')[0].isdigit() else 0
        remark = str(r[col_remark]) if col_remark and pd.notna(r[col_remark]) else ""

        email_raw = str(r[col_email]).strip().lower() if col_email and pd.notna(r[col_email]) else ""
        email_local = email_raw.split('@')[0].strip() if '@' in email_raw else email_raw

        signal_hours = (now - last_signal).total_seconds() / 3600
        no_signal = signal_hours > SIGNAL_LIMIT_HOURS
        warning = (not no_signal) and valid_count <= 2

        if no_signal: status = "🔴 No Signal"
        elif warning: status = "🟡 Weak"
        else: status = "🟢 Normal"

        rows.append({
            "油輪": vessel_name,
            "email": email_raw,
            "email_local": email_local,
            "lat": pos["lat"] if pos else None,
            "lon": pos["lon"] if pos else None,
            "speed": speed_info["speed"],
            "heading": speed_info["heading"],
            "last_signal": last_signal,
            "signal_hours": round(signal_hours, 1),
            "validity": validity,
            "remark": remark,
            "no_signal": no_signal,
            "warning": warning,
            "status": status,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def build_vessel_summary(df: pd.DataFrame, vessel_pos_df: pd.DataFrame) -> pd.DataFrame:
    if vessel_pos_df.empty: return vessel_pos_df
    df_key = df["油輪"].astype(str).str.strip().str.lower()
    summary_rows = []
    
    for _, v in vessel_pos_df.iterrows():
        email_local = str(v.get("email_local", "")).strip().lower()
        if email_local: vdf = df[df_key == email_local]
        else: vdf = df[df["油輪"] == v["油輪"]]

        matched = not vdf.empty
        pending_count = int((vdf["狀態"] == "PENDING").sum())
        approved_count = int(vdf["狀態"].str.contains("APPROVED", case=False, na=False).sum())
        completed_count = int(vdf["狀態"].str.contains("COMPLETED", case=False, na=False).sum())
        kyc_fail_count = int(vdf["狀態"].str.contains("KYC", case=False, na=False).sum())

        latest = vdf.sort_values("日期", ascending=False).head(1)
        latest_subject = latest["主旨"].values[0] if not latest.empty else "-"
        latest_date = latest["日期"].values[0] if not latest.empty else pd.NaT
        matched_name = vdf["油輪"].iloc[0] if matched else None

        # ==========================================
        # 📌 排除已配對結案的紀錄，保留尚未走完流程的訂單
        # ==========================================
        paired_indices = set()
        valid_imo_df = vdf[~vdf['IMO'].isin(['-', '', '(本次無資料)'])]
        for imo, group in valid_imo_df.groupby('IMO'):
            approves = group[group['狀態'].str.contains('APPROVED', case=False, na=False)]
            completes = group[group['狀態'].str.contains('COMPLETED', case=False, na=False)]
            if not approves.empty and not completes.empty:
                for a_idx, a_row in approves.iterrows():
                    for c_idx, c_row in completes.iterrows():
                        a_time, c_time = a_row['日期'], c_row['日期']
                        if pd.notnull(a_time) and pd.notnull(c_time):
                            diff = c_time - a_time
                            if pd.Timedelta(0) <= diff <= pd.Timedelta(days=7):
                                # 若配對成功，則將 APPROVED 及 COMPLETED 從待處理清單中排除
                                paired_indices.add(a_idx)
                                paired_indices.add(c_idx)

        active_vdf = vdf.drop(index=list(paired_indices))

        # 抓「最新一筆的日期」往前推 2 天內的『未結案』紀錄
        recent_sorted = active_vdf.sort_values("日期", ascending=False)
        if not recent_sorted.empty and pd.notnull(recent_sorted["日期"].iloc[0]):
            cutoff = recent_sorted["日期"].iloc[0] - pd.Timedelta(days=2)
            recent_sorted = recent_sorted[recent_sorted["日期"] >= cutoff]
        recent_orders = recent_sorted[["狀態", "船名"]].to_dict("records") if not recent_sorted.empty else []

        row = v.to_dict()
        row.update({
            "matched": matched,
            "matched_油輪": matched_name,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "completed_count": completed_count,
            "kyc_fail_count": kyc_fail_count,
            "total_orders": len(vdf),
            "latest_subject": latest_subject,
            "latest_date": latest_date,
            "recent_orders": recent_orders,
        })
        summary_rows.append(row)
    return pd.DataFrame(summary_rows)


_MARKER_COLOR = {"🔴 No Signal": "red", "🟡 Weak": "orange", "🟢 Normal": "green"}


class EdgeTickOverlay(MacroElement):
    """
    在地圖容器的四個邊緣顯示動態經緯度刻度，跟著 moveend / zoomend
    即時重新計算像素位置，效果類似固定在畫面邊框的座標軸。
    """
    def __init__(self):
        super().__init__()
        self._template = Template("""
        {% macro script(this, kwargs) %}
        (function() {
            var map = {{ this._parent.get_name() }};
            var container = map.getContainer();

            var overlay = document.createElement('div');
            overlay.style.position = 'absolute';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.width = '100%';
            overlay.style.height = '100%';
            overlay.style.pointerEvents = 'none';
            overlay.style.zIndex = '650';
            container.appendChild(overlay);

            var NICE_STEPS = [1, 2, 5, 10, 15, 30, 45, 60, 90];
            function niceStep(span, targetCount) {
                var raw = span / targetCount;
                for (var i = 0; i < NICE_STEPS.length; i++) {
                    if (NICE_STEPS[i] >= raw) return NICE_STEPS[i];
                }
                return 90;
            }

            function fmtLon(lon) {
                var l = ((lon % 360) + 540) % 360 - 180; // 正規化到 -180~180
                l = Math.round(l);
                if (l === 0) return '0°';
                if (Math.abs(l) === 180) return '180°';
                return Math.abs(l) + (l > 0 ? '°E' : '°W');
            }
            function fmtLat(lat) {
                lat = Math.round(lat);
                if (lat === 0) return '0°';
                return Math.abs(lat) + (lat > 0 ? '°N' : '°S');
            }

            function addLabel(text, x, y, transform) {
                var el = document.createElement('div');
                el.textContent = text;
                el.style.position = 'absolute';
                el.style.fontSize = '10px';
                el.style.fontWeight = 'bold';
                el.style.color = '#546e7a';
                el.style.background = 'rgba(255,255,255,0.85)';
                el.style.padding = '1px 3px';
                el.style.borderRadius = '2px';
                el.style.whiteSpace = 'nowrap';
                el.style.left = x + 'px';
                el.style.top = y + 'px';
                el.style.transform = transform;
                overlay.appendChild(el);
            }

            function redraw() {
                overlay.innerHTML = '';
                var size = map.getSize();
                var bounds = map.getBounds();
                var west = bounds.getWest();
                var east = bounds.getEast();
                var south = bounds.getSouth();
                var north = bounds.getNorth();
                var lonSpan = east - west;
                var latSpan = north - south;
                if (lonSpan <= 0 || latSpan <= 0) return;

                var lonStep = niceStep(lonSpan, 6);
                var latStep = niceStep(latSpan, 5);

                var lonStart = Math.ceil(west / lonStep) * lonStep;
                for (var lon = lonStart; lon <= east; lon += lonStep) {
                    var ptTop = map.latLngToContainerPoint([north, lon]);
                    var ptBottom = map.latLngToContainerPoint([south, lon]);
                    addLabel(fmtLon(lon), ptTop.x, 4, 'translateX(-50%)');
                    addLabel(fmtLon(lon), ptBottom.x, size.y - 16, 'translateX(-50%)');
                }

                var latStart = Math.ceil(south / latStep) * latStep;
                for (var lat = latStart; lat <= north; lat += latStep) {
                    var ptLeft = map.latLngToContainerPoint([lat, west]);
                    var ptRight = map.latLngToContainerPoint([lat, east]);
                    addLabel(fmtLat(lat), 4, ptLeft.y, 'translateY(-50%)');
                    addLabel(fmtLat(lat), size.x - 4, ptRight.y, 'translate(-100%, -50%)');
                }
            }

            map.on('moveend', redraw);
            map.on('zoomend', redraw);
            map.whenReady(redraw);
            setTimeout(redraw, 200);
        })();
        {% endmacro %}
        """)


def _status_emoji(status):
    s = str(status).upper()
    if "APPROVED" in s: return "✅"
    if "COMPLETED" in s: return "🏁"
    if "KYC" in s or "CANCEL" in s: return "🚫"
    if "PENDING" in s: return "📋"
    return "•"


def _build_recent_orders_html(recent_orders, vessel_name):
    """組出 popup 裡「未結案訂單」的 HTML：利用 onclick 切換顯示，取代 details 標籤"""
    if not recent_orders:
        return '<div style="color:#999; margin-top:2px;">近期無待辦或未結案訂單</div>'

    def _item(o):
        status = o.get("狀態", "-") or "-"
        ship = o.get("船名", "-") or "-"
        return (
            f'<div style="padding:2px 0; border-bottom:1px solid #f0f0f0;">'
            f'{_status_emoji(status)} <b>{status}</b> ・ {ship}</div>'
        )

    MAX_TOTAL = 30  
    items = [_item(o) for o in recent_orders[:MAX_TOTAL]]
    html = '<div style="margin-top:4px;">' + "".join(items[:3])

    if len(items) > 3:
        rest_html = "".join(items[3:])
        # 產生安全的 HTML ID，避免特殊字元導致 JS 失效
        safe_id = re.sub(r'\W+', '_', str(vessel_name))
        
        # 這裡將額外的內容預設隱藏，點擊按鈕後將其顯示，同時將按鈕本身隱藏
        html += (
            f'<div id="extra_{safe_id}" style="display:none;">{rest_html}</div>'
            f'<div id="btn_{safe_id}" style="cursor:pointer; color:#1a73e8; font-size:11px; margin-top:4px; text-align:center;" '
            f'onclick="document.getElementById(\'extra_{safe_id}\').style.display=\'block\'; this.style.display=\'none\';">'
            f'▼ 顯示更多未結案訂單（共 {len(recent_orders)} 筆）</div>'
        )

    html += "</div>"
    return html


def render_fleet_map(vessel_summary_df: pd.DataFrame):
    valid = vessel_summary_df.dropna(subset=["lat", "lon"]).copy()
    if valid.empty:
        st.info("目前沒有可顯示座標的船舶資料。")
        return None

    # 跨太平洋日期變更線處理 (Rotate Lon)
    valid["map_lon"] = valid["lon"].apply(lambda x: x + 360 if pd.notnull(x) and x < 0 else x)

    center_lat = valid["lat"].mean()
    center_lon = valid["map_lon"].mean()

    # 初始化地圖
    m = folium.Map(location=[center_lat, center_lon], zoom_start=3, tiles="CartoDB positron")

    # 繪製經緯網格線 (純 Python 實現，極度穩定)
    for lat_line in range(-75, 76, 15):
        folium.PolyLine([[lat_line, 0], [lat_line, 360]], color="#8fa3af", weight=1.1, opacity=0.75, dash_array="6,4").add_to(m)
    for lon_line in range(0, 361, 30):
        folium.PolyLine([[-80, lon_line], [80, lon_line]], color="#8fa3af", weight=1.1, opacity=0.75, dash_array="6,4").add_to(m)

    # 邊緣經緯度刻度：跟著 moveend / zoomend 即時重算位置
    EdgeTickOverlay().add_to(m)

    # 聚類設定 (MarkerCluster)
    marker_cluster = MarkerCluster(
        options={"maxClusterRadius": 50, "disableClusteringAtZoom": 6}
    ).add_to(m)

    for _, v in valid.iterrows():
        color = _MARKER_COLOR.get(v["status"], "blue")
        last_signal_str = v["last_signal"].strftime("%m/%d %H:%M") if pd.notnull(v["last_signal"]) else "-"
        latest_date_str = (
            pd.to_datetime(v["latest_date"]).strftime("%m/%d %H:%M")
            if pd.notnull(v.get("latest_date")) else "-"
        )
        match_line = "" if v.get("matched") else '<div style="color:#d32f2f; margin-top:4px;">⚠️ 尚未配對到訂單資料</div>'
        
        # 將船名傳入以產生獨立的 Popup 控制按鈕 ID
        recent_orders_html = _build_recent_orders_html(v.get("recent_orders", []), v['油輪'])

        popup_html = f"""
        <div style="font-family:sans-serif; font-size:13px; min-width:220px;">
            <b style="font-size:14px;">🚢 {v['油輪']}</b><br>
            狀態：{v['status']}<br>
            座標：{v['lat']:.4f}, {v['lon']:.4f}<br>
            動態：航向 {v['heading']:.0f}° ・ 速度 {v['speed']:.1f} kn<br>
            最後訊號：{last_signal_str}（{v['signal_hours']:.1f} hr 前）<br>
            <hr style="margin:6px 0;">
            📋 待審 <b>{v.get('pending_count', 0)}</b> ・
            ✅ 已核准 <b>{v.get('approved_count', 0)}</b> ・
            🏁 已完成 <b>{v.get('completed_count', 0)}</b>
            {recent_orders_html}
            {match_line}
        </div>
        """

        folium.Marker(
            location=[v["lat"], v["map_lon"]],  
            tooltip=folium.Tooltip(f"<b>{v['油輪']}</b>", permanent=True, direction="right"),
            popup=folium.Popup(popup_html, max_width=280),
            icon=folium.Icon(color=color, icon="ship", prefix="fa"),
        ).add_to(marker_cluster)

    map_state = st_folium(
        m,
        height=460,
        use_container_width=True,
        key="fleet_map",
        returned_objects=["last_object_clicked_tooltip"],
    )
    return map_state


# --- 1. 讀取 Update Log ---
def load_update_log():
    if os.path.exists('update_log.json'):
        try:
            with open('update_log.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return None
    return None

# --- 2. 讀取 Kingdee JSON ---
@st.cache_data(ttl=600)
def load_ship_map():
    if os.path.exists('Kingdee_Export_UTF8.json'):
        try:
            with open('Kingdee_Export_UTF8.json', 'r', encoding='utf-8-sig') as f:
                return {str(item.get('imo', '')).strip(): item for item in json.load(f)}
        except: return {}
    return {}

ship_map = load_ship_map()

# --- 3. 解析工具 ---
def clean_mail_field(raw):
    if not raw: return ""
    raw = str(raw)
    raw = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', raw)
    return raw.strip()

def parse_ship_entries(target):
    if not target or str(target).strip() == "(本次無資料)":
        return [{"fv": "(本次無資料)", "imo": "-"}]
    segments = [s.strip() for s in str(target).split('|') if s.strip()]
    res = []
    for seg in segments:
        fv = re.search(r'FV:(.*?)丨', seg)
        if not fv: fv = re.search(r'FV:(.*)$', seg)
        imo = re.search(r'IMO:(\d+)', seg)
        res.append({"fv": fv.group(1).strip() if fv else "-", "imo": imo.group(1).strip() if imo else "-"})
    return res

@st.cache_data(ttl=60)
def build_tanker_excel(full_df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    export_df = full_df.drop(columns=["原始內文"], errors="ignore")

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        tankers = sorted([t for t in export_df["油輪"].unique() if t and t != "-"])
        used_names = set()

        for tanker in tankers:
            sheet_df = export_df[export_df["油輪"] == tanker].sort_values(
                by=["日期", "主旨"], ascending=[False, False]
            )

            safe_name = re.sub(r'[\\/*?:\[\]]', '_', str(tanker))[:31] or "sheet"
            base_name, n = safe_name, 1
            while safe_name in used_names:
                suffix = f"_{n}"
                safe_name = base_name[: 31 - len(suffix)] + suffix
                n += 1
            used_names.add(safe_name)

            sheet_df.to_excel(writer, sheet_name=safe_name, index=False)

            ws = writer.sheets[safe_name]
            for col_idx, col in enumerate(sheet_df.columns, start=1):
                values = sheet_df[col].astype(str).tolist()
                max_len = max([len(str(col))] + [len(v) for v in values]) if values else len(str(col))
                ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 50)
            ws.freeze_panes = "A2"

        if not tankers:
            pd.DataFrame().to_excel(writer, sheet_name="無資料", index=False)

    return output.getvalue()

@st.cache_data(ttl=60)
def load_all_data():
    rows = []
    parse_errors = []
    DATA_DIR = 'data_John'
    if not os.path.exists(DATA_DIR): return pd.DataFrame(rows), parse_errors
        
    EXCLUDE_FILES = {'checklist.md', 'schedule操作介面.md'}
    for root, _, files in os.walk(DATA_DIR):
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
            except Exception as e:
                parse_errors.append((fpath, f"{type(e).__name__}: {e}"))
                continue
    return pd.DataFrame(rows), parse_errors

# --- 4. 分割版面 (固定 3 欄結構) ---
def apply_split_layout(marker_id: str, n_selected: int):
    js = f"""
    <script>
    (function() {{
        function findTargetBlock(doc, marker) {{
            const allBlocks = Array.from(doc.querySelectorAll('[data-testid="stHorizontalBlock"]'));
            for (const b of allBlocks) {{
                if (marker.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) return b;
            }}
            return null;
        }}

        function setupHandle(doc, hBlock, id, left, right) {{
            const old = hBlock.querySelector('#' + id);
            if (old) old.remove();
            const h = doc.createElement('div');
            h.id = id;
            h.style.cssText = 'flex:0 0 8px;width:8px;cursor:col-resize;position:relative;z-index:999;display:flex;align-items:center;justify-content:center;';
            h.innerHTML = '<div style="width:2px;height:32px;background:#4a4a4a;border-radius:2px;pointer-events:none;"></div>';
            h.addEventListener('mouseenter', () => {{ h.firstChild.style.background = '#1a73e8'; }});
            h.addEventListener('mouseleave', () => {{ if (!h.dataset.dragging) h.firstChild.style.background = '#4a4a4a'; }});
            h.addEventListener('mousedown', (e) => {{
                h.dataset.dragging = '1';
                h.firstChild.style.background = '#1a73e8';
                doc.body.style.userSelect = 'none';
                e.preventDefault();
                const onMove = (ev) => {{
                    const lRect = left.getBoundingClientRect();
                    const rRect = right.getBoundingClientRect();
                    const combinedLeft = lRect.left;
                    const combinedWidth = rRect.right - lRect.left;
                    let newLeftWidth = ev.clientX - combinedLeft;
                    const minW = 80;
                    if (newLeftWidth < minW) newLeftWidth = minW;
                    if (newLeftWidth > combinedWidth - minW) newLeftWidth = combinedWidth - minW;
                    const pct = newLeftWidth / combinedWidth;
                    left.style.flex = pct + ' 1 0px';
                    right.style.flex = (1 - pct) + ' 1 0px';
                }};
                const onUp = () => {{
                    h.dataset.dragging = '';
                    h.firstChild.style.background = '#4a4a4a';
                    doc.body.style.userSelect = '';
                    doc.removeEventListener('mousemove', onMove);
                    doc.removeEventListener('mouseup', onUp);
                }};
                doc.addEventListener('mousemove', onMove);
                doc.addEventListener('mouseup', onUp);
            }});
            right.parentNode.insertBefore(h, right);
            return h;
        }}

        let attempts = 0;
        function init() {{
            attempts++;
            const doc = window.parent.document;
            const marker = doc.getElementById('{marker_id}');
            if (!marker) {{ if (attempts < 30) setTimeout(init, 80); return; }}
            const hBlock = findTargetBlock(doc, marker);
            if (!hBlock) {{ if (attempts < 30) setTimeout(init, 80); return; }}
            const cols = Array.from(hBlock.children).filter(c => c.getAttribute && c.getAttribute('data-testid') === 'stColumn');
            if (cols.length < 3) {{ if (attempts < 30) setTimeout(init, 80); return; }}

            hBlock.style.display = 'flex';
            hBlock.style.alignItems = 'stretch';
            const [c0, c1, c2] = cols;
            [c0, c1, c2].forEach(c => {{ c.style.overflow = 'hidden'; c.style.minWidth = '0'; c.style.transition = 'none'; }});

            const handle1 = setupHandle(doc, hBlock, 'split-handle-1', c0, c1);
            const handle2 = setupHandle(doc, hBlock, 'split-handle-2', c1, c2);

            const n = {n_selected};
            if (n === 0) {{
                c0.style.flex = '1 1 100%'; c0.style.display = '';
                c1.style.display = 'none';
                c2.style.display = 'none';
                handle1.style.display = 'none';
                handle2.style.display = 'none';
            }} else if (n === 1) {{
                c0.style.display = ''; c1.style.display = ''; c2.style.display = 'none';
                c0.style.flex = '1 1 0px'; c1.style.flex = '1 1 0px';
                handle1.style.display = 'flex';
                handle2.style.display = 'none';
            }} else {{
                c0.style.display = ''; c1.style.display = ''; c2.style.display = '';
                c0.style.flex = '1 1 0px'; c1.style.flex = '1 1 0px'; c2.style.flex = '1 1 0px';
                handle1.style.display = 'flex';
                handle2.style.display = 'flex';
            }}
        }}
        setTimeout(init, 60);
    }})();
    </script>
    """
    components.html(js, height=0, width=0)

# --- 5. 強制手機版篩選器維持同一行不拆行 ---
def apply_mobile_filter_layout():
    js = """
    <script>
    (function() {
        let attempts = 0;
        function fixFilter() {
            attempts++;
            const doc = window.parent.document;
            const container = doc.getElementById('mobile-filter-container');
            if (!container) {
                if (attempts < 30) setTimeout(fixFilter, 80);
                return;
            }
            
            const hBlock = container.querySelector('[data-testid="stHorizontalBlock"]');
            if (!hBlock) return;
            
            hBlock.style.setProperty('display', 'flex', 'important');
            hBlock.style.setProperty('flex-direction', 'row', 'important');
            hBlock.style.setProperty('flex-wrap', 'nowrap', 'important');
            hBlock.style.setProperty('gap', '8px', 'important');
            
            const cols = Array.from(hBlock.children).filter(c => c.getAttribute && c.getAttribute('data-testid') === 'stColumn');
            cols.forEach(col => {
                col.style.setProperty('flex', '1 1 0%', 'important');
                col.style.setProperty('min-width', '0', 'important');
                col.style.setProperty('width', 'auto', 'important'); 
            });
        }
        setTimeout(fixFilter, 50);
    })();
    </script>
    """
    components.html(js, height=0, width=0)


# --- 介面渲染 ---
st.markdown("""
    <div class="compact-title">🚢 船隊實時調度報表</div>
    """, unsafe_allow_html=True)

# 載入資料庫
df, parse_errors = load_all_data()

if parse_errors:
    with st.sidebar.expander(f"⚠️ 解析失敗的信件 ({len(parse_errors)} 筆)"):
        for fpath, err in parse_errors:
            st.write(f"`{fpath}`")
            st.caption(err)

# 數據看板 (Metrics)
log = load_update_log()
if log:
    update_time = log.get('update_time', '未知')
    total_files = log.get('total_files', 0)
    latest_date_str = log.get('latest_date_str', '未知')
    latest_emails = log.get('latest_emails', 0)
    latest_imos = log.get('latest_imos', 0)
    latest_nodata = log.get('latest_nodata', 0)
    total_targets = latest_imos + latest_nodata

    with st.expander(f"📊 資料看板：總信件庫 {total_files} 封 ・ 最新 {latest_emails} 封 ・ 最後同步 {update_time}", expanded=False):
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("📁 總信件庫", f"{total_files} 封")
        col_m2.metric(f"📅 最新 ({latest_date_str})", f"{latest_emails} 封")
        col_m3.metric("🚢 最新解析郵件", f"{total_targets} 筆")
        col_m4.metric("⏱️ 最後同步時間", update_time)

if not df.empty:
    vessel_pos_df = load_vessel_positions()
    vessel_summary_df = build_vessel_summary(df, vessel_pos_df)

    if "selected_tanker" not in st.session_state:
        st.session_state["selected_tanker"] = "全部"

    # 頂部篩選器
    st.markdown('<div id="mobile-filter-container">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 1])
    
    with c1:
        tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        if st.session_state["selected_tanker"] not in tankers:
            st.session_state["selected_tanker"] = "全部"
            
        def _on_tanker_change():
            st.session_state["selected_tanker"] = st.session_state.tanker_select_widget
            
        st.selectbox(
            "🚢 篩選油輪", 
            tankers, 
            index=tankers.index(st.session_state["selected_tanker"]),
            key="tanker_select_widget",
            on_change=_on_tanker_change
        )
        
    with c2:
        dynamic_statuses = ["全部"] + sorted(list(df["狀態"].unique()))
        sel_status = st.selectbox("📂 篩選狀態", dynamic_statuses)
        
    with c3:
        valid_dates = df["日期"].dropna()
        m_date = valid_dates.min().date() if not valid_dates.empty else datetime.today().date()
        x_date = valid_dates.max().date() if not valid_dates.empty else datetime.today().date()
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date))
        
    st.markdown('</div>', unsafe_allow_html=True)
    apply_mobile_filter_layout()

    # 資料過濾邏輯
    mask = pd.Series([True] * len(df))
    if st.session_state["selected_tanker"] != "全部": 
        mask &= (df["油輪"] == st.session_state["selected_tanker"])
    if sel_status != "全部": 
        mask &= (df["狀態"] == sel_status)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        start_dt = pd.to_datetime(sel_range[0])
        end_dt = pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
        mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

    display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False]).reset_index(drop=True)

    # --- 船隊即時地圖 ---
    with st.expander("🗺️ 船隊即時位置地圖", expanded=True):
        map_state = render_fleet_map(vessel_summary_df)

        clicked_vessel = None
        if map_state and map_state.get("last_object_clicked_tooltip"):
            clicked_html = map_state["last_object_clicked_tooltip"]
            clicked_vessel = clicked_html.replace('<b>', '').replace('</b>', '').strip()

        if clicked_vessel and clicked_vessel != st.session_state.get("_last_clicked_vessel"):
            st.session_state["_last_clicked_vessel"] = clicked_vessel

            match_row = vessel_summary_df[vessel_summary_df["油輪"] == clicked_vessel]
            if not match_row.empty and match_row["matched"].iloc[0]:
                st.session_state["selected_tanker"] = match_row["matched_油輪"].iloc[0]
            else:
                st.session_state["selected_tanker"] = "全部"
                st.toast(f"⚠️ {clicked_vessel} 尚未配對到任何訂單郵件")
            st.rerun()

    # ===============================================
    # 表格選取與重置邏輯
    # ===============================================
    if "df_key_counter" not in st.session_state:
        st.session_state.df_key_counter = 0
    DF_KEY = f"email_table_{st.session_state.df_key_counter}"

    if "sel_seq" not in st.session_state:
        st.session_state.sel_seq = {}   
    if "sel_counter" not in st.session_state:
        st.session_state.sel_counter = 0

    _hint_rows = st.session_state.get(DF_KEY, {}).get("selection", {}).get("rows", [])
    guess_has_selection = len(st.session_state.sel_seq) > 0 or len(_hint_rows) > 0

    if not guess_has_selection:
        marker_id = None
        col_list = st.container()
        preview_cols = []
    else:
        marker_id = "split-marker"
        st.markdown(f'<div id="{marker_id}"></div>', unsafe_allow_html=True)
        col_list, col_preview1, col_preview2 = st.columns([1, 1, 1], gap="small")
        preview_cols = [col_preview1, col_preview2]

    with col_list:
        DISPLAY_COLUMNS = ["油輪", "日期", "狀態", "船名", "IMO", "呼號", "ETA", "位置", "主旨"]

        def style_status(val):
            val_upper = str(val).upper().strip()
            if "APPROVED" in val_upper: 
                return "background-color: rgba(250, 225, 50, 0.3);"
            elif "COMPLETED" in val_upper: 
                return "background-color: rgba(255, 128, 128, 0.3);"
            elif "CANCELLED" in val_upper or "KYC" in val_upper: 
                return "background-color: rgba(230, 120, 230, 0.3);"
            elif "PENDING" in val_upper: 
                return "background-color: rgba(255, 243, 205, 0.3);"
            return ""

        valid_dup_indices = set()
        valid_imo_mask = ~display_df['IMO'].isin(['-', '', '(本次無資料)'])
        valid_df = display_df[valid_imo_mask]
        
        for (tanker, imo), group in valid_df.groupby(['油輪', 'IMO']):
            approved_rows = group[group['狀態'].str.contains('APPROVED', case=False, na=False)]
            completed_rows = group[group['狀態'].str.contains('COMPLETED', case=False, na=False)]
            
            if not approved_rows.empty and not completed_rows.empty:
                for a_idx, a_row in approved_rows.iterrows():
                    for c_idx, c_row in completed_rows.iterrows():
                        a_time = a_row['日期']
                        c_time = c_row['日期']
                        
                        if pd.notnull(a_time) and pd.notnull(c_time):
                            time_diff = c_time - a_time
                            if pd.Timedelta(0) < time_diff <= pd.Timedelta(days=7):
                                valid_dup_indices.add(a_idx)
                                valid_dup_indices.add(c_idx)

        def style_duplicate_imo(s):
            return ['background-color: rgba(253, 126, 20, 0.5);' if i in valid_dup_indices else '' for i in s.index]
            
        styled_df = display_df[DISPLAY_COLUMNS].style.map(style_status, subset=["狀態"])
        styled_df = styled_df.apply(style_duplicate_imo, subset=["IMO"])
        
        event = st.dataframe(
            styled_df,  
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="multi-row",
            key=DF_KEY,
            height=500,
            column_config={
                "日期": st.column_config.DatetimeColumn("收信時間", format="MM/DD HH:mm"), 
                "狀態": st.column_config.TextColumn("狀態", width="small"),
                "主旨": st.column_config.TextColumn("郵件主旨", width="medium")
            }
        )
        
        st.markdown("<br>", unsafe_allow_html=True)
        exp_c1, exp_c2, exp_c3 = st.columns([1, 1, 1])
        with exp_c1:
            st.download_button(
                f"📊 匯出目前篩選 ({len(display_df)} 筆)", 
                display_df.to_csv(index=False).encode('utf-8-sig'), 
                "ship_report.csv", 
                "text/csv"
            )
        with exp_c2:
            st.download_button(
                f"🗂️ 匯出全部資料",
                build_tanker_excel(df),
                "ship_report_by_tanker.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        # 加入「關閉預覽」按鈕
        with exp_c3:
            if guess_has_selection:
                if st.button("❌ 關閉預覽 (清除選取)", use_container_width=True):
                    st.session_state.sel_seq = {}
                    st.session_state.df_key_counter += 1
                    st.rerun()

    # === 更新序號並計算預覽項目 ===
    raw_rows = event.get("selection", {}).get("rows", [])
    raw_set = set(raw_rows)

    for r in list(st.session_state.sel_seq.keys()):
        if r not in raw_set:
            del st.session_state.sel_seq[r]

    for r in raw_rows:
        if r not in st.session_state.sel_seq:
            st.session_state.sel_counter += 1
            st.session_state.sel_seq[r] = st.session_state.sel_counter

    all_checked = sorted(st.session_state.sel_seq.keys(), key=lambda r: st.session_state.sel_seq[r])
    preview_order = all_checked[-2:] if len(all_checked) > 2 else all_checked
    n_selected = len(preview_order)

    if len(all_checked) > 2:
        st.warning(
            f"⚠️ 目前勾選了 {len(all_checked)} 筆，僅預覽最後選取的 2 筆。"
            "若要讓表格勾選狀態也只剩 2 筆，請手動取消較舊的勾選。"
        )

    if marker_id:
        apply_split_layout(marker_id, n_selected)

    def render_email_pane(container, row):
        time_str = row['日期'].strftime('%Y-%m-%d %H:%M') if pd.notnull(row['日期']) else '未知時間'
        with container:
            st.markdown(f'''
            <div class="email-pane">
                <div class="email-header">
                    <div class="email-subject">{row['主旨']}</div>
                    <div class="email-meta">
                        🚢 <b>{row['油輪']}</b> &nbsp; | &nbsp; 📅 {time_str} &nbsp; | &nbsp; 📂 {row['狀態']}
                    </div>
                </div>
                <div class="email-body">{row["原始內文"]}</div>
            </div>
            ''', unsafe_allow_html=True)

    for i, row_idx in enumerate(preview_order):
        if i < len(preview_cols) and row_idx < len(display_df):
            render_email_pane(preview_cols[i], display_df.iloc[row_idx])

    if (n_selected == 0) != (not guess_has_selection):
        st.rerun()
