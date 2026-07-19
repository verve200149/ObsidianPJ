import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os, yaml, json, re, io, html
from datetime import datetime, timezone, timedelta

import folium
from folium.plugins import MarkerCluster
from folium.elements import MacroElement
from jinja2 import Template
from streamlit_folium import st_folium

# ==========================================
# 🛡️ 維護建議與基本設定
# ==========================================
st.set_page_config(layout="wide", page_title="船隊調度管理系統", page_icon="🚢")

st.markdown("""
    <style>
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #1a73e8; font-weight: 600; }
    .row_heading.level0 {display:none}
    .blank {display:none}
    .email-pane { 
        background-color: #ffffff; color: #333333; padding: 25px; 
        border-radius: 8px; border: 1px solid #e0e0e0; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        height: 500px; box-sizing: border-box; overflow-y: auto;
    }
    .email-header { border-bottom: 1px solid #eeeeee; padding-bottom: 12px; margin-bottom: 20px; }
    .email-subject { font-size: 1.3em; font-weight: bold; color: #202124; margin-bottom: 8px; }
    .email-meta { font-size: 0.9em; color: #5f6368; }
    .email-body { white-space: pre-wrap; font-family: 'Consolas', 'Courier New', monospace; font-size: 14px; line-height: 1.6; color: #444444; }
    div[data-testid="stElementContainer"] { margin-bottom: 0.3rem; }
    .leaflet-tooltip {
        background-color: rgba(255, 255, 255, 0.65) !important;
        border: 1px solid rgba(200, 200, 200, 0.2) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important;
        font-size: 10px !important; font-weight: 600 !important;
        padding: 2px 6px !important; backdrop-filter: blur(2px);
    }
    .leaflet-tooltip-right::before, .leaflet-tooltip-left::before { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 🗺️ 常數與工具函式
# ==========================================
ARROW_HEADING = {'→': 90, '↗': 45, '↑': 0, '↖': 315, '←': 270, '↙': 225, '↓': 180, '↘': 135}
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

def _status_emoji(status):
    s = str(status).upper()
    if "APPROVED" in s: return "✅"
    if "COMPLETED" in s: return "🏁"
    if "KYC" in s or "CANCEL" in s: return "🚫"
    if "PENDING" in s: return "📋"
    return "•"

def _format_coord(lat, lon):
    lat_dir = "N" if lat >= 0 else "S"
    lon_dir = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f}°{lat_dir}, {abs(lon):.4f}°{lon_dir}"

def _progress_bar(done, plan, width=8):
    if plan <= 0: return "░" * width
    ratio = max(0.0, min(1.0, done / plan))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)

# ==========================================
# ⚙️ 核心狀態機與資料處理
# ==========================================
def get_imo_current_status(imo_group_df):
    valid_df = imo_group_df.dropna(subset=["日期"]).sort_values("日期", ascending=False)
    if valid_df.empty: return None

    last_app = valid_df[valid_df["狀態"].str.contains("APPROVED", case=False, na=False)]["日期"].max()
    last_done = valid_df[valid_df["狀態"].str.contains("COMPLETED", case=False, na=False)]["日期"].max()
    last_cancel = valid_df[valid_df["狀態"].str.contains("CANCEL", case=False, na=False)]["日期"].max()

    candidates = []
    if pd.notnull(last_app): candidates.append(("PLAN", last_app))
    if pd.notnull(last_done): candidates.append(("DONE", last_done))
    if pd.notnull(last_cancel): candidates.append(("CANCELLED", last_cancel))

    latest_row = valid_df.iloc[0]

    if not candidates:
        raw_status = str(latest_row["狀態"]).upper()
        return {
            "current_status": "PENDING" if "PENDING" in raw_status else raw_status,
            "last_date": latest_row["日期"],
            "is_overdue": False,
            "vessel_name": latest_row["船名"],
            "subject": latest_row["主旨"]
        }

    latest_status, latest_date = max(candidates, key=lambda x: x[1])

    is_overdue = False
    if latest_status == "PLAN":
        tz_info = latest_date.tzinfo if hasattr(latest_date, 'tzinfo') else None
        now = pd.Timestamp.now(tz=tz_info)
        if (now - latest_date).days > 14:
            is_overdue = True

    return {
        "current_status": latest_status,
        "last_date": latest_date,
        "is_overdue": is_overdue,
        "vessel_name": latest_row["船名"],
        "subject": latest_row["主旨"]
    }

@st.cache_data(ttl=300, show_spinner=False)
def load_vessel_positions():
    csv_url = f"https://docs.google.com/spreadsheets/d/{VMS_SPREADSHEET_ID}/export?format=csv&gid={VMS_VESSELDATA_GID}"
    try: raw = pd.read_csv(csv_url)
    except Exception as e:
        st.sidebar.error(f"⚠️ 無法讀取船位資料：{e}")
        return pd.DataFrame()

    col_name = _find_column(raw.columns, ["vessel name", "vessel", "name"])
    col_last_signal = _find_column(raw.columns, ["last signal", "signal"])
    col_location = _find_column(raw.columns, ["location", "position"])
    col_speed = _find_column(raw.columns, ["speed/direction", "speed", "direction"])
    col_validity = _find_column(raw.columns, ["validity"])
    col_remark = _find_column(raw.columns, ["remark"])
    col_email = _find_column(raw.columns, ["email", "e-mail", "mail"])

    if col_name is None or col_last_signal is None: return pd.DataFrame()

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
            "油輪": vessel_name, "email": email_raw, "email_local": email_local,
            "lat": pos["lat"] if pos else None, "lon": pos["lon"] if pos else None,
            "speed": speed_info["speed"], "heading": speed_info["heading"],
            "last_signal": last_signal, "signal_hours": round(signal_hours, 1),
            "validity": validity, "remark": remark, "no_signal": no_signal,
            "warning": warning, "status": status,
        })
    return pd.DataFrame(rows)

@st.cache_data(ttl=60, show_spinner=False)
def build_vessel_summary(df: pd.DataFrame, vessel_pos_df: pd.DataFrame) -> pd.DataFrame:
    if vessel_pos_df.empty: return vessel_pos_df

    df = df.copy()
    df["_key"] = df["油輪"].astype(str).str.strip().str.lower()
    grouped = dict(tuple(df.groupby("_key")))
    empty_df = df.iloc[0:0] 

    summary_rows = []
    
    for _, v in vessel_pos_df.iterrows():
        email_local = str(v.get("email_local", "")).strip().lower()
        if email_local: vdf = grouped.get(email_local, empty_df)
        else: vdf = df[df["油輪"] == v["油輪"]]

        matched = not vdf.empty
        completed_count = int(vdf["狀態"].str.contains("COMPLETED", case=False, na=False).sum())
        latest = vdf.sort_values("日期", ascending=False).head(1)
        latest_subject = latest["主旨"].values[0] if not latest.empty else "-"
        latest_date = latest["日期"].values[0] if not latest.empty else pd.NaT

        plan_count = 0
        done_count = 0
        overdue_count = 0
        ready_count = 0 
        recent_orders = []

        if 'IMO' in vdf.columns:
            valid_imo_df = vdf[~vdf['IMO'].isin(['-', '', '(本次無資料)'])]
            imo_states = {}
            for imo, group in valid_imo_df.groupby('IMO'):
                status_info = get_imo_current_status(group)
                if status_info: imo_states[imo] = status_info

            for imo, info in imo_states.items():
                c_status = info["current_status"]
                is_overdue = info["is_overdue"]
                
                if c_status == "PLAN":
                    plan_count += 1
                    ready_count += 1
                    if is_overdue: overdue_count += 1
                elif c_status == "DONE":
                    done_count += 1

                tz_info = info["last_date"].tzinfo if hasattr(info["last_date"], 'tzinfo') else None
                cutoff = pd.Timestamp.now(tz=tz_info) - pd.Timedelta(days=5)
                
                if c_status == "PLAN" or info["last_date"] >= cutoff:
                    display_status = "OVERDUE ⚠️" if is_overdue else c_status
                    recent_orders.append({
                        "狀態": display_status, "日期": info["last_date"],
                        "船名": info["vessel_name"], "IMO": imo
                    })

            recent_orders = sorted(recent_orders, key=lambda x: x["日期"], reverse=True)

        row = v.to_dict()
        row.update({
            "matched": matched, "matched_油輪": vdf["油輪"].iloc[0] if matched else None,
            "ready_count": ready_count, "plan_count": plan_count, "done_count": done_count,
            "overdue_count": overdue_count, "completed_count": completed_count,
            "total_orders": len(vdf), "latest_subject": latest_subject,
            "latest_date": latest_date, "recent_orders": recent_orders,
        })
        summary_rows.append(row)
        
    return pd.DataFrame(summary_rows)

# ==========================================
# 🗺️ 地圖渲染相關
# ==========================================
_MARKER_COLOR = {"🔴 No Signal": "red", "🟡 Weak": "orange", "🟢 Normal": "green"}
_MARKER_HEX = {"🔴 No Signal": "#e53935", "🟡 Weak": "#fb8c00", "🟢 Normal": "#2e7d32"}

MAJOR_PORTS = [
    {"name": "Kaohsiung", "lat": 22.61, "lon": 120.31},
    {"name": "Singapore", "lat": 1.26, "lon": 103.83},
    # ... (省略部分港口以節省空間，請自行補回你原有的 MAJOR_PORTS 清單) ...
]

class EdgeTickOverlay(MacroElement):
    def __init__(self):
        super().__init__()
        self._template = Template("""
        {% macro script(this, kwargs) %}
        (function() {
            // ... (請補回你原有的 EdgeTickOverlay JS 邏輯) ...
        })();
        {% endmacro %}
        """)

def _add_major_ports(m):
    for p in MAJOR_PORTS:
        map_lon = p["lon"] + 360 if p["lon"] < 0 else p["lon"]
        folium.CircleMarker(location=[p["lat"], map_lon], radius=3, color="#78909c", weight=1, fill=True, fill_color="#cfd8dc", fill_opacity=0.9, tooltip=p["name"]).add_to(m)
        folium.Marker(location=[p["lat"], map_lon], icon=folium.DivIcon(html=('<div style="font-size:9px; color:#78909c; font-weight:600; white-space:nowrap; transform:translate(6px,-4px); text-shadow:0 0 2px #fff, 0 0 2px #fff;">' + p["name"] + '</div>'), icon_size=(0, 0), icon_anchor=(0, 0))).add_to(m)

def _ship_div_icon(color_hex, heading):
    svg = f'<div style="width:24px; height:24px; transform:rotate({heading}deg); filter:drop-shadow(0 1px 1px rgba(0,0,0,0.35));"><svg viewBox="0 0 24 24" width="24" height="24"><path d="M12 1.5 L19 16 L12 12.5 L5 16 Z" fill="{color_hex}" stroke="#2d2d2d" stroke-width="1" stroke-linejoin="round"/></svg></div>'
    return folium.DivIcon(html=svg, icon_size=(24, 24), icon_anchor=(12, 12))

def _tooltip_style(v):
    if not v.get("matched"): return "#9e9e9e"
    ready_count = v.get("ready_count", 0)
    speed = v.get("speed", 0) or 0
    if ready_count >= 10: return "#e65100"
    if speed < 0.5: return "#1565c0"
    return "#2e7d32"

def _build_recent_orders_html(recent_orders, vessel_name):
    if not recent_orders: return '<div style="color:#999; margin-top:2px;">近期無待辦或未結案訂單</div>'
    def _item(o):
        status = o.get("狀態", "-") or "-"
        display_status = "APPD" if "APPROVED" in str(status).upper() else status
        ship = o.get("船名", "-") or "-"
        dt = o.get("日期", pd.NaT)
        dt_str = dt.strftime('%m/%d') if pd.notnull(dt) else ""
        dt_html = f"<span style='color:#888; font-size:11px;'>({dt_str})</span>" if dt_str else ""
        return f'<div style="padding:2px 0; border-bottom:1px solid #f0f0f0; font-size:12px;">{_status_emoji(status)} <b>{display_status}</b> {dt_html} ・ {ship}</div>'
    
    items = [_item(o) for o in recent_orders]
    total = len(items)
    html_out = '<div style="margin-top:4px;">' + "".join(items[:3])
    if total > 3:
        rest_html = "".join(items[3:])
        safe_id = re.sub(r'\W+', '_', str(vessel_name))
        scroll_style = " max-height:220px; overflow-y:auto;" if total > 10 else ""
        html_out += f'<div id="extra_{safe_id}" style="display:none;{scroll_style}">{rest_html}</div><div id="btn_{safe_id}" style="cursor:pointer; color:#1a73e8; font-size:11px; margin-top:4px; text-align:center;" onclick="document.getElementById(\'extra_{safe_id}\').style.display=\'block\'; this.style.display=\'none\';">▼ 顯示更多近五天訂單（共 {total} 筆）</div>'
    html_out += "</div>"
    return html_out

def _build_copy_text(v, plan_count, done_count, coord_str, last_signal_str):
    status_emoji_only = str(v.get('status', '')).split(' ')[0]
    lines = [
        f"{status_emoji_only} {v['油輪']}",
        f"狀態：{v['status']}",
        f"POS：{coord_str}",
        f"HDG {v['heading']:.0f}° ・ SPD {v['speed']:.1f}kn",
        f"LSIG：{last_signal_str}（{v['signal_hours']:.1f}hr）",
        f"PLAN：{plan_count} ｜ DONE：{done_count} {_progress_bar(done_count, plan_count)}",
    ]
    recent_orders = v.get("recent_orders", []) or []
    if recent_orders:
        lines.append("近期訂單：")
        for o in recent_orders:
            status = o.get("狀態", "-") or "-"
            display_status = "APPD" if "APPROVED" in str(status).upper() else status
            ship = o.get("船名", "-") or "-"
            dt = o.get("日期", pd.NaT)
            dt_str = dt.strftime('%m/%d') if pd.notnull(dt) else "-"
            lines.append(f"  {display_status} ({dt_str}) - {ship}")
    return "\n".join(lines)

def render_fleet_map(vessel_summary_df: pd.DataFrame):
    valid = vessel_summary_df.dropna(subset=["lat", "lon"]).copy()
    if valid.empty:
        st.info("目前沒有可顯示座標的船舶資料。")
        return None

    valid["map_lon"] = valid["lon"].apply(lambda x: x + 360 if pd.notnull(x) and x < 0 else x)
    center_lat = valid["lat"].mean()
    center_lon = valid["map_lon"].mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=3, tiles="CartoDB positron")

    for lat_line in range(-75, 76, 15):
        folium.PolyLine([[lat_line, 0], [lat_line, 360]], color="#8fa3af", weight=1.1, opacity=0.75, dash_array="6,4").add_to(m)
    for lon_line in range(0, 361, 30):
        folium.PolyLine([[-80, lon_line], [80, lon_line]], color="#8fa3af", weight=1.1, opacity=0.75, dash_array="6,4").add_to(m)

    EdgeTickOverlay().add_to(m)
    _add_major_ports(m)

    marker_cluster = MarkerCluster(options={"maxClusterRadius": 50, "disableClusteringAtZoom": 6}).add_to(m)

    for _, v in valid.iterrows():
        last_signal_str = v["last_signal"].strftime("%m/%d %H:%M") if pd.notnull(v["last_signal"]) else "-"
        match_line = "" if v.get("matched") else '<div style="color:#d32f2f; margin-top:4px;">⚠️ 尚未配對到訂單資料</div>'
        recent_orders_html = _build_recent_orders_html(v.get("recent_orders", []), v['油輪'])

        plan_count = v.get('plan_count', 0)
        done_count = v.get('done_count', 0)
        label_color = _tooltip_style(v)
        tooltip_html = f"<div style='color:{label_color};'><i class='fa fa-ship'></i> {v['油輪']}</div>"
        icon_hex = _MARKER_HEX.get(v["status"], "#1e88e5")
        coord_str = _format_coord(v["lat"], v["lon"])
        copy_text = _build_copy_text(v, plan_count, done_count, coord_str, last_signal_str)
        copy_text_attr = html.escape(copy_text, quote=True)

        copy_btn_html = f'<button type="button" data-copytext="{copy_text_attr}" style="margin-top:6px; width:100%; padding:4px 0; font-size:11px; color:#1a73e8; background:#f1f6fe; border:1px solid #cfe0fb; border-radius:4px; cursor:pointer;" onclick="var t=this.getAttribute(\'data-copytext\'); var done=function(){{ this.textContent=\'✅ 已複製\'; var b=this; setTimeout(function(){{ b.textContent=\'📋 複製船舶資訊\'; }}, 1500); }}.bind(this); if(navigator.clipboard && navigator.clipboard.writeText){{ navigator.clipboard.writeText(t).then(done).catch(function(){{ var ta=document.createElement(\'textarea\'); ta.value=t; ta.style.position=\'fixed\'; ta.style.opacity=\'0\'; document.body.appendChild(ta); ta.focus(); ta.select(); try{{ document.execCommand(\'copy\'); }}catch(e){{}} document.body.removeChild(ta); }}); }}else{{ var ta=document.createElement(\'textarea\'); ta.value=t; ta.style.position=\'fixed\'; ta.style.opacity=\'0\'; document.body.appendChild(ta); ta.focus(); ta.select(); try{{ document.execCommand(\'copy\'); }}catch(e){{}} document.body.removeChild(ta); }} this.textContent=\'✅ 已複製\'; var b=this; setTimeout(function(){{ b.textContent=\'📋 複製船舶資訊\'; }}, 1500); ">📋 複製船舶資訊</button>'

        status_emoji_only = str(v.get('status', '')).split(' ')[0]
        progress_bar_str = _progress_bar(done_count, plan_count)

        popup_html = f"""
        <div style="font-family:sans-serif; font-size:13px; min-width:220px;">
            <b style="font-size:14px;">{status_emoji_only} {v['油輪']}</b><br>
            POS：{coord_str}<br>
            HDG {v['heading']:.0f}° ・ SPD {v['speed']:.1f}kn<br>
            LSIG：{last_signal_str}（{v['signal_hours']:.1f}hr）<br>
            <hr style="margin:6px 0;">
            <div style="font-family:'Consolas','Courier New',monospace; font-size:12px; letter-spacing:1px;">
                PLAN：{plan_count} ｜ DONE：{done_count} {progress_bar_str}
            </div>
            {recent_orders_html}
            {match_line}
            {copy_btn_html}
        </div>
        """
        folium.Marker(location=[v["lat"], v["map_lon"]], tooltip=folium.Tooltip(tooltip_html, permanent=True, direction="right"), popup=folium.Popup(popup_html, max_width=280), icon=_ship_div_icon(icon_hex, v.get("heading", 0) or 0)).add_to(marker_cluster)

    return st_folium(m, height=460, use_container_width=True, key="fleet_map", returned_objects=["last_object_clicked_tooltip"])

# ==========================================
# 📂 檔案讀寫與資料載入
# ==========================================
def load_update_log():
    if os.path.exists('update_log.json'):
        try:
            with open('update_log.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: return None
    return None

@st.cache_data(ttl=600)
def load_ship_map():
    if os.path.exists('Kingdee_Export_UTF8.json'):
        try:
            with open('Kingdee_Export_UTF8.json', 'r', encoding='utf-8-sig') as f:
                return {str(item.get('imo', '')).strip(): item for item in json.load(f)}
        except: return {}
    return {}

ship_map = load_ship_map()

def clean_mail_field(raw):
    if not raw: return ""
    raw = str(raw)
    return re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', raw).strip()

def parse_ship_entries(target):
    if not target or str(target).strip() == "(本次無資料)": return [{"fv": "(本次無資料)", "imo": "-"}]
    segments = [s.strip() for s in str(target).split('|') if s.strip()]
    res = []
    for seg in segments:
        fv = re.search(r'FV:(.*?)丨', seg)
        if not fv: fv = re.search(r'FV:(.*)$', seg)
        imo = re.search(r'IMO:(\d+)', seg)
        res.append({"fv": fv.group(1).strip() if fv else "-", "imo": imo.group(1).strip() if imo else "-"})
    return res

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
                with open(fpath, 'r', encoding='utf-8') as f: raw_text = f.read()
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
                        "日期": pd.to_datetime(fm.get('date'), errors='coerce'),
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

@st.cache_data(ttl=30, show_spinner=False)
def _compute_duplicate_pair_indices(display_df: pd.DataFrame) -> set:
    valid_dup_indices = set()
    valid_imo_mask = ~display_df['IMO'].isin(['-', '', '(本次無資料)'])
    valid_df = display_df[valid_imo_mask]
    for (tanker, imo), group in valid_df.groupby(['油輪', 'IMO']):
        approved_rows = group[group['狀態'].str.contains('APPROVED', case=False, na=False)]
        completed_rows = group[group['狀態'].str.contains('COMPLETED', case=False, na=False)]
        if not approved_rows.empty and not completed_rows.empty:
            for a_idx, a_row in approved_rows.iterrows():
                for c_idx, c_row in completed_rows.iterrows():
                    a_time, c_time = a_row['日期'], c_row['日期']
                    if pd.notnull(a_time) and pd.notnull(c_time):
                        time_diff = c_time - a_time
                        if pd.Timedelta(0) < time_diff <= pd.Timedelta(days=7):
                            valid_dup_indices.add(a_idx)
                            valid_dup_indices.add(c_idx)
    return valid_dup_indices

@st.cache_data(ttl=60)
def build_tanker_excel(full_df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    export_df = full_df.drop(columns=["原始內文"], errors="ignore")
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        tankers = sorted([t for t in export_df["油輪"].unique() if t and t != "-"])
        used_names = set()
        for tanker in tankers:
            sheet_df = export_df[export_df["油輪"] == tanker].sort_values(by=["日期", "主旨"], ascending=[False, False])
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
        if not tankers: pd.DataFrame().to_excel(writer, sheet_name="無資料", index=False)
    return output.getvalue()

def apply_split_layout(marker_id: str, n_selected: int):
    js = f"""
    <script>
    (function() {{
        function findTargetBlock(doc, marker) {{
            const allBlocks = Array.from(doc.querySelectorAll('[data-testid="stHorizontalBlock"]'));
            for (const b of allBlocks) {{ if (marker.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) return b; }}
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
                h.dataset.dragging = '1'; h.firstChild.style.background = '#1a73e8'; doc.body.style.userSelect = 'none'; e.preventDefault();
                const onMove = (ev) => {{
                    const lRect = left.getBoundingClientRect(), rRect = right.getBoundingClientRect();
                    const combinedLeft = lRect.left, combinedWidth = rRect.right - lRect.left;
                    let newLeftWidth = ev.clientX - combinedLeft;
                    const minW = 80;
                    if (newLeftWidth < minW) newLeftWidth = minW;
                    if (newLeftWidth > combinedWidth - minW) newLeftWidth = combinedWidth - minW;
                    const pct = newLeftWidth / combinedWidth;
                    left.style.flex = pct + ' 1 0px'; right.style.flex = (1 - pct) + ' 1 0px';
                }};
                const onUp = () => {{
                    h.dataset.dragging = ''; h.firstChild.style.background = '#4a4a4a'; doc.body.style.userSelect = '';
                    doc.removeEventListener('mousemove', onMove); doc.removeEventListener('mouseup', onUp);
                }};
                doc.addEventListener('mousemove', onMove); doc.addEventListener('mouseup', onUp);
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
            hBlock.style.display = 'flex'; hBlock.style.alignItems = 'stretch';
            const [c0, c1, c2] = cols;
            [c0, c1, c2].forEach(c => {{ c.style.overflow = 'hidden'; c.style.minWidth = '0'; c.style.transition = 'none'; }});
            const handle1 = setupHandle(doc, hBlock, 'split-handle-1', c0, c1);
            const handle2 = setupHandle(doc, hBlock, 'split-handle-2', c1, c2);
            const n = {n_selected};
            if (n === 0) {{
                c0.style.flex = '1 1 100%'; c0.style.display = ''; c1.style.display = 'none'; c2.style.display = 'none';
                handle1.style.display = 'none'; handle2.style.display = 'none';
            }} else if (n === 1) {{
                c0.style.display = ''; c1.style.display = ''; c2.style.display = 'none';
                c0.style.flex = '1 1 0px'; c1.style.flex = '1 1 0px';
                handle1.style.display = 'flex'; handle2.style.display = 'none';
            }} else {{
                c0.style.display = ''; c1.style.display = ''; c2.style.display = '';
                c0.style.flex = '1 1 0px'; c1.style.flex = '1 1 0px'; c2.style.flex = '1 1 0px';
                handle1.style.display = 'flex'; handle2.style.display = 'flex';
            }}
        }}
        setTimeout(init, 60);
    }})();
    </script>
    """
    components.html(js, height=0, width=0)

# ==========================================
# 🚀 主程式邏輯與 UI 渲染
# ==========================================
st.markdown('<div class="compact-title">🚢 船隊實時調度報表</div>', unsafe_allow_html=True)

df, parse_errors = load_all_data()

if parse_errors:
    with st.sidebar.expander(f"⚠️ 解析失敗的信件 ({len(parse_errors)} 筆)"):
        for fpath, err in parse_errors:
            st.write(f"`{fpath}`")
            st.caption(err)

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

    if "selected_tanker" not in st.session_state: st.session_state["selected_tanker"] = "全部"

    c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1.2])
    
    with c1:
        tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        if st.session_state["selected_tanker"] not in tankers: st.session_state["selected_tanker"] = "全部"
        def _on_tanker_change(): st.session_state["selected_tanker"] = st.session_state.tanker_select_widget
        st.selectbox("🚢 篩選油輪", tankers, index=tankers.index(st.session_state["selected_tanker"]), key="tanker_select_widget", on_change=_on_tanker_change)
        
    with c2:
        dynamic_statuses = ["全部"] + sorted(list(df["狀態"].unique()))
        sel_status = st.selectbox("📂 篩選狀態", dynamic_statuses)
        
    with c3:
        valid_dates = df["日期"].dropna()
        m_date = valid_dates.min().date() if not valid_dates.empty else datetime.today().date()
        x_date = valid_dates.max().date() if not valid_dates.empty else datetime.today().date()
        sel_range = st.date_input("📅 日期範圍", value=(m_date, x_date))
        
    with c4:
        search_kw = st.text_input("🔍 關鍵字搜尋", placeholder="搜尋船名、IMO、主旨、內文...")

    # 資料過濾邏輯
    mask = pd.Series([True] * len(df))
    if st.session_state["selected_tanker"] != "全部": mask &= (df["油輪"] == st.session_state["selected_tanker"])
    if sel_status != "全部": mask &= (df["狀態"] == sel_status)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        start_dt, end_dt = pd.to_datetime(sel_range[0]), pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
        mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

    # 處理關鍵字搜尋
    search_keywords = []
    if search_kw:
        search_cols = ["油輪", "狀態", "船名", "IMO", "呼號", "主旨", "原始內文"]
        search_keywords = [k.strip() for k in search_kw.split() if k.strip()]
        missing_keywords = []
        combined_kw_mask = pd.Series([False] * len(df))
        
        for kw in search_keywords:
            kw_mask = df[search_cols].astype(str).apply(lambda col: col.str.contains(kw, case=False, na=False, regex=False)).any(axis=1)
            if not kw_mask.any(): missing_keywords.append(kw)
            else: combined_kw_mask |= kw_mask
                
        if missing_keywords: st.warning(f"⚠️ 提示：以下字串不在表格中： **{', '.join(missing_keywords)}**", icon="🚨")
        if combined_kw_mask.any(): mask &= combined_kw_mask
        elif missing_keywords: mask &= False

    display_df = df[mask].sort_values(by=["日期", "主旨"], ascending=[False, False]).reset_index(drop=True)

    with st.expander("🗺️ 船隊即時位置地圖", expanded=True):
        map_state = render_fleet_map(vessel_summary_df)
        clicked_vessel = None
        if map_state and map_state.get("last_object_clicked_tooltip"):
            clicked_html = map_state["last_object_clicked_tooltip"]
            clicked_vessel = re.sub(r'<[^>]*>', '', clicked_html).strip()
        if clicked_vessel and clicked_vessel != st.session_state.get("_last_clicked_vessel"):
            st.session_state["_last_clicked_vessel"] = clicked_vessel
            match_row = vessel_summary_df[vessel_summary_df["油輪"] == clicked_vessel]
            if not match_row.empty and match_row["matched"].iloc[0]: st.session_state["selected_tanker"] = match_row["matched_油輪"].iloc[0]
            else:
                st.session_state["selected_tanker"] = "全部"
                st.toast(f"⚠️ {clicked_vessel} 尚未配對到任何訂單郵件")
            st.rerun()

    # 表格選取與重置邏輯
    if "df_key_counter" not in st.session_state: st.session_state.df_key_counter = 0
    DF_KEY = f"email_table_{st.session_state.df_key_counter}"
    if "sel_seq" not in st.session_state: st.session_state.sel_seq = {}   
    if "sel_counter" not in st.session_state: st.session_state.sel_counter = 0

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
            if "APPROVED" in val_upper: return "background-color: rgba(250, 225, 50, 0.3);"
            elif "COMPLETED" in val_upper: return "background-color: rgba(255, 128, 128, 0.3);"
            elif "CANCELLED" in val_upper or "KYC" in val_upper: return "background-color: rgba(230, 120, 230, 0.3);"
            elif "PENDING" in val_upper: return "background-color: rgba(255, 243, 205, 0.3);"
            return ""

        valid_dup_indices = _compute_duplicate_pair_indices(display_df)
        def style_duplicate_imo(s): return ['background-color: rgba(253, 126, 20, 0.5);' if i in valid_dup_indices else '' for i in s.index]

        def style_search_match(val):
            if search_kw and search_keywords:
                val_str = str(val).lower()
                for kw in search_keywords:
                    if kw.lower() in val_str: return "background-color: #ffeb3b; color: #000000; font-weight: bold;"
            return ""
            
        styled_df = display_df[DISPLAY_COLUMNS].style.map(style_status, subset=["狀態"]).apply(style_duplicate_imo, subset=["IMO"])
        if search_kw: styled_df = styled_df.map(style_search_match)
        
        event = st.dataframe(
            styled_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row",
            key=DF_KEY, height=500, column_config={
                "日期": st.column_config.DatetimeColumn("收信時間", format="MM/DD HH:mm"), 
                "狀態": st.column_config.TextColumn("狀態", width="small"),
                "主旨": st.column_config.TextColumn("郵件主旨", width="medium")
            }
        )
        
        st.markdown("<br>", unsafe_allow_html=True)
        exp_c1, exp_c2, exp_c3 = st.columns([1, 1, 1])
        with exp_c1: st.download_button(f"📊 匯出目前篩選 ({len(display_df)} 筆)", display_df.to_csv(index=False).encode('utf-8-sig'), "ship_report.csv", "text/csv")
        with exp_c2: st.download_button(f"🗂️ 匯出全部資料", build_tanker_excel(df), "ship_report_by_tanker.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with exp_c3:
            if guess_has_selection:
                if st.button("❌ 關閉預覽 (清除選取)", use_container_width=True):
                    st.session_state.sel_seq = {}
                    st.session_state.df_key_counter += 1
                    st.rerun()

    raw_rows = event.get("selection", {}).get("rows", [])
    raw_set = set(raw_rows)
    for r in list(st.session_state.sel_seq.keys()):
        if r not in raw_set: del st.session_state.sel_seq[r]
    for r in raw_rows:
        if r not in st.session_state.sel_seq:
            st.session_state.sel_counter += 1
            st.session_state.sel_seq[r] = st.session_state.sel_counter

    all_checked = sorted(st.session_state.sel_seq.keys(), key=lambda r: st.session_state.sel_seq[r])
    preview_order = all_checked[-2:] if len(all_checked) > 2 else all_checked
    n_selected = len(preview_order)

    if len(all_checked) > 2:
        st.warning("⚠️ 目前勾選了多筆，僅預覽最後選取的 2 筆。若要讓表格勾選狀態也只剩 2 筆，請手動取消較舊的勾選。")

    if marker_id: apply_split_layout(marker_id, n_selected)

    def render_email_pane(container, row):
        time_str = row['日期'].strftime('%Y-%m-%d %H:%M') if pd.notnull(row['日期']) else '未知時間'
        with container:
            st.markdown(f'''
            <div class="email-pane">
                <div class="email-header">
                    <div class="email-subject">{row['主旨']}</div>
                    <div class="email-meta">🚢 <b>{row['油輪']}</b> &nbsp; | &nbsp; 📅 {time_str} &nbsp; | &nbsp; 📂 {row['狀態']}</div>
                </div>
                <div class="email-body">{row["原始內文"]}</div>
            </div>
            ''', unsafe_allow_html=True)

    for i, row_idx in enumerate(preview_order):
        if i < len(preview_cols) and row_idx < len(display_df):
            render_email_pane(preview_cols[i], display_df.iloc[row_idx])

    if (n_selected == 0) != (not guess_has_selection):
        st.rerun()
