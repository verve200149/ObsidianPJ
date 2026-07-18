# ==========================================================
# 🚢 船隊實時調度管理系統 - Streamlit Lite Version
# ==========================================================

import streamlit as st
import pandas as pd
import os
import json
import yaml
import re
import io

from datetime import datetime, timezone, timedelta


# ==========================================================
# Streamlit 設定
# ==========================================================

st.set_page_config(
    layout="wide",
    page_title="船隊調度管理系統",
    page_icon="🚢"
)


# ==========================================================
# 系統設定
# ==========================================================

TAIPEI_TZ = timezone(timedelta(hours=8))

SIGNAL_LIMIT_HOURS = 6


VMS_SPREADSHEET_ID = (
    "1wwFluz-H4-r7HRKya1AUZ"
    "_2KyZ6bVow_2v-TBQXj46c"
)

VMS_VESSELDATA_GID = "1420495034"


STATUS_COLOR = {
    "🔴 No Signal": "red",
    "🟡 Weak": "orange",
    "🟢 Normal": "green"
}



# ==========================================================
# 基本解析工具
# ==========================================================


def parse_custom_date(value):

    """
    VMS 日期格式：
    YYYYMMDD HH:mm
    """

    m = re.match(
        r"^(\d{4})(\d{2})(\d{2}) (\d{2}):(\d{2})$",
        str(value or "").strip()
    )

    if not m:
        return None

    try:
        y, mo, d, h, mi = map(int, m.groups())

        return datetime(
            y,
            mo,
            d,
            h,
            mi,
            tzinfo=TAIPEI_TZ
        )

    except Exception:
        return None



def parse_position(value):

    """
    Location:
    lat,long
    """

    try:
        lat, lon = str(value).split(",")[:2]

        return {
            "lat": float(lat),
            "lon": float(lon)
        }

    except Exception:
        return None



def parse_speed(value):

    """
    Speed/Direction:

    →8.5
    ↙13
    """

    arrow_map = {
        "→":90,
        "↗":45,
        "↑":0,
        "↖":315,
        "←":270,
        "↙":225,
        "↓":180,
        "↘":135
    }


    s = str(value or "").strip()

    arrow = s[:1]

    heading = arrow_map.get(
        arrow,
        0
    )


    num = re.sub(
        r"[^\d.]",
        "",
        s
    )


    speed = (
        float(num)
        if num
        else 0
    )


    return {
        "speed":speed,
        "heading":heading
    }




def find_column(columns, candidates):

    """
    自動找欄位名稱
    """

    cols = {
        str(c).lower():c
        for c in columns
    }


    for c in candidates:

        if c.lower() in cols:
            return cols[c.lower()]


    for name, original in cols.items():

        for c in candidates:

            if c.lower() in name:
                return original


    return None




# ==========================================================
# Kingdee 船舶資料
# ==========================================================


@st.cache_data(ttl=600)
def load_ship_map():

    filename = "Kingdee_Export_UTF8.json"


    if not os.path.exists(filename):
        return {}


    try:

        with open(
            filename,
            "r",
            encoding="utf-8-sig"
        ) as f:

            data=json.load(f)


        return {
            str(x.get("imo","")).strip():x
            for x in data
        }


    except Exception:

        return {}



ship_map = load_ship_map()




# ==========================================================
# Markdown Email 資料庫
# ==========================================================


def clean_mail_field(value):

    if not value:
        return ""

    value=str(value)

    value=re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        value
    )

    return value.strip()




def parse_ship_entries(target):

    if not target or target=="(本次無資料)":

        return [{
            "fv":"(本次無資料)",
            "imo":"-"
        }]


    result=[]


    for seg in str(target).split("|"):


        seg=seg.strip()

        if not seg:
            continue


        fv=re.search(
            r"FV:(.*?)丨",
            seg
        )


        if not fv:

            fv=re.search(
                r"FV:(.*)$",
                seg
            )


        imo=re.search(
            r"IMO:(\d+)",
            seg
        )


        result.append({

            "fv":
                fv.group(1).strip()
                if fv else "-",

            "imo":
                imo.group(1)
                if imo else "-"

        })


    return result




