import streamlit as st
import io
from openpyxl import load_workbook

st.title("🔍 Excel Coordinate Debugger")

uploaded_file = st.file_uploader("Upload Excel file (.xlsx or .xlsm)", type=["xlsx", "xlsm"])

if uploaded_file:
    try:
        uploaded_file.seek(0)
        data = uploaded_file.read()
        wb = load_workbook(io.BytesIO(data), data_only=True)
        st.success(f"Workbook loaded. Sheets: {wb.sheetnames}")

        dig_tabs = [
            s for s in wb.sheetnames
            if s.lower().startswith("dig") and s.lower() != "dig list"
        ]
        if not dig_tabs:
            st.warning("No valid Dig tabs found (excluding 'Dig list').")
        else:
            st.write(f"Found {len(dig_tabs)} Dig tabs: {dig_tabs}")

            for sheet in dig_tabs:
                ws = wb[sheet]
                lat_val = ws["AR15"].value
                lon_val = ws["AS15"].value
                st.write(f"Sheet '{sheet}': AR15={lat_val}, AS15={lon_val}")

    except Exception as e:
        st.error(f"Error reading workbook: {e}")
