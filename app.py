import streamlit as st
import requests
import polyline
import folium

MAPBOX_TOKEN = st.secrets["mapbox"]["token"]

st.title("Dig Site Directions Generator")

lat = st.number_input("Latitude", value=35.4676, format="%.6f")
lon = st.number_input("Longitude", value=-97.5164, format="%.6f")

# Initialize session state
if "narrative" not in st.session_state:
    st.session_state.narrative = None
if "map_html" not in st.session_state:
    st.session_state.map_html = None

def bearing_to_cardinal(bearing):
    dirs = ["North","Northeast","East","Southeast","South","Southwest","West","Northwest"]
    return dirs[round(bearing/45) % 8]

if st.button("Get Directions"):
    # --- Reverse geocode ---
    geo_url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json?types=address&access_token={MAPBOX_TOKEN}"
    geo_resp = requests.get(geo_url).json()
    if not geo_resp.get("features"):
        st.error("No address found.")
        st.stop()

    feature = geo_resp["features"][0]
    start_coords = feature["center"]
    street = feature.get("text","Unknown Street")
    context = {c["id"].split(".")[0]: c["text"] for c in feature.get("context",[])}
    town = context.get("place","Unknown Town")
    state = context.get("region","")

    # --- Directions ---
    dir_url = f"https://api.mapbox.com/directions/v5/mapbox/driving/{start_coords[0]},{start_coords[1]};{lon},{lat}?steps=true&geometries=polyline&access_token={MAPBOX_TOKEN}"
    dir_resp = requests.get(dir_url).json()
    steps = dir_resp["routes"][0]["legs"][0]["steps"]

    narrative = [f"From the intersection of {street} in {town}, {state}, travel as follows:"]
    for i, step in enumerate(steps):
        dist_mi = step["distance"]/1609.34
        bearing = step["maneuver"].get("bearing_after",0)
        cardinal = bearing_to_cardinal(bearing)
        if i == len(steps)-1:
            side = "right" if 90 < bearing < 270 else "left"
            narrative.append(f"- The dig site will be located on your {side}.")
        else:
            narrative.append(f"- Drive {cardinal} for {dist_mi:.2f} miles")

    # Build map once
    coords = polyline.decode(dir_resp["routes"][0]["geometry"])
    m = folium.Map(location=[lat, lon], zoom_start=12)
    folium.Marker([lat, lon], tooltip="Dig Site", icon=folium.Icon(color="red")).add_to(m)
    folium.Marker([start_coords[1], start_coords[0]], tooltip="Start Point").add_to(m)
    folium.PolyLine(coords, color="blue", weight=3).add_to(m)

    # Save results
    st.session_state.narrative = narrative
    st.session_state.map_html = m._repr_html_()

# --- Display cached results ---
if st.session_state.narrative:
    st.subheader("Turn‑by‑Turn Directions")
    st.write("\n".join(st.session_state.narrative))

if st.session_state.map_html:
    st.components.v1.html(st.session_state.map_html, height=500)
