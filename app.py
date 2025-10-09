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
def mercator_xy(lon, lat):
    R = 6378137.0
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi/4 + math.radians(lat)/2)) * R
    return x, y

def segment_distance_sq(a_lon, a_lat, b_lon, b_lat, p_lon, p_lat):
    ax, ay = mercator_xy(a_lon, a_lat)
    bx, by = mercator_xy(b_lon, b_lat)
    px, py = mercator_xy(p_lon, p_lat)
    vx, vy = (bx - ax, by - ay)         # segment vector
    wx, wy = (px - ax, py - ay)         # point vector
    seg_len2 = vx*vx + vy*vy
    if seg_len2 == 0:
        # degenerate segment
        dx, dy = px - ax, py - ay
        return dx*dx + dy*dy, (ax, ay), (bx, by), (px, py)
    t = max(0.0, min(1.0, (wx*vx + wy*vy) / seg_len2))  # clamp to segment
    projx, projy = ax + t*vx, ay + t*vy
    dx, dy = px - projx, py - projy
    return dx*dx + dy*dy, (ax, ay), (bx, by), (px, py)

def left_or_right_from_segment(a_lon, a_lat, b_lon, b_lat, p_lon, p_lat):
    ax, ay = mercator_xy(a_lon, a_lat)
    bx, by = mercator_xy(b_lon, b_lat)
    px, py = mercator_xy(p_lon, p_lat)
    vx, vy = (bx - ax, by - ay)
    wx, wy = (px - ax, py - ay)
    cross = vx*wy - vy*wx
    return "left" if cross > 0 else "right"

def side_relative_to_route_nearest_segment(route_latlon, dig_lat, dig_lon):
    # route_latlon: [(lat, lon), ...]
    if len(route_latlon) < 2:
        return "right"
    best_d2 = float("inf")
    best_seg = None
    for i in range(len(route_latlon) - 1):
        (alat, alon) = route_latlon[i]
        (blat, blon) = route_latlon[i+1]
        d2, _, _, _ = segment_distance_sq(alon, alat, blon, blat, dig_lon, dig_lat)
        if d2 < best_d2:
            best_d2 = d2
            best_seg = (alon, alat, blon, blat)  # (a_lon, a_lat, b_lon, b_lat)
    if not best_seg:
        return "right"
    a_lon, a_lat, b_lon, b_lat = best_seg
    return left_or_right_from_segment(a_lon, a_lat, b_lon, b_lat, dig_lon, dig_lat)

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
    # Prefer explicit step name; fall back to parsing instruction
    name = step.get("name")
    if name:
        return name
    instr = step.get("maneuver", {}).get("instruction", "")
    for token in ["onto ", "on "]:
        if token in instr:
            part = instr.split(token, 1)[1].strip()
            for sep in [" and", ","]:
                part = part.split(sep, 1)[0]
            return part
    return ""

def format_turn_step(step, dist_mi):
    man = step.get("maneuver", {})
    instr = man.get("instruction", "").strip()
    road_after = step_road_name(step)
    if road_after and ("onto " not in instr and "on " not in instr):
        # Add explicit road context when Mapbox instruction lacks it
        return f"- {instr} and continue on {road_after} for {dist_mi:.2f} miles"
    elif road_after:
        return f"- {instr} and continue on {road_after} for {dist_mi:.2f} miles"
    else:
        return f"- {instr} for {dist_mi:.2f} miles"

# =========================
# Input form
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
        # 1) Nearest town
        town_url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json?types=place&access_token={MAPBOX_TOKEN}"
        town_resp = requests.get(town_url).json()
        if not town_resp.get("features"):
            st.error("No nearby town found.")
            st.stop()
        town_feat = town_resp["features"][0]
        town_name, town_state = extract_town_state(town_feat)
        town_center = town_feat["center"]  # [lon, lat]

        # 2) Intersection label
        intersection_label = pick_intersection_label_near_town_center(town_center)
        start_coords = town_center

        # 3) Directions (full overview for geometry)
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

        # 4) Narrative: use maneuver.instructions and road names
        narrative = [f"From the intersection of {intersection_label} in {town_name}, {town_state}, travel as follows:"]
        for i, step in enumerate(steps):
            dist_mi = step["distance"] / 1609.34
            man = step.get("maneuver", {})
            man_type = man.get("type", "")
            road_after = step_road_name(step)

            if i == len(steps) - 1:
                # Final: correct left/right relative to nearest route segment to the dig point
                side = side_relative_to_route_nearest_segment(route_coords, lat, lon)
                narrative.append(f"- The dig site will be located on your {side}.")
            else:
                if man_type == "depart":
                    if road_after:
                        narrative.append(f"- Continue on {road_after} for {dist_mi:.2f} miles")
                    else:
                        narrative.append(f"- Continue for {dist_mi:.2f} miles")
                elif man_type in ("turn", "fork", "merge", "exit", "roundabout", "on ramp", "off ramp"):
                    narrative.append(format_turn_step(step, dist_mi))
                else:
                    # Generic continuation (Mapbox often uses 'continue' and provides the road name)
                    if road_after:
                        narrative.append(f"- Continue on {road_after} for {dist_mi:.2f} miles")
                    else:
                        narrative.append(f"- Continue for {dist_mi:.2f} miles")

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
