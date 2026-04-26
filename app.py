"""
HyPIS Ug  v7.6  — Bug-Fixed
═══════════════════════════════════════════════════════════════════════════════
FIXES in v7.6 (over v7.5):
  ✔ CRITICAL — estimate_sm initial SM changed from 70% → 50% of available
    water content.  In Uganda's bi-modal rainy climate the ERA5 10-day
    back-run was starting at Dr=0.30×TAW; frequent light rain kept Dr < RAW
    for the entire 5-day forecast window → irrigation NEVER triggered.
    At 50% start Dr=0.50×TAW ≥ RAW for most crops after even a short dry
    spell, producing physically realistic irrigation recommendations.
  ✔ CRITICAL — depletion_status() simplified to the canonical FAO-56 rule:
    irrigate when Dr > RAW, period.  Rain (Pe) is irrelevant to the trigger;
    it has already been accounted for when computing dr_new.  The previous
    "Pe ≥ ETc → no irrigate" guard was double-counting rainfall and blocking
    irrigation even when the root zone was critically depleted.
  ✔ Decimal display — every numeric column in all three result tables now
    carries an explicit .format() entry so pandas never shows 6-decimal floats.
  ✔ Today Summary table now uses .style.format() instead of bare st.dataframe().

FIXES in v7.5 (retained):
  ✔ Rain always sourced from Open-Meteo forecast (no manual rain input).
  ✔ Forecast filter timezone-aware (Africa/Nairobi).
  ✔ SM% rounding uses round(...,1) not int() truncation.
  ✔ estimate_sm uses ETc = Kc×ET₀.

Author: Prosper BYARUHANGA · HyPIS App v7.6 · FAO-56 PM
═══════════════════════════════════════════════════════════════════════════════
"""

import os, sys, time as _time, subprocess, pathlib, io
import numpy as np
import pandas as pd
import requests
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta, date

_PD_VER = tuple(int(x) for x in pd.__version__.split(".")[:2])

def _styler_map(styler, func, subset=None):
    if _PD_VER >= (2, 0):
        return styler.map(func, subset=subset)
    return styler.applymap(func, subset=subset)

for _pkg in ("joblib", "xgboost", "openpyxl"):
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

try:
    import openpyxl  # noqa: F401
    OPENPYXL_OK = True
except Exception:
    OPENPYXL_OK = False

st.set_page_config(page_title="HyPIS Ug – Uganda IWR", layout="wide",
                   initial_sidebar_state="expanded")
_HERE = os.path.dirname(os.path.abspath(__file__))

LOCATIONS = {
    " Kampala (Makerere Uni)": ( 0.33396,  32.56801, 1239.01),
    "MUARiK (Kabanyoro)":      ( 0.464533, 32.612517, 1178.97),
    "Mbarara":                 (-0.6133,   30.6544,   1433),
    "Isingiro (Kabuyanda)":   (-0.95658,  30.61432,  1364.59),
    "Gulu":                   ( 2.7746,   32.2990,   1105),
    "Jinja":                  ( 0.4244,   33.2041,   1137),
    "Mbale":                  ( 1.0804,   34.1751,   1155),
    "Kabale":                 (-1.2490,   29.9900,   1869),
    "Fort Portal":            ( 0.6710,   30.2750,   1537),
    "Masaka":                 (-0.3310,   31.7373,   1148),
    "Lira":                   ( 2.2499,   32.9002,   1074),
    "Soroti":                 ( 1.7153,   33.6107,   1130),
    "Arua":                   ( 3.0210,   30.9110,   1047),
    "Hoima":                  ( 1.4352,   31.3524,   1562),
    "Kasese":                 ( 0.1820,   30.0804,    933),
    "Tororo":                 ( 0.6920,   34.1810,   1148),
    "Moroto":                 ( 2.5340,   34.6650,   1390),
    "Custom Location":        (None,      None,      None),
}

DISTRICT_SOIL = {
    "Kampala (Makerere Uni)": {"fc":0.32,"pwp":0.18,"texture":"Clay Loam",       "source":"HWSD v2"},
    "MUARiK (kabanyoro)":      {"fc":0.26,"pwp":0.12,"texture":"Sandy Clay Loam","source":"HWSD v2"},
    "Mbarara":                 {"fc":0.30,"pwp":0.15,"texture":"Loam",            "source":"HWSD v2"},
    "Isingiro (Kabuyanda)":   {"fc":0.28,"pwp":0.14,"texture":"Loam",            "source":"HWSD v2"},
    "Gulu":                   {"fc":0.24,"pwp":0.11,"texture":"Sandy Loam",       "source":"HWSD v2"},
    "Jinja":                  {"fc":0.31,"pwp":0.16,"texture":"Clay Loam",        "source":"HWSD v2"},
    "Mbale":                  {"fc":0.27,"pwp":0.13,"texture":"Loam",             "source":"HWSD v2"},
    "Kabale":                 {"fc":0.33,"pwp":0.19,"texture":"Clay",             "source":"HWSD v2"},
    "Fort Portal":            {"fc":0.29,"pwp":0.14,"texture":"Loam",             "source":"HWSD v2"},
    "Masaka":                 {"fc":0.25,"pwp":0.12,"texture":"Sandy Loam",       "source":"HWSD v2"},
    "Lira":                   {"fc":0.23,"pwp":0.10,"texture":"Sandy Loam",       "source":"HWSD v2"},
    "Soroti":                 {"fc":0.22,"pwp":0.09,"texture":"Sandy Loam",       "source":"HWSD v2"},
    "Arua":                   {"fc":0.21,"pwp":0.08,"texture":"Loamy Sand",       "source":"HWSD v2"},
    "Hoima":                  {"fc":0.28,"pwp":0.13,"texture":"Sandy Loam",       "source":"HWSD v2"},
    "Kasese":                 {"fc":0.35,"pwp":0.20,"texture":"Clay",             "source":"HWSD v2"},
    "Tororo":                 {"fc":0.26,"pwp":0.12,"texture":"Sandy Clay Loam",  "source":"HWSD v2"},
    "Moroto":                 {"fc":0.18,"pwp":0.08,"texture":"Sandy Loam",       "source":"HWSD v2"},
    "Custom Location":        {"fc":0.28,"pwp":0.14,"texture":"Loam (default)",   "source":"FAO-56 default"},
}

SOIL_OPTS = {
    "Sand":            {"fc":0.10,"pwp":0.05,"desc":"Very fast drainage, very low retention"},
    "Loamy Sand":      {"fc":0.14,"pwp":0.07,"desc":"Fast drainage, low retention"},
    "Sandy Loam":      {"fc":0.20,"pwp":0.09,"desc":"Moderate drainage, moderate retention"},
    "Sandy Clay Loam": {"fc":0.26,"pwp":0.12,"desc":"Moderate-high retention"},
    "Loam":            {"fc":0.28,"pwp":0.14,"desc":"Good balance of drainage and retention"},
    "Silt Loam":       {"fc":0.31,"pwp":0.15,"desc":"High retention, moderate drainage"},
    "Silt":            {"fc":0.33,"pwp":0.16,"desc":"High retention"},
    "Clay Loam":       {"fc":0.32,"pwp":0.18,"desc":"High retention, slow drainage"},
    "Silty Clay Loam": {"fc":0.35,"pwp":0.20,"desc":"Very high retention"},
    "Sandy Clay":      {"fc":0.28,"pwp":0.16,"desc":"Moderate-high retention"},
    "Silty Clay":      {"fc":0.38,"pwp":0.23,"desc":"Very high retention, poor drainage"},
    "Clay":            {"fc":0.40,"pwp":0.25,"desc":"Maximum retention, waterlogging risk"},
}

TEXTURE_MAD_ADJ = {
    "Sand":            +0.10,
    "Loamy Sand":      +0.08,
    "Sandy Loam":      +0.05,
    "Sandy Clay Loam": -0.03,
    "Loam":            +0.00,
    "Silt Loam":       -0.05,
    "Silt":            -0.05,
    "Clay Loam":       -0.05,
    "Silty Clay Loam": -0.08,
    "Sandy Clay":      -0.05,
    "Silty Clay":      -0.10,
    "Clay":            -0.10,
    "Loam (default)":  +0.00,
}

def adjust_mad_for_soil(mad_crop, texture):
    adj = TEXTURE_MAD_ADJ.get(texture, 0.0)
    if adj == 0.0:
        for k, v in TEXTURE_MAD_ADJ.items():
            if k.lower() in texture.lower():
                adj = v; break
    return round(max(0.10, min(0.90, mad_crop + adj)), 3)

TIMEZONE = "Africa/Nairobi"
_SIGMA   = 4.903e-9
_W2M     = 4.87 / np.log(67.8 * 10.0 - 5.42)

ML_MODEL    = None
ML_OK       = False
ML_STATUS   = ""
ML_FEATURES = ["tmean","rh","wind","kc","precipitation","soil_fc","soil_pwp","root_depth"]
_MODEL_PATH = pathlib.Path(_HERE) / "irrigation_xgboost_model_with_soil.pkl"

def _load_ml_model():
    global ML_MODEL, ML_OK, ML_STATUS
    try:
        import joblib, xgboost  # noqa
        if not _MODEL_PATH.exists():
            ML_STATUS = f"⚠️ Model file not found: {_MODEL_PATH.name}"; return
        ML_MODEL  = joblib.load(str(_MODEL_PATH))
        ML_OK     = True
        ML_STATUS = "✅ XGBoost model loaded"
    except Exception as e:
        ML_STATUS = f"⚠️ {e}"

_load_ml_model()

crop_params = {
    "Tomatoes":       {"ini":0.60,"mid":1.15,"end":0.80,"zr":0.70,"mad":0.40},
    "Cabbages":       {"ini":0.70,"mid":1.05,"end":0.95,"zr":0.50,"mad":0.45},
    "Maize":          {"ini":0.30,"mid":1.20,"end":0.60,"zr":1.00,"mad":0.55},
    "Beans":          {"ini":0.40,"mid":1.15,"end":0.75,"zr":0.60,"mad":0.45},
    "Rice":           {"ini":1.05,"mid":1.30,"end":0.95,"zr":0.50,"mad":0.20},
    "Potatoes":       {"ini":0.50,"mid":1.15,"end":0.75,"zr":0.60,"mad":0.35},
    "Onions":         {"ini":0.70,"mid":1.05,"end":0.95,"zr":0.30,"mad":0.30},
    "Peppers":        {"ini":0.60,"mid":1.10,"end":0.80,"zr":0.50,"mad":0.30},
    "Cassava":        {"ini":0.40,"mid":0.85,"end":0.70,"zr":1.00,"mad":0.60},
    "Bananas":        {"ini":0.50,"mid":1.00,"end":0.80,"zr":0.90,"mad":0.35},
    "Wheat":          {"ini":0.70,"mid":1.15,"end":0.40,"zr":1.00,"mad":0.55},
    "Sorghum":        {"ini":0.30,"mid":1.00,"end":0.55,"zr":1.00,"mad":0.55},
    "Groundnuts":     {"ini":0.40,"mid":1.15,"end":0.75,"zr":0.50,"mad":0.50},
    "Sweet Potatoes": {"ini":0.50,"mid":1.15,"end":0.75,"zr":1.00,"mad":0.65},
    "Sunflower":      {"ini":0.35,"mid":1.10,"end":0.35,"zr":1.00,"mad":0.45},
    "Soybeans":       {"ini":0.40,"mid":1.15,"end":0.50,"zr":0.60,"mad":0.50},
}

