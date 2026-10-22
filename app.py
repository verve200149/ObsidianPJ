import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os, yaml, json, re, io, html, hashlib
from datetime import datetime, timezone, timedelta

import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

# ==========================================
# 🛡️ 基本設定
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

# st.download_button 的 data 可傳 callable（點下載才執行）需要 Streamlit >= 1.46
try:
    _ST_VER = tuple(int(x) for x in re.findall(r'\d+', st.__version__)[:2])
except Exception:
    _ST_VER = (0, 0)
_ST_SUPPORTS_LAZY_DOWNLOAD = _ST_VER >= (1, 46)


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
    """
    狀態機邏輯 (依時間軸由舊到新重播)：
      APPROVED (含 Extend) -> PLAN
      COMPLETED            -> DONE
      CANCELLED / KYC      -> CANCEL
      status="close"       -> DONE
      status="clear"       -> DONE-C (僅作用在仍為 PLAN 的最後事件)
    """
    valid_df = imo_group_df.dropna(subset=["日期"]).sort_values("日期")
    if valid_df.empty: return None

    current_state = "PENDING"
    last_event = None

    for _, row in valid_df.iterrows():
        raw_status = str(row["狀態"]).upper()
        manual_status_row = str(row.get('手動狀態', 'pending')).strip().lower()

        if manual_status_row == 'close':
            current_state = "DONE"
        elif "APPROVED" in raw_status:
            current_state = "PLAN"
        elif "COMPLETED" in raw_status:
            current_state = "DONE"
        elif "CANCEL" in raw_status or "KYC" in raw_status:
            current_state = "CANCEL"

        last_event = row

    if last_event is None:
        return None

    if current_state == "PLAN":
        manual_status = str(last_event.get('手動狀態', 'pending')).strip().lower()
        if manual_status == 'clear':
            current_state = "DONE-C"

    is_overdue = False
    if current_state == "PLAN":
        app_time = last_event["日期"]
        if pd.notna(app_time):
            tz_info = app_time.tzinfo if hasattr(app_time, 'tzinfo') else None
            is_overdue = (pd.Timestamp.now(tz=tz_info) - app_time).days > 14

    return {
        "current_status": current_state,
        "last_date": last_event["日期"],
        "is_overdue": is_overdue,
        "vessel_name": last_event["船名"],
        "subject": last_event["主旨"]
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

def _df_signature(df: pd.DataFrame):
    """輕量簽章：取代對整個 DataFrame（含超長原始內文）做 hash。"""
    if df is None or df.empty: return (0,)
    return (
        len(df),
        str(df["日期"].max()),
        hash(tuple(df["狀態"].astype(str))),
        hash(tuple(df["手動狀態"].astype(str))),
    )

def _pos_signature(pos_df: pd.DataFrame):
    if pos_df is None or pos_df.empty: return (0,)
    return (
        len(pos_df),
        hash(tuple(zip(pos_df["油輪"], pos_df["last_signal"].astype(str), pos_df["lat"].astype(str), pos_df["lon"].astype(str)))),
    )

@st.cache_data(ttl=60, show_spinner=False)
def build_vessel_summary(_df: pd.DataFrame, _vessel_pos_df: pd.DataFrame, df_sig, pos_sig) -> pd.DataFrame:
    # 參數前綴 _ 代表 Streamlit 不 hash 它，改由 df_sig / pos_sig 判斷是否需要重算
    if _vessel_pos_df.empty: return _vessel_pos_df

    df = _df.copy()
    df["_key"] = df["油輪"].astype(str).str.strip().str.lower()
    grouped = dict(tuple(df.groupby("_key")))
    empty_df = df.iloc[0:0]

    summary_rows = []

    for _, v in _vessel_pos_df.iterrows():
        email_local = str(v.get("email_local", "")).strip().lower()
        if email_local:
            vdf = grouped.get(email_local, empty_df)
        else:
            vdf = df[df["油輪"] == v["油輪"]]

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
                if status_info:
                    imo_states[imo] = status_info

            for imo, info in imo_states.items():
                c_status = info["current_status"]
                is_overdue = info["is_overdue"]

                if c_status == "PLAN":
                    plan_count += 1
                    ready_count += 1
                    if is_overdue: overdue_count += 1
                elif c_status.startswith("DONE"):
                    done_count += 1

                # 未完成 (PLAN/OVERDUE) 一律列出；已結案只列近 5 天
                tz_info = info["last_date"].tzinfo if hasattr(info["last_date"], 'tzinfo') else None
                cutoff = pd.Timestamp.now(tz=tz_info) - pd.Timedelta(days=5)

                if c_status == "PLAN" or info["last_date"] >= cutoff:
                    display_status = "OVERDUE ⚠️" if is_overdue else c_status
                    recent_orders.append({
                        "狀態": display_status,
                        "日期": info["last_date"],
                        "船名": info["vessel_name"],
                        "IMO": imo
                    })

            def _status_priority(status_text):
                s = str(status_text).upper()
                if "OVERDUE" in s or "PLAN" in s: return 0
                if "DONE" in s: return 1
                return 2

            # 兩次穩定排序：先依日期新到舊，再依優先序分組
            recent_orders = sorted(recent_orders, key=lambda x: x["日期"], reverse=True)
            recent_orders = sorted(recent_orders, key=lambda x: _status_priority(x["狀態"]))

        row = v.to_dict()
        row.update({
            "matched": matched,
            "matched_油輪": vdf["油輪"].iloc[0] if matched else None,
            "ready_count": ready_count,
            "plan_count": plan_count,
            "done_count": done_count,
            "overdue_count": overdue_count,
            "completed_count": completed_count,
            "total_orders": len(vdf),
            "latest_subject": latest_subject,
            "latest_date": latest_date,
            "recent_orders": recent_orders,
        })
        summary_rows.append(row)

    return pd.DataFrame(summary_rows)

@st.cache_data(ttl=60, show_spinner=False)
def compute_process_status(_df: pd.DataFrame, df_sig) -> list:
    """為整個表格計算每一列的「處理」狀態（原本主程式的 iterrows 迴圈，現在有 cache）。"""
    final_statuses = []
    grouped_df = _df.groupby(['油輪', 'IMO'])
    now_cache = {}

    for idx, row in _df.iterrows():
        tanker = row.get("油輪")
        imo = row.get("IMO")
        raw_status = str(row.get('狀態', '-')).upper()
        manual_status = str(row.get('手動狀態', 'pending')).strip().lower()

        # 手動 close：最高優先權，直接結案
        if manual_status == 'close':
            final_statuses.append("DONE")
            continue

        # 無效 IMO
        if pd.isna(imo) or imo in ['-', '', '(本次無資料)']:
            if "COMPLETED" in raw_status: final_statuses.append("DONE")
            elif "CANCEL" in raw_status or "KYC" in raw_status: final_statuses.append("CANCEL")
            elif "APPROVED" in raw_status: final_statuses.append("PLAN")
            else: final_statuses.append(raw_status)
            continue

        if "COMPLETED" in raw_status:
            final_statuses.append("DONE")
            continue
        if "CANCEL" in raw_status or "KYC" in raw_status:
            final_statuses.append("CANCEL")
            continue

        # APPROVED：往未來找結案 / 取消 / 重新排程
        if "APPROVED" in raw_status or "PLAN" in raw_status:
            t = row['日期']
            if pd.isna(t):
                final_statuses.append("PLAN")
                continue

            try:
                imo_group = grouped_df.get_group((tanker, imo))
            except KeyError:
                imo_group = pd.DataFrame(columns=_df.columns)

            future_events = imo_group[imo_group['日期'] >= t]

            comp_ev = future_events[future_events['狀態'].str.contains("COMPLETED", case=False, na=False)]
            canc_ev = future_events[future_events['狀態'].str.contains("CANCEL", case=False, na=False)]
            reschedule_ev = future_events[
                (future_events['狀態'].str.contains("APPROVED", case=False, na=False))
                & (future_events['日期'] > t)
            ]

            first_comp = comp_ev['日期'].min() if not comp_ev.empty else pd.NaT
            first_canc = canc_ev['日期'].min() if not canc_ev.empty else pd.NaT
            first_reschedule = reschedule_ev['日期'].min() if not reschedule_ev.empty else pd.NaT

            cands = []
            if pd.notnull(first_comp): cands.append(("DONE", first_comp))
            if pd.notnull(first_canc): cands.append(("CANCEL", first_canc))
            if pd.notnull(first_reschedule): cands.append(("EXTEND", first_reschedule))

            if not cands:
                if manual_status == 'clear':
                    final_statuses.append("DONE-C")
                else:
                    tz_info = t.tzinfo if hasattr(t, 'tzinfo') else None
                    if tz_info not in now_cache:
                        now_cache[tz_info] = pd.Timestamp.now(tz=tz_info)
                    if (now_cache[tz_info] - t).days > 14:
                        final_statuses.append("OVERDUE")
                    else:
                        final_statuses.append("PLAN")
            else:
                final_statuses.append(min(cands, key=lambda x: x[1])[0])
            continue

        final_statuses.append(raw_status)

    return final_statuses

# ==========================================
# 🗺️ 地圖渲染相關
# ==========================================
# 沒有配對到任何訂單的船，icon 維持灰色（優先於航速色階）
_NO_ORDER_COLOR = "#9e9e9e"

def _icon_color_by_speed(matched, speed):
    if not matched:
        return _NO_ORDER_COLOR
    speed = speed or 0
    if speed < 2: return "#90CAF9"
    elif speed < 6: return "#42A5F5"
    elif speed < 10: return "#1E88E5"
    else: return "#0D47A1"

# 主要港口／島國參考點
MAJOR_PORTS = [
    {"name": "Kaohsiung", "lat": 22.61, "lon": 120.31},
    {"name": "Singapore", "lat": 1.26, "lon": 103.83},
    {"name": "Busan", "lat": 35.10, "lon": 129.04},
    {"name": "Yeosu", "lat": 34.74, "lon": 127.75},
    {"name": "Callao", "lat": -12.06, "lon": -77.15},
    {"name": "Valparaiso", "lat": -33.04, "lon": -71.62},
    {"name": "San Antonio", "lat": -33.58, "lon": -71.63},
    {"name": "Antofagasta", "lat": -23.65, "lon": -70.40},
    {"name": "Dili", "lat": -8.55, "lon": 125.57},
    {"name": "Christmas Is.", "lat": -10.42, "lon": 105.67},
    {"name": "Kiritimati", "lat": 1.87, "lon": -157.42},
    {"name": "Pohnpei", "lat": 6.92, "lon": 158.15},
    {"name": "Kosrae", "lat": 5.32, "lon": 162.98},
    {"name": "Tuvalu", "lat": -8.52, "lon": 179.19},
    {"name": "Nauru", "lat": -0.53, "lon": 166.91},
    {"name": "Marshall Is.", "lat": 7.09, "lon": 171.38},
    {"name": "Rabaul", "lat": -4.20, "lon": 152.18},
    {"name": "Papeete", "lat": -17.53, "lon": -149.57},
    {"name": "Tarawa", "lat": 1.53, "lon": 173.57},
]

def _add_major_ports(m):
    """輕量版：只留 CircleMarker + tooltip，不再為每個港口多建一個文字 DivIcon。"""
    for p in MAJOR_PORTS:
        lon = p["lon"] + 360 if p["lon"] < 0 else p["lon"]
        folium.CircleMarker(
            location=[p["lat"], lon], radius=3, color="#78909c", weight=1,
            fill=True, fill_color="#cfd8dc", fill_opacity=0.9, tooltip=p["name"],
        ).add_to(m)

def _ship_div_icon(color_hex, heading, size=34):
    """船形 icon：三角箭頭造型，會依航向旋轉。"""
    half = size / 2
    svg = (
        f'<div style="width:{size}px; height:{size}px; transform:rotate({heading}deg); '
        f'filter:drop-shadow(0 1px 1.5px rgba(0,0,0,0.4));">'
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}">'
        f'<path d="M12 1.5 L19 16 L12 12.5 L5 16 Z" fill="{color_hex}" stroke="#2d2d2d" stroke-width="1" stroke-linejoin="round"/>'
        f'</svg></div>'
    )
    return folium.DivIcon(html=svg, icon_size=(size, size), icon_anchor=(int(half), int(half)))

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
        status = str(o.get("狀態", "-")).upper()
        if "OVERDUE" in status: emoji, display = "⚠️", "OVERDUE"
        elif "DONE-C" in status: emoji, display = "🏁", "DONE-C"
        elif "PLAN" in status or "APPROVED" in status: emoji, display = "✅", "APPD"
        elif "DONE" in status or "COMPLETED" in status: emoji, display = "🏁", "CMP"
        elif "CANCEL" in status: emoji, display = "🚫", "CANCEL"
        else: emoji, display = "📋", status

        ship = o.get("船名", "-") or "-"
        imo = str(o.get("IMO", "")).strip()

        dt = o.get("日期", pd.NaT)
        dt_str = dt.strftime('%m/%d') if pd.notnull(dt) else ""
        dt_html = f"<span style='color:#888; font-size:11px;'>({dt_str})</span>" if dt_str else ""

        # 優先帶入 IMO，沒有或無效則用船名
        copy_target = imo if imo and imo not in ["-", "(本次無資料)", "nan"] else ship
        safe_copy_target = copy_target.replace("'", "\\'")

        # 點擊後把關鍵字丟進上方 Streamlit 搜尋框（找不到時退回複製到剪貼簿）
        js_script = (
            f"var val = '{safe_copy_target}'; "
            "var pDoc = window.parent.document; "
            "var inputs = pDoc.querySelectorAll('input'); "
            "var target = null; "
            "for(var i=0; i<inputs.length; i++){ if(inputs[i].placeholder && inputs[i].placeholder.includes('搜尋')){ target=inputs[i]; break; } } "
            "if(target) { "
                "var cur = target.value || ''; "
                "if(cur.indexOf(val) === -1) { "
                    "var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; "
                    "var space = (cur && !cur.endsWith(' ')) ? ' ' : ''; "
                    "setter.call(target, cur + space + val + ' '); "
                    "target.dispatchEvent(new Event('input', {bubbles: true})); "
                "} "
            "} else { navigator.clipboard.writeText(val + ' '); } "
            "var self = this; self.style.backgroundColor='#d2e3fc'; setTimeout(function(){self.style.backgroundColor='transparent';}, 400);"
        )

        return f'<div style="padding:4px 2px; border-bottom:1px solid #f0f0f0; font-size:12px; cursor:pointer; transition: background-color 0.2s; border-radius:3px;" onclick="{js_script}" title="點擊帶入 IMO / 船名至搜尋框" onmouseover="this.style.backgroundColor=\'#f1f3f4\'" onmouseout="this.style.backgroundColor=\'transparent\'">{emoji} <b>{display}</b> {dt_html} ・ {ship}</div>'

    items = [_item(o) for o in recent_orders]
    total = len(items)

    html_out = '<div style="margin-top:4px;">' + "".join(items[:3])

    if total > 3:
        rest_html = "".join(items[3:])
        safe_id = re.sub(r'\W+', '_', str(vessel_name))
        scroll_style = " max-height:220px; overflow-y:auto;" if total > 10 else ""
        html_out += f'<div id="extra_{safe_id}" style="display:none;{scroll_style}">{rest_html}</div><div id="btn_{safe_id}" style="cursor:pointer; color:#1a73e8; font-size:11px; margin-top:4px; text-align:center;" onclick="document.getElementById(\'extra_{safe_id}\').style.display=\'block\'; this.style.display=\'none\';">▼ 顯示全部訂單（共 {total} 筆，已結案僅列近5天）</div>'
    html_out += "</div>"
    return html_out