@st.cache_data(ttl=300)
def load_all_data():

    rows=[]

    errors=[]


    DATA_DIR="data_John"


    if not os.path.exists(DATA_DIR):

        return pd.DataFrame(),errors



    exclude={
        "checklist.md",
        "schedule操作介面.md"
    }


    for root,_,files in os.walk(DATA_DIR):

        if ".git" in root:
            continue


        for file in files:


            if (
                not file.endswith(".md")
                or file in exclude
            ):
                continue



            path=os.path.join(
                root,
                file
            )


            try:

                with open(
                    path,
                    "r",
                    encoding="utf-8"
                ) as f:

                    text=f.read()



                if not text.startswith("---"):
                    continue


                parts=text.split("---")


                if len(parts)<3:
                    continue



                fm=yaml.safe_load(parts[1])


                if not fm:
                    continue



                body="---".join(parts[2:]).strip()



                ships=parse_ship_entries(
                    fm.get("target","")
                )



                for ship in ships:


                    imo=ship["imo"]

                    info=ship_map.get(
                        imo,
                        {}
                    )


                    rows.append({

                        "油輪":
                            clean_mail_field(
                                fm.get("ships","")
                            ).split("@")[0] or "-",

                        "日期":
                            pd.to_datetime(
                                fm.get("date"),
                                errors="coerce"
                            ),

                        "位置":
                            fm.get(
                                "Position",
                                "-"
                            ),

                        "船名":
                            info.get(
                                "name",
                                ship["fv"]
                            ),

                        "狀態":
                            str(
                                fm.get(
                                    "category",
                                    "PENDING"
                                )
                            ).upper(),


                        "ETA":
                            fm.get(
                                "ETA",
                                "-"
                            ),


                        "IMO":
                            imo,


                        "呼號":
                            info.get(
                                "callSign",
                                "-"
                            ),


                        "主旨":
                            fm.get(
                                "subject",
                                "-"
                            ),


                        "原始內文":
                            body
                    })


            except Exception as e:

                errors.append(
                    (
                        path,
                        str(e)
                    )
                )


    return (
        pd.DataFrame(rows),
        errors
    )

# ==========================================================
# VMS 船位資料
# ==========================================================

@st.cache_data(ttl=300, show_spinner=False)
def load_vessel_positions():

    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{VMS_SPREADSHEET_ID}"
        f"/export?format=csv&gid={VMS_VESSELDATA_GID}"
    )


    try:

        raw = pd.read_csv(url)

    except Exception as e:

        st.error(
            f"無法讀取 VesselData: {e}"
        )

        return pd.DataFrame()



    col_name = find_column(
        raw.columns,
        [
            "vessel name",
            "vessel",
            "name"
        ]
    )


    col_signal = find_column(
        raw.columns,
        [
            "last signal",
            "signal"
        ]
    )


    col_location = find_column(
        raw.columns,
        [
            "location",
            "position"
        ]
    )


    col_speed = find_column(
        raw.columns,
        [
            "speed/direction",
            "speed"
        ]
    )


    col_valid = find_column(
        raw.columns,
        [
            "validity"
        ]
    )


    col_email = find_column(
        raw.columns,
        [
            "email",
            "mail"
        ]
    )


    col_remark = find_column(
        raw.columns,
        [
            "remark"
        ]
    )



    if not col_name or not col_signal:

        return pd.DataFrame()



    now = datetime.now(
        TAIPEI_TZ
    )


    result=[]



    for _,row in raw.iterrows():

        name=str(
            row[col_name]
        ).strip()


        if not name:
            continue



        last_signal=parse_custom_date(
            row[col_signal]
        )


        if not last_signal:
            continue



        pos=None


        if col_location:

            pos=parse_position(
                row[col_location]
            )



        speed={

            "speed":0,

            "heading":0

        }


        if col_speed:

            speed=parse_speed(
                row[col_speed]
            )



        validity="0/6"


        if col_valid:

            validity=str(
                row[col_valid]
            )



        valid_count=0


        if "/" in validity:

            try:

                valid_count=int(
                    validity.split("/")[0]
                )

            except:
                pass



        email=""


        if col_email:

            email=str(
                row[col_email]
            ).lower().strip()



        email_local = (

            email.split("@")[0]

            if "@"
            in email

            else email

        )



        hours=(

            now-last_signal

        ).total_seconds()/3600



        no_signal = (
            hours > SIGNAL_LIMIT_HOURS
        )


        weak = (

            not no_signal

            and valid_count <=2

        )



        if no_signal:

            status="🔴 No Signal"

        elif weak:

            status="🟡 Weak"

        else:

            status="🟢 Normal"



        result.append({

            "油輪":name,

            "email":email,

            "email_local":email_local,

            "lat":
                pos["lat"]
                if pos else None,

            "lon":
                pos["lon"]
                if pos else None,


            "speed":
                speed["speed"],


            "heading":
                speed["heading"],


            "last_signal":
                last_signal,


            "signal_hours":
                round(hours,1),


            "validity":
                validity,


            "remark":
                row[col_remark]
                if col_remark
                else "",


            "status":status

        })



    return pd.DataFrame(result)






# ==========================================================
# 船隊摘要
# ==========================================================

