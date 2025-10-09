import streamlit as st
import io
import traceback
from openpyxl import load_workbook

st.title("🔍 Excel Coordinate Debugger")

f = st.file_uploader("Upload Excel file (.xlsx or .xlsm)", type=["xlsx","xlsm"])

if f:
    try:
        f.seek(0)
        data = f.read()
        st.write(f"Read {len(data)} bytes from upload")

        wb = load_workbook(io.BytesIO(data), data_only=True)
        st.success(f"Workbook loaded. Sheets: {wb.sheetnames}")

        dig_tabs = [s for s in wb.sheetnames if s.lower().startswith("dig") and s.lower() != "dig list"]
        if not dig_tabs:
            st.warning("No valid Dig tabs found (excluding 'Dig list').")
        else:
            for sheet in dig_tabs:
                try:
                    ws = wb[sheet]
                    lat_val = ws["AR15"].value
                    lon_val = ws["AS15"].value
                    st.write(f"Sheet '{sheet}': AR15={lat_val!r}, AS15={lon_val!r}")
                except Exception as e:
                    st.error(f"Error reading {sheet}: {e}")
                    st.code(traceback.format_exc(), language="text")

    except Exception as e:
        st.error(f"Top-level error: {e}")
        st.code(traceback.format_exc(), language="text")
