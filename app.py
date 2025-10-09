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
# Geometry helpers (Web Mercator)
# =========================
def mercator_xy(lon, lat):
    R = 6378137.0
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi/4 + math.radians(lat)/2)) * R
    return x, y

def segment_projection(a_lon, a_lat, b_lon, b_lat, p_lon, p_lat):
    ax, ay = mercator_xy(a_lon, a_lat)
    bx, by = mercator_xy(b_lon, b_lat)
    px, py = mercator_xy(p_lon, p_lat)
    vx, vy = (bx - ax, by - ay)
    seg_len2 = vx*vx + vy*vy
    if seg_len2 == 0:
        return 0.0, ax, ay, ax, ay, bx, by
    t = ((px - ax)*vx + (py - ay)*vy) / seg_len2
    t = max(0.0, min(1.0, t))
    projx, projy = ax + t*vx, ay + t*vy
    return t, projx, projy, ax, ay, bx, by

def nearest_segment_with_projection(route_latlon, dig_lat, dig_lon):
    """Find nearest route segment to the dig point; return endpoints (lon,lat) and projection point."""
    best = None
    best_d2 = float("inf")
    px, py = mercator_xy(dig_lon, dig_lat)
    for i in range(len(route_latlon) - 1):
        (alat, alon) = route_latlon[i]
        (blat, blon) = route_latlon[i+1]
        t, projx, projy, ax, ay, bx, by = segment_projection(alon, alat, blon, blat, dig_lon, dig_lat)
        dx, dy = px - projx, py - projy
        d2 = dx*dx + dy*dy
        if d2 < best_d2:
            best_d2 = d2
            best = ((alon, alat), (blon, blat), (projx, projy), t)
    return best  # ((a_lon,a_lat),(b_lon,b_lat),(projx,projy),t)

def side_from_local_tangent(a_ll, b_ll, proj_xy, dig_lon, dig_lat):
    ax, ay = mercator_xy(a_ll[0], a_ll[1])
    bx, by = mercator_xy(b_ll[0], b_ll[1])
    projx, projy = proj_xy
    tx, ty = (bx - ax, by - ay)            # tangent along segment
    px, py = mercator_xy(dig_lon, dig_lat)
    wx, wy = (px - projx, py - projy)      # offset from road to dig point
    cross = tx*wy - ty*wx
    return "left" if cross > 0 else "right"

def side_relative_to_route(route_latlon, dig_lat, dig_lon):
    """Robust left/right: nearest segment, project dig point, use local tangent heading."""
    if len(route_latlon) < 2:
        return "right"
    nearest = nearest_segment_with_projection(route_latlon, dig_lat, dig_lon)
    if not nearest:
        return "right"
    a_ll, b_ll, proj_xy, _ = nearest
    return side_from_local_tangent(a_ll, b_ll, proj_xy, dig_lon, dig_lat)

# =========================
# Town and intersection helpers
# =========================
def extract_town_state(feature):
    town, state = "", ""
    for c in feature.get("context", []):
        cid = c.get("id", "")
        if cid.startswith("place."): town = c.get("text", "")
        if cid.startswith("region."): state = c.get("text", "")
    if not town:
        town = feature.get("text", "")
    return town, state

def pick_intersection_label_near_point(lon, lat):
    """Label a recognizable intersection near a coordinate using Tilequery roads."""
    tile_url = (
        f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/"
        f"{lon},{lat}.json?layers=road&radius=300&limit=24&access_token={MAPBOX_TOKEN}"
    )
    r = requests.get(tile_url).json()
    primary, other = [], []
    for f in r.get("features", []):
        props = f.get("properties", {})
        name = props.get("name")
        cls = props.get("class", "")
        if not name:
            continue
        if name in primary or name in other:
            continue
        if cls in ("motorway", "trunk", "primary", "secondary", "tertiary"):
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

# =========================
# Turn-by-turn formatting
# =========================
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

def format_step(step, dist_mi):
    man = step.get("maneuver", {})
    man_type = man.get("type", "")
    instr = man.get("instruction", "").strip()
    road_after = step_road_name(step)

    # Depart: “Drive on X for …”
    if man_type == "depart":
        if road_after:
            return f"- Drive on {road_after} for {dist_mi:.2f} miles"
        return f"- Drive for {dist_mi:.2f} miles"

    # Typical turn / merge / exit steps
    if man_type in ("turn", "fork", "merge", "exit", "roundabout", "on ramp", "off ramp"):
        if road_after and (" onto " not in instr and " on " not in instr):
            return f"- {instr} onto {road_after}; continue for {dist_mi:.2f} miles"
        if road_after:
            return f"- {instr}; continue on {road_after} for {dist_mi:.2f} miles"
        return f"- {instr} for {dist_mi:.2f} miles"

    # Generic continuation
    if road_after:
        return f"- Continue on {road_after} for {dist_mi:.2f} miles"
    return f"- Continue for {dist_mi:.2f} miles"

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
        # 1) Nearest town (name and center)
        town_url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json?types=place&access_token={MAPBOX_TOKEN}"
        town_resp = requests.get(town_url).json()
        if not town_resp.get("features"):
            st.error("No nearby town found.")
            st.stop()
        town_feat = town_resp["features"][0]
        town_name, town_state = extract_town_state(town_feat)
        town_center = town_feat["center"]  # [lon, lat]

        # 2) First route from town center to dig (to get true route start coord)
        dir_seed_url = (
            f"https://api.mapbox.com/directions/v5/mapbox/driving/"
            f"{town_center[0]},{town_center[1]};{lon},{lat}"
            f"?steps=true&geometries=polyline&overview=full&access_token={MAPBOX_TOKEN}"
        )
        dir_seed = requests.get(dir_seed_url).json()
        if not dir_seed.get("routes"):
            st.error("No route found from town.")
            st.stop()
        seed_route = dir_seed["routes"][0]
        seed_steps = seed_route["legs"][0]["steps"]

        # Align start to the actual first step’s start location
        first_step = seed_steps[0]
        start_location = first_step["maneuver"]["location"]  # [lon, lat]

        # 3) Label that start location with an intersection near it (inside the town)
        intersection_label = pick_intersection_label_near_point(start_location[0], start_location[1])

        # 4) Final directions from this aligned start to the dig site
        dir_url = (
            f"https://api.mapbox.com/directions/v5/mapbox/driving/"
            f"{start_location[0]},{start_location[1]};{lon},{lat}"
            f"?steps=true&geometries=polyline&overview=full&access_token={MAPBOX_TOKEN}"
        )
        dir_resp = requests.get(dir_url).json()
        if not dir_resp.get("routes"):
            st.error("No route found.")
            st.stop()

        route = dir_resp["routes"][0]
        steps = route["legs"][0]["steps"]
        route_coords = polyline.decode(route["geometry"])  # list of (lat, lon)

        # 5) Narrative: use Mapbox instructions and road names; final left/right via nearest-segment projection
        narrative = [f"From the intersection of {intersection_label} in {town_name}, {town_state}, travel as follows:"]
        for i, step in enumerate(steps):
            if i == len(steps) - 1:
                side = side_relative_to_route(route_coords, lat, lon)
                narrative.append(f"- The dig site will be located on your {side}.")
            else:
                dist_mi = step["distance"] / 1609.34
                narrative.append(format_step(step, dist_mi))

        # 6) Map
        m = folium.Map(location=[lat, lon], zoom_start=14)
        folium.Marker([lat, lon], tooltip="Dig Site", icon=folium.Icon(color="red")).add_to(m)
        folium.Marker([start_location[1], start_location[0]], tooltip="Start Intersection").add_to(m)
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