STAGE_LABELS = {"ini":"🌱 Initial","mid":"🌿 Mid-Season","end":"🍂 End-Season"}

WMO_DESC = {
    0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",
    51:"Light drizzle",53:"Moderate drizzle",55:"Dense drizzle",
    61:"Slight rain",63:"Moderate rain",65:"Heavy rain",
    80:"Slight showers",81:"Moderate showers",82:"Violent showers",
    95:"Thunderstorm",96:"Thunderstorm+hail",99:"Heavy thunderstorm+hail",
}

def wmo_icon(code):
    c = int(code or 0)
    if c == 0: return "☀️"
    if c in (1,2,3): return "🌤️"
    if 51 <= c <= 67: return "🌧️"
    if 80 <= c <= 82: return "🌦️"
    if 95 <= c <= 99: return "⛈️"
    return "🌥️"

st.markdown("""<style>
:root{--hb:#1a5fc8;--hg:#0b6b1b;--hr:#b81c1c;--bg:#f4f8f2;--sf:#fff;
  --bd:#dbe9db;--tx:#17301b;--gn:#0b6b1b;--gd:#075214;--gs:#e7f3e6;}
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{
  background:var(--bg)!important;color:var(--tx)!important;}
[data-testid="stHeader"],[data-testid="stToolbar"]{background:transparent!important;}
[data-testid="stMetric"]{background:var(--sf);border:1px solid var(--bd);
  border-radius:12px;padding:.5rem .7rem;}
[data-testid="stMetricLabel"] p{font-size:.76rem!important;margin:0!important;}
[data-testid="stMetricValue"] div{font-size:1.05rem!important;font-weight:700!important;}
div[data-baseweb="tab-list"]{gap:.3rem;background:transparent!important;}
button[data-baseweb="tab"]{background:var(--gs)!important;border:1px solid #b8d1b8!important;
  border-radius:999px!important;color:var(--gd)!important;padding:.35rem .75rem!important;font-size:.83rem!important;}
button[data-baseweb="tab"]>div{color:var(--gd)!important;font-weight:600;}
button[data-baseweb="tab"][aria-selected="true"]{background:var(--gn)!important;border-color:var(--gn)!important;}
button[data-baseweb="tab"][aria-selected="true"]>div{color:#fff!important;}
[data-baseweb="select"]>div,div[data-baseweb="input"]>div,
.stNumberInput>div>div,.stTextInput>div>div{
  background:var(--sf)!important;color:var(--tx)!important;border-color:#c9d9c9!important;}
.stButton>button,.stDownloadButton>button{background:var(--gn)!important;color:#fff!important;
  border:1px solid var(--gn)!important;border-radius:10px!important;}
.stButton>button:hover{background:var(--gd)!important;}
section[data-testid="stSidebar"]{background:#eef5ec!important;}
button[title="Fork this app"],[data-testid="stToolbarActionButtonIcon"],
[data-testid="stBottomBlockContainer"],.stDeployButton,footer{display:none!important;}
.block-container{padding-top:.8rem!important;}
.hx-outer{border-radius:20px;overflow:hidden;margin:0 0 10px 0;
  background:linear-gradient(90deg,var(--hb) 0%,var(--hb) 33.3%,
  var(--hg) 33.3%,var(--hg) 66.6%,var(--hr) 66.6%,var(--hr) 100%);padding:9px 9px 7px 9px;}
.hx-panel{background:#fff;border:2px solid #d0ddd0;border-radius:14px;padding:9px 16px 7px 16px;}
.hx-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.hx-wm{font-family:Georgia,serif;font-size:2.4rem;font-weight:700;line-height:1;letter-spacing:-1px;flex-shrink:0;}
.hx-wm .H{color:#1a5fc8;}.hx-wm .y{color:#0b6b1b;}.hx-wm .P{color:#b81c1c;}
.hx-wm .I{color:#1a5fc8;}.hx-wm .S{color:#0b6b1b;}
.hx-wm .Ug{color:#b81c1c;font-size:1.4rem;vertical-align:middle;margin-left:4px;}
.hx-sub{font-family:Georgia,serif;font-size:.95rem;flex:1 1 160px;color:#444;}
.hx-auth{margin:4px 0 0 4px;font-family:Georgia,serif;font-size:.78rem;color:#ddd;}
.hx-auth strong{color:#fff;}
.geo-panel{background:#fff;border:1.5px solid #b8d4f8;border-radius:14px;
  padding:10px 16px;margin:6px 0 10px 0;font-size:.86rem;color:#14324d;}
.geo-panel b{color:#1a5fc8;}
.geo-coord{font-family:monospace;background:#eef4ff;padding:2px 6px;border-radius:6px;font-size:.82rem;}
.mad-panel{background:#f0f4ff;border:1px solid #7b9ed9;border-radius:10px;padding:9px 14px;font-size:.85rem;margin:4px 0;}
.soil-panel{background:#fef9ee;border:1px solid #e0c97a;border-radius:10px;padding:8px 14px;font-size:.85rem;margin:4px 0;}
.kc-stage{background:#e8f6ea;border:1px solid #a8d8a8;border-radius:10px;padding:6px 14px;font-size:.85rem;color:#073f12;margin:4px 0;font-weight:600;}
.nir-box{background:#fff3cd;border:1px solid #ffc107;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;}
.iwr-box{background:#d4edda;border:1px solid #28a745;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;font-weight:600;}
.vol-box{background:#cfe2ff;border:1px solid #0d6efd;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;}
.no-irr-box{background:#e8f5e9;border:1px solid #43a047;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;}
.warn-raw{background:#fff8e1;border:1.5px solid #ffa000;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;font-weight:600;}
.warn-pwp{background:#ffebee;border:1.5px solid #c62828;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;font-weight:700;}
.warn-fc{background:#fff0f0;border:1px solid #d73027;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;}
.refill-box{background:#e8eaf6;border:1px solid #5c6bc0;border-radius:10px;padding:8px 14px;font-size:.87rem;margin:4px 0;}
.wb-summary{background:linear-gradient(135deg,#e8f5e9 0%,#e3f2fd 100%);border:1.5px solid #81c784;border-radius:14px;padding:12px 18px;margin:8px 0;font-size:.88rem;}
.past-hdr{background:linear-gradient(90deg,#0b6b1b 0%,#1a8a2e 100%);color:#fff;
  border-radius:10px 10px 0 0;padding:8px 16px;font-weight:700;font-size:.93rem;}
.today-hdr{background:linear-gradient(90deg,#1a5fc8 0%,#2a7fd4 100%);color:#fff;
  border-radius:10px 10px 0 0;padding:8px 16px;font-weight:700;font-size:.93rem;}
.live-dot{width:7px;height:7px;background:#22c55e;border-radius:50%;
  display:inline-block;margin-right:4px;animation:blink 1.4s infinite;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
</style>""", unsafe_allow_html=True)

if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = _time.time()
_el = _time.time() - st.session_state["last_refresh"]
if _el >= 3600:
    st.cache_data.clear()
    st.session_state["last_refresh"] = _time.time()
    st.rerun()
_rem = max(0, 3600 - int(_el))

st.markdown("""<div class="hx-outer"><div class="hx-panel"><div class="hx-row">
<span style="font-size:1.5rem;">&#127807;</span>
<span class="hx-wm">
  <span class="H">H</span><span class="y">y</span><span class="P">P</span>
  <span class="I">I</span><span class="S">S</span><span class="Ug"> Ug</span>
</span>
<span class="hx-sub">HydroPredict · IrrigSched · Uganda Multi-Location IWR v7.7</span>
</div></div>
<div class="hx-auth">by: Prosper <strong>BYARUHANGA</strong>
&nbsp;·&nbsp; HyPIS App v7.7 &nbsp;·&nbsp; FAO-56 PM · Soil-adjusted MAD · Uganda</div>
</div>""", unsafe_allow_html=True)

_now_str = datetime.now().strftime("%d %b %Y %H:%M")
st.caption(
    f'<span class="live-dot"></span> Live &middot; <b>{_now_str}</b>'
    f" &nbsp;·&nbsp; Auto-refresh in <b>{_rem//3600}h {(_rem%3600)//60}m</b>"
    f" &nbsp;·&nbsp; pandas {pd.__version__}",
    unsafe_allow_html=True)

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
st.sidebar.header("📍 Location — Uganda")
loc_name = st.sidebar.selectbox("Select District / Site",
                                list(LOCATIONS.keys()), index=0, key="loc_sel")
_lcoords = LOCATIONS[loc_name]

if loc_name == "Custom Location":
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

_dsoil   = DISTRICT_SOIL.get(loc_name, DISTRICT_SOIL["Custom Location"])
SITE_FC  = _dsoil["fc"];  SITE_PWP = _dsoil["pwp"]
SITE_TXT = _dsoil["texture"]; SITE_SRC = _dsoil["source"]

st.sidebar.markdown(f"**📍 {SITE_NAME}**  \n`Lat {LAT}°` · `Lon {LON}°` · `{ELEV} m`  \n"
                    f"[🗺️ Maps]({GMAPS_URL}) | [🛰️ Sat]({GMAPS_SAT})")
st.sidebar.markdown("---\n### 🌍 Soil Type")
st.sidebar.info(f"**Auto-loaded:** {SITE_TXT}  \nFC: **{SITE_FC*100:.0f}%** · PWP: **{SITE_PWP*100:.0f}%**  \nSource: {SITE_SRC}")

soil_override = st.sidebar.checkbox("Override soil type", value=False, key="soil_ov")
if soil_override:
    soil_sel_s = st.sidebar.selectbox("Soil Type", list(SOIL_OPTS.keys()), key="soil_sel_s")
    so = SOIL_OPTS[soil_sel_s]
    ACTIVE_FC = so["fc"]; ACTIVE_PWP = so["pwp"]; ACTIVE_TXT = soil_sel_s
else:
    ACTIVE_FC = SITE_FC; ACTIVE_PWP = SITE_PWP; ACTIVE_TXT = SITE_TXT

st.sidebar.markdown("---\n### 💧 Irrigation System")
IRRIG_SYSTEMS = {"Drip / Trickle":0.90,"Sprinkler":0.80,"Surface / Furrow":0.65,
                 "Flood":0.55,"Centre Pivot":0.85}
irrig_sys = st.sidebar.selectbox("System Type", list(IRRIG_SYSTEMS.keys()), index=0, key="irrig_sys")
Ef = IRRIG_SYSTEMS[irrig_sys]
st.sidebar.info(f"Efficiency **Ef = {Ef*100:.0f}%**  \nIWR (gross) = NIR ÷ {Ef:.2f}")

st.sidebar.markdown("---\n### 📐 Field & Pump")
area_ha   = st.sidebar.number_input("Field Area (ha)",       value=1.0, min_value=0.1, step=0.1, key="area_g")
pump_flow = st.sidebar.number_input("Pump Flow Rate (m³/hr)",value=5.0, min_value=0.5, step=0.5, key="pump_g")

if ML_OK:
    st.sidebar.markdown("---")
    st.sidebar.caption(f"🤖 ML model loaded (unused — FAO-56 rule-based decisions only)")