def _build_copy_text(v, plan_count, done_count, coord_str, last_signal_str):
    lines = [
        f"{v['油輪']}",
        f"位置\t{coord_str}",
        f"航向/航速\t{v['heading']:.0f}° / {v['speed']:.1f}kn",
        f"最後訊號\t{last_signal_str}",
        "近期訂單：",
        "狀態-船名\tIMO"
    ]

    recent_orders = v.get("recent_orders", []) or []
    for o in recent_orders:
        status = str(o.get("狀態", "-")).upper()

        if "OVERDUE" in status: display = "OVERDUE"
        elif "DONE-C" in status: display = "DONE-C"
        elif "PLAN" in status or "APPROVED" in status: display = "APPD"
        elif "DONE" in status or "COMPLETED" in status: display = "CMP"
        elif "CANCEL" in status: display = "CANCEL"
        else: display = status

        ship = o.get("船名", "-") or "-"
        dt = o.get("日期", pd.NaT)
        dt_str = dt.strftime('%m/%d') if pd.notnull(dt) else "-"
        imo = str(o.get("IMO", "")).strip()
        imo_val = imo if imo and imo not in ["-", "(本次無資料)", "nan", ""] else ""

        lines.append(f"{display} ({dt_str}) - {ship}\t{imo_val}")

    return "__NEWLINE__".join(lines)

