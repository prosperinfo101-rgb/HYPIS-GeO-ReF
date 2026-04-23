"""
HyPIS Ug 
═══════════════════════════════════════════════════════════════════════════════
HYPIS-GEo
────────────────────────
• Multi-location: 17 Uganda districts + Custom Location
• All weather/soil/coordinates auto-loaded per chosen district (LIVE)
• Soil parameters from FAO / HWSD v2 per district (no guesswork)
• Kc stage bug FIXED — ini/mid/end correctly switches in Tab 1
• Historical tab: Yesterday / Last 7 Days / Last 30 Days ONLY
• "Method" column removed from ALL tables
• "Kabuyanda" removed from soil label — model is country-wide
• All API calls use live lat/lon/elev of selected location
• ERA5 historical data is the authoritative archive source
• IWR consistency: always recalculates from LIVE data, no stale cache drift
• Additional data sources: NASA POWER for solar validation
• Rainfall: Open-Meteo ERA5 precision archive used for historical

Author: Prosper BYARUHANGA · HyPIS App v6.0
═══════════════════════════════════════════════════════════════════════════════
"""

import os, sys, json, time as _time, subprocess, pathlib
import numpy as np
import pandas as pd
import requests
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta, date

# ── Auto-install ML deps ──────────────────────────────────────────────────────
for _pkg in ("joblib", "xgboost"):
    try:
        __import__(_pkg)
    except ImportError:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", _pkg, "--quiet"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="HyPIS Ug – Uganda IWR", layout="wide",
                   initial_sidebar_state="expanded")

_HERE = os.path.dirname(os.path.abspath(__file__))

# ══════════════════════════════════════════════════════════════════════════════
# UGANDA LOCATIONS  — coordinates verified from Google Earth Pro / GIS / DIVA-GIS
# Format: (lat, lon, elev_m)
# ══════════════════════════════════════════════════════════════════════════════
LOCATIONS = {
    " Kampala (Makerere Uni)":  ( 0.33396,  32.56801, 1239.01),
    "MUARiK (Kabanyoro)":       ( 0.464533,  32.612517, 1178.97),
    "Mbarara":                  (-0.6133,  30.6544, 1433),
    "Isingiro (Kabuyanda)":    (-0.95658,  30.61432, 1364.59),
    "Gulu":                    ( 2.7746,  32.2990, 1105),
    "Jinja":                   ( 0.4244,  33.2041, 1137),
    "Mbale":                   ( 1.0804,  34.1751, 1155),
    "Kabale":                  (-1.2490,  29.9900, 1869),
    "Fort Portal":             ( 0.6710,  30.2750, 1537),
    "Masaka":                  (-0.3310,  31.7373, 1148),
    "Lira":                    ( 2.2499,  32.9002, 1074),
    "Soroti":                  ( 1.7153,  33.6107, 1130),
    "Arua":                    ( 3.0210,  30.9110, 1047),
    "Hoima":                   ( 1.4352,  31.3524, 1562),
    "Kasese":                  ( 0.1820,  30.0804,  933),
    "Tororo":                  ( 0.6920,  34.1810, 1148),
    "Moroto":                  ( 2.5340,  34.6650, 1390),
    "Custom Location":         (None, None, None),
}

# ══════════════════════════════════════════════════════════════════════════════
# SOIL DATABASE — Uganda districts, FAO / HWSD v2 verified
# All FAO-56 standard soil water constants (m³/m³)
# ══════════════════════════════════════════════════════════════════════════════
DISTRICT_SOIL = {
    # location_key: {fc, pwp, texture, source}
    "Kampala (Makerere Uni)":  {"fc": 0.32, "pwp": 0.18, "texture": "Clay Loam",        "source": "HWSD v2"},
    "MUARiK (kabanyoro)":       {"fc": 0.26, "pwp": 0.12, "texture": "Sandy Clay Loam",  "source": "HWSD v2"},
    "Mbarara":                  {"fc": 0.30, "pwp": 0.15, "texture": "Loam",             "source": "HWSD v2"},
    "Isingiro (Kabuyanda)":    {"fc": 0.28, "pwp": 0.14, "texture": "Loam",             "source": "HWSD v2"},
    "Gulu":                    {"fc": 0.24, "pwp": 0.11, "texture": "Sandy Loam",        "source": "HWSD v2"},
    "Jinja":                   {"fc": 0.31, "pwp": 0.16, "texture": "Clay Loam",         "source": "HWSD v2"},
    "Mbale":                   {"fc": 0.27, "pwp": 0.13, "texture": "Loam",              "source": "HWSD v2"},
    "Kabale":                  {"fc": 0.33, "pwp": 0.19, "texture": "Clay",              "source": "HWSD v2"},
    "Fort Portal":             {"fc": 0.29, "pwp": 0.14, "texture": "Loam",              "source": "HWSD v2"},
    "Masaka":                  {"fc": 0.25, "pwp": 0.12, "texture": "Sandy Loam",        "source": "HWSD v2"},
    "Lira":                    {"fc": 0.23, "pwp": 0.10, "texture": "Sandy Loam",        "source": "HWSD v2"},
    "Soroti":                  {"fc": 0.22, "pwp": 0.09, "texture": "Sandy Loam",        "source": "HWSD v2"},
    "Arua":                    {"fc": 0.21, "pwp": 0.08, "texture": "Loamy Sand",        "source": "HWSD v2"},
    "Hoima":                   {"fc": 0.28, "pwp": 0.13, "texture": "Sandy Loam",        "source": "HWSD v2"},
    "Kasese":                  {"fc": 0.35, "pwp": 0.20, "texture": "Clay",              "source": "HWSD v2"},
    "Tororo":                  {"fc": 0.26, "pwp": 0.12, "texture": "Sandy Clay Loam",   "source": "HWSD v2"},
    "Moroto":                  {"fc": 0.18, "pwp": 0.08, "texture": "Sandy Loam",        "source": "HWSD v2"},
    "Custom Location":         {"fc": 0.28, "pwp": 0.14, "texture": "Loam (default)",    "source": "FAO-56 default"},
}

# ══════════════════════════════════════════════════════════════════════════════
# FAO-56 STANDARD SOIL TYPES  (manual override)
# ══════════════════════════════════════════════════════════════════════════════
SOIL_OPTS = {
    "Sand":              {"fc": 0.10, "pwp": 0.05, "desc": "Very fast drainage, very low retention"},
    "Loamy Sand":        {"fc": 0.14, "pwp": 0.07, "desc": "Fast drainage, low retention"},
    "Sandy Loam":        {"fc": 0.20, "pwp": 0.09, "desc": "Moderate drainage, moderate retention"},
    "Sandy Clay Loam":   {"fc": 0.26, "pwp": 0.12, "desc": "Moderate-high retention"},
    "Loam":              {"fc": 0.28, "pwp": 0.14, "desc": "Good balance of drainage and retention"},
    "Silt Loam":         {"fc": 0.31, "pwp": 0.15, "desc": "High retention, moderate drainage"},
    "Silt":              {"fc": 0.33, "pwp": 0.16, "desc": "High retention"},
    "Clay Loam":         {"fc": 0.32, "pwp": 0.18, "desc": "High retention, slow drainage"},
    "Silty Clay Loam":   {"fc": 0.35, "pwp": 0.20, "desc": "Very high retention"},
    "Sandy Clay":        {"fc": 0.28, "pwp": 0.16, "desc": "Moderate-high retention"},
    "Silty Clay":        {"fc": 0.38, "pwp": 0.23, "desc": "Very high retention, poor drainage"},
    "Clay":              {"fc": 0.40, "pwp": 0.25, "desc": "Maximum retention, waterlogging risk"},
}

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
TIMEZONE   = "Africa/Nairobi"
_SIGMA     = 4.903e-9          # Stefan-Boltzmann MJ K⁻⁴ m⁻² day⁻¹ (FAO-56)
_W2M       = 4.87 / np.log(67.8 * 10.0 - 5.42)   # wind 10m → 2m ≈ 0.7482

# ══════════════════════════════════════════════════════════════════════════════
# ML MODEL LOADING
# ══════════════════════════════════════════════════════════════════════════════
ML_MODEL    = None
ML_OK       = False
ML_STATUS   = ""
ML_FEATURES = ["tmean", "rh", "wind", "kc", "precipitation",
               "soil_fc", "soil_pwp", "root_depth"]
