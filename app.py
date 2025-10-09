# app.py
import streamlit as st
import zipfile
import io
import requests
from PIL import Image, ImageDraw, ImageFont
from openpyxl import load_workbook

st.title("📑 Dig Site Aerial Snapshot Generator")

# --- Mapbox token handling (secrets fallback) ---
def get_mapbox_token():
    try:
        return st.secrets["mapbox"]["token"]
    except Exception:
        return None

MAPBOX_TOKEN = get_mapbox_token()
if MAPBOX_TOKEN is None:
    MAPBOX_TOKEN = st.sidebar.text_input("Mapbox access token", type="password")
    st.sidebar.info("Enter your Mapbox token here since none was found in st.secrets under [mapbox]['token'].")

# --- UI: file upload ---
uploaded_file = st.file_uploader("Upload Excel file (.xlsx or .xlsm)", type=["xlsx", "xlsm"])

# --- Fetch and annotate satellite image from Mapbox ---
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
    except Exception:
        return None
    if resp.status_code != 200:
        return None

    image = Image.open(io.BytesIO(resp.content)).convert("RGB")
    draw = ImageDraw.Draw(image)

    # Font setup
    font_size = 28
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
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
    except Exception:
        try:
            text_width = draw.textlength(label, font=font)
            text_height = font_size
        except Exception:
            text_width, text_height = 100, font_size

    # Position label above/right of dot
    label_x = center_x + dot_radius + 6
    label_y = center_y - text_height - 6

    # Ensure label box stays in bounds
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
    draw.rectangle(box_coords, fill="white", outline="black")

    # Draw text
    draw.text((label_x, label_y), label, fill="black", font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    buffer.seek(0)
    return buffer.read()

# --- Main logic ---
if uploaded_file:
    if not MAPBOX_TOKEN:
        st.error("No Mapbox token provided. Set st.secrets['mapbox']['token'] or enter it in the sidebar.")
    else:
        try:
            uploaded_file.seek(0)
            wb = load_workbook(io.BytesIO(uploaded_file.read()), data_only=True)
        except Exception as e:
            st.error(f"Failed to open workbook: {e}")
            wb = None

        if wb:
            # Filter sheets: start with "dig" and not exactly "dig list"
            dig_tabs = [
                s for s in wb.sheetnames
                if s.lower().startswith("dig") and s.lower() != "dig list"
            ]

            if not dig_tabs:
                st.error("No valid Dig tabs found (excluding 'Dig list').")
            else:
                st.success(f"Found {len(dig_tabs)} Dig tabs.")

                if st.button("Generate Aerial Images"):
                    zip_buffer = io.BytesIO()
                    images_written = 0
                    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                        for sheet in dig_tabs:
                            ws = wb[sheet]

                            # Read AR15 and AS15 directly (numeric values)
                            lat_val = ws["AR15"].value
                            lon_val = ws["AS15"].value

                            if lat_val is None or lon_val is None:
                                st.warning(f"Skipping {sheet}: AR15/AS15 are empty")
                                continue

                            # Clean possible strings with leading/trailing spaces
                            try:
                                lat = float(str(lat_val).strip())
                                lon = float(str(lon_val).strip())
                            except Exception as e:
                                st.warning(f"Skipping {sheet}: could not convert AR15/AS15 to float ({e})")
                                continue

                            # Basic sanity bounds
                            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                                st.warning(f"Skipping {sheet}: coordinates out of bounds (lat {lat}, lon {lon})")
                                continue

                            image_data = fetch_satellite_image(lat, lon, sheet, MAPBOX_TOKEN)
                            if image_data:
                                zip_file.writestr(f"{sheet}.jpg", image_data)
                                images_written += 1
                            else:
                                st.warning(f"Skipping {sheet}: failed to fetch Mapbox image")

                    if images_written > 0:
                        zip_buffer.seek(0)
                        st.download_button(
                            label=f"📦 Download {images_written} Dig Site Images ZIP",
                            data=zip_buffer,
                            file_name="dig_site_images.zip",
                            mime="application/zip"
                        )
                    else:
                        st.error("No images generated. Check AR15/AS15 values and Mapbox token.")

# --- Attribution footer ---
st.caption("© Mapbox © OpenStreetMap contributors")