@st.cache_data(ttl=60)
def build_vessel_summary(
        df,
        vessel_pos_df
):


    if vessel_pos_df.empty:

        return vessel_pos_df



    # 建立索引，加速比對

    df["_key"] = (
        df["油輪"]
        .astype(str)
        .str.strip()
        .str.lower()
    )


    grouped=dict(
        tuple(
            df.groupby("_key")
        )
    )



    rows=[]



    for _,v in vessel_pos_df.iterrows():


        key=str(
            v.get(
                "email_local",
                ""
            )
        ).lower()



        vdf=grouped.get(
            key,
            pd.DataFrame()
        )



        matched=not vdf.empty



        completed=0


        if matched:

            completed=int(

                vdf["狀態"]
                .str.contains(
                    "COMPLETED",
                    case=False,
                    na=False
                )
                .sum()

            )



        latest_subject="-"

        latest_date=pd.NaT



        if matched:


            latest=vdf.sort_values(
                "日期",
                ascending=False
            ).head(1)



            if not latest.empty:

                latest_subject=latest["主旨"].iloc[0]

                latest_date=latest["日期"].iloc[0]



        ready=0


        if matched and "IMO" in vdf:


            ready_df=vdf[

                vdf["狀態"]
                .str.contains(
                    "APPROVED",
                    case=False,
                    na=False
                )

                &

                ~vdf["IMO"].isin(
                    [
                        "-",
                        "",
                        "(本次無資料)"
                    ]
                )

            ]



            ready=ready_df["IMO"].nunique()



        item=v.to_dict()


        item.update({

            "matched":matched,

            "matched_油輪":
                vdf["油輪"].iloc[0]
                if matched else None,


            "ready_count":
                int(ready),


            "completed_count":
                completed,


            "latest_subject":
                latest_subject,


            "latest_date":
                latest_date,


        })


        rows.append(item)



    return pd.DataFrame(rows)






# ==========================================================
# Folium 船隊地圖
# ==========================================================

def render_fleet_map(df):


    from streamlit_folium import st_folium

    import folium

    from folium.plugins import MarkerCluster



    map_df=df.dropna(
        subset=[
            "lat",
            "lon"
        ]
    ).copy()



    if map_df.empty:

        st.info(
            "目前沒有船位資料"
        )

        return None



    # 處理跨日期線

    map_df["map_lon"]=map_df["lon"].apply(

        lambda x:
        x+360
        if x < 0
        else x

    )



    center=[

        map_df["lat"].mean(),

        map_df["map_lon"].mean()

    ]



    m=folium.Map(

        location=center,

        zoom_start=3,

        tiles="CartoDB positron"

    )



    cluster=MarkerCluster(

        options={

            "maxClusterRadius":50,

            "disableClusteringAtZoom":6

        }

    ).add_to(m)




    for _,v in map_df.iterrows():


        color=STATUS_COLOR.get(

            v["status"],

            "blue"

        )



        popup=f"""

        <b>🚢 {v['油輪']}</b><br>

        狀態:
        {v['status']}<br>

        座標:
        {v['lat']:.4f},
        {v['lon']:.4f}<br>

        航向:
        {v['heading']}°<br>

        速度:
        {v['speed']} kn<br>

        最後訊號:
        {v['last_signal']}<br>

        準備加油:
        {v.get('ready_count',0)}<br>

        已完成:
        {v.get('completed_count',0)}

        """



        folium.Marker(

            location=[

                v["lat"],

                v["map_lon"]

            ],


            tooltip=v["油輪"],


            popup=folium.Popup(

                popup,

                max_width=300

            ),


            icon=folium.Icon(

                color=color,

                icon="ship",

                prefix="fa"

            )

        ).add_to(cluster)



    state=st_folium(

        m,

        height=450,

        use_container_width=True,

        returned_objects=[

            "last_object_clicked_tooltip"

        ]

    )


    return state

# ==========================================================
# 選取郵件預覽
# ==========================================================


if selected_rows:


    st.divider()


    st.subheader(
        "📧 郵件預覽"
    )


    # 最多預覽兩封

    preview_rows = selected_rows[-2:]


    preview_cols = st.columns(
        len(preview_rows)
    )



    for col, idx in zip(
        preview_cols,
        preview_rows
    ):


        if idx >= len(show):

            continue



        row = show.iloc[idx]



        with col:


            st.markdown(
                f"### {row['主旨']}"
            )


            st.caption(

                f"""
🚢 {row['油輪']}

📅 {row['日期']}

📂 {row['狀態']}

IMO:
{row['IMO']}
                """

            )



            st.text_area(

                "內容",

                row["原始內文"],

                height=350,

                key=f"mail_{idx}"

            )





# ==========================================================
# 匯出
# ==========================================================


st.divider()


e1,e2=st.columns(2)



with e1:


    csv_data=show.to_csv(

        index=False,

        encoding="utf-8-sig"

    )



    st.download_button(

        label=f"📄 匯出目前篩選 ({len(show)} 筆)",


        data=csv_data,


        file_name="ship_report.csv",


        mime="text/csv"

    )





with e2:


    excel_data=build_tanker_excel(df)



    st.download_button(

        label="📊 匯出全部船隊 Excel",


        data=excel_data,


        file_name="ship_report_by_tanker.xlsx",


        mime=
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    )
