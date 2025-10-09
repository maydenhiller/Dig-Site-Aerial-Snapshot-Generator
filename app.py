import streamlit as st
import io, zipfile, traceback, requests
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="Dig Site Aerial Snapshot Generator")
st.title("📑 Dig Site Aerial Snapshot Generator")

try:
    # --- Mapbox token ---
    MAPBOX_TOKEN = None
    try:
        MAPBOX_TOKEN = st.secrets["mapbox"]["token"]
    except Exception:
        pass
    if not MAPBOX_TOKEN:
        MAPBOX_TOKEN = st.sidebar.text_input("Mapbox access token", type="password")
    if not MAPBOX_TOKEN:
        st.warning("No Mapbox token provided. Add it in secrets or paste it in the sidebar.")

    # --- File upload ---
    uploaded_file = st.file_uploader("Upload Excel file (.xlsx or .xlsm)", type=["xlsx","xlsm"])

    # --- Mapbox fetch ---
    def fetch_satellite_image(lat, lon, label, token):
        url = (
            f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
            f"{lon},{lat},18,0/640x312?access_token={token}"
        )
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            st.error(f"Mapbox error {resp.status_code}: {resp.text[:200]}")
            return None
        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
        draw = ImageDraw.Draw(image)
        # Yellow dot at center
        cx, cy = image.width//2, image.height//2
        draw.ellipse([(cx-6, cy-6), (cx+6, cy+6)], fill="yellow", outline="black")
        # Label
        label = label.upper()
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except:
            font = ImageFont.load_default()
        tw, th = draw.textlength(label, font=font), 28
        lx, ly = cx+12, cy-th-6
        draw.rectangle([lx-4, ly-4, lx+tw+4, ly+th+4], fill="white", outline="black")
        draw.text((lx, ly), label, fill="black", font=font)
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        buf.seek(0)
        return buf.read()

    # --- Main logic ---
    if uploaded_file and MAPBOX_TOKEN:
        uploaded_file.seek(0)
        wb = load_workbook(io.BytesIO(uploaded_file.read()), data_only=True)
        dig_tabs = [s for s in wb.sheetnames if s.lower().startswith("dig") and s.lower() != "dig list"]

        if not dig_tabs:
            st.error("No valid Dig tabs found (excluding 'Dig list').")
        else:
            st.success(f"Found {len(dig_tabs)} Dig tabs: {dig_tabs}")
            if st.button("Generate Aerial Images"):
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    for sheet in dig_tabs:
                        ws = wb[sheet]
                        lat_val, lon_val = ws["AR15"].value, ws["AS15"].value
                        st.write(f"{sheet}: AR15={lat_val}, AS15={lon_val}")
                        try:
                            lat, lon = float(lat_val), float(lon_val)
                        except Exception as e:
                            st.warning(f"Skipping {sheet}: invalid coords ({e})")
                            continue
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            st.warning(f"Skipping {sheet}: out-of-bounds coords ({lat}, {lon})")
                            continue
                        img = fetch_satellite_image(lat, lon, sheet, MAPBOX_TOKEN)
                        if img:
                            zip_file.writestr(f"{sheet}.jpg", img)
                zip_buffer.seek(0)
                st.download_button(
                    "📦 Download Dig Site Images ZIP",
                    data=zip_buffer,
                    file_name="dig_site_images.zip",
                    mime="application/zip"
                )

except Exception as e:
    st.error(f"App crashed: {e}")
    st.code(traceback.format_exc(), language="text")

st.caption("© Mapbox © OpenStreetMap contributors")
