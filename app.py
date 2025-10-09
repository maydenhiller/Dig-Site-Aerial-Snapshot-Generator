# app.py
import streamlit as st
import zipfile
import io
import traceback
import requests
from PIL import Image, ImageDraw, ImageFont
from openpyxl import load_workbook

st.title("📑 Dig Site Aerial Snapshot Generator (with debugger)")

# --- Debug logger ---
debug = []
def log(msg):
    debug.append(str(msg))
    st.write(msg)

def log_exception(ctx, exc):
    tb = traceback.format_exc()
    debug.append(f"[ERROR] {ctx}: {exc}\n{tb}")
    st.error(f"{ctx}: {exc}")
    st.code(tb, language="text")

# --- Mapbox token handling ---
def get_mapbox_token():
    try:
        token = st.secrets["mapbox"]["token"]
        log("Loaded Mapbox token from st.secrets['mapbox']['token']")
        return token
    except Exception as e:
        log(f"No Mapbox token in secrets: {e}")
        return None

MAPBOX_TOKEN = get_mapbox_token()
if MAPBOX_TOKEN is None:
    MAPBOX_TOKEN = st.sidebar.text_input("Mapbox access token", type="password")
    if MAPBOX_TOKEN:
        log("Using Mapbox token provided via sidebar input")
    else:
        st.sidebar.info("Enter your Mapbox token here since none was found in st.secrets under [mapbox]['token'].")

uploaded_file = st.file_uploader("Upload Excel file (.xlsx or .xlsm)", type=["xlsx", "xlsm"])

# --- Mapbox fetch + annotate ---
def fetch_satellite_image(lat, lon, label, token):
    width_px = 640   # 6.69" wide
    height_px = 312  # 3.25" high
    zoom = 18
    bearing = 0

    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{lon},{lat},{zoom},{bearing}/{width_px}x{height_px}?access_token={token}"
    )
    try:
        resp = requests.get(url, timeout=20)
    except Exception as e:
        log(f"Mapbox request error for {label}: {e}")
        return None

    if resp.status_code != 200:
        log(f"Mapbox non-200 for {label}: status={resp.status_code}, body={resp.text[:200]}")
        return None

    try:
        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        log(f"PIL open error for {label}: {e}")
        return None

    draw = ImageDraw.Draw(image)

    # Font setup
    font_size = 28
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception as e:
        log(f"Arial font not found, fallback to default: {e}")
        font = ImageFont.load_default()

    label = (label or "").upper().strip()

    # Center point
    center_x = image.width // 2
    center_y = image.height // 2

    # Yellow dot at center
    dot_radius = 6
    draw.ellipse(
        [
            (center_x - dot_radius, center_y - dot_radius),
            (center_x + dot_radius, center_y + dot_radius)
        ],
        fill="yellow",
        outline="black"
    )

    # Measure text size
    try:
        bbox = font.getbbox(label)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except Exception as e:
        log(f"font.getbbox failed, using textlength: {e}")
        try:
            text_width = draw.textlength(label, font=font)
            text_height = font_size
        except Exception as e2:
            log(f"textlength failed, using defaults: {e2}")
            text_width, text_height = 100, font_size

    # Position label above/right of dot
    label_x = center_x + dot_radius + 6
    label_y = center_y - text_height - 6

    # Keep in bounds
    label_x = max(6, min(label_x, image.width - text_width - 12))
    label_y = max(6, min(label_y, image.height - text_height - 12))

    # White background with black border
    box_margin = 6
    box_coords = [
        label_x - box_margin,
        label_y - box_margin,
        label_x + text_width + box_margin,
        label_y + text_height + box_margin
    ]
