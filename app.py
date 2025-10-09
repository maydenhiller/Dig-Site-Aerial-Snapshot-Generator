import streamlit as st, traceback

st.title("🔍 Crash Debugger")

try:
    st.write("App started")

    # --- your logic here ---
    raise RuntimeError("Forced test error")

except Exception as e:
    st.error(f"App crashed: {e}")
    st.code(traceback.format_exc(), language="text")