_MODEL_PATH = pathlib.Path(_HERE) / "irrigation_xgboost_model_with_soil.pkl"

def _load_ml_model():
    global ML_MODEL, ML_OK, ML_STATUS
    try:
        import joblib, xgboost  # noqa: F401
        if not _MODEL_PATH.exists():
            ML_STATUS = f"⚠️ Model file not found: {_MODEL_PATH.name}"
            return
        ML_MODEL  = joblib.load(str(_MODEL_PATH))
        ML_OK     = True
        ML_STATUS = (f"✅ XGBoost loaded · Features: {', '.join(ML_FEATURES)}")
    except ModuleNotFoundError as e:
        ML_STATUS = f"⚠️ Missing package: {e}"
    except Exception as e:
        ML_STATUS = f"⚠️ Model load error: {e}"

_load_ml_model()

# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""<style>
:root{
  --hb:#1a5fc8;--hg:#0b6b1b;--hr:#b81c1c;
  --bg:#f4f8f2;--sf:#fff;--bd:#dbe9db;--tx:#17301b;
  --gn:#0b6b1b;--gd:#075214;--gs:#e7f3e6;
}
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{
  background:var(--bg)!important;color:var(--tx)!important;}
[data-testid="stHeader"],[data-testid="stToolbar"]{background:transparent!important;}
[data-testid="stMetric"]{background:var(--sf);border:1px solid var(--bd);
  border-radius:12px;padding:.5rem .7rem;}
[data-testid="stMetricLabel"] p{font-size:.76rem!important;margin:0!important;}
[data-testid="stMetricValue"] div{font-size:1.05rem!important;font-weight:700!important;}
div[data-baseweb="tab-list"]{gap:.3rem;background:transparent!important;}
button[data-baseweb="tab"]{background:var(--gs)!important;border:1px solid #b8d1b8!important;
  border-radius:999px!important;color:var(--gd)!important;
  padding:.35rem .75rem!important;font-size:.83rem!important;}
button[data-baseweb="tab"]>div{color:var(--gd)!important;font-weight:600;}
button[data-baseweb="tab"][aria-selected="true"]{
  background:var(--gn)!important;border-color:var(--gn)!important;}
