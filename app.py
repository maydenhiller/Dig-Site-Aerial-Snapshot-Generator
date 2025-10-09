import math
import requests
import streamlit as st
import folium
import polyline

MAPBOX_TOKEN = st.secrets["mapbox"]["token"]

st.title("Dig Site Directions Generator")

# Persisted outputs
if "narrative" not in st.session_state:
    st.session_state.narrative = None
if "map_html" not in st.session_state:
    st.session_state.map_html = None

# --- Helpers ---
def bearing_to_cardinal(bearing_deg):
    dirs = ["North","Northeast","East","Southeast","South","Southwest","West","Northwest"]
    return dirs[round((bearing_deg % 360)/45) % 8]

def mercator_xy(lon, lat):
    R = 6378137.0
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi/4 + math.radians(lat)/2)) * R
    return x, y

def side_of_line(seg_start_ll, seg_end_ll, point_ll):
    # seg_start_ll/seg_end_ll/point_ll are (lon, lat)
    sx, sy = mercator_xy(seg_start_ll[0], seg_start_ll[1])
    ex, ey = mercator_xy(seg_end_ll[0], seg_end_ll[1])
    px, py = mercator_xy(point_ll[0], point_ll[1])
    vx, vy = (ex - sx, ey - sy)      # segment vector
    wx, wy = (px - sx, py - sy)      # point-from-start vector
    cross = vx * wy - vy * wx
    return "left" if cross > 0 else "right"

def extract_town_state(feature):
    town, state = "", ""
    for c in feature.get("context", []):
        cid = c.get("id","")
        if cid.startswith("place."): town = c.get("text","")
        if cid.startswith("region."): state = c.get("text","")
    if not town: town = feature.get("text","")
    return town, state

def pick_intersection_label_near_town_center(town_center_ll):
    # Prefer recognizable roads; increase radius for small towns
    tile_url = (
        f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/"
        f"{town_center_ll[0]},{town_center_ll[1]}.json?"
        f"layers=road&radius=900&limit=20&access_token={MAPBOX_TOKEN}"
    )
    r = requests.get(tile_url).json()
    names = []
    for f in r.get("features", []):
        props = f.get("properties", {})
        name = props.get("name")
        cls = props.get("class","")
        if name and name not in names:
            # Bias toward primary/secondary/tertiary for clearer labels
            if cls in ("primary","secondary","tertiary","trunk","motorway"):
                names.insert(0, name)  # push to front
            else:
                names.append(name)
        if len(names) >= 3:
            break
    if len(names) >= 2:
        return f"{names[0]} & {names[1]}"
    elif names:
        return names[0]
    return "Unknown Intersection"

# Use a form so inputs don’t trigger reruns until submit
with st.form("dig_form", clear_on_submit=False):
    lat = st.number_input("Latitude", value=35.4676, format="%.6f")
    lon = st.number_input("Longitude", value=-97.5164, format="%.6f")
    submitted = st.form_submit_button("Get directions")

if submitted:
    try:
        # 1) Nearest town/city
        town_url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json?types=place&access_token={MAPBOX_TOKEN}"
        town_resp = requests.get(town_url).json()
        if not town_resp.get("features"):
            st.error("No nearby town found.")
            st.stop()
        town_feat = town_resp["features"][0]
        town_name, town_state = extract_town_state(town_feat)
        town_center = town_feat["center"]  # [lon, lat]

        # 2) Intersection label in that town
        intersection_label = pick_intersection_label_near_town_center(town_center)
        start_coords = town_center

        # 3) Directions from town to dig site (full overview for final segment)
        dir_url = (
            f"https://api.mapbox.com/directions/v5/mapbox/driving/"
            f"{start_coords[0]},{start_coords[1]};{lon},{lat}"
            f"?steps=true&geometries=polyline&overview=full&access_token={MAPBOX_TOKEN}"
        )
        dir_resp = requests.get(dir_url).json()
        if not dir_resp.get("routes"):
            st.error("No route found.")
            st.stop()

        route = dir_resp["routes"][0]
        steps = route["legs"][0]["steps"]

        # 4) Build narrative — consolidate repeated cardinals
        narrative = [f"From the intersection of {intersection_label} in {town_name}, {town_state}, travel as follows:"]
        consolidated = []
        accum_dist = 0.0
        current_cardinal = None

        for i, step in enumerate(steps):
            bearing = step["maneuver"].get("bearing_after", 0)
            cardinal = bearing_to_cardinal(bearing)
            d_mi = step["distance"] / 1609.34

            if i == len(steps) - 1:
                # Commit any accumulated segment
                if accum_dist > 0 and current_cardinal:
                    consolidated.append((current_cardinal, accum_dist))
                # Accurate left/right: use final approach segment from full route geometry
                full_coords = polyline.decode(route["geometry"])  # list of (lat, lon)
                if len(full_coords) >= 2:
                    # last segment in (lon, lat)
                    seg_start_ll = (full_coords[-2][1], full_coords[-2][0])
                    seg_end_ll   = (full_coords[-1][1], full_coords[-1][0])
                    side = side_of_line(seg_start_ll, seg_end_ll, (lon, lat))
                else:
                    side = "right" if 90 < bearing < 270 else "left"

                narrative.extend([f"- Drive {c} for {d:.2f} miles" for c, d in consolidated])
                narrative.append(f"- The dig site will be located on your {side}.")
            else:
                if current_cardinal is None:
                    current_cardinal = cardinal
                    accum_dist = d_mi
                elif cardinal == current_cardinal:
                    accum_dist += d_mi
                else:
                    consolidated.append((current_cardinal, accum_dist))
                    current_cardinal = cardinal
                    accum_dist = d_mi

        # 5) Map
        route_coords = polyline.decode(route["geometry"])  # list of (lat, lon)
        m = folium.Map(location=[lat, lon], zoom_start=12)
        folium.Marker([lat, lon], tooltip="Dig Site", icon=folium.Icon(color="red")).add_to(m)
        folium.Marker([start_coords[1], start_coords[0]], tooltip="Start Intersection").add_to(m)
        folium.PolyLine(route_coords, color="blue", weight=3).add_to(m)

        st.session_state.narrative = narrative
        st.session_state.map_html = m._repr_html_()

    except Exception as e:
        st.error(f"Error: {e}")

# --- Persisted display ---
if st.session_state.narrative:
    st.subheader("Turn‑by‑Turn Directions")
    st.write("\n".join(st.session_state.narrative))

if st.session_state.map_html:
    st.components.v1.html(st.session_state.map_html, height=500)

if st.button("Clear results"):
    st.session_state.narrative = None
    st.session_state.map_html = None