def _add_vessel_marker(v, marker_cluster):
    """建立單一船隻 marker（tooltip + popup + icon）並加入 cluster。"""
    last_signal_str = v["last_signal"].strftime("%m/%d %H:%M") if pd.notnull(v["last_signal"]) else "-"
    match_line = "" if v.get("matched") else '<div style="color:#d32f2f; margin-top:4px;">⚠️ 尚未配對到訂單資料</div>'
    recent_orders_html = _build_recent_orders_html(v.get("recent_orders", []), v['油輪'])

    plan_count = v.get('plan_count', 0)
    done_count = v.get('done_count', 0)
    label_color = _tooltip_style(v)
    tooltip_html = f"<div style='color:{label_color}; font-size:8px; line-height:1.1;'><i class='fa fa-ship'></i> {v['油輪']}</div>"
    icon_hex = _icon_color_by_speed(v.get("matched"), v.get("speed", 0))
    coord_str = _format_coord(v["lat"], v["lon"])
    copy_text = _build_copy_text(v, plan_count, done_count, coord_str, last_signal_str)
    copy_text_attr = html.escape(copy_text, quote=True)

    # 用 String.fromCharCode(10) 產生真實換行，避開轉義衝突
    copy_btn_html = f'<button type="button" data-copytext="{copy_text_attr}" style="margin-top:6px; width:100%; padding:4px 0; font-size:11px; color:#1a73e8; background:#f1f6fe; border:1px solid #cfe0fb; border-radius:4px; cursor:pointer;" onclick="var t=this.getAttribute(\'data-copytext\').replace(/__NEWLINE__/g, String.fromCharCode(10)); var done=function(){{ this.textContent=\'✅ 已複製\'; var b=this; setTimeout(function(){{ b.textContent=\'📋 複製船舶資訊\'; }}, 1500); }}.bind(this); if(navigator.clipboard && navigator.clipboard.writeText){{ navigator.clipboard.writeText(t).then(done).catch(function(){{ var ta=document.createElement(\'textarea\'); ta.value=t; ta.style.position=\'fixed\'; ta.style.opacity=\'0\'; document.body.appendChild(ta); ta.focus(); ta.select(); try{{ document.execCommand(\'copy\'); }}catch(e){{}} document.body.removeChild(ta); }}); }}else{{ var ta=document.createElement(\'textarea\'); ta.value=t; ta.style.position=\'fixed\'; ta.style.opacity=\'0\'; document.body.appendChild(ta); ta.focus(); ta.select(); try{{ document.execCommand(\'copy\'); }}catch(e){{}} document.body.removeChild(ta); }} this.textContent=\'✅ 已複製\'; var b=this; setTimeout(function(){{ b.textContent=\'📋 複製船舶資訊\'; }}, 1500); ">📋 複製船舶資訊</button>'

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
    folium.Marker(
        location=[v["lat"], v["map_lon"]],
        tooltip=folium.Tooltip(tooltip_html, permanent=True, direction="right"),
        popup=folium.Popup(popup_html, max_width=280),
        icon=_ship_div_icon(icon_hex, v.get("heading", 0) or 0),
    ).add_to(marker_cluster)

