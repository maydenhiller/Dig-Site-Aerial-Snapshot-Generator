import streamlit as st
import pandas as pd
import zipfile
import io
import requests
from PIL import Image, ImageDraw, ImageFont

st.title("📑 Dig Site Aerial Snapshot Generator")

# --- Load Mapbox token from Streamlit secrets ---
MAPBOX_TOKEN = st.secrets["mapbox"]["token"]

uploaded_file = st.file_uploader("Upload Excel file (.xlsx or .xlsm)", type=["xlsx", "xlsm"])

# --- Fetch and annotate satellite image from Mapbox ---
def fetch_satellite_image(lat, lon, label):
    # 6.69" wide × 3.25" high ≈ 640 × 312 pixels
    width_px = 640
    height_px = 312

    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{lon},{lat},18,0/{width_px}x{height_px}?access_token={MAPBOX_TOKEN}"
    )
    response = requests.get(url)
    if response.status_code != 200:
        return None

    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    draw = ImageDraw.Draw(image)

    # Font setup
    font_size = 28
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()

    label = label.upper()

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
    except AttributeError:
        text_width, text_height = draw.textlength(label, font=font), font_size

    # Position label above/right of dot
    label_x = center_x + dot_radius + 6
    label_y = center_y - text_height - 6

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
    # Load Excel file
    xls = pd.ExcelFile(uploaded_file)

    # Only include sheets that start with "dig" but are not exactly "dig list"
    dig_tabs = [
        sheet for sheet in xls.sheet_names
        if sheet.lower().startswith("dig") and sheet.lower() != "dig list"
    ]

    if not dig_tabs:
        st.error("No valid Dig tabs found (excluding 'Dig list').")
    else:
        st.success(f"Found {len(dig_tabs)} Dig tabs: {', '.join(dig_tabs)}")

        if st.button("Generate Aerial Images"):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                for sheet in dig_tabs:
                    df = pd.read_excel(uploaded_file, sheet_name=sheet, header=None)

                    try:
                        lat = float(df.iloc[12, 9])  # J13
                        lon = float(df.iloc[13, 9])  # J14
                    except Exception as e:
                        st.warning(f"Skipping {sheet}: could not read coordinates ({e})")
                        continue

                    image_data = fetch_satellite_image(lat, lon, sheet)
                    if image_data:
                        zip_file.writestr(f"{sheet}.jpg", image_data)

            zip_buffer.seek(0)
            st.download_button(
                label="📦 Download Dig Site Images ZIP",
                data=zip_buffer,
                file_name="dig_site_images.zip",
                mime="application/zip"
            )

# --- Attribution footer ---
st.caption("© Mapbox © OpenStreetMap contributors")
