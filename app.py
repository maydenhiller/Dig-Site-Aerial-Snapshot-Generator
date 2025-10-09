import math
import requests
import streamlit as st
import folium
import polyline

# =========================
# Config
# =========================
MAPBOX_TOKEN = st.secrets["mapbox"]["token"]

st.title("Dig Site Directions Generator")

# Persisted outputs
if "narrative" not in st.session_state:
    st.session_state.narrative = None
if "map_html" not in st.session_state:
    st.session_state.map_html = None

# =========================
# Helpers
# =========================
def bearing_to_cardinal(bearing_deg):
    dirs = ["North","Northeast","East","Southeast","South","Southwest","West","Northwest"]
    return dirs[round((bearing_deg % 360)/45) % 8]

def mercator_xy(lon, lat):
    R = 6378137.0
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi/4 + math.radians(lat)/2)) * R
    return x, y

def nearest_vertex_index(route_latlon, dig_lat, dig_lon):
    # route_latlon: list of (lat, lon)
    px, py = mercator_xy(dig_lon, dig_lat)
    best_i, best_d2 = 0, float("inf")
    for i, (lat, lon) in enumerate(route_latlon):
        x, y = mercator_xy(lon, lat)
        d2 = (x - px)**2 + (y - py)**2
        if d2 < best_d2:
            best_i, best_d2 = i, d2
    return best_i

def side_of_segment(seg_start_ll, seg_end_ll, point_ll):
    # Inputs are (lon, lat)
    sx, sy = mercator_xy(seg_start_ll[0], seg_start_ll[1])
    ex, ey = mercator_xy(seg_end_ll[0], seg_end_ll[1])
    px, py = mercator_xy(point_ll[0], point_ll[1])
    vx, vy = (ex - sx, ey - sy)       # segment vector
    wx, wy = (px - sx, py - sy)       # point-from-start vector
    cross = vx * wy - vy * wx
    return "left" if cross > 0 else "right"

def side_relative_to_route(route_latlon, dig_lat, dig_lon):
    # Pick the segment that actually touches the nearest route vertex to the dig point
    if len(route_latlon) < 2:
        return "right"  # fallback
    i = nearest_vertex_index(route_latlon, dig_lat, dig_lon)

    if i == 0:
        a = route_latlon[0]; b = route_latlon[1]
    elif i == len(route_latlon) - 1:
        a = route_latlon[-2]; b = route_latlon[-1]
    else:
        a_prev = route_latlon[i-1]; a_curr = route_latlon[i]; a_next = route_latlon[i+1]
        ax, ay = mercator_xy(a_prev[1], a_prev[0])
        bx, by = mercator_xy(a_curr[1], a_curr[0])
        cx, cy = mercator_xy(a_next[1], a_next[0])
        len_prev = (bx - ax)**2 + (by - ay)**2
        len_next = (cx - bx)**2 + (cy - by)**2
        if len_prev <= len_next:
            a, b = a_prev, a_curr
        else:
            a, b = a_curr, a_next

    seg_start_ll = (a[1], a[0])  # (lon, lat)
    seg_end_ll   = (b[1], b[0])
    return side_of_segment(seg_start_ll, seg_end_ll, (dig_lon, dig_lat))

def extract_town_state(feature):
    town, state = "", ""
    for c in feature.get("context", []):
        cid = c.get("id","")
        if cid.startswith("place."): town = c.get("text","")
        if cid.startswith("region."): state = c.get("text","")
    if not town: town = feature.get("text","")
    return town, state

def pick_intersection_label_near_town_center(town_center_ll):
    # Pull recognizable road names near town center via Tilequery
    tile_url = (
        f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/"
        f"{town_center_ll[0]},{town_center_ll[1]}.json?"
        f"layers=road&radius=900&limit=24&access_token={MAPBOX_TOKEN}"
    )
    r = requests.get(tile_url).json()
    primary, other = [], []
    for f in r.get("features", []):
        props = f.get("properties", {})
        name = props.get("name")
        cls = props.get("class","")
        if not name:
            continue
        # Deduplicate while preserving order
        if name in primary or name in other:
            continue
        if cls in ("motorway","trunk","primary","secondary","tertiary"):
            primary.append(name)
        else:
            other.append(name)
        if len(primary) + len(other) >= 6:
            break
    names = primary + other
    if len(names) >= 2:
        return f"{names[0]} & {names[1]}"
    elif names:
        return names[0]
    return "Unknown Intersection"