def _map_signature(valid_df: pd.DataFrame) -> str:
    """只有影響地圖內容的欄位真的變了，簽章才會變 → 才會重建地圖。"""
    cols = ["油輪", "lat", "lon", "speed", "heading", "matched", "ready_count",
            "plan_count", "done_count", "status", "last_signal", "signal_hours"]
    raw = valid_df[cols].astype(str).to_csv() + str(valid_df["recent_orders"].tolist())
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

@st.cache_resource(show_spinner="🗺️ 建立地圖中…", max_entries=2)
def build_fleet_map(_summary_df: pd.DataFrame, sig: str):
    """地圖物件只在 sig 改變時重建；其他重跑直接拿快取的同一個物件。"""
    valid = _summary_df.dropna(subset=["lat", "lon"]).copy()
    valid["map_lon"] = valid["lon"].apply(lambda x: x + 360 if x < 0 else x)

    m = folium.Map(
        location=[valid["lat"].mean(), valid["map_lon"].mean()],
        zoom_start=3, tiles="CartoDB positron", prefer_canvas=True,
    )

    # 船名標籤縮小 CSS：注入地圖自己的 <head>（在 iframe 內才會生效）
    m.get_root().header.add_child(folium.Element("""
    <style>
    .leaflet-tooltip {
        background-color: rgba(255, 255, 255, 0.72) !important;
        border: 1px solid rgba(200, 200, 200, 0.35) !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.15) !important;
        font-size: 8px !important;
        font-weight: 600 !important;
        padding: 1px 4px !important;
        line-height: 1.2 !important;
    }
    .leaflet-tooltip-right::before, .leaflet-tooltip-left::before { display: none !important; }
    </style>
    """))

    _add_major_ports(m)

    cluster = MarkerCluster(options={"maxClusterRadius": 50, "disableClusteringAtZoom": 6}).add_to(m)
    for _, v in valid.iterrows():
        _add_vessel_marker(v, cluster)
    return m

