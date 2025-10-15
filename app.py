import streamlit as st
import io, zipfile, requests, traceback
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="Dig Site Aerial Snapshot Generator")
st.title("📑 Dig Site Aerial Snapshot Generator")

# --- Mapbox token ---
MAPBOX_TOKEN = None
try:
    MAPBOX_TOKEN = st.secrets["mapbox"]["token"]
except Exception:
    pass
if not MAPBOX_TOKEN:
    MAPBOX_TOKEN = st.sidebar.text_input("Mapbox access token", type="password")

# --- Mapbox fetch ---
def fetch_satellite_image(lat, lon, label, token):
    width_px = 1280
    height_px = 624  # sharper resolution

    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{lon},{lat},18,0/{width_px}x{height_px}?access_token={token}"
    )
    try:
        resp = requests.get(url, timeout=20)
    except Exception as e:
        st.error(f"Request error for {label}: {e}")
        return None

    if resp.status_code != 200:
        st.error(f"Mapbox error for {label}: {resp.status_code} {resp.text[:200]}")
        return None

    try:
        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        st.error(f"PIL error for {label}: {e}")
        return None

    draw = ImageDraw.Draw(image)

    # Yellow dot at center
    cx, cy = image.width // 2, image.height // 2
    draw.ellipse([(cx-6, cy-6), (cx+6, cy+6)], fill="yellow", outline="black")

    # Label
    label = label.upper()
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        font = ImageFont.load_default()

    try:
        bbox = font.getbbox(label)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = draw.textlength(label, font=font), 28

    lx, ly = cx + 12, cy - th - 6
    draw.rectangle([lx-4, ly-4, lx+tw+4, ly+th+4], fill="white", outline="black")
    draw.text((lx, ly), label, fill="black", font=font)

    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    buf.seek(0)
    return buf.read()

# --- Main logic ---
uploaded_file = st.file_uploader("Upload Excel file (.xlsx or .xlsm)", type=["xlsx","xlsm"])
if uploaded_file and MAPBOX_TOKEN:
    try:
        uploaded_file.seek(0)
        wb = load_workbook(io.BytesIO(uploaded_file.read()), data_only=True, read_only=True)
        dig_tabs = [s for s in wb.sheetnames if s.lower().startswith("dig") and s.lower() != "dig list"]

        if not dig_tabs:
            st.error("No valid Dig tabs found (excluding 'Dig list').")
        else:
            st.success(f"Found {len(dig_tabs)} Dig tabs")
            if st.button("Generate Aerial Images"):
                zip_buffer = io.BytesIO()
                success_count, fail_count = 0, 0
                progress = st.progress(0)

                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    for i, sheet in enumerate(dig_tabs):
                        try:
                            ws = wb[sheet]
                            lat_val, lon_val = ws["AR15"].value, ws["AS15"].value
                            lat, lon = float(lat_val), float(lon_val)

                            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                                st.warning(f"Skipping {sheet}: out-of-bounds coords ({lat}, {lon})")
                                fail_count += 1
                                continue

                            img = fetch_satellite_image(lat, lon, sheet, MAPBOX_TOKEN)
                            if img:
                                zip_file.writestr(f"{sheet}.jpg", img)
                                success_count += 1
                            else:
                                fail_count += 1
                        except Exception as e:
                            st.error(f"Error processing {sheet}: {e}")
                            st.code(traceback.format_exc())
                            fail_count += 1

                        progress.progress((i+1)/len(dig_tabs))

                zip_buffer.seek(0)
                st.download_button(
                    f"📦 Download {success_count} Images (failed {fail_count})",
                    data=zip_buffer,
                    file_name="dig_site_images.zip",
                    mime="application/zip"
                )
    except Exception as e:
        st.error(f"Top-level error: {e}")
        st.code(traceback.format_exc())

st.caption("© Mapbox © OpenStreetMap contributors")