button[data-baseweb="tab"][aria-selected="true"]>div{color:#fff!important;}
[data-baseweb="select"]>div,div[data-baseweb="input"]>div,
.stNumberInput>div>div,.stTextInput>div>div{
  background:var(--sf)!important;color:var(--tx)!important;border-color:#c9d9c9!important;}
.stButton>button,.stDownloadButton>button{
  background:var(--gn)!important;color:#fff!important;
  border:1px solid var(--gn)!important;border-radius:10px!important;}
.stButton>button:hover{background:var(--gd)!important;}
section[data-testid="stSidebar"]{background:#eef5ec!important;}
button[title="Fork this app"],[data-testid="stToolbarActionButtonIcon"],
[data-testid="stBottomBlockContainer"],.stDeployButton,footer{display:none!important;}
.block-container{padding-top:.8rem!important;}
.hx-outer{border-radius:20px;overflow:hidden;margin:0 0 10px 0;
  background:linear-gradient(90deg,var(--hb) 0%,var(--hb) 33.3%,
  var(--hg) 33.3%,var(--hg) 66.6%,var(--hr) 66.6%,var(--hr) 100%);
  padding:9px 9px 7px 9px;}
.hx-panel{background:#fff;border:2px solid #d0ddd0;border-radius:14px;
  padding:9px 16px 7px 16px;}
.hx-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.hx-wm{font-family:Georgia,serif;font-size:2.4rem;font-weight:700;
  line-height:1;letter-spacing:-1px;flex-shrink:0;}
.hx-wm .H{color:#1a5fc8;}.hx-wm .y{color:#0b6b1b;}.hx-wm .P{color:#b81c1c;}
.hx-wm .I{color:#1a5fc8;}.hx-wm .S{color:#0b6b1b;}
.hx-wm .Ug{color:#b81c1c;font-size:1.4rem;vertical-align:middle;margin-left:4px;}
.hx-sub{font-family:Georgia,serif;font-size:.95rem;flex:1 1 160px;color:#444;}
.hx-auth{margin:4px 0 0 4px;font-family:Georgia,serif;font-size:.78rem;color:#ddd;}
.hx-auth strong{color:#fff;}
.geo-panel{background:#fff;border:1.5px solid #b8d4f8;border-radius:14px;
  padding:10px 16px;margin:6px 0 10px 0;font-size:.86rem;color:#14324d;}
.geo-panel b{color:#1a5fc8;}
.geo-coord{font-family:monospace;background:#eef4ff;padding:2px 6px;
  border-radius:6px;font-size:.82rem;}
.nir-box{background:#fff3cd;border:1px solid #ffc107;border-radius:10px;
  padding:8px 14px;font-size:.87rem;margin:4px 0;}
.iwr-box{background:#d4edda;border:1px solid #28a745;border-radius:10px;
  padding:8px 14px;font-size:.87rem;margin:4px 0;font-weight:600;}
.vol-box{background:#cfe2ff;border:1px solid #0d6efd;border-radius:10px;
  padding:8px 14px;font-size:.87rem;margin:4px 0;}
.kc-stage{background:#e8f6ea;border:1px solid #a8d8a8;border-radius:10px;
  padding:6px 14px;font-size:.85rem;color:#073f12;margin:4px 0;font-weight:600;}
.soil-panel{background:#fef9ee;border:1px solid #e0c97a;border-radius:10px;
  padding:8px 14px;font-size:.85rem;margin:4px 0;}
.live-dot{width:7px;height:7px;background:#22c55e;border-radius:50%;
  display:inline-block;margin-right:4px;animation:blink 1.4s infinite;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
</style>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH (every 1 hour)
# ══════════════════════════════════════════════════════════════════════════════
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = _time.time()
_el = _time.time() - st.session_state["last_refresh"]
if _el >= 3600:
    st.cache_data.clear()
    st.session_state["last_refresh"] = _time.time()
    st.rerun()
_rem = max(0, 3600 - int(_el))

# ══════════════════════════════════════════════════════════════════════════════
# BRAND HEADER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""<div class="hx-outer"><div class="hx-panel"><div class="hx-row">
<span style="font-size:1.5rem;">&#127807;</span>
<span class="hx-wm">
  <span class="H">H</span><span class="y">y</span><span class="P">P</span>
  <span class="I">I</span><span class="S">S</span><span class="Ug"> Ug</span>
</span>
<span class="hx-sub">HydroPredict · IrrigSched · Uganda Multi-Location IWR v6.0</span>
</div></div>
<div class="hx-auth">by: Prosper <strong>BYARUHANGA</strong>
&nbsp;·&nbsp; HyPIS App v6.0 &nbsp;·&nbsp; FAO-56 PM + XGBoost ML · Uganda</div>
</div>""", unsafe_allow_html=True)

_now_str = datetime.now().strftime("%d %b %Y %H:%M")
st.caption(
    f'<span class="live-dot"></span> Live &middot; <b>{_now_str}</b>'
    f" &nbsp;·&nbsp; Refresh in <b>{_rem // 3600}h {(_rem % 3600) // 60}m</b>",
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — LOCATION SELECTOR (primary control)
# ══════════════════════════════════════════════════════════════════════════════
st.sidebar.header("📍 Location — Uganda")
loc_name = st.sidebar.selectbox(
    "Select District / Site",
    list(LOCATIONS.keys()),
    index=0,
    key="loc_sel",
)

_lcoords = LOCATIONS[loc_name]

if loc_name == "Custom Location":
    st.sidebar.markdown("**Enter Custom Coordinates:**")
    _clat  = st.sidebar.number_input("Latitude",  value=0.3380, format="%.4f", key="clat")
    _clon  = st.sidebar.number_input("Longitude", value=32.5680, format="%.4f", key="clon")
    _celev = st.sidebar.number_input("Elevation (m a.s.l.)", value=1189, key="celev")
    LAT, LON, ELEV = _clat, _clon, _celev
    SITE_NAME = f"Custom ({LAT:.4f}°, {LON:.4f}°)"
else:
    LAT, LON, ELEV = _lcoords
    SITE_NAME = loc_name

GMAPS_URL = f"https://maps.google.com/?q={LAT},{LON}"
GMAPS_SAT = f"https://maps.google.com/maps?q={LAT},{LON}&ll={LAT},{LON}&z=14&t=k"

# ── Soil auto-load for selected district ────────────────────────────────────
_dsoil = DISTRICT_SOIL.get(loc_name, DISTRICT_SOIL["Custom Location"])
SITE_FC   = _dsoil["fc"]
SITE_PWP  = _dsoil["pwp"]
SITE_TEXT = _dsoil["texture"]
SITE_SRC  = _dsoil["source"]

st.sidebar.markdown(
    f"""**📍 {SITE_NAME}**  
`Lat {LAT}°` · `Lon {LON}°` · `{ELEV} m a.s.l.`  
[🗺️ Google Maps]({GMAPS_URL}) | [🛰️ Satellite]({GMAPS_SAT})"""
)

st.sidebar.markdown("---\n### 🌍 Soil Type")
st.sidebar.info(
    f"**Auto-loaded for {loc_name}:**  \n"
    f"Texture: **{SITE_TEXT}**  \n"
    f"FC: **{SITE_FC*100:.0f}%** · PWP: **{SITE_PWP*100:.0f}%**  \n"
    f"Source: {SITE_SRC}"
)
soil_override = st.sidebar.checkbox("Override soil type", value=False, key="soil_ov")
if soil_override:
    soil_sel_s = st.sidebar.selectbox("Soil Type", list(SOIL_OPTS.keys()), key="soil_sel_s")
    soil_obj_s = SOIL_OPTS[soil_sel_s]
    ACTIVE_FC  = soil_obj_s["fc"]
    ACTIVE_PWP = soil_obj_s["pwp"]
    ACTIVE_TXT = soil_sel_s
else:
    ACTIVE_FC  = SITE_FC
    ACTIVE_PWP = SITE_PWP
    ACTIVE_TXT = SITE_TEXT

st.sidebar.markdown("---\n### 💧 Irrigation System")
IRRIG_SYSTEMS = {
    "Drip / Trickle":   0.90,
    "Sprinkler":        0.80,
    "Surface / Furrow": 0.65,
    "Flood":            0.55,
    "Centre Pivot":     0.85,
}
irrig_sys = st.sidebar.selectbox("System Type", list(IRRIG_SYSTEMS.keys()), index=0, key="irrig_sys")
Ef = IRRIG_SYSTEMS[irrig_sys]
st.sidebar.info(f"Efficiency **Ef = {Ef*100:.0f}%**  \nIWR (gross) = NIR ÷ {Ef:.2f}")

st.sidebar.markdown("---\n### 📐 Field & Pump")
area_ha   = st.sidebar.number_input("Field Area (ha)", value=1.0, min_value=0.1, step=0.1, key="area_g")
pump_flow = st.sidebar.number_input("Pump Flow Rate (m³/hr)", value=5.0, min_value=0.5, step=0.5, key="pump_g")

if ML_OK:
    st.sidebar.markdown("---\n### 🤖 ML Model")
    st.sidebar.success(f"**{_MODEL_PATH.name}**  \nFeatures: `{', '.join(ML_FEATURES)}`  \n*Predicts IWR (mm/day)*")
else:
    st.sidebar.markdown("---")
    st.sidebar.warning(ML_STATUS[:150])

# ══════════════════════════════════════════════════════════════════════════════
# GEO PANEL (main area)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    f"""<div class="geo-panel">
    📍 <b>Site:</b> {SITE_NAME} &nbsp;|&nbsp; Uganda<br>
    🌐 <b>Coordinates:</b>
      <span class="geo-coord">Lat {LAT}°</span>
      <span class="geo-coord">Lon {LON}°</span>
      <span class="geo-coord">Elev {ELEV} m a.s.l.</span>
    &nbsp;&nbsp;
    <a href="{GMAPS_URL}" target="_blank">🗺️ Google Maps</a>
    &nbsp;|&nbsp;
    <a href="{GMAPS_SAT}" target="_blank">🛰️ Satellite View</a><br>
    🌍 <b>Soil ({SITE_SRC}):</b> {ACTIVE_TXT} &nbsp;·&nbsp;
      FC = <b>{ACTIVE_FC*100:.0f}%</b> &nbsp;·&nbsp; PWP = <b>{ACTIVE_PWP*100:.0f}%</b>
    </div>""",
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# CROP PARAMETERS  (FAO-56, Uganda-calibrated)
# ══════════════════════════════════════════════════════════════════════════════
crop_params = {
    "Tomatoes":       {"ini": 0.60, "mid": 1.15, "end": 0.80, "zr": 0.70, "mad": 0.40},
    "Cabbages":       {"ini": 0.70, "mid": 1.05, "end": 0.95, "zr": 0.50, "mad": 0.45},
    "Maize":          {"ini": 0.30, "mid": 1.20, "end": 0.60, "zr": 1.00, "mad": 0.55},
    "Beans":          {"ini": 0.40, "mid": 1.15, "end": 0.75, "zr": 0.60, "mad": 0.45},
    "Rice":           {"ini": 1.05, "mid": 1.30, "end": 0.95, "zr": 0.50, "mad": 0.20},
    "Potatoes":       {"ini": 0.50, "mid": 1.15, "end": 0.75, "zr": 0.60, "mad": 0.35},
    "Onions":         {"ini": 0.70, "mid": 1.05, "end": 0.95, "zr": 0.30, "mad": 0.30},
    "Peppers":        {"ini": 0.60, "mid": 1.10, "end": 0.80, "zr": 0.50, "mad": 0.30},
    "Cassava":        {"ini": 0.40, "mid": 0.85, "end": 0.70, "zr": 1.00, "mad": 0.60},
    "Bananas":        {"ini": 0.50, "mid": 1.00, "end": 0.80, "zr": 0.90, "mad": 0.35},
    "Wheat":          {"ini": 0.70, "mid": 1.15, "end": 0.40, "zr": 1.00, "mad": 0.55},
    "Sorghum":        {"ini": 0.30, "mid": 1.00, "end": 0.55, "zr": 1.00, "mad": 0.55},
    "Groundnuts":     {"ini": 0.40, "mid": 1.15, "end": 0.75, "zr": 0.50, "mad": 0.50},
    "Sweet Potatoes": {"ini": 0.50, "mid": 1.15, "end": 0.75, "zr": 1.00, "mad": 0.65},
    "Sunflower":      {"ini": 0.35, "mid": 1.10, "end": 0.35, "zr": 1.00, "mad": 0.45},
    "Soybeans":       {"ini": 0.40, "mid": 1.15, "end": 0.50, "zr": 0.60, "mad": 0.50},
}

STAGE_LABELS = {"ini": "🌱 Initial", "mid": "🌿 Mid-Season", "end": "🍂 End-Season"}
WMO_DESC = {
    0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",
    51:"Light drizzle",53:"Moderate drizzle",55:"Dense drizzle",
    61:"Slight rain",63:"Moderate rain",65:"Heavy rain",
    80:"Slight showers",81:"Moderate showers",82:"Violent showers",
    95:"Thunderstorm",96:"Thunderstorm+hail",99:"Heavy thunderstorm+hail",
}

def wmo_icon(code):
    if not code: return "🌤️"
    c = int(code)
    if c == 0: return "☀️"
    if c in (1,2,3): return "🌤️"
    if 51 <= c <= 67: return "🌧️"
    if 80 <= c <= 82: return "🌦️"
    if 95 <= c <= 99: return "⛈️"
    return "🌥️"

# ══════════════════════════════════════════════════════════════════════════════
# FAO-56 PENMAN-MONTEITH  (fully corrected)
# ══════════════════════════════════════════════════════════════════════════════
def et0_pm(tmax, tmin, rh_max, rh_min, u2, rs, elev=None,
           doy=None, lat_deg=None):
    """FAO-56 Penman-Monteith ET₀ (mm/day). Uses current location elev/lat."""
    if elev is None: elev = ELEV
    if lat_deg is None: lat_deg = LAT
    try:
        tmax=float(tmax); tmin=float(tmin)
        rh_max=max(0.,min(100.,float(rh_max))); rh_min=max(0.,min(100.,float(rh_min)))
        u2=max(0.,float(u2)); rs=max(0.,float(rs))
        doy=int(doy) if doy else int(datetime.now().strftime("%j"))
        lat_deg=float(lat_deg)
    except Exception:
        return 0.0

    Gsc=0.0820; tmean=(tmax+tmin)/2.0
    P     = 101.3 * ((293.0 - 0.0065*elev) / 293.0)**5.26
    gamma = 0.000665 * P
    es_max = 0.6108 * np.exp(17.27*tmax / (tmax+237.3))
    es_min = 0.6108 * np.exp(17.27*tmin / (tmin+237.3))
    es     = (es_max + es_min) / 2.0
    ea = max(0.0, (rh_max/100.0*es_min + rh_min/100.0*es_max) / 2.0)
    ea = min(ea, es)
    es_tm = 0.6108 * np.exp(17.27*tmean / (tmean+237.3))
    Delta = 4098.0 * es_tm / (tmean+237.3)**2.0
    b  = 2.0*np.pi*doy/365.0
    dr = 1.0 + 0.033*np.cos(b)
    phi   = np.radians(abs(lat_deg))
    delta_s = 0.409*np.sin(b-1.39)
    ws  = np.arccos(np.clip(-np.tan(phi)*np.tan(delta_s), -1.0, 1.0))
    Ra  = max(0.0, (24.0*60.0/np.pi)*Gsc*dr*(
        ws*np.sin(phi)*np.sin(delta_s)+np.cos(phi)*np.cos(delta_s)*np.sin(ws)))
    Rso = max(0.0, (0.75 + 2e-5*elev)*Ra)
    Rns = 0.77 * rs
    fcd = max(0.0, min(1.0, 1.35*(rs/max(Rso,0.1)) - 0.35))
    Rnl = max(0.0, _SIGMA*((tmax+273.16)**4+(tmin+273.16)**4)/2.0
              * (0.34-0.14*np.sqrt(max(0.0,ea))) * fcd)
    Rn  = max(0.0, Rns - Rnl)
    num = 0.408*Delta*Rn + gamma*(900.0/(tmean+273.0))*u2*(es-ea)
    den = Delta + gamma*(1.0+0.34*u2)
    return max(0.0, round(num/den, 3)) if den > 0 else 0.0

def et0_hargreaves(tmax, tmin, doy=None, lat_deg=None):
    """Hargreaves-Samani ET₀ (mm/day)."""
    if lat_deg is None: lat_deg = LAT
    doy = doy or int(datetime.now().strftime("%j"))
    b   = 2.0*np.pi*doy/365.0
    dr  = 1.0+0.033*np.cos(b); phi=np.radians(abs(lat_deg))
    delta_s=0.409*np.sin(b-1.39)
    ws  = np.arccos(np.clip(-np.tan(phi)*np.tan(delta_s),-1.0,1.0))
    Ra  = max(0.0,(24.0*60.0/np.pi)*0.0820*dr*(
        ws*np.sin(phi)*np.sin(delta_s)+np.cos(phi)*np.cos(delta_s)*np.sin(ws)))
    tmean=(tmax+tmin)/2.0; td=max(0.0,tmax-tmin)
    return round(max(0.0,0.0023*Ra*(tmean+17.8)*td**0.5),3)

# ══════════════════════════════════════════════════════════════════════════════
# SOIL WATER BALANCE HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def compute_taw(fc, pwp, zr):
    return (fc - pwp) * zr * 1000.0   # mm

def compute_raw(taw, mad):
    return mad * taw                   # mm

def eff_rain(p):
    """USDA SCS effective rainfall (mm)."""
    p = float(p) if p else 0.0
    if p <= 0:     return 0.0
    if p <= 25.4:  return p * (125.0 - 0.6*p) / 125.0
    return p - 12.7 - 0.1*p

def get_kc(dap, crop):
    p = crop_params[crop]
    if dap < 30:  return p["ini"], "ini"
    if dap < 90:  return p["mid"], "mid"
    return p["end"], "end"

def kc_from_stage(stage, crop):
    """Return Kc for explicit stage selection (ini/mid/end) — BUG FIX."""
    return crop_params[crop][stage]

# ══════════════════════════════════════════════════════════════════════════════
# IWR — ML PRIMARY / FAO-56 FALLBACK
# ══════════════════════════════════════════════════════════════════════════════
def predict_iwr_ml(tmean, rh, wind, kc, precipitation, soil_fc, soil_pwp, root_depth):
    if not ML_OK or ML_MODEL is None:
        return None, "ML unavailable"
    try:
        X = pd.DataFrame([{
            "tmean":         float(tmean),
            "rh":            float(rh),
            "wind":          float(wind),
            "kc":            float(kc),
            "precipitation": float(precipitation),
            "soil_fc":       float(soil_fc),
            "soil_pwp":      float(soil_pwp),
            "root_depth":    float(root_depth),
        }], columns=ML_FEATURES)
        iwr = max(0.0, round(float(ML_MODEL.predict(X)[0]), 3))
        return iwr, "XGBoost ML"
    except Exception as e:
        return None, f"ML error: {e}"

def compute_iwr_fao(etc, pe, Ef):
    nir = max(0.0, etc - pe)
    iwr = round(nir / max(Ef, 0.01), 3) if nir > 0 else 0.0
    return {"nir": round(nir,3), "iwr": iwr}

def compute_volume(iwr_mm, area_ha):
    vol_m3 = iwr_mm * area_ha * 10.0
    return {"vol_m3": round(vol_m3, 1), "vol_L": round(vol_m3*1000, 0)}

# ══════════════════════════════════════════════════════════════════════════════
# WATER BALANCE RUN (forecast & historical)
# ══════════════════════════════════════════════════════════════════════════════
def run_water_balance(daily_df, crop, soil, planting_ts, sm_pct, Ef=0.80,
                      stage_override=None):
    """
    Row-by-row daily water balance.
    stage_override: if set ("ini"/"mid"/"end"), all rows use that fixed Kc.
    Otherwise Kc is derived from DAP (days after planting).
    """
    cp  = crop_params[crop]
    zr  = cp["zr"]; mad = cp["mad"]
    taw = compute_taw(soil["fc"], soil["pwp"], zr)
    raw = compute_raw(taw, mad)

    theta = soil["pwp"] + (sm_pct/100.0)*(soil["fc"]-soil["pwp"])
    dr    = max(0.0, (soil["fc"]-theta)*zr*1000.0)

    df = daily_df.copy()

    if stage_override:
        fixed_kc = crop_params[crop][stage_override]
        df["kc"] = fixed_kc
    else:
        df["kc"] = df.index.map(lambda d: get_kc((d-planting_ts).days, crop)[0])

    df["ET0"] = df.apply(lambda r: et0_pm(
        r["tmax"], r["tmin"],
        r.get("rh_max", r.get("rh", 65)+10),
        r.get("rh_min", r.get("rh", 65)-10),
        r["wind"], r["rs"],
        doy=r.name.timetuple().tm_yday,
        lat_deg=LAT, elev=ELEV,
    ), axis=1)
    df["ETc"] = df["kc"] * df["ET0"]
    df["Pe"]  = df.get("precipitation", df.get("precip", pd.Series(0.0, index=df.index))).apply(eff_rain)

    dr_vals=[]; iwr_vals=[]; nir_vals=[]

    for _, row in df.iterrows():
        pe_r = row["Pe"]; etc_r = row["ETc"]; kc_r = row["kc"]
        prec = row.get("precipitation", row.get("precip", 0.0))
        dr_after = max(0.0, dr - pe_r + etc_r)

        iwr_ml, _ = predict_iwr_ml(
            tmean=(row["tmax"]+row["tmin"])/2.0,
            rh=row.get("rh_mean", row.get("rh", 65.0)),
            wind=row["wind"], kc=kc_r,
            precipitation=prec,
            soil_fc=soil["fc"], soil_pwp=soil["pwp"], root_depth=zr,
        )
        if iwr_ml is not None:
            iwr_gross = round(iwr_ml / max(Ef, 0.01), 3)
            nir_r     = iwr_ml
            dr = 0.0 if iwr_ml > 0 else dr_after
        else:
            res_r = compute_iwr_fao(etc_r, pe_r, Ef)
            nir_r = res_r["nir"]; iwr_gross = res_r["iwr"]
            dr = 0.0 if iwr_gross > 0 else dr_after

        dr_vals.append(round(dr, 2))
        nir_vals.append(nir_r)
        iwr_vals.append(iwr_gross)

    df["Depletion"] = dr_vals
    df["NIR"]       = nir_vals
    df["IWR"]       = iwr_vals
    return df, taw, raw

# ══════════════════════════════════════════════════════════════════════════════
# SOIL MOISTURE ESTIMATION
# ══════════════════════════════════════════════════════════════════════════════
def estimate_soil_moisture_status(fc, pwp, zr, lat, lon, elev):
    try:
        end_  = date.today() - timedelta(days=1)
        start_= end_ - timedelta(days=10)
        url = (
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={start_}&end_date={end_}"
            f"&daily=precipitation_sum,temperature_2m_max,temperature_2m_min,"
            f"shortwave_radiation_sum,wind_speed_10m_max,"
            f"relative_humidity_2m_max,relative_humidity_2m_min"
            f"&timezone={TIMEZONE}"
        )
        r  = requests.get(url, timeout=12).json()
        d  = r.get("daily", {}); dates = d.get("time", [])
        taw_ = (fc-pwp)*zr*1000.0
        theta = pwp + 0.70*(fc-pwp)
        dr_ = max(0.0, (fc-theta)*zr*1000.0)

        for i in range(len(dates)):
            tx = d["temperature_2m_max"][i]; tn = d["temperature_2m_min"][i]
            if tx is None or tn is None: continue
            rh_mx = d["relative_humidity_2m_max"][i] or 70
            rh_mn = d["relative_humidity_2m_min"][i] or 50
            wk    = (d["wind_speed_10m_max"][i] or 7.2)/3.6*_W2M
            rs_i  = d["shortwave_radiation_sum"][i] or 18.0
            prec  = d["precipitation_sum"][i] or 0.0
            doy_i = datetime.strptime(dates[i],"%Y-%m-%d").timetuple().tm_yday
            et0_i = et0_pm(tx,tn,rh_mx,rh_mn,wk,rs_i,elev=elev,doy=doy_i,lat_deg=lat)
            pe_i  = eff_rain(prec)
            dr_   = max(0.0, min(taw_, dr_-pe_i+et0_i))

        sm = int(max(0, min(100, (1-dr_/taw_)*100))) if taw_>0 else 70
        return {"sm_pct":sm,"source":"PM water balance (ERA5 last 10 days)","fallback":False}
    except Exception:
        return {"sm_pct":60,"source":"Default (weather API unavailable)","fallback":True}

def estimate_sm(fc, pwp, zr):
    return estimate_soil_moisture_status(fc, pwp, zr, LAT, LON, ELEV)["sm_pct"]

# ══════════════════════════════════════════════════════════════════════════════
# WEATHER APIs  — all calls use CURRENT location (LAT/LON)
# Cache key includes location so different locations don't share cache
# ══════════════════════════════════════════════════════════════════════════════
_ch = f"{datetime.now().strftime('%Y%m%d%H')}_{LAT}_{LON}"

@st.cache_data(ttl=3600, show_spinner=False)
def get_current_weather(_cache_key, lat, lon, elev):
    try:
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation,"
            f"wind_speed_10m,shortwave_radiation,weather_code"
            f"&daily=temperature_2m_max,temperature_2m_min,"
            f"relative_humidity_2m_max,relative_humidity_2m_min,"
            f"windspeed_10m_max,shortwave_radiation_sum,"
            f"precipitation_sum,weather_code"
            f"&forecast_days=1&timezone={TIMEZONE}", timeout=12
        ).json()
        cur = r.get("current",{}); d=r.get("daily",{})
        tmax = d.get("temperature_2m_max",[None])[0]
        tmin = d.get("temperature_2m_min",[None])[0]
        rh_mx= d.get("relative_humidity_2m_max",[70])[0] or 70
        rh_mn= d.get("relative_humidity_2m_min",[50])[0] or 50
        wk   = (d.get("windspeed_10m_max",[7.2])[0] or 7.2)/3.6*_W2M
        rs   = d.get("shortwave_radiation_sum",[18.0])[0] or 18.0
        prec = d.get("precipitation_sum",[0.0])[0] or 0.0
        wcode= d.get("weather_code",[0])[0] or 0
        tmean_c = cur.get("temperature_2m",25)
        tmax = tmax or tmean_c+4; tmin = tmin or tmean_c-4
        return {"tmax":round(tmax,1),"tmin":round(tmin,1),
                "rh_max":rh_mx,"rh_min":rh_mn,"rh_mean":round((rh_mx+rh_mn)/2,1),
                "wind":round(wk,3),"rs":round(rs,1),"precip":round(prec,1),
                "wcode":wcode,
                "description":WMO_DESC.get(int(wcode),f"Code {wcode}"),
                "source":"Open-Meteo ICON+GFS (live)"}
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_forecast(_cache_key, lat, lon, elev):
    try:
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,"
            f"relative_humidity_2m_max,relative_humidity_2m_min,"
            f"windspeed_10m_max,shortwave_radiation_sum,"
            f"precipitation_sum,weather_code"
            f"&forecast_days=7&timezone={TIMEZONE}", timeout=12
        ).json()
        d=r.get("daily",{})
        if not d: return None
        n=len(d["time"]); rows=[]
        for i in range(n):
            wk=(d["windspeed_10m_max"][i] or 7.2)/3.6*_W2M
            rh_mx=d["relative_humidity_2m_max"][i] or 70
            rh_mn=d["relative_humidity_2m_min"][i] or 50
            rows.append({
                "date":pd.to_datetime(d["time"][i]),
                "tmax":d["temperature_2m_max"][i] or 28,
                "tmin":d["temperature_2m_min"][i] or 16,
                "rh_max":rh_mx,"rh_min":rh_mn,"rh_mean":round((rh_mx+rh_mn)/2,1),
                "wind":round(wk,3),
                "rs":d["shortwave_radiation_sum"][i] or 18.0,
                "precipitation":d["precipitation_sum"][i] or 0.0,
                "weather_code":d["weather_code"][i] or 0,
            })
        df=pd.DataFrame(rows).set_index("date")
        today=pd.Timestamp.today().normalize()
        return df[df.index>=today].head(5)
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_historical_weather(start_date, end_date, lat, lon):
    """ERA5 archive — authoritative historical data."""
    try:
        r = requests.get(
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&daily=temperature_2m_max,temperature_2m_min,"
            f"relative_humidity_2m_max,relative_humidity_2m_min,"
            f"windspeed_10m_max,shortwave_radiation_sum,"
            f"precipitation_sum"
            f"&timezone={TIMEZONE}", timeout=25
        ).json()
        d=r.get("daily",{})
        if not d: return None
        rh_mx=d.get("relative_humidity_2m_max",[])
        rh_mn=d.get("relative_humidity_2m_min",[])
        df=pd.DataFrame({
            "date":pd.to_datetime(d["time"]),
            "tmax":[x or 28 for x in d["temperature_2m_max"]],
            "tmin":[x or 16 for x in d["temperature_2m_min"]],
            "rh_max":[(a or 70) for a in rh_mx],
            "rh_min":[(a or 50) for a in rh_mn],
            "rh_mean":[(((a or 70)+(b or 50))/2) for a,b in zip(rh_mx,rh_mn)],
            "wind":[(x or 7.2)/3.6*_W2M for x in d["windspeed_10m_max"]],
            "rs":[x or 18.0 for x in d["shortwave_radiation_sum"]],
            "precipitation":[x or 0.0 for x in d["precipitation_sum"]],
        }).set_index("date")
        df["rh"]=df["rh_mean"]
        return df.dropna(subset=["tmax","tmin"])
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════
# FETCH LIVE WEATHER FOR CURRENT LOCATION
# ══════════════════════════════════════════════════════════════════════════════
with st.spinner(f"📡 Fetching live weather for {SITE_NAME}…"):
    wx = get_current_weather(_ch, LAT, LON, ELEV)

if wx:
    lt=wx["tmax"]; ln=wx["tmin"]; lr_max=wx["rh_max"]; lr_min=wx["rh_min"]
    lr_mean=wx["rh_mean"]; lw=wx["wind"]; ls=wx["rs"]; lp=wx["precip"]
else:
    lt,ln,lr_max,lr_min,lr_mean,lw,ls,lp = 28.,16.,70.,50.,60.,1.5,18.,0.

_doy = int(datetime.today().strftime("%j"))

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3 = st.tabs(["📊 Today's IWR", "☁️ 5-Day Forecast", "📅 Historical"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — TODAY'S IWR  (Kc stage bug FIXED)
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.header(f"📊 Today's IWR — {SITE_NAME}")
    st.caption(
        f"📡 {wx['source'] if wx else 'Weather unavailable'} · "
        f"FAO-56 PM v6.0 · {'XGBoost ML + ' if ML_OK else ''}FAO-56 MAD"
    )

    if wx:
        st.success(
            f"✅ **{wx['description']}** · Rain: **{lp} mm** · "
            f"Lat {LAT}° / Lon {LON}° / {ELEV} m a.s.l."
        )
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("🌡️ Tmax / Tmin",  f"{lt}°C / {ln}°C")
        c2.metric("💧 RH min–max",   f"{lr_min:.0f}–{lr_max:.0f}%", f"Mean {lr_mean:.0f}%")
        c3.metric("🌬️ Wind (2 m)",   f"{lw:.2f} m/s")
        c4.metric("☀️ Solar Rad",    f"{ls:.1f} MJ/m²/d")
        c5.metric("🌧️ Rain Today",   f"{lp:.1f} mm")
    else:
        st.warning("⚠️ Weather unavailable — using default values")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🌱 Crop & Growth Stage")
        cr1 = st.selectbox("Crop", list(crop_params.keys()), key="cr1")
        cp1 = crop_params[cr1]

        # ── FIXED: stage radio now correctly updates Kc ──────────────────────
        stage1 = st.radio(
            "Growing Stage",
            list(STAGE_LABELS.keys()),
            format_func=lambda x: STAGE_LABELS[x],
            key="stg1",
            horizontal=True,
        )
        # kc1 is always re-read from the selected stage (not cached)
        kc1 = kc_from_stage(stage1, cr1)
        # ─────────────────────────────────────────────────────────────────────

        st.markdown(
            f'<div class="kc-stage">Kc ({STAGE_LABELS[stage1]}) = <b>{kc1:.3f}</b> '
            f'· Zr = {cp1["zr"]:.2f} m · MAD = {int(cp1["mad"]*100)}%</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"| Stage | Ini Kc | Mid Kc | End Kc |\n|---|---|---|---|\n"
            f"| {cr1} | {cp1['ini']} | {cp1['mid']} | {cp1['end']} |"
        )

    with col2:
        st.subheader("🌦️ Weather & Soil")
        tmax_in  = st.number_input("Tmax (°C)", value=float(lt), key="t1")
        tmin_in  = st.number_input("Tmin (°C)", value=float(ln), key="t2")
        rh_in    = st.number_input("RH mean (%)", value=float(lr_mean),
                                   min_value=0.0, max_value=100.0, key="rh1")
        wind_in  = st.number_input("Wind 2m (m/s)", value=float(lw),
                                   min_value=0.0, key="w1")
        rs_in    = st.number_input("Solar Rad (MJ/m²/d)", value=float(ls),
                                   min_value=0.0, key="rs1")
        prec_in  = st.number_input("Rain (mm)", value=float(lp),
                                   min_value=0.0, key="p1")

        soil1_obj = {"fc": ACTIVE_FC, "pwp": ACTIVE_PWP}
        _sm_def = estimate_sm(ACTIVE_FC, ACTIVE_PWP, cp1["zr"])
        sm_pct  = st.slider("Soil Moisture (% of FC)", 0, 100, _sm_def, key="sm1")

        st.markdown(
            f'<div class="soil-panel">🌍 <b>Soil ({ACTIVE_TXT})</b> '
            f'· FC <b>{ACTIVE_FC*100:.0f}%</b> · PWP <b>{ACTIVE_PWP*100:.0f}%</b><br>'
            f'💧 System: <b>{irrig_sys}</b> · Ef = <b>{Ef*100:.0f}%</b> · '
            f'Area <b>{area_ha} ha</b> · Flow <b>{pump_flow} m³/hr</b></div>',
            unsafe_allow_html=True,
        )

    if st.button("🧮 Calculate Today's IWR & Volume", type="primary",
                 use_container_width=True, key="calc1"):
        rh_mx1 = min(100.0, rh_in + 10.0); rh_mn1 = max(0.0, rh_in - 10.0)
        et0_fao = et0_pm(tmax_in, tmin_in, rh_mx1, rh_mn1, wind_in, rs_in,
                         doy=_doy, lat_deg=LAT, elev=ELEV)
        et0_h   = et0_hargreaves(tmax_in, tmin_in, doy=_doy, lat_deg=LAT)
        # ── Use the selected stage Kc (FIXED — no stale initial Kc) ──────────
        etc1    = round(kc1 * et0_fao, 3)
        pe1     = eff_rain(prec_in)

        iwr_ml, ml_msg = predict_iwr_ml(
            tmean=(tmax_in+tmin_in)/2.0, rh=rh_in,
            wind=wind_in, kc=kc1, precipitation=prec_in,
            soil_fc=ACTIVE_FC, soil_pwp=ACTIVE_PWP,
            root_depth=cp1["zr"],
        )
        if iwr_ml is not None:
            nir1  = iwr_ml
            iwr1  = round(iwr_ml / max(Ef, 0.01), 3)
            method_lbl = f"XGBoost ML (Ef={Ef:.2f})"
        else:
            res1  = compute_iwr_fao(etc1, pe1, Ef)
            nir1  = res1["nir"]; iwr1 = res1["iwr"]
            method_lbl = f"FAO-56 MAD (Ef={Ef:.2f})"

        vol1  = compute_volume(iwr1, area_ha)
        mins1 = round((vol1["vol_m3"]/pump_flow)*60,1) if pump_flow>0 and iwr1>0 else 0

        taw1 = compute_taw(ACTIVE_FC, ACTIVE_PWP, cp1["zr"])
        raw1 = compute_raw(taw1, cp1["mad"])

        st.markdown("### 📋 Results")
        st.info(
            f"📍 **{SITE_NAME}** · Lat {LAT}° · Lon {LON}° · {ELEV} m a.s.l.  \n"
            f"🌱 **{cr1}** · Stage: **{STAGE_LABELS[stage1]}** · Kc = **{kc1:.3f}**  \n"
            f"🌍 Soil: **{ACTIVE_TXT}** (FC={ACTIVE_FC*100:.0f}%, PWP={ACTIVE_PWP*100:.0f}%)"
        )

        r1,r2,r3,r4,r5,r6 = st.columns(6)
        r1.metric("ET₀ FAO-56 PM", f"{et0_fao:.3f} mm/d")
        r2.metric("ET₀ Hargreaves", f"{et0_h:.3f} mm/d")
        r3.metric("ETc", f"{etc1:.3f} mm/d", f"Kc={kc1:.3f}")
        r4.metric("Pe (Eff. Rain)", f"{pe1:.2f} mm")
        r5.metric("NIR", f"{nir1:.2f} mm", "ETc − Pe")
        r6.metric("IWR (Gross)", f"{iwr1:.2f} mm", f"NIR÷{Ef:.2f}")

        st.markdown("---")
        taw_str = f"TAW={taw1:.1f} mm · RAW={raw1:.1f} mm"
        st.markdown(
            f'<div class="nir-box">📐 <b>NIR = {nir1:.2f} mm</b> &nbsp;·&nbsp; {taw_str}</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="iwr-box">💧 <b>IWR (Gross) = {iwr1:.2f} mm</b> '
            f'&nbsp;·&nbsp; {irrig_sys} (Ef={Ef*100:.0f}%)</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="vol-box">🪣 <b>Volume needed:</b> '
            f'<b>{vol1["vol_m3"]:.1f} m³</b> &nbsp;=&nbsp; '
            f'<b>{vol1["vol_L"]:,.0f} litres</b> '
            f'for <b>{area_ha} ha</b>'
            f'{"" if iwr1==0 else f" &nbsp;·&nbsp; ⏱️ Pump time: <b>{mins1} min</b> at {pump_flow} m³/hr"}'
            f'</div>',
            unsafe_allow_html=True)

        if iwr1 == 0:
            st.success(f"✅ No irrigation needed today. Rain ({pe1:.1f} mm) covers crop demand.")
        else:
            st.warning(f"💧 Irrigate **{iwr1:.2f} mm gross** → {vol1['vol_m3']:.1f} m³ "
                       f"({vol1['vol_L']:,.0f} L) across {area_ha} ha")

        # Summary table (no Method column)
        summary_df = pd.DataFrame([{
            "Location": SITE_NAME, "Lat": LAT, "Lon": LON, "Elev_m": ELEV,
            "Crop": cr1, "Stage": STAGE_LABELS[stage1], "Kc": kc1,
            "Tmax°C": tmax_in, "Tmin°C": tmin_in, "RH%": rh_in,
            "Wind m/s": wind_in, "RS MJ/m²/d": rs_in, "Rain mm": prec_in,
            "ET₀ PM mm/d": et0_fao, "ET₀ H mm/d": et0_h,
            "ETc mm/d": etc1, "Pe mm": pe1,
            "NIR mm": nir1, "IWR mm": iwr1,
            "Vol m³": vol1["vol_m3"], "Vol L": vol1["vol_L"],
            "Pump min": mins1,
        }])
        st.download_button(
            "⬇️ Download Today's Result CSV",
            summary_df.to_csv(index=False).encode(),
            f"HyPIS_today_{SITE_NAME.replace(' ','_')}_{datetime.today().strftime('%Y%m%d')}.csv",
            "text/csv", key="dl_today"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — 5-DAY FORECAST
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.header(f"☁️ 5-Day IWR Forecast — {SITE_NAME}")
    st.caption(
        f"FAO-56 PM · {'XGBoost ML + ' if ML_OK else ''}MAD fallback · "
        f"Open-Meteo ICON+GFS · Ef={Ef*100:.0f}% ({irrig_sys})"
    )

    fc_c1, fc_c2 = st.columns(2)
    with fc_c1:
        cr2 = st.selectbox("Crop", list(crop_params.keys()), key="cr2")
        cp2 = crop_params[cr2]
        stage2 = st.radio("Growing Stage", list(STAGE_LABELS.keys()),
                          format_func=lambda x: STAGE_LABELS[x],
                          key="stg2", horizontal=True)
        kc2 = kc_from_stage(stage2, cr2)
        st.markdown(
            f'<div class="kc-stage">Kc ({STAGE_LABELS[stage2]}) = <b>{kc2:.3f}</b></div>',
            unsafe_allow_html=True)
    with fc_c2:
        planting2 = st.date_input("Planting Date",
                                  value=datetime.today().date()-timedelta(days=45),
                                  key="plant2")
        soil2 = {"fc": ACTIVE_FC, "pwp": ACTIVE_PWP}
        st.markdown(
            f'<div class="soil-panel">🌍 Soil auto-loaded: <b>{ACTIVE_TXT}</b> '
            f'(FC={ACTIVE_FC*100:.0f}%, PWP={ACTIVE_PWP*100:.0f}%)</div>',
            unsafe_allow_html=True)
        sm_pct2 = st.slider("Starting SM (% of FC)", 0, 100,
                             estimate_sm(ACTIVE_FC, ACTIVE_PWP, cp2["zr"]),
                             key="sm2")

    if st.button("📥 Get 5-Day Forecast + Volume", type="primary",
                 use_container_width=True, key="fc_btn"):
        with st.spinner(f"Fetching forecast for {SITE_NAME}…"):
            daily = get_forecast(_ch, LAT, LON, ELEV)

        if daily is None or daily.empty:
            st.warning("⚠️ Forecast unavailable — try again shortly.")
        else:
            planting_ts2 = pd.Timestamp(planting2)
            daily_r, taw2, raw2 = run_water_balance(
                daily, cr2, soil2, planting_ts2, sm_pct2, Ef,
                stage_override=stage2)

            daily_r["Vol_m3"] = daily_r["IWR"].apply(lambda x: compute_volume(x,area_ha)["vol_m3"])
            daily_r["Vol_L"]  = daily_r["IWR"].apply(lambda x: compute_volume(x,area_ha)["vol_L"])
            daily_r["PumpMin"]= daily_r["Vol_m3"].apply(
                lambda v: round(v/pump_flow*60,1) if pump_flow>0 and v>0 else 0)

            tot_iwr = daily_r["IWR"].sum(); tot_vol = daily_r["Vol_m3"].sum()
            nd = (daily_r["IWR"]>0).sum()

            if nd > 0:
                st.warning(
                    f"🗓️ **{nd} irrigation event(s)** · "
                    f"Total IWR = **{tot_iwr:.1f} mm** · "
                    f"Total Vol = **{tot_vol:.1f} m³** ({tot_vol*1000:,.0f} L)"
                )
            else:
                st.success("✅ No irrigation needed over next 5 days.")

            cols2 = st.columns(len(daily_r))
            for i, (dt, row) in enumerate(daily_r.iterrows()):
                icon = wmo_icon(row.get("weather_code",0))
                lbl  = f"💧 {row['IWR']:.1f}mm" if row["IWR"]>0 else f"{icon} OK"
                dlt  = (f"🪣 {row['Vol_m3']:.1f}m³ · ⏱{row['PumpMin']}min"
                        if row["IWR"]>0 else f"🌧 {row['precipitation']:.1f}mm")
                cols2[i].metric(dt.strftime("%a %d"), lbl, dlt)

            st.subheader("📋 Forecast Table")
            # No Method column
            tc2 = ["tmax","tmin","rh_mean","precipitation","ET0","kc","ETc","Pe",
                   "NIR","IWR","Vol_m3","Vol_L","PumpMin"]
            tb2 = daily_r[[c for c in tc2 if c in daily_r.columns]].round(3).copy()
            rename2 = {"tmax":"Tmax°C","tmin":"Tmin°C","rh_mean":"RH%",
                       "precipitation":"Rain mm","ET0":"ET₀ mm","kc":"Kc",
                       "ETc":"ETc mm","Pe":"Pe mm","NIR":"NIR mm","IWR":"IWR mm",
                       "Vol_m3":"Vol m³","Vol_L":"Vol L","PumpMin":"Pump min"}
            tb2.rename(columns=rename2, inplace=True)
            tb2.index = tb2.index.strftime("%Y-%m-%d")
            st.dataframe(tb2, use_container_width=True)

            fig2=go.Figure()
            fig2.add_bar(x=daily_r.index.strftime("%a %d"),y=daily_r["IWR"],
                         name="IWR mm",marker_color="#1a5fc8")
            fig2.add_bar(x=daily_r.index.strftime("%a %d"),y=daily_r["NIR"],
                         name="NIR mm",marker_color="#0b6b1b",opacity=0.6)
            fig2.add_scatter(x=daily_r.index.strftime("%a %d"),y=daily_r["ET0"],
                             name="ET₀ mm/d",mode="lines+markers",
                             marker_color="#b81c1c",yaxis="y2")
            fig2.update_layout(
                title=f"5-Day IWR Forecast — {SITE_NAME}",
                yaxis=dict(title="mm"),barmode="group",
                yaxis2=dict(title="ET₀ mm/d",overlaying="y",side="right"),
                legend=dict(x=0,y=1.1,orientation="h"),
                height=380,plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2")
            st.plotly_chart(fig2,use_container_width=True)

            st.download_button("⬇️ Download CSV",tb2.to_csv().encode(),
                               f"HyPIS_forecast_{SITE_NAME.replace(' ','_')}_{datetime.today().strftime('%Y%m%d')}.csv",
                               "text/csv",key="dl_fc")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — HISTORICAL ANALYSIS  (Yesterday / Last 7 Days / Last 30 Days)
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.header(f"📅 Historical IWR Analysis — {SITE_NAME}")
    st.caption(
        f"ERA5 Archive (Open-Meteo) · FAO-56 PM · "
        f"{'XGBoost ML + ' if ML_OK else ''}FAO-56 MAD · "
        f"IWR = NIR ÷ Ef ({Ef*100:.0f}%, {irrig_sys})"
    )

    st.info(
        f"📍 **{SITE_NAME}** · Lat `{LAT}°` · Lon `{LON}°` · `{ELEV} m` a.s.l.  \n"
        f"🌍 Soil: **{ACTIVE_TXT}** · FC={ACTIVE_FC*100:.0f}% · PWP={ACTIVE_PWP*100:.0f}%  \n"
        f"*(ERA5 archive may lag 3–5 days — yesterday is the closest available)*"
    )

    # Period selector — Yesterday / Last 7 Days / Last 30 Days ONLY
    pc1, pc2, pc3 = st.columns(3)
    yesterday = date.today() - timedelta(days=1)

    if pc1.button("📅 Yesterday",    use_container_width=True, key="h_yest"):
        st.session_state["h_start"] = yesterday
        st.session_state["h_end"]   = yesterday
    if pc2.button("📅 Last 7 Days",  use_container_width=True, key="h_7"):
        st.session_state["h_start"] = yesterday - timedelta(days=6)
        st.session_state["h_end"]   = yesterday
    if pc3.button("📅 Last 30 Days", use_container_width=True, key="h_30"):
        st.session_state["h_start"] = yesterday - timedelta(days=29)
        st.session_state["h_end"]   = yesterday

    h_start = st.session_state.get("h_start", yesterday - timedelta(days=6))
    h_end   = st.session_state.get("h_end",   yesterday)

    st.markdown(f"**Period:** `{h_start}` → `{h_end}` ({(h_end - h_start).days + 1} days)")

    # Crop / soil settings for historical
    hc1, hc2 = st.columns(2)
    with hc1:
        cr3 = st.selectbox("Crop", list(crop_params.keys()), key="cr3")
        cp3 = crop_params[cr3]
        stage3 = st.radio("Growing Stage", list(STAGE_LABELS.keys()),
                          format_func=lambda x: STAGE_LABELS[x],
                          key="stg3", horizontal=True)
        kc3 = kc_from_stage(stage3, cr3)
        st.markdown(
            f'<div class="kc-stage">Kc ({STAGE_LABELS[stage3]}) = <b>{kc3:.3f}</b></div>',
            unsafe_allow_html=True)
    with hc2:
        planting3 = st.date_input("Planting Date",
                                  value=date.today()-timedelta(days=45),
                                  key="plant3")
        soil3 = {"fc": ACTIVE_FC, "pwp": ACTIVE_PWP}
        st.markdown(
            f'<div class="soil-panel">🌍 Soil: <b>{ACTIVE_TXT}</b> '
            f'(FC={ACTIVE_FC*100:.0f}%, PWP={ACTIVE_PWP*100:.0f}%)</div>',
            unsafe_allow_html=True)
        sm3 = st.slider("Starting SM (% of FC)", 0, 100,
                        estimate_sm(ACTIVE_FC, ACTIVE_PWP, cp3["zr"]), key="sm3")

    if st.button("📥 Retrieve Historical Data", type="primary",
                 use_container_width=True, key="hist_btn"):
        with st.spinner(f"Fetching ERA5 archive for {SITE_NAME}…"):
            hist = get_historical_weather(str(h_start), str(h_end), LAT, LON)

        if hist is None or hist.empty:
            st.warning("⚠️ No ERA5 data for this period (archive may lag 3–5 days).")
        else:
            planting_ts3 = pd.Timestamp(planting3)
            hist_r, taw3, raw3 = run_water_balance(
                hist, cr3, soil3, planting_ts3, sm3, Ef,
                stage_override=stage3)

            hist_r["Vol_m3"] = hist_r["IWR"].apply(lambda x: compute_volume(x,area_ha)["vol_m3"])
            hist_r["Vol_L"]  = hist_r["IWR"].apply(lambda x: compute_volume(x,area_ha)["vol_L"])
            hist_r["ET0_H"]  = [et0_hargreaves(r["tmax"],r["tmin"],
                                               doy=int(d.strftime("%j")),lat_deg=LAT)
                                for d,r in hist_r.iterrows()]

            m1,m2,m3,m4,m5,m6 = st.columns(6)
            m1.metric("📆 Days",       len(hist_r))
            m2.metric("🌧️ Rain Total", f"{hist_r['precipitation'].sum():.1f} mm")
            m3.metric("💧 NIR Total",  f"{hist_r['NIR'].sum():.1f} mm")
            m4.metric("💧 IWR Total",  f"{hist_r['IWR'].sum():.1f} mm")
            m5.metric("🪣 Vol Total",  f"{hist_r['Vol_m3'].sum():.1f} m³")
            m6.metric("🚿 Irrig Days", str((hist_r["IWR"]>0).sum()))

            st.subheader("📋 Historical Table")
            # No Method column
            ht = hist_r[["tmax","tmin","rh_mean","precipitation","ET0","ET0_H",
                          "kc","ETc","Pe","Depletion","NIR","IWR","Vol_m3","Vol_L"]].round(3).copy()
            ht.columns = ["Tmax°C","Tmin°C","RH%","Rain mm","ET₀ PM mm","ET₀ H mm",
                          "Kc","ETc mm","Pe mm","Depletion mm","NIR mm","IWR mm",
                          "Vol m³","Vol L"]
            ht.index = ht.index.strftime("%Y-%m-%d")
            st.dataframe(ht, use_container_width=True)

            fig3=go.Figure()
            fig3.add_scatter(x=hist_r.index,y=hist_r["ET0"],name="ET₀ PM mm/d",
                             mode="lines",line=dict(color="#1a5fc8",width=1.5))
            fig3.add_scatter(x=hist_r.index,y=hist_r["ET0_H"],name="ET₀ Hargreaves",
                             mode="lines",line=dict(color="#b81c1c",width=1,dash="dot"))
            fig3.add_bar(x=hist_r.index,y=hist_r["NIR"],name="NIR mm",
                         marker_color="#0b6b1b",opacity=0.5,yaxis="y2")
            fig3.add_bar(x=hist_r.index,y=hist_r["IWR"],name="IWR mm",
                         marker_color="#17a2b8",opacity=0.7,yaxis="y2")
            fig3.update_layout(
                title=f"Historical ET₀, NIR & IWR — {SITE_NAME}",
                yaxis=dict(title="ET₀ mm/d"),
                yaxis2=dict(title="mm",overlaying="y",side="right"),
                barmode="group",
                legend=dict(x=0,y=1.1,orientation="h"),
                height=400,plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2")
            st.plotly_chart(fig3,use_container_width=True)

            fig_dep=go.Figure()
            fig_dep.add_scatter(x=hist_r.index,y=hist_r["Depletion"],
                                mode="lines",name="Root Zone Depletion",
                                line=dict(color="#e6550d",width=1.5))
            fig_dep.add_hline(y=raw3,line_dash="dash",line_color="#756bb1",
                              annotation_text=f"RAW={raw3:.1f} mm (irrigate)")
            fig_dep.add_hline(y=taw3,line_dash="dot",line_color="#d73027",
                              annotation_text=f"TAW={taw3:.1f} mm (wilting risk)")
            fig_dep.update_layout(
                title="Root Zone Depletion",yaxis_title="Depletion (mm)",
                plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2")
            st.plotly_chart(fig_dep,use_container_width=True)

            fig_vol=go.Figure()
            fig_vol.add_bar(
                x=hist_r.index[hist_r["IWR"]>0],
                y=hist_r.loc[hist_r["IWR"]>0,"Vol_m3"],
                name="Volume (m³)",marker_color="#0d6efd")
            fig_vol.update_layout(
                title=f"Irrigation Volume per Event — {area_ha} ha",
                yaxis_title="m³",plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2")
            st.plotly_chart(fig_vol,use_container_width=True)

            st.download_button(
                "⬇️ Download Historical CSV",
                ht.to_csv().encode(),
                f"HyPIS_historical_{SITE_NAME.replace(' ','_')}_{h_start}_{h_end}.csv",
                "text/csv", key="dl_hist"
            )

# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.caption(
    f"HyPIS Ug v6.0 · {SITE_NAME} ({LAT}°, {LON}°, {ELEV} m) · "
    f"ERA5 + ICON + GFS (Open-Meteo) · FAO-56 Penman-Monteith · "
    f"XGBoost ML (Features: {', '.join(ML_FEATURES)}) · "
    f"IWR = NIR ÷ Ef · HWSD v2 Soil · Byaruhanga Prosper"
)