def render_fleet_map(vessel_summary_df: pd.DataFrame):
    if vessel_summary_df is None or vessel_summary_df.empty or "lat" not in vessel_summary_df.columns:
        st.info("目前沒有可顯示座標的船舶資料。")
        return None
    valid = vessel_summary_df.dropna(subset=["lat", "lon"])
    if valid.empty:
        st.info("目前沒有可顯示座標的船舶資料。")
        return None

    m = build_fleet_map(vessel_summary_df, _map_signature(valid))
    return st_folium(
        m, height=460, use_container_width=True,
        key="fleet_map", returned_objects=["last_object_clicked_tooltip"],
    )

@st.fragment
def render_map_section(vessel_summary_df: pd.DataFrame):
    """
    地圖獨立成 fragment：
    - 拖曳/縮放地圖只重跑這個 fragment。
    - 只有真的點到新的船時，才呼叫不帶 scope 的 st.rerun()，讓篩選器 + 表格連動。
    """
    map_state = render_fleet_map(vessel_summary_df)
    clicked_vessel = None
    if map_state and map_state.get("last_object_clicked_tooltip"):
        clicked_html = map_state["last_object_clicked_tooltip"]
        clicked_vessel = re.sub(r'<[^>]*>', '', clicked_html).strip()

    if clicked_vessel and clicked_vessel != st.session_state.get("_last_clicked_vessel"):
        st.session_state["_last_clicked_vessel"] = clicked_vessel
        match_row = vessel_summary_df[vessel_summary_df["油輪"] == clicked_vessel]
        if not match_row.empty and match_row["matched"].iloc[0]:
            st.session_state["selected_tanker"] = match_row["matched_油輪"].iloc[0]
        else:
            st.session_state["selected_tanker"] = "全部"
            st.toast(f"⚠️ {clicked_vessel} 尚未配對到任何訂單郵件")
        st.rerun()

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
                        "手動狀態": str(fm.get('status', 'pending')).strip().lower(),
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