def step_road_name(step):
    # Prefer explicit step name; fall back to maneuver text parsing if missing
    name = step.get("name")
    if name:
        return name
    instr = step.get("maneuver", {}).get("instruction", "")
    # crude parse: look for 'onto XYZ' or 'on XYZ'
    for token in ["onto ", "on "]:
        if token in instr:
            part = instr.split(token, 1)[1].strip()
            # stop at ' and', ',' or end
            for sep in [" and", ","]:
                part = part.split(sep, 1)[0]
            return part
    return ""  # unknown

# =========================
# Input form (prevents intermediate reruns)
# =========================
with st.form("dig_form", clear_on_submit=False):
    lat = st.number_input("Latitude", value=39.432544, format="%.6f")
    lon = st.number_input("Longitude", value=-94.275491, format="%.6f")
    submitted = st.form_submit_button("Get directions")

# =========================
# Compute once on submit
# =========================
if submitted:
    try:
        # 1) Nearest town/city to dig site
        town_url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json?types=place&access_token={MAPBOX_TOKEN}"
        town_resp = requests.get(town_url).json()
        if not town_resp.get("features"):
            st.error("No nearby town found.")
            st.stop()
        town_feat = town_resp["features"][0]
        town_name, town_state = extract_town_state(town_feat)
        town_center = town_feat["center"]  # [lon, lat]

        # 2) Intersection label inside that town
        intersection_label = pick_intersection_label_near_town_center(town_center)
        start_coords = town_center  # start from town center (label is the intersection name)

        # 3) Directions from town to dig site (use full overview for geometry)
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
        route_coords = polyline.decode(route["geometry"])  # [(lat, lon), ...]

        # 4) Build narrative — include road names and turning info
        narrative = [f"From the intersection of {intersection_label} in {town_name}, {town_state}, travel as follows:"]

        for i, step in enumerate(steps):
            dist_mi = step["distance"] / 1609.34
            man = step.get("maneuver", {})
            man_type = man.get("type", "")
            man_instr = man.get("instruction", "")
            bearing = man.get("bearing_after", 0)
            cardinal = bearing_to_cardinal(bearing)
            road_after = step_road_name(step)

            if i == len(steps) - 1:
                # Accurate left/right: segment nearest to the dig point
                side = side_relative_to_route(route_coords, lat, lon)
                narrative.append(f"- The dig site will be located on your {side}.")
            else:
                if man_type == "depart":
                    # Starting movement
                    if road_after:
                        narrative.append(f"- Drive {cardinal} on {road_after} for {dist_mi:.2f} miles")
                    else:
                        narrative.append(f"- Drive {cardinal} for {dist_mi:.2f} miles")
                elif man_type in ("turn","fork","merge","exit","roundabout","on ramp","off ramp"):
                    # Explicit turn/merge style using Mapbox instruction, plus cardinal and road name
                    if road_after:
                        narrative.append(f"- {man_instr} and continue {cardinal} on {road_after} for {dist_mi:.2f} miles")
                    else:
                        narrative.append(f"- {man_instr} and continue {cardinal} for {dist_mi:.2f} miles")
                else:
                    # General continuation
                    if road_after:
                        narrative.append(f"- Continue {cardinal} on {road_after} for {dist_mi:.2f} miles")
                    else:
                        narrative.append(f"- Continue {cardinal} for {dist_mi:.2f} miles")

        # 5) Map
        m = folium.Map(location=[lat, lon], zoom_start=14)
        folium.Marker([lat, lon], tooltip="Dig Site", icon=folium.Icon(color="red")).add_to(m)
        folium.Marker([start_coords[1], start_coords[0]], tooltip="Start Intersection").add_to(m)
        folium.PolyLine(route_coords, color="blue", weight=3).add_to(m)

        st.session_state.narrative = narrative
        st.session_state.map_html = m._repr_html_()

    except Exception as e:
        st.error(f"Error: {e}")

# =========================
# Persisted display
# =========================
if st.session_state.narrative:
    st.subheader("Turn‑by‑Turn Directions")
    st.write("\n".join(st.session_state.narrative))

if st.session_state.map_html:
    st.components.v1.html(st.session_state.map_html, height=520)

# Manual reset
if st.button("Clear results"):
    st.session_state.narrative = None
    st.session_state.map_html = None