# ── GEO PANEL ─────────────────────────────────────────────────────────────────
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
    <a href="{GMAPS_SAT}" target="_blank">🛰️ Satellite</a><br>
    🌍 <b>Soil ({SITE_SRC}):</b> {ACTIVE_TXT} &nbsp;·&nbsp;
      FC = <b>{ACTIVE_FC*100:.0f}%</b> &nbsp;·&nbsp; PWP = <b>{ACTIVE_PWP*100:.0f}%</b>
    </div>""", unsafe_allow_html=True)

# ── FAO-56 PENMAN-MONTEITH ────────────────────────────────────────────────────
def et0_pm(tmax, tmin, rh_max, rh_min, u2, rs, elev=None, doy=None, lat_deg=None):
    if elev is None: elev = ELEV
    if lat_deg is None: lat_deg = LAT
    try:
        tmax=float(tmax); tmin=float(tmin)
        rh_max=max(0.,min(100.,float(rh_max))); rh_min=max(0.,min(100.,float(rh_min)))
        u2=max(0.,float(u2)); rs=max(0.,float(rs))
        doy=int(doy) if doy else int(datetime.now().strftime("%j"))
    except Exception: return 0.0
    Gsc=0.0820; tm=(tmax+tmin)/2.
    P=101.3*((293.-0.0065*elev)/293.)**5.26; gamma=0.000665*P
    esmax=0.6108*np.exp(17.27*tmax/(tmax+237.3))
    esmin=0.6108*np.exp(17.27*tmin/(tmin+237.3)); es=(esmax+esmin)/2.
    ea=max(0.,min(es,(rh_max/100.*esmin+rh_min/100.*esmax)/2.))
    estm=0.6108*np.exp(17.27*tm/(tm+237.3))
    Delta=4098.*estm/(tm+237.3)**2.
    b=2.*np.pi*doy/365.; dr=1.+0.033*np.cos(b)
    phi=np.radians(abs(lat_deg)); ds=0.409*np.sin(b-1.39)
    ws=np.arccos(np.clip(-np.tan(phi)*np.tan(ds),-1.,1.))
    Ra=max(0.,(24.*60./np.pi)*Gsc*dr*(ws*np.sin(phi)*np.sin(ds)+np.cos(phi)*np.cos(ds)*np.sin(ws)))
    Rso=max(0.,(0.75+2e-5*elev)*Ra); Rns=0.77*rs
    fcd=max(0.,min(1.,1.35*(rs/max(Rso,.1))-.35))
    Rnl=max(0.,_SIGMA*((tmax+273.16)**4+(tmin+273.16)**4)/2.*(0.34-0.14*np.sqrt(max(0.,ea)))*fcd)
    Rn=max(0.,Rns-Rnl)
    num=0.408*Delta*Rn+gamma*(900./(tm+273.))*u2*(es-ea)
    den=Delta+gamma*(1.+0.34*u2)
    return max(0.,round(num/den,3)) if den>0 else 0.

def et0_hargreaves(tmax, tmin, doy=None, lat_deg=None):
    if lat_deg is None: lat_deg = LAT
    doy=doy or int(datetime.now().strftime("%j"))
    b=2.*np.pi*doy/365.; dr=1.+0.033*np.cos(b); phi=np.radians(abs(lat_deg))
    ds=0.409*np.sin(b-1.39); ws=np.arccos(np.clip(-np.tan(phi)*np.tan(ds),-1.,1.))
    Ra=max(0.,(24.*60./np.pi)*0.0820*dr*(ws*np.sin(phi)*np.sin(ds)+np.cos(phi)*np.cos(ds)*np.sin(ws)))
    tm=(tmax+tmin)/2.; td=max(0.,tmax-tmin)
    return round(max(0.,0.0023*Ra*(tm+17.8)*td**0.5),3)

# ── SOIL WATER HELPERS ────────────────────────────────────────────────────────
def compute_taw(fc, pwp, zr):
    return (fc - pwp) * zr * 1000.

def compute_raw(taw, mad):
    return mad * taw

def eff_rain(p):
    p = float(p or 0)
    if p <= 0:    return 0.
    if p <= 25.4: return p*(125.-0.6*p)/125.
    return p - 12.7 - 0.1*p

def kc_from_stage(stage, crop):
    return crop_params[crop][stage]

def compute_volume(iwr_mm, area_ha):
    v = float(iwr_mm) * float(area_ha) * 10.
    return {"vol_m3": round(v,1), "vol_L": round(v*1000.,0)}

# ── DEPLETION STATUS — canonical FAO-56 ───────────────────────────────────────
def depletion_status(dr, raw, taw, ef=None):
    """
    v7.7 — canonical FAO-56 trigger (Dr > RAW → irrigate).
    Optional ef param: when provided, Monitor note includes pre-emptive volume.

    Thresholds:
      dr ≤ 0          → FC, no action
      0 < dr ≤ RAW×0.5 → comfortable, no action
      RAW×0.5 < dr ≤ RAW → Monitor — approaching MAD (show pre-emptive amount)
      dr > RAW        → IRRIGATE
      dr > TAW×0.85   → URGENT near wilting
    """
    if dr <= 0:
        return "🟢 Field Capacity", False, "Soil at FC — no irrigation needed"
    if dr <= raw * 0.5:
        return "✅ Adequate moisture", False, \
               f"Dr={dr:.1f} mm — soil water well within safe range, no irrigation"
    if dr <= raw:
        # v7.7: include pre-emptive irrigation amount when ef is known
        if ef is not None and ef > 0:
            pre_mm = round(dr / ef, 2)
            note = (f"Dr={dr:.1f} mm approaching RAW={raw:.1f} mm — "
                    f"pre-emptive irrigation: apply {pre_mm:.1f} mm gross "
                    f"(= {round(dr*10,1)} L/m² net) now to refill; "
                    f"or wait — irrigate tomorrow if no rain")
        else:
            note = (f"Dr={dr:.1f} mm approaching RAW={raw:.1f} mm — "
                    f"irrigate tomorrow if no rain")
        return ("🟡 Monitor — nearing MAD", False, note)
    if dr <= taw * 0.85:
        return ("⚠️ Below MAD — irrigate", True,
                f"Dr={dr:.1f} mm > RAW={raw:.1f} mm — crop stress beginning; irrigate now")
    return ("🔴 Near wilting point — URGENT", True,
            f"Dr={dr:.1f} mm ≈ TAW={taw:.1f} mm — immediate irrigation!")

# ── CORE DAILY WATER BALANCE (FAO-56 Dr approach) ────────────────────────────
def run_water_balance(daily_df, crop, soil, planting_ts, sm_pct,
                      Ef=0.80, stage_override=None, mad_eff=None):
    cp   = crop_params[crop]
    zr   = cp["zr"]
    mad  = mad_eff if mad_eff is not None else cp["mad"]
    taw  = compute_taw(soil["fc"], soil["pwp"], zr)
    raw  = compute_raw(taw, mad)

    theta = soil["pwp"] + (sm_pct/100.) * (soil["fc"] - soil["pwp"])
    theta = min(theta, soil["fc"])
    dr    = max(0., (soil["fc"] - theta) * zr * 1000.)

    df = daily_df.copy()

    if "rh_max" not in df.columns:
        rh_col = "rh_mean" if "rh_mean" in df.columns else ("rh" if "rh" in df.columns else None)
        if rh_col:
            df["rh_max"] = (df[rh_col] + 10).clip(upper=100)
            df["rh_min"] = (df[rh_col] - 10).clip(lower=0)
        else:
            df["rh_max"] = 70.; df["rh_min"] = 50.

    if stage_override:
        df["kc"] = crop_params[crop][stage_override]
    else:
        df["kc"] = df.index.map(
            lambda d: crop_params[crop]["ini"]
            if (d - planting_ts).days < 30
            else (crop_params[crop]["mid"]
                  if (d - planting_ts).days < 90
                  else crop_params[crop]["end"])
        )

    df["ET0"] = df.apply(lambda r: et0_pm(
        r["tmax"], r["tmin"], r["rh_max"], r["rh_min"],
        r["wind"], r["rs"],
        doy=r.name.timetuple().tm_yday, lat_deg=LAT, elev=ELEV,
    ), axis=1)
    df["ETc"] = (df["kc"] * df["ET0"]).round(3)

    prec_col = "precipitation" if "precipitation" in df.columns else (
               "precip" if "precip" in df.columns else None)
    if prec_col:
        df["Pe"] = df[prec_col].fillna(0.).apply(eff_rain)
    else:
        df["Pe"] = 0.
        prec_col = "precipitation"
        df[prec_col] = 0.

    dr_vals=[]; nir_vals=[]; iwr_vals=[]; status_vals=[]; sm_vals=[]; note_vals=[]

    for _, row in df.iterrows():
        pe_r   = row["Pe"];  etc_r  = row["ETc"]
        # Update depletion: subtract Pe (rain refill) then add ETc (crop use)
        dr_new = max(0., min(taw, dr - pe_r + etc_r))
        nir_day = round(max(0., etc_r - pe_r), 3)

        # FIX v7.6: pass only dr_new, raw, taw — rain already in dr_new
        # FIX v7.7: also pass Ef so Monitor note shows pre-emptive volume
        lbl, irrigate, note = depletion_status(dr_new, raw, taw, ef=Ef)

        if irrigate:
            iwr_gross = round(dr_new / max(Ef, 0.01), 3)
            dr = 0.  # root zone refilled to FC
        else:
            iwr_gross = 0.
            dr = dr_new

        sm_now = max(0., min(100., round((1. - dr/taw)*100, 1))) if taw > 0 else 70

        dr_vals.append(round(dr, 2))
        nir_vals.append(nir_day)
        iwr_vals.append(iwr_gross)
        status_vals.append(lbl)
        sm_vals.append(sm_now)
        note_vals.append(note)

    df["Dr_mm"]   = dr_vals
    df["SM_pct"]  = sm_vals
    df["NIR"]     = nir_vals
    df["IWR"]     = iwr_vals
    df["Status"]  = status_vals
    df["Note"]    = note_vals
    return df, taw, raw

# ── SOIL MOISTURE ESTIMATION — ERA5 10-day back-run ──────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def estimate_sm(fc, pwp, zr, lat=None, lon=None, elev=None, default_kc=1.0):
    """
    FIX v7.6: Initial SM changed from 70% → 50% of TAW.

    WHY: In Uganda's bi-modal rainy climate, starting at 70% SM (Dr=30%TAW)
    + 10 days of ERA5 rain kept Dr well below RAW for most crops.  The slider
    defaulted to 85-95% SM, meaning Dr_start was tiny and the 5-day window
    was never long enough to deplete past RAW → irrigation NEVER triggered.

    At 50% SM start (Dr=50%TAW), the ERA5 back-run correctly reflects dry
    spells: frequent light rain still keeps soil moist (correct), while 2+
    consecutive dry days raise Dr above RAW and trigger irrigation (also
    correct).  This matches the FAO-56 recommendation to initialise at 50%
    of TAW when actual soil moisture is unknown (Allen et al. 1998, §8.3.2).
    """
    lat = lat or LAT; lon = lon or LON; elev = elev or ELEV
    try:
        end_  = date.today() - timedelta(days=1)
        start_= end_ - timedelta(days=10)
        r = requests.get(
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}&start_date={start_}&end_date={end_}"
            f"&daily=precipitation_sum,temperature_2m_max,temperature_2m_min,"
            f"shortwave_radiation_sum,wind_speed_10m_max,"
            f"relative_humidity_2m_max,relative_humidity_2m_min&timezone={TIMEZONE}",
            timeout=12).json()
        d = r.get("daily",{}); dates = d.get("time",[])
        taw_ = (fc-pwp)*zr*1000.
        # FIX v7.6: start at 50% SM (Dr=50%TAW) instead of 70% SM (Dr=30%TAW)
        # This is the FAO-56 §8.3.2 default when actual SM is unknown.
        theta = pwp + 0.50*(fc-pwp)
        dr_   = max(0., (fc-theta)*zr*1000.)
        for i in range(len(dates)):
            tx=d["temperature_2m_max"][i]; tn=d["temperature_2m_min"][i]
            if tx is None or tn is None: continue
            rh_mx=d["relative_humidity_2m_max"][i] or 70
            rh_mn=d["relative_humidity_2m_min"][i] or 50
            wk=(d["wind_speed_10m_max"][i] or 7.2)/3.6*_W2M
            rs_i=d["shortwave_radiation_sum"][i] or 18.
            prec=d["precipitation_sum"][i] or 0.
            doy_i=datetime.strptime(dates[i],"%Y-%m-%d").timetuple().tm_yday
            et0_i=et0_pm(tx,tn,rh_mx,rh_mn,wk,rs_i,elev=elev,doy=doy_i,lat_deg=lat)
            etc_i = et0_i * default_kc
            pe_i  = eff_rain(prec)
            dr_   = max(0., min(taw_, dr_ - pe_i + etc_i))
        sm_est = int(max(0, min(100, (1-dr_/taw_)*100))) if taw_>0 else 60
        return sm_est
    except Exception:
        return 55  # conservative default: just above typical RAW

# ── EXCEL EXPORT HELPER ───────────────────────────────────────────────────────
def df_to_excel_bytes(df_dict: dict):
    if not OPENPYXL_OK:
        return None
    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for sheet, df in df_dict.items():
                df.to_excel(writer, sheet_name=sheet[:31])
        return buf.getvalue()
    except Exception:
        return None

def _show_download_buttons(dl_csv, dl_xlsx, fn_base, csv_key, xlsx_key):
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            "⬇️ Download CSV", dl_csv,
            f"{fn_base}.csv", "text/csv", key=csv_key)
    with dl_col2:
        if dl_xlsx is not None:
            st.download_button(
                "⬇️ Download Excel (.xlsx)", dl_xlsx,
                f"{fn_base}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=xlsx_key)
        else:
            st.info("Excel export unavailable on this Python version — CSV available above.")

# ── SM GAUGE CHART ────────────────────────────────────────────────────────────
def sm_gauge(sm_pct, raw_pct_of_taw, title="Soil Moisture"):
    color = "#22c55e" if sm_pct > 60 else ("#f59e0b" if sm_pct > 35 else "#ef4444")
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=sm_pct,
        delta={"reference": 100, "suffix":"%"},
        title={"text": title, "font":{"size":14}},
        gauge={
            "axis": {"range":[0,100], "ticksuffix":"%"},
            "bar":  {"color": color, "thickness":0.28},
            "steps":[
                {"range":[0, raw_pct_of_taw*50], "color":"#fee2e2"},
                {"range":[raw_pct_of_taw*50, raw_pct_of_taw*100], "color":"#fef3c7"},
                {"range":[raw_pct_of_taw*100, 100], "color":"#dcfce7"},
            ],
            "threshold":{"line":{"color":"#b91c1c","width":3},
                         "thickness":0.75,"value": raw_pct_of_taw*100},
        }
    ))
    fig.update_layout(height=220, margin=dict(l=20,r=20,t=40,b=10),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig

# ── WEATHER APIs ──────────────────────────────────────────────────────────────
_ch = f"{datetime.now().strftime('%Y%m%d%H')}_{LAT}_{LON}"

@st.cache_data(ttl=3600, show_spinner=False)
def get_current_weather(_k, lat, lon, elev):
    try:
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation,"
            f"wind_speed_10m,shortwave_radiation,weather_code"
            f"&daily=temperature_2m_max,temperature_2m_min,"
            f"relative_humidity_2m_max,relative_humidity_2m_min,"
            f"windspeed_10m_max,shortwave_radiation_sum,precipitation_sum,weather_code"
            f"&forecast_days=1&timezone={TIMEZONE}", timeout=12).json()
        cur=r.get("current",{}); d=r.get("daily",{})
        tmax=d.get("temperature_2m_max",[None])[0]; tmin=d.get("temperature_2m_min",[None])[0]
        rh_mx=d.get("relative_humidity_2m_max",[70])[0] or 70
        rh_mn=d.get("relative_humidity_2m_min",[50])[0] or 50
        wk=(d.get("windspeed_10m_max",[7.2])[0] or 7.2)/3.6*_W2M
        rs=d.get("shortwave_radiation_sum",[18.])[0] or 18.
        prec=d.get("precipitation_sum",[0.])[0] or 0.
        wcode=d.get("weather_code",[0])[0] or 0
        tc=cur.get("temperature_2m",25)
        tmax=tmax or tc+4; tmin=tmin or tc-4
        return {"tmax":round(tmax,1),"tmin":round(tmin,1),"rh_max":rh_mx,"rh_min":rh_mn,
                "rh_mean":round((rh_mx+rh_mn)/2,1),"wind":round(wk,3),"rs":round(rs,1),
                "precip":round(prec,1),"wcode":wcode,
                "description":WMO_DESC.get(int(wcode),f"Code {wcode}"),
                "source":"Open-Meteo ICON+GFS (live)"}
    except Exception: return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_forecast(_k, lat, lon, elev):
    try:
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,"
            f"relative_humidity_2m_max,relative_humidity_2m_min,"
            f"windspeed_10m_max,shortwave_radiation_sum,precipitation_sum,weather_code"
            f"&forecast_days=7&timezone={TIMEZONE}", timeout=12).json()
        d=r.get("daily",{})
        if not d: return None
        rows=[]
        for i in range(len(d["time"])):
            wk=(d["windspeed_10m_max"][i] or 7.2)/3.6*_W2M
            rh_mx=d["relative_humidity_2m_max"][i] or 70
            rh_mn=d["relative_humidity_2m_min"][i] or 50
            rows.append({"date":pd.to_datetime(d["time"][i]),
                "tmax":d["temperature_2m_max"][i] or 28,"tmin":d["temperature_2m_min"][i] or 16,
                "rh_max":rh_mx,"rh_min":rh_mn,"rh_mean":round((rh_mx+rh_mn)/2,1),
                "wind":round(wk,3),"rs":d["shortwave_radiation_sum"][i] or 18.,
                "precipitation":d["precipitation_sum"][i] or 0.,
                "weather_code":d["weather_code"][i] or 0})
        df=pd.DataFrame(rows).set_index("date")
        today_tz = pd.Timestamp.now(tz=TIMEZONE).normalize().tz_localize(None)
        return df[df.index >= today_tz].head(5)
    except Exception: return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_historical_weather(start_date, end_date, lat, lon):
    try:
        r = requests.get(
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&daily=temperature_2m_max,temperature_2m_min,"
            f"relative_humidity_2m_max,relative_humidity_2m_min,"
            f"windspeed_10m_max,shortwave_radiation_sum,precipitation_sum"
            f"&timezone={TIMEZONE}", timeout=25).json()
        d=r.get("daily",{})
        if not d: return None
        rh_mx=d.get("relative_humidity_2m_max",[]); rh_mn=d.get("relative_humidity_2m_min",[])
        df=pd.DataFrame({
            "date":pd.to_datetime(d["time"]),
            "tmax":[x or 28 for x in d["temperature_2m_max"]],
            "tmin":[x or 16 for x in d["temperature_2m_min"]],
            "rh_max":[(a or 70) for a in rh_mx],"rh_min":[(a or 50) for a in rh_mn],
            "rh_mean":[((a or 70)+(b or 50))/2 for a,b in zip(rh_mx,rh_mn)],
            "wind":[(x or 7.2)/3.6*_W2M for x in d["windspeed_10m_max"]],
            "rs":[x or 18. for x in d["shortwave_radiation_sum"]],
            "precipitation":[x or 0. for x in d["precipitation_sum"]],
        }).set_index("date")
        df["rh"]=df["rh_mean"]
        return df.dropna(subset=["tmax","tmin"])
    except Exception: return None

# ── FETCH TODAY'S LIVE WEATHER ────────────────────────────────────────────────
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
# TAB 1 — TODAY'S IWR
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.header(f"📊 Today's IWR — {SITE_NAME}")
    st.caption(
        f"📡 {wx['source'] if wx else 'Weather unavailable'} · "
        f"FAO-56 PM v7.6 · Trigger: Dr > RAW (soil depleted past MAD) · "
        f"Rain already accounted for in depletion update · All values per 24-hour day"
    )

    if wx:
        st.success(
            f"✅ **{wx['description']}** · 📡 Forecast Rain: **{lp} mm** · "
            f"Lat {LAT}° / Lon {LON}° / {ELEV} m")
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("🌡️ Tmax / Tmin",  f"{lt}°C / {ln}°C")
        c2.metric("💧 RH min–max",   f"{lr_min:.0f}–{lr_max:.0f}%", f"Mean {lr_mean:.0f}%")
        c3.metric("🌬️ Wind (2 m)",   f"{lw:.2f} m/s")
        c4.metric("☀️ Solar Rad",    f"{ls:.1f} MJ/m²/d")
        c5.metric("🌧️ Forecast Rain", f"{lp:.1f} mm", "📡 predicted")
    else:
        st.warning("⚠️ Weather unavailable — using default values")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🌱 Crop & Growth Stage")
        cr1    = st.selectbox("Crop", list(crop_params.keys()), key="cr1")
        cp1    = crop_params[cr1]
        stage1 = st.radio("Growing Stage", list(STAGE_LABELS.keys()),
                          format_func=lambda x: STAGE_LABELS[x],
                          key="stg1", horizontal=True)
        kc1    = kc_from_stage(stage1, cr1)

        mad_crop  = cp1["mad"]
        mad_adj   = adjust_mad_for_soil(mad_crop, ACTIVE_TXT)
        mad_delta = mad_adj - mad_crop

        st.markdown(
            f'<div class="kc-stage">Kc ({STAGE_LABELS[stage1]}) = <b>{kc1:.3f}</b> '
            f'· Zr = {cp1["zr"]:.2f} m</div>', unsafe_allow_html=True)

        _taw_p = compute_taw(ACTIVE_FC, ACTIVE_PWP, cp1["zr"])
        _raw_p = compute_raw(_taw_p, mad_adj)
        st.markdown(
            f'<div class="mad-panel">'
            f'📐 <b>FAO-56 Irrigation Thresholds</b><br>'
            f'TAW = <b>{_taw_p:.1f} mm</b> &nbsp;·&nbsp; '
            f'Crop MAD = <b>{mad_crop:.2f}</b>'
            f'{"" if mad_delta==0 else f" → soil-adjusted to <b>{mad_adj:.2f}</b>"}<br>'
            f'RAW (trigger) = <b>{_raw_p:.1f} mm</b> &nbsp;·&nbsp; '
            f'Irrigate when Dr &gt; <b>{_raw_p:.1f} mm</b><br>'
            f'<small>🟢 Dr≤{_raw_p*0.5:.1f} OK · 🟡 Dr≤{_raw_p:.1f} Monitor · '
            f'⚠️ Dr&gt;{_raw_p:.1f} Irrigate · 🔴 Dr&gt;{_taw_p*0.85:.1f} Urgent</small></div>',
            unsafe_allow_html=True)

        st.markdown(
            f"| Stage | Ini Kc | Mid Kc | End Kc | MAD |\n|---|---|---|---|---|\n"
            f"| {cr1} | {cp1['ini']} | {cp1['mid']} | {cp1['end']} | {mad_crop:.2f} → **{mad_adj:.2f}** |")

    with col2:
        st.subheader("🌦️ Weather Input (24-hour period)")
        tmax_in = st.number_input("Tmax (°C)",            value=float(lt),      key="t1")
        tmin_in = st.number_input("Tmin (°C)",            value=float(ln),      key="t2")
        rh_in   = st.number_input("RH mean (%)",          value=float(lr_mean), min_value=0., max_value=100., key="rh1")
        wind_in = st.number_input("Wind 2m (m/s)",        value=float(lw),      min_value=0., key="w1")
        rs_in   = st.number_input("Solar Rad (MJ/m²/d)",  value=float(ls),      min_value=0., key="rs1")

        prec_in = lp
        st.info(f"🌧️ **Rainfall (Open-Meteo forecast): {prec_in:.1f} mm**")

        soil_obj = {"fc": ACTIVE_FC, "pwp": ACTIVE_PWP}
        _sm_def  = estimate_sm(ACTIVE_FC, ACTIVE_PWP, cp1["zr"], LAT, LON, ELEV)
        # v7.7: quick-set buttons for season simulation
        st.markdown("**🌡️ Season scenario:**")
        _t1, _t2, _t3 = st.columns(3)
        if _t1.button("☀️ Dry (30%)",  key="sm1_dry", use_container_width=True):
            st.session_state["sm1_val"] = 30
        if _t2.button("🌤️ Mod (55%)", key="sm1_mod", use_container_width=True):
            st.session_state["sm1_val"] = 55
        if _t3.button("🌧️ Wet (80%)", key="sm1_wet", use_container_width=True):
            st.session_state["sm1_val"] = 80
        _sm1_v = st.session_state.get("sm1_val", _sm_def)
        sm_pct = st.slider("Current Soil Moisture (% of FC)", 0, 100, _sm1_v, key="sm1")

        if sm_pct >= 95:
            st.markdown(
                '<div class="warn-fc">⚠️ <b>Soil near Field Capacity</b> — '
                'do NOT irrigate; waterlogging risk.</div>', unsafe_allow_html=True)

        st.markdown(
            f'<div class="soil-panel">🌍 <b>{ACTIVE_TXT}</b> · '
            f'FC={ACTIVE_FC*100:.0f}% · PWP={ACTIVE_PWP*100:.0f}%<br>'
            f'💧 {irrig_sys} · Ef={Ef*100:.0f}% · '
            f'{area_ha} ha · {pump_flow} m³/hr</div>', unsafe_allow_html=True)

    if st.button("🧮 Calculate Today's IWR + Past 5 Days Water History",
                 type="primary", use_container_width=True, key="calc1"):

        mad_eff1 = adjust_mad_for_soil(cp1["mad"], ACTIVE_TXT)
        taw1     = compute_taw(ACTIVE_FC, ACTIVE_PWP, cp1["zr"])
        raw1     = compute_raw(taw1, mad_eff1)

        rh_mx1  = min(100., rh_in+10.); rh_mn1 = max(0., rh_in-10.)
        et0_fao = et0_pm(tmax_in, tmin_in, rh_mx1, rh_mn1, wind_in, rs_in, doy=_doy)
        et0_h   = et0_hargreaves(tmax_in, tmin_in, doy=_doy)
        etc1    = round(kc1 * et0_fao, 3)
        pe1     = eff_rain(prec_in)
        nir1_day = round(max(0., etc1 - pe1), 3)

        theta1   = ACTIVE_PWP + (sm_pct/100.)*(ACTIVE_FC-ACTIVE_PWP)
        theta1   = min(theta1, ACTIVE_FC)
        dr_start = max(0., (ACTIVE_FC - theta1)*cp1["zr"]*1000.)
        dr_today = max(0., min(taw1, dr_start - pe1 + etc1))

        # FIX v7.6: simplified call — no Pe argument
        # FIX v7.7: pass Ef so Monitor note includes pre-emptive volume
        status_lbl, irrigate, note_today = depletion_status(dr_today, raw1, taw1, ef=Ef)

        if irrigate:
            nir1       = round(dr_today, 3)
            iwr1       = round(nir1/max(Ef,0.01), 3)
            dr_after   = 0.
        else:
            nir1       = 0.
            iwr1       = 0.
            dr_after   = dr_today

        vol1   = compute_volume(iwr1, area_ha)
        mins1  = round(vol1["vol_m3"]/pump_flow*60,1) if pump_flow>0 and iwr1>0 else 0
        sm_now = max(0., min(100., round((1-dr_today/taw1)*100, 1))) if taw1>0 else 70
        sm_aft = max(0., min(100., round((1-dr_after/taw1)*100, 1))) if taw1>0 else 100

        irr_to_fc = round(dr_today / max(Ef,0.01), 3)
        vol_to_fc = compute_volume(irr_to_fc, area_ha)

        raw_pct_fc = int((1 - raw1/taw1)*100) if taw1>0 else 50
        st.markdown(
            f'<div class="wb-summary">'
            f'<b>🌊 Water Balance Summary</b> — {cr1} · {ACTIVE_TXT}<br>'
            f'TAW = <b>{taw1:.1f} mm</b> &nbsp;|&nbsp; '
            f'RAW threshold = <b>{raw1:.1f} mm</b> (MAD={mad_eff1:.2f}) &nbsp;|&nbsp; '
            f'ET₀ PM = <b>{et0_fao:.2f} mm/d</b> &nbsp;|&nbsp; '
            f'ETc = <b>{etc1:.2f} mm/d</b><br>'
            f'Pe = <b>{pe1:.2f} mm</b> &nbsp;|&nbsp; '
            f'NIR = <b>{nir1_day:.2f} mm/d</b> &nbsp;|&nbsp; '
            f'Dr = <b>{dr_today:.2f} mm</b> &nbsp;|&nbsp; '
            f'SM = <b>{sm_now:.1f}% of FC</b><br>'
            f'<b>Decision: {status_lbl}</b></div>',
            unsafe_allow_html=True)

        gcol1, gcol2 = st.columns([1,2])
        with gcol1:
            st.plotly_chart(
                sm_gauge(sm_now, 1-(raw1/taw1) if taw1>0 else 0.5,
                         f"SM% of FC — {cr1}"),
                use_container_width=True)
        with gcol2:
            if "🔴" in status_lbl:
                st.markdown(
                    f'<div class="warn-pwp">🔴 <b>SOIL AT/NEAR WILTING POINT</b> — '
                    f'Dr = {dr_today:.1f} mm ≈ TAW = {taw1:.1f} mm — '
                    f'Immediate irrigation required!</div>', unsafe_allow_html=True)
            elif "⚠️" in status_lbl:
                st.markdown(
                    f'<div class="warn-raw">⚠️ <b>Soil moisture below MAD threshold</b> — '
                    f'Dr = {dr_today:.1f} mm > RAW = {raw1:.1f} mm — '
                    f'Schedule irrigation today.</div>', unsafe_allow_html=True)
            elif "🟡" in status_lbl:
                # v7.7: compute and display pre-emptive irrigation amount
                _pre_mm  = round(dr_today / max(Ef, 0.01), 2)
                _pre_vol = compute_volume(_pre_mm, area_ha)
                _pre_min = round(_pre_vol["vol_m3"]/pump_flow*60, 1) if pump_flow > 0 else 0
                st.markdown(
                    f'<div class="nir-box">🟡 <b>Monitor — approaching MAD threshold</b><br>'
                    f'Dr = {dr_today:.1f} mm · RAW = {raw1:.1f} mm · not yet depleted past threshold<br>'
                    f'<b>Pre-emptive irrigation (to refill now):</b> '
                    f'<b>{_pre_mm:.2f} mm gross</b> = '
                    f'<b>{_pre_vol["vol_m3"]:.1f} m³</b> = '
                    f'<b>{_pre_vol["vol_L"]:,.0f} L</b> for {area_ha} ha '
                    f'· ⏱️ <b>{_pre_min} min</b> pump time<br>'
                    f'<small>You may irrigate now (pre-emptively) OR wait — '
                    f'mandatory if Dr > RAW tomorrow without rain</small></div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div class="no-irr-box">{status_lbl}<br>{note_today}</div>',
                    unsafe_allow_html=True)

            st.markdown(
                f'<div class="nir-box">📐 <b>Daily NIR = {nir1_day:.2f} mm</b> '
                f'= ETc ({etc1:.2f}) − Pe ({pe1:.2f}) &nbsp;·&nbsp; '
                f'Dr = <b>{dr_today:.2f} mm</b> &nbsp;·&nbsp; '
                f'TAW = {taw1:.1f} mm · RAW = {raw1:.1f} mm</div>',
                unsafe_allow_html=True)

        # ── PAST 5 DAYS CONTEXT ───────────────────────────────────────────────
        st.markdown("---")
        st.markdown('<div class="past-hdr">📅 PAST 5 DAYS — Soil & Crop Water History</div>',
                    unsafe_allow_html=True)
        st.caption("Showing how soil moisture and crop water need evolved BEFORE today.")

        past_end_d   = date.today() - timedelta(days=1)
        past_start_d = past_end_d - timedelta(days=4)
        with st.spinner("📡 Fetching ERA5 past 5 days…"):
            hist_ctx = get_historical_weather(str(past_start_d), str(past_end_d), LAT, LON)

        past_r = None
        if hist_ctx is not None and not hist_ctx.empty:
            past_r, _, _ = run_water_balance(
                hist_ctx, cr1, soil_obj,
                pd.Timestamp(date.today()-timedelta(days=45)),
                sm_pct, Ef, stage_override=stage1, mad_eff=mad_eff1)
            past_r["Vol_m3"] = past_r["IWR"].apply(
                lambda x: compute_volume(x,area_ha)["vol_m3"])

            def _style_row(val):
                v = str(val)
                if "⚠️" in v or "🔴" in v: return "background:#ffe0e0;font-weight:bold"
                if "🌧️" in v: return "background:#e0f7fa"
                if "🟢" in v or "✅" in v: return "background:#e8f5e9"
                if "🟡" in v: return "background:#fff9c4"
                return ""

            rows_past = []
            for dt, row in past_r.iterrows():
                dr_val   = float(row["Dr_mm"])
                irw_val  = float(row["IWR"])
                status_v = row["Status"]
                # v7.7: for Monitor rows, compute pre-emptive gross irrigation
                if "🟡" in str(status_v) and dr_val > 0:
                    pre_mm  = round(dr_val / max(Ef, 0.01), 2)
                    pre_vol = round(pre_mm * area_ha * 10, 1)
                    pre_str = f"{pre_mm:.2f} mm → {pre_vol:.1f} m³ (pre-emptive)"
                elif irw_val > 0:
                    pre_str = f"{irw_val:.2f} mm → {round(irw_val*area_ha*10,1):.1f} m³ (triggered)"
                else:
                    pre_str = "—"
                rows_past.append({
                    "Date":               dt.strftime("%Y-%m-%d (%a)"),
                    "Rain mm":            round(float(row.get("precipitation",0.)),1),
                    "ETc mm/d":           round(float(row["ETc"]),2),
                    "Pe mm":              round(float(row["Pe"]),2),
                    "Dr mm":              round(dr_val,2),
                    "SM %FC":             round(float(row["SM_pct"]),1),
                    "NIR mm":             round(float(row["NIR"]),2),
                    "IWR mm":             round(irw_val,2),
                    "Vol m³":             round(float(row["Vol_m3"]),1),
                    "💧 Action":          pre_str,
                    "Status":             status_v,
                    "Note":               row["Note"],
                })
            past_df = pd.DataFrame(rows_past).set_index("Date")

            # FIX v7.6: explicit format for every numeric column → no 6-decimal display
            _num_fmt = {
                "Rain mm":  "{:.1f}",
                "ETc mm/d": "{:.2f}",
                "Pe mm":    "{:.2f}",
                "Dr mm":    "{:.2f}",
                "SM %FC":   "{:.1f}",
                "NIR mm":   "{:.2f}",
                "IWR mm":   "{:.2f}",
                "Vol m³":   "{:.1f}",
            }
            styled = _styler_map(past_df.style, _style_row, subset=["Status"])
            styled = styled.format(_num_fmt, na_rep="—")

            st.markdown(
                f'<div class="mad-panel">'
                f'📐 <b>Reference thresholds — {cr1} / {ACTIVE_TXT}</b><br>'
                f'TAW = <b>{taw1:.1f} mm</b> · RAW = <b>{raw1:.1f} mm</b> · '
                f'MAD = <b>{mad_eff1:.2f}</b> (soil-adjusted from {cp1["mad"]:.2f})<br>'
                f'<small>Irrigate when Dr &gt; RAW. NIR = ETc – Pe (daily crop deficit).</small></div>',
                unsafe_allow_html=True)

            st.dataframe(styled, use_container_width=True)

            fig_ctx = go.Figure()
            fig_ctx.add_scatter(
                x=past_r.index.strftime("%a %d"),
                y=past_r["Dr_mm"].astype(float),
                mode="lines+markers+text", name="Dr Deficit (mm)",
                text=past_r["Dr_mm"].round(1).astype(str)+" mm",
                textposition="top center",
                line=dict(color="#e6550d",width=2.5), marker=dict(size=9))
            fig_ctx.add_bar(
                x=past_r.index.strftime("%a %d"),
                y=past_r["precipitation"].astype(float),
                name="Rain mm", marker_color="#1a5fc8", opacity=0.4, yaxis="y2")
            fig_ctx.add_bar(
                x=past_r.index.strftime("%a %d"),
                y=past_r["NIR"].astype(float),
                name="NIR mm/d", marker_color="#0b6b1b", opacity=0.5, yaxis="y2")
            fig_ctx.add_hline(y=raw1, line_dash="dash", line_color="#756bb1",
                              annotation_text=f"RAW={raw1:.1f} mm — irrigate above this")
            fig_ctx.add_hline(y=taw1, line_dash="dot",  line_color="#d73027",
                              annotation_text=f"TAW={taw1:.1f} mm — wilting risk")
            fig_ctx.update_layout(
                title="Past 5 Days: Root-Zone Depletion (Dr) vs Thresholds",
                yaxis=dict(title="Depletion Dr (mm)"),
                yaxis2=dict(title="mm/d",overlaying="y",side="right"),
                barmode="group", legend=dict(x=0,y=1.12,orientation="h"),
                height=320, plot_bgcolor="#f4f8f2", paper_bgcolor="#f4f8f2")
            st.plotly_chart(fig_ctx, use_container_width=True)
        else:
            st.info("ℹ️ ERA5 past data unavailable — archive may lag 3–5 days.")

        # ── TODAY'S RESULT ────────────────────────────────────────────────────
        st.markdown('<div class="today-hdr">💧 TODAY\'S IRRIGATION DECISION</div>',
                    unsafe_allow_html=True)

        st.info(
            f"📍 **{SITE_NAME}** · Lat {LAT}° · Lon {LON}° · {ELEV} m  \n"
            f"🌱 **{cr1}** · Stage: **{STAGE_LABELS[stage1]}** · Kc = **{kc1:.3f}**  \n"
            f"🌍 Soil: **{ACTIVE_TXT}** · FC={ACTIVE_FC*100:.0f}% · PWP={ACTIVE_PWP*100:.0f}%  \n"
            f"📐 TAW = **{taw1:.1f} mm** · RAW (trigger) = **{raw1:.1f} mm** "
            f"(crop MAD {cp1['mad']:.2f} → soil-adj. **{mad_eff1:.2f}**)"
        )

        r1,r2,r3,r4,r5,r6,r7 = st.columns(7)
        r1.metric("ET₀ PM mm/d",   f"{et0_fao:.2f}")
        r2.metric("ET₀ H mm/d",    f"{et0_h:.2f}")
        r3.metric("ETc mm/d",      f"{etc1:.2f}", f"Kc={kc1:.3f}")
        r4.metric("Pe mm",         f"{pe1:.2f}")
        r5.metric("NIR mm/d",      f"{nir1_day:.2f}", "ETc − Pe")
        r6.metric("Dr mm",         f"{dr_today:.2f}", f"RAW={raw1:.1f}")
        r7.metric("SM % FC",       f"{sm_now:.1f}%", f"→{sm_aft:.1f}% after")

        st.markdown("---")

        if irrigate:
            st.markdown(
                f'<div class="refill-box">🔧 <b>Refill to FC:</b> '
                f'NIR (net) = <b>{nir1:.2f} mm</b> · '
                f'IWR (gross, Ef={Ef:.0%}) = <b>{iwr1:.2f} mm</b><br>'
                f'Full refill gross = <b>{irr_to_fc:.2f} mm</b> = '
                f'{vol_to_fc["vol_m3"]:.1f} m³ = {vol_to_fc["vol_L"]:,.0f} L</div>',
                unsafe_allow_html=True)
            st.markdown(
                f'<div class="iwr-box">💧 <b>IWR (Gross) = {iwr1:.2f} mm/day</b> '
                f'&nbsp;·&nbsp; {irrig_sys} (Ef={Ef*100:.0f}%)</div>',
                unsafe_allow_html=True)
            st.markdown(
                f'<div class="vol-box">🪣 <b>Volume to apply:</b> '
                f'<b>{vol1["vol_m3"]:.1f} m³</b> = <b>{vol1["vol_L"]:,.0f} litres</b> '
                f'for <b>{area_ha} ha</b>'
                f' &nbsp;·&nbsp; ⏱️ Pump time: <b>{mins1} min</b> at {pump_flow} m³/hr<br>'
                f'After irrigation → SM: <b>{sm_aft:.1f}% of FC</b> ✅</div>',
                unsafe_allow_html=True)
            st.warning(
                f"⚠️ **Irrigate today** — Dr = {dr_today:.2f} mm > RAW = {raw1:.1f} mm  \n"
                f"Apply **{iwr1:.2f} mm gross** = {vol1['vol_m3']:.1f} m³ "
                f"({vol1['vol_L']:,.0f} L) across {area_ha} ha.")
        else:
            st.markdown(
                f'<div class="no-irr-box">✅ <b>No irrigation needed today</b><br>'
                f'{note_today}<br>Volume = 0 m³ · Pump time = 0 min</div>',
                unsafe_allow_html=True)
            if pe1 >= etc1:
                st.success(
                    f"🌧️ **Rain covers crop demand today.**  \n"
                    f"Pe = {pe1:.2f} mm ≥ ETc = {etc1:.2f} mm → NIR = 0, IWR = 0.")
            else:
                st.success(
                    f"✅ **Soil moisture adequate — no irrigation needed.**  \n"
                    f"Dr = {dr_today:.2f} mm ≤ RAW = {raw1:.1f} mm. "
                    f"NIR = {nir1_day:.2f} mm/d — soil buffer covers this today.")

        # ── TODAY'S SUMMARY TABLE — FIX v7.6: use .style.format() ────────────
        st.markdown("#### 📋 Today's Daily Summary")
        today_tbl = pd.DataFrame([{
            "Rain used mm":         round(prec_in,1),
            "ETc mm/d":             round(etc1,2),
            "Pe mm":                round(pe1,2),
            "Dr mm":                round(dr_today,2),
            "SM %FC":               round(sm_now,1),
            "NIR mm":               round(nir1_day,2),
            "IWR gross mm":         round(iwr1,2),
            "Vol m³":               round(vol1["vol_m3"],1),
            "Vol L":                int(vol1["vol_L"]),
            "Pump min":             round(mins1,1),
            "ET₀ PM mm/d":          round(et0_fao,2),
            "ET₀ H mm/d":           round(et0_h,2),
            "Kc":                   round(kc1,3),
            "TAW mm":               round(taw1,1),
            "RAW mm":               round(raw1,1),
            "MAD adj":              round(mad_eff1,3),
            "Status":               status_lbl,
        }], index=[datetime.today().strftime("%Y-%m-%d (%a)")])

        # explicit format — no 6-decimal columns
        _today_fmt = {
            "Rain used mm":  "{:.1f}",
            "ETc mm/d":      "{:.2f}",
            "Pe mm":         "{:.2f}",
            "Dr mm":         "{:.2f}",
            "SM %FC":        "{:.1f}",
            "NIR mm":        "{:.2f}",
            "IWR gross mm":  "{:.2f}",
            "Vol m³":        "{:.1f}",
            "Vol L":         "{:.0f}",
            "Pump min":      "{:.1f}",
            "ET₀ PM mm/d":   "{:.2f}",
            "ET₀ H mm/d":    "{:.2f}",
            "Kc":            "{:.3f}",
            "TAW mm":        "{:.1f}",
            "RAW mm":        "{:.1f}",
            "MAD adj":       "{:.3f}",
        }
        st.dataframe(today_tbl.style.format(_today_fmt, na_rep="—"),
                     use_container_width=True)

        # ── DOWNLOADS ─────────────────────────────────────────────────────────
        if past_r is not None:
            combined_rows = []
            for dt, row in past_r.iterrows():
                combined_rows.append({
                    "Date": dt.strftime("%Y-%m-%d"), "Period": "Past",
                    "Rain mm": round(float(row.get("precipitation",0.)),1),
                    "ETc mm/d": round(float(row["ETc"]),2),
                    "Pe mm": round(float(row["Pe"]),2),
                    "Dr mm": round(float(row["Dr_mm"]),2),
                    "SM %FC": round(float(row["SM_pct"]),1),
                    "NIR mm": round(float(row["NIR"]),2),
                    "IWR mm": round(float(row["IWR"]),2),
                    "Vol m³": round(float(row["Vol_m3"]),1),
                    "Status": row["Status"],
                })
            combined_rows.append({
                "Date": datetime.today().strftime("%Y-%m-%d"), "Period": "TODAY",
                "Rain mm": round(prec_in,1), "ETc mm/d": round(etc1,2),
                "Pe mm": round(pe1,2), "Dr mm": round(dr_today,2),
                "SM %FC": round(sm_now,1), "NIR mm": round(nir1_day,2),
                "IWR mm": round(iwr1,2), "Vol m³": round(vol1["vol_m3"],1),
                "Status": status_lbl,
            })
            combined_df = pd.DataFrame(combined_rows).set_index("Date")
            dl_csv  = combined_df.to_csv().encode()
            dl_xlsx = df_to_excel_bytes({"Past5Days+Today": combined_df, "TodaySummary": today_tbl})
        else:
            dl_csv  = today_tbl.to_csv().encode()
            dl_xlsx = df_to_excel_bytes({"TodaySummary": today_tbl})

        _fn = f"HyPIS_{SITE_NAME.replace(' ','_')}_{datetime.today().strftime('%Y%m%d')}"
        _show_download_buttons(dl_csv, dl_xlsx, _fn, "dl_today_csv", "dl_today_xlsx")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — 5-DAY FORECAST
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.header(f"☁️ 5-Day IWR Forecast — {SITE_NAME}")
    st.caption(
        f"FAO-56 PM · Trigger: Dr > RAW · Ef={Ef*100:.0f}% ({irrig_sys})"
    )

    fc_c1, fc_c2 = st.columns(2)
    with fc_c1:
        cr2    = st.selectbox("Crop", list(crop_params.keys()), key="cr2")
        cp2    = crop_params[cr2]
        stage2 = st.radio("Growing Stage", list(STAGE_LABELS.keys()),
                          format_func=lambda x: STAGE_LABELS[x], key="stg2", horizontal=True)
        kc2    = kc_from_stage(stage2, cr2)
        mad2   = adjust_mad_for_soil(cp2["mad"], ACTIVE_TXT)
        st.markdown(f'<div class="kc-stage">Kc = <b>{kc2:.3f}</b> · '
                    f'MAD = {cp2["mad"]:.2f} → soil-adj. <b>{mad2:.2f}</b></div>',
                    unsafe_allow_html=True)
    with fc_c2:
        planting2 = st.date_input("Planting Date",
                                  value=datetime.today().date()-timedelta(days=45), key="plant2")
        soil2   = {"fc":ACTIVE_FC,"pwp":ACTIVE_PWP}
        # v7.7: quick-set buttons for dry/wet season simulation
        st.markdown("**🌡️ Season scenario (sets starting soil moisture):**")
        _sc1, _sc2, _sc3 = st.columns(3)
        if _sc1.button("☀️ Dry (30%)",  key="sm2_dry",  use_container_width=True):
            st.session_state["sm2_val"] = 30
        if _sc2.button("🌤️ Mod (55%)", key="sm2_mod",  use_container_width=True):
            st.session_state["sm2_val"] = 55
        if _sc3.button("🌧️ Wet (80%)", key="sm2_wet",  use_container_width=True):
            st.session_state["sm2_val"] = 80
        _sm2_default = st.session_state.get("sm2_val",
                        estimate_sm(ACTIVE_FC,ACTIVE_PWP,cp2["zr"],LAT,LON,ELEV))
        sm_pct2 = st.slider("Starting SM (% of FC)", 0, 100, _sm2_default, key="sm2")
        st.markdown(f'<div class="soil-panel">🌍 <b>{ACTIVE_TXT}</b> · '
                    f'FC={ACTIVE_FC*100:.0f}% · PWP={ACTIVE_PWP*100:.0f}%<br>'
                    f'<small>💡 <b>Uganda rainy season (Mar–May, Oct–Nov):</b> soil stays moist '
                    f'→ use ☀️ Dry to simulate dry season or irrigation planning.</small></div>',
                    unsafe_allow_html=True)

    if st.button("📥 Get 5-Day Forecast", type="primary",
                 use_container_width=True, key="fc_btn"):
        with st.spinner("Fetching forecast…"):
            daily = get_forecast(_ch, LAT, LON, ELEV)

        if daily is None or daily.empty:
            st.warning("⚠️ Forecast unavailable.")
        else:
            daily_r, taw2, raw2 = run_water_balance(
                daily, cr2, soil2, pd.Timestamp(planting2),
                sm_pct2, Ef, stage_override=stage2, mad_eff=mad2)

            daily_r["Vol_m3"]  = daily_r["IWR"].apply(lambda x: compute_volume(x,area_ha)["vol_m3"])
            daily_r["Vol_L"]   = daily_r["IWR"].apply(lambda x: float(compute_volume(x,area_ha)["vol_L"]))
            daily_r["PumpMin"] = daily_r["Vol_m3"].apply(
                lambda v: round(float(v)/pump_flow*60,1) if pump_flow>0 and float(v)>0 else 0)

            nd     = (daily_r["IWR"]>0).sum()
            rain_d = (daily_r.get("precipitation", pd.Series(0,index=daily_r.index))>1).sum()

            st.info(
                f"📐 TAW = **{taw2:.1f} mm** · RAW = **{raw2:.1f} mm** "
                f"(MAD {cp2['mad']:.2f}→{mad2:.2f})  \n"
                f"Irrigation fires when Dr > {raw2:.1f} mm")

            if nd > 0:
                st.warning(
                    f"🗓️ **{nd} irrigation event(s)** · {rain_d} rainy day(s)  \n"
                    f"Total IWR = **{daily_r['IWR'].sum():.1f} mm** · "
                    f"Vol = **{daily_r['Vol_m3'].sum():.1f} m³**")
            else:
                rain_total = daily_r.get("precipitation", pd.Series(0,index=daily_r.index)).sum()
                if sm_pct2 >= 65:
                    st.success(
                        f"✅ **No irrigation needed over next 5 days.**  \n"
                        f"Soil starts at **{sm_pct2}% SM** (Dr well below RAW={raw2:.1f} mm) "
                        f"and forecast rain ({rain_total:.1f} mm total) keeps it replenished.  \n"
                        f"⚠️ **This is correct behaviour for Uganda's rainy season (Mar–May, Oct–Nov).**  \n"
                        f"To see irrigation needs during a dry spell: press **☀️ Dry (30%)** above and re-run.")
                else:
                    st.success(
                        f"✅ **No irrigation needed over next 5 days.**  \n"
                        f"({rain_d} rainy day(s) + Dr remains below RAW={raw2:.1f} mm throughout)")

            cols2 = st.columns(len(daily_r))
            for i,(dt,row) in enumerate(daily_r.iterrows()):
                icon = wmo_icon(row.get("weather_code",0))
                lbl  = f"💧 {row['IWR']:.1f} mm" if row["IWR"]>0 else f"{icon} No irrig"
                dlt  = (f"🪣 {row['Vol_m3']:.1f}m³ · ⏱{row['PumpMin']}min"
                        if row["IWR"]>0
                        else f"Dr={row['Dr_mm']:.1f}mm · NIR={row['NIR']:.1f}mm")
                cols2[i].metric(dt.strftime("%a %d"), lbl, dlt)

            st.subheader("📋 5-Day Forecast Table")
            cols_fc = ["tmax","tmin","rh_mean","precipitation","Pe",
                       "ET0","kc","ETc","Dr_mm","SM_pct",
                       "NIR","IWR","Vol_m3","Vol_L","PumpMin","Status"]
            tb2 = daily_r[[c for c in cols_fc if c in daily_r.columns]].copy()
            tb2.rename(columns={
                "tmax":"Tmax °C","tmin":"Tmin °C","rh_mean":"RH %",
                "precipitation":"Rain mm","Pe":"Pe mm",
                "ET0":"ET₀ mm/d","kc":"Kc","ETc":"ETc mm/d",
                "Dr_mm":"Dr mm","SM_pct":"SM %FC",
                "NIR":"NIR mm","IWR":"IWR mm",
                "Vol_m3":"Vol m³","Vol_L":"Vol L",
                "PumpMin":"Pump min","Status":"Status",
            }, inplace=True)
            tb2.index = tb2.index.strftime("%Y-%m-%d (%a)")
            _tb2_fmt = {
                "Tmax °C": "{:.1f}", "Tmin °C": "{:.1f}", "RH %":    "{:.0f}",
                "Rain mm": "{:.1f}", "Pe mm":   "{:.2f}", "ET₀ mm/d":"{:.2f}",
                "Kc":      "{:.3f}", "ETc mm/d":"{:.2f}", "Dr mm":   "{:.2f}",
                "SM %FC":  "{:.1f}", "NIR mm":  "{:.2f}", "IWR mm":  "{:.2f}",
                "Vol m³":  "{:.1f}", "Vol L":   "{:.0f}", "Pump min":"{:.1f}",
            }
            st.dataframe(tb2.style.format(_tb2_fmt, na_rep="—"), use_container_width=True)

            fig2d = go.Figure()
            fig2d.add_scatter(x=daily_r.index.strftime("%a %d"), y=daily_r["Dr_mm"].astype(float),
                              mode="lines+markers+text", name="Dr mm",
                              text=daily_r["Dr_mm"].round(1).astype(str),
                              textposition="top center",
                              line=dict(color="#e6550d",width=2))
            if "precipitation" in daily_r.columns:
                fig2d.add_bar(x=daily_r.index.strftime("%a %d"),
                              y=daily_r["precipitation"].astype(float),
                              name="Rain mm", marker_color="#1a5fc8",opacity=0.4,yaxis="y2")
            fig2d.add_bar(x=daily_r.index.strftime("%a %d"), y=daily_r["IWR"].astype(float),
                          name="IWR mm", marker_color="#17a2b8",opacity=0.7,yaxis="y2")
            fig2d.add_bar(x=daily_r.index.strftime("%a %d"), y=daily_r["NIR"].astype(float),
                          name="NIR mm/d", marker_color="#0b6b1b",opacity=0.5,yaxis="y2")
            fig2d.add_hline(y=raw2,line_dash="dash",line_color="#756bb1",
                            annotation_text=f"RAW={raw2:.1f} mm")
            fig2d.add_hline(y=taw2,line_dash="dot", line_color="#d73027",
                            annotation_text=f"TAW={taw2:.1f} mm")
            fig2d.update_layout(
                title=f"5-Day: Dr, NIR, IWR — {SITE_NAME}",
                yaxis=dict(title="Dr (mm)"),
                yaxis2=dict(title="mm/d",overlaying="y",side="right"),
                barmode="group",legend=dict(x=0,y=1.12,orientation="h"),
                height=400,plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2")
            st.plotly_chart(fig2d, use_container_width=True)

            dl_fc_csv  = tb2.to_csv().encode()
            dl_fc_xlsx = df_to_excel_bytes({"5DayForecast": tb2})
            _fn_fc = f"HyPIS_forecast_{SITE_NAME.replace(' ','_')}_{date.today()}"
            _show_download_buttons(dl_fc_csv, dl_fc_xlsx, _fn_fc, "dl_fc_csv", "dl_fc_xlsx")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — HISTORICAL ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.header(f"📅 Historical IWR Analysis — {SITE_NAME}")
    st.caption(
        f"ERA5 Archive · FAO-56 PM · Dr > RAW trigger · "
        f"Ef={Ef*100:.0f}% ({irrig_sys})")

    st.info(
        f"📍 **{SITE_NAME}** · `{LAT}°, {LON}°, {ELEV} m`  \n"
        f"🌍 Soil: **{ACTIVE_TXT}** · FC={ACTIVE_FC*100:.0f}% · PWP={ACTIVE_PWP*100:.0f}%  \n"
        f"*(ERA5 may lag 3–5 days — yesterday is the closest available)*")

    pc1,pc2,pc3 = st.columns(3)
    yesterday = date.today()-timedelta(days=1)
    if pc1.button("📅 Yesterday",    use_container_width=True, key="h_yest"):
        st.session_state["h_start"]=yesterday; st.session_state["h_end"]=yesterday
    if pc2.button("📅 Last 7 Days",  use_container_width=True, key="h_7"):
        st.session_state["h_start"]=yesterday-timedelta(days=6); st.session_state["h_end"]=yesterday
    if pc3.button("📅 Last 30 Days", use_container_width=True, key="h_30"):
        st.session_state["h_start"]=yesterday-timedelta(days=29); st.session_state["h_end"]=yesterday

    h_start = st.session_state.get("h_start", yesterday-timedelta(days=6))
    h_end   = st.session_state.get("h_end",   yesterday)
    st.markdown(f"**Period:** `{h_start}` → `{h_end}` ({(h_end-h_start).days+1} days)")

    hc1,hc2 = st.columns(2)
    with hc1:
        cr3    = st.selectbox("Crop",list(crop_params.keys()),key="cr3")
        cp3    = crop_params[cr3]
        stage3 = st.radio("Growing Stage",list(STAGE_LABELS.keys()),
                          format_func=lambda x:STAGE_LABELS[x],key="stg3",horizontal=True)
        kc3    = kc_from_stage(stage3, cr3)
        mad3   = adjust_mad_for_soil(cp3["mad"], ACTIVE_TXT)
        st.markdown(f'<div class="kc-stage">Kc={kc3:.3f} · MAD {cp3["mad"]:.2f}→{mad3:.2f}</div>',
                    unsafe_allow_html=True)
    with hc2:
        planting3 = st.date_input("Planting Date",value=date.today()-timedelta(days=45),key="plant3")
        soil3  = {"fc":ACTIVE_FC,"pwp":ACTIVE_PWP}
        # v7.7: quick-set buttons
        st.markdown("**🌡️ Season scenario:**")
        _h1, _h2, _h3 = st.columns(3)
        if _h1.button("☀️ Dry (30%)",  key="sm3_dry", use_container_width=True):
            st.session_state["sm3_val"] = 30
        if _h2.button("🌤️ Mod (55%)", key="sm3_mod", use_container_width=True):
            st.session_state["sm3_val"] = 55
        if _h3.button("🌧️ Wet (80%)", key="sm3_wet", use_container_width=True):
            st.session_state["sm3_val"] = 80
        _sm3_def = estimate_sm(ACTIVE_FC,ACTIVE_PWP,cp3["zr"],LAT,LON,ELEV)
        sm3 = st.slider("Starting SM (% of FC)", 0, 100,
                        st.session_state.get("sm3_val", _sm3_def), key="sm3")
        st.markdown(f'<div class="soil-panel">🌍 <b>{ACTIVE_TXT}</b> · '
                    f'FC={ACTIVE_FC*100:.0f}% · PWP={ACTIVE_PWP*100:.0f}%</div>',
                    unsafe_allow_html=True)

    if st.button("📥 Retrieve Historical Data", type="primary",
                 use_container_width=True, key="hist_btn"):
        with st.spinner("Fetching ERA5 archive…"):
            hist = get_historical_weather(str(h_start),str(h_end),LAT,LON)

        if hist is None or hist.empty:
            st.warning("⚠️ No ERA5 data for this period.")
        else:
            hist_r, taw3, raw3 = run_water_balance(
                hist,cr3,soil3,pd.Timestamp(planting3),sm3,Ef,
                stage_override=stage3, mad_eff=mad3)

            hist_r["Vol_m3"]  = hist_r["IWR"].apply(lambda x: compute_volume(x,area_ha)["vol_m3"])
            hist_r["Vol_L"]   = hist_r["IWR"].apply(lambda x: float(compute_volume(x,area_ha)["vol_L"]))
            hist_r["ET0_H"]   = [et0_hargreaves(r["tmax"],r["tmin"],
                                  doy=int(d.strftime("%j")),lat_deg=LAT)
                                 for d,r in hist_r.iterrows()]
            hist_r["PumpMin"] = hist_r["Vol_m3"].apply(
                lambda v: round(float(v)/pump_flow*60,1) if pump_flow>0 and float(v)>0 else 0)

            st.info(
                f"📐 TAW = **{taw3:.1f} mm** · RAW = **{raw3:.1f} mm** "
                f"(MAD {cp3['mad']:.2f}→{mad3:.2f})  \n"
                f"Irrigation fires when Dr > {raw3:.1f} mm")

            m1,m2,m3,m4,m5,m6,m7 = st.columns(7)
            m1.metric("📆 Days",       len(hist_r))
            m2.metric("🌧️ Rain Total", f"{hist_r['precipitation'].sum():.1f} mm")
            m3.metric("💧 NIR Total",  f"{hist_r['NIR'].sum():.1f} mm")
            m4.metric("💧 IWR Total",  f"{hist_r['IWR'].sum():.1f} mm")
            m5.metric("🪣 Vol Total",  f"{hist_r['Vol_m3'].sum():.1f} m³")
            m6.metric("🚿 Irrig Days", str((hist_r["IWR"]>0).sum()))
            m7.metric("🌧️ Rain Days",  str((hist_r["precipitation"]>1).sum()))

            st.subheader("📋 Historical Table")
            ht = hist_r[[
                "tmax","tmin","rh_mean","precipitation","Pe",
                "ET0","ET0_H","kc","ETc","Dr_mm","SM_pct",
                "NIR","IWR","Vol_m3","Vol_L","PumpMin","Status","Note"
            ]].copy()
            ht.columns = [
                "Tmax °C","Tmin °C","RH %","Rain mm","Pe mm",
                "ET₀ PM mm","ET₀ H mm","Kc","ETc mm/d",
                "Dr mm","SM %FC",
                "NIR mm","IWR mm","Vol m³","Vol L",
                "Pump min","Status","Decision Note"
            ]
            ht.index = ht.index.strftime("%Y-%m-%d (%a)")
            _ht_fmt = {
                "Tmax °C":   "{:.1f}", "Tmin °C":   "{:.1f}", "RH %":      "{:.0f}",
                "Rain mm":   "{:.1f}", "Pe mm":      "{:.2f}",
                "ET₀ PM mm": "{:.2f}", "ET₀ H mm":  "{:.2f}", "Kc":        "{:.3f}",
                "ETc mm/d":  "{:.2f}", "Dr mm":      "{:.2f}", "SM %FC":    "{:.1f}",
                "NIR mm":    "{:.2f}", "IWR mm":     "{:.2f}",
                "Vol m³":    "{:.1f}", "Vol L":      "{:.0f}", "Pump min":  "{:.1f}",
            }
            st.dataframe(ht.style.format(_ht_fmt, na_rep="—"), use_container_width=True)

            fig3d = go.Figure()
            fig3d.add_scatter(x=hist_r.index,y=hist_r["Dr_mm"].astype(float),mode="lines",
                              name="Dr mm",line=dict(color="#e6550d",width=1.5))
            fig3d.add_bar(x=hist_r.index,y=hist_r["precipitation"].astype(float),
                          name="Rain mm",marker_color="#1a5fc8",opacity=0.35,yaxis="y2")
            fig3d.add_bar(x=hist_r.index,y=hist_r["IWR"].astype(float),
                          name="IWR mm",marker_color="#17a2b8",opacity=0.7,yaxis="y2")
            fig3d.add_bar(x=hist_r.index,y=hist_r["NIR"].astype(float),
                          name="NIR mm/d",marker_color="#0b6b1b",opacity=0.4,yaxis="y2")
            fig3d.add_hline(y=raw3,line_dash="dash",line_color="#756bb1",
                            annotation_text=f"RAW={raw3:.1f} mm — irrigate above")
            fig3d.add_hline(y=taw3,line_dash="dot", line_color="#d73027",
                            annotation_text=f"TAW={taw3:.1f} mm — wilting risk")
            fig3d.update_layout(
                title="Historical Dr, NIR, IWR vs Thresholds",
                yaxis=dict(title="Dr (mm)"),
                yaxis2=dict(title="mm",overlaying="y",side="right"),
                barmode="overlay",legend=dict(x=0,y=1.12,orientation="h"),
                height=420,plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2")
            st.plotly_chart(fig3d, use_container_width=True)

            fig3e = go.Figure()
            fig3e.add_scatter(x=hist_r.index,y=hist_r["ET0"].astype(float),name="ET₀ PM",
                              mode="lines",line=dict(color="#1a5fc8",width=1.5))
            fig3e.add_scatter(x=hist_r.index,y=hist_r["ET0_H"].astype(float),
                              name="ET₀ Hargreaves",
                              mode="lines",line=dict(color="#b81c1c",width=1,dash="dot"))
            fig3e.add_scatter(x=hist_r.index,y=hist_r["ETc"].astype(float),name="ETc",
                              mode="lines",line=dict(color="#0b6b1b",width=1.5,dash="dash"))
            fig3e.update_layout(title="ET₀ & ETc",yaxis_title="mm/d",
                                height=300,plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2",
                                legend=dict(x=0,y=1.12,orientation="h"))
            st.plotly_chart(fig3e, use_container_width=True)

            irrig_d = hist_r[hist_r["IWR"]>0]
            if not irrig_d.empty:
                fig3v = go.Figure()
                fig3v.add_bar(x=irrig_d.index,y=irrig_d["Vol_m3"].astype(float),
                              name="Volume m³",marker_color="#0d6efd",
                              text=irrig_d["Vol_m3"].round(1).astype(str)+" m³",
                              textposition="outside")
                fig3v.update_layout(
                    title=f"Irrigation Volume (m³) — {area_ha} ha",
                    yaxis_title="m³",height=280,
                    plot_bgcolor="#f4f8f2",paper_bgcolor="#f4f8f2")
                st.plotly_chart(fig3v, use_container_width=True)
            else:
                st.success("✅ No irrigation events in this period — "
                           "rain and soil moisture were sufficient throughout.")

            dl_h_csv  = ht.to_csv().encode()
            dl_h_xlsx = df_to_excel_bytes({"Historical": ht})
            _fn_h = f"HyPIS_hist_{SITE_NAME.replace(' ','_')}_{h_start}_{h_end}"
            _show_download_buttons(dl_h_csv, dl_h_xlsx, _fn_h, "dl_hist_csv", "dl_hist_xlsx")

# ── FOOTER ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"HyPIS Ug v7.7 · {SITE_NAME} ({LAT}°, {LON}°, {ELEV} m) · "
    f"ERA5+ICON+GFS (Open-Meteo) · FAO-56 Penman-Monteith · "
    f"Soil-adjusted MAD (FAO-56 ±5–10% texture) · "
    f"Trigger: Dr > RAW (canonical FAO-56 §8) · "
    f"HWSD v2 Soil · pandas {pd.__version__} · Byaruhanga Prosper"
)