def _excel_download_data(df: pd.DataFrame):
    """新版 Streamlit 點下載才產生 Excel；舊版退回即時產生。"""
    if _ST_SUPPORTS_LAZY_DOWNLOAD:
        return lambda: build_tanker_excel(df)
    return build_tanker_excel(df)

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


@st.fragment
def render_table_section(display_df: pd.DataFrame, search_kw: str, search_keywords: list):
    """
    表格獨立成 fragment：勾選列、下載、關閉預覽等互動只重跑這裡，地圖不受影響。
    """
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
        DISPLAY_COLUMNS = ["油輪", "日期", "狀態", "處理", "船名", "IMO", "呼號", "ETA", "位置", "主旨"]

        def style_status(val):
            val_upper = str(val).upper().strip()

            if "OVERDUE" in val_upper: return "background-color: rgba(198, 40, 40, 0.5); color: rgba(255, 255, 255, 0.6); font-weight: bold;"
            elif "EXTEND" in val_upper: return "background-color: rgba(92, 107, 192, 0.5); color: rgba(255, 255, 255, 0.6); font-weight: bold;"
            elif "DONE-C" in val_upper: return "background-color: rgba(0, 137, 123, 0.5); color: rgba(255, 255, 255, 0.6); font-weight: bold;"
            elif "APPROVED" in val_upper or "PLAN" in val_upper: return "background-color: rgba(251, 140, 0, 0.8); color: #ffffff; font-weight: bold;"
            elif "COMPLETED" in val_upper or "DONE" in val_upper: return "background-color: rgba(229, 57, 53, 0.5); color: rgba(255, 255, 255, 0.6); font-weight: bold;"
            elif "CANCEL" in val_upper or "KYC" in val_upper: return "background-color: rgba(142, 36, 170, 0.5); color: rgba(255, 255, 255, 0.6); font-weight: bold;"
            elif "PENDING" in val_upper: return "background-color: rgba(117, 117, 117, 0.5); color: rgba(255, 255, 255, 0.6); font-weight: bold;"

            return ""

        # 只傳需要的欄位進 cache 函式，避免 hash 超長的「原始內文」
        valid_dup_indices = _compute_duplicate_pair_indices(display_df[["油輪", "IMO", "狀態", "日期"]])
        def style_duplicate_imo(s): return ['background-color: rgba(253, 126, 20, 0.5);' if i in valid_dup_indices else '' for i in s.index]

        def style_search_match(val):
            if search_kw and search_keywords:
                val_str = str(val).lower()
                for kw in search_keywords:
                    if kw.lower() in val_str: return "background-color: #ffeb3b; color: #000000; font-weight: bold;"
            return ""

        styled_df = display_df[DISPLAY_COLUMNS].style.map(style_status, subset=["處理"]).apply(style_duplicate_imo, subset=["IMO"])
        if search_kw: styled_df = styled_df.map(style_search_match)

        event = st.dataframe(
            styled_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row",
            key=DF_KEY, height=500, column_config={
                "日期": st.column_config.DatetimeColumn("收信時間", format="MM/DD HH:mm"),
                "狀態": st.column_config.TextColumn("單信狀態", width="small"),
                "處理": st.column_config.TextColumn("處理", width="small"),
                "主旨": st.column_config.TextColumn("郵件主旨", width="medium")
            }
        )

        st.markdown("<br>", unsafe_allow_html=True)
        exp_c1, exp_c2, exp_c3 = st.columns([1, 1, 1])
        with exp_c1: st.download_button(f"📊 匯出目前篩選 ({len(display_df)} 筆)", display_df.to_csv(index=False).encode('utf-8-sig'), "ship_report.csv", "text/csv")
        with exp_c2: st.download_button(f"🗂️ 匯出全部資料", _excel_download_data(display_df), "ship_report_by_tanker.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with exp_c3:
            if guess_has_selection:
                if st.button("❌ 關閉預覽 (清除選取)", use_container_width=True):
                    st.session_state.sel_seq = {}
                    st.session_state.df_key_counter += 1
                    st.rerun(scope="fragment")

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

    for i, row_idx in enumerate(preview_order):
        if i < len(preview_cols) and row_idx < len(display_df):
            render_email_pane(preview_cols[i], display_df.iloc[row_idx])

    # 讓 split layout 欄數即時跟上勾選狀態；只重跑表格 fragment，不波及地圖
    if (n_selected == 0) != (not guess_has_selection):
        st.rerun(scope="fragment")


# ==========================================
# 🚀 主程式邏輯與 UI 渲染
# ==========================================
st.markdown('<div class="compact-title">🚢 船隊實時調度報表</div>', unsafe_allow_html=True)

df, parse_errors = load_all_data()
df_sig = _df_signature(df)

# 為每一列計算「處理」狀態（有 cache，不會每次重跑都重算）
if not df.empty and "IMO" in df.columns:
    df["處理"] = compute_process_status(df, df_sig)
else:
    df["處理"] = "-"

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
    vessel_summary_df = build_vessel_summary(df, vessel_pos_df, df_sig, _pos_signature(vessel_pos_df))

    if "selected_tanker" not in st.session_state: st.session_state["selected_tanker"] = "全部"

    c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1.2])

    with c1:
        tankers = ["全部"] + sorted([x for x in df["油輪"].unique() if x])
        if st.session_state["selected_tanker"] not in tankers: st.session_state["selected_tanker"] = "全部"
        def _on_tanker_change():
            if "tanker_select_widget" in st.session_state:
                st.session_state["selected_tanker"] = st.session_state.tanker_select_widget
        st.selectbox(
            "🚢 篩選油輪",
            tankers,
            index=tankers.index(st.session_state["selected_tanker"]) if st.session_state["selected_tanker"] in tankers else 0,
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

    with c4:
        search_kw = st.text_input("🔍 關鍵字搜尋", placeholder="搜尋船名、IMO、主旨、內文...", key="main_search_input")

    mask = pd.Series([True] * len(df))
    if st.session_state["selected_tanker"] != "全部": mask &= (df["油輪"] == st.session_state["selected_tanker"])
    if sel_status != "全部": mask &= (df["狀態"] == sel_status)
    if isinstance(sel_range, tuple) and len(sel_range) == 2:
        start_dt, end_dt = pd.to_datetime(sel_range[0]), pd.to_datetime(sel_range[1]).replace(hour=23, minute=59, second=59)
        mask &= (df["日期"] >= start_dt) & (df["日期"] <= end_dt)

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
        render_map_section(vessel_summary_df)

    render_table_section(display_df, search_kw, search_keywords)
