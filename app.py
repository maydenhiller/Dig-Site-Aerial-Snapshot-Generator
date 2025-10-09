import math
import requests
import streamlit as st
import folium
import polyline

# --- Config ---
MAPBOX_TOKEN = st.secrets["mapbox"]["token"]

st.title("Dig Site Directions Generator")

# --- Session state init ---
if "narrative" not in st.session_state:
    st.session_state.narrative = None
if "map_html" not in st.session_state:
    st.session_state.map_html = None

# --- Helpers ---
def bearing_to_cardinal(bearing_deg):
    dirs = ["North","Northeast","East","Southeast","South","Southwest","West","Northwest"]
    return dirs[round((bearing_deg % 360)/45) % 8]

def latlon_to_mercator(lon, lat):
    # Spherical Web Mercator (EPSG:3857) in meters
    R = 6378137.0
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi/4 + math.radians(lat)/2)) * R
    return x, y

def side_of_road(seg_start_ll, seg_end_ll, point_ll):
    # Convert to meters, compute 2D cross product
    sx, sy = latlon_to_mercator(seg_start_ll[0], seg_start_ll[1])
    ex, ey = latlon_to_mercator(seg_end_ll[0], seg_end_ll[1])
    px, py = latlon_to_mercator(point_ll[0], point_ll[1])
    vx, vy = (ex - sx, ey - sy)         # segment vector
    wx, wy = (px - sx, py - sy)         # point vector from start
    cross = vx * wy - vy * wx
    return "left" if cross > 0 else "right"

def clean_step_instruction(step, cardinal):
    # Prefer cardinal + distance; avoid Mapbox's verbose text stacking
    dist_mi = step["distance"] / 1609.34
    return f"Drive {cardinal} for {dist_mi:.2f} miles"

def extract_town_state(feature):
    town = ""
    state = ""
    for c in feature.get("context", []):
        if c.get("id","").startswith("place."):
            town = c.get("text","")
        if c.get("id","").startswith("region."):
            state = c.get("text","")
    # Fallback to feature's place_name parsing
    if not town:
        town = feature.get("text","")
    return town, state

def pick_intersection_label_near_town_center(town_center_ll):
    # Tilequery near town center to get road names
    tile_url = (
        f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/"
        f"{town_center_ll[0]},{town_center_ll[1]}.json?"
        f"layers=road&radius=800&limit=12&access_token={MAPBOX_TOKEN}"
    )
    tile_resp = requests.get(tile_url).json()
    road_names = []
    for f in tile_resp.get("features", []):
        name = f.get("properties", {}).get("name")
        if name and name not in road_names:
            road_names.append(name)
        if len(road_names) >= 2:
            break
    if len(road_names) >= 2:
        return f"{road_names[0]} & {road_names[1]}"
    elif road_names:
        return road_names[0]
    else:
        return "Unknown Intersection"

# --- Input form to avoid intermediate reruns ---
with st.form("dig_form", clear_on_submit=False):
    lat = st.number_input("Latitude", value=35.4676, format="%.6f")
    lon = st.number_input("Longitude", value=-97.5164, format="%.6f")
    submitted = st.form_submit_button("Get directions")

if submitted:
    try:
        # 1) Nearest town/city
        town_url = (
            f"https://api.mapbox.com/geocoding/v5/mapbox.places/"
            f"{lon},{lat}.json?types=place&access_token={MAPBOX_TOKEN}"
        )
        town_resp = requests.get(town_url).json()
        if not town_resp.get("features"):
            st.error("No nearby town found.")
            st.stop()

        town_feature = town_resp["features"][0]
        town_name = town_feature.get("text","")
        town_state = ""
        for c in town_feature.get("context", []):
            if c.get("id","").startswith("region."):
                town_state = c.get("text","")
        town_center = town_feature["center"]  # [lon, lat]

        # Fallback if names are missing
        if not town_name or not town_state:
            tn, ts = extract_town_state(town_feature)
            town_name = town_name or tn
            town_state = town_state or ts

        # 2) Construct intersection label in that town
        intersection_label = pick_intersection_label_near_town_center(town_center)
        start_coords = town_center  # using town center as the start point coordinate

        # 3) Directions from town center to dig site
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

        # 4) Build narrative with cardinal directions, deduplicated
        narrative = [f"From the intersection of {intersection_label} in {town_name}, {town_state}, travel as follows:"]

        # Consolidate consecutive steps with the same cardinal to reduce spam
        consolidated = []
        accum_dist = 0.0
        current_cardinal = None

        for i, step in enumerate(steps):
            bearing = step["maneuver"].get("bearing_after", 0)
            cardinal = bearing_to_cardinal(bearing)
            dist_mi = step["distance"] / 1609.34

            if i == len(steps) - 1:
                # Commit any accumulated segment before final
                if accum_dist > 0 and current_cardinal:
                    consolidated.append((current_cardinal, accum_dist))
                # Final step: compute side using last road segment geometry
                coords_final = polyline.decode(step["geometry"]) if step.get("geometry") else []
                if len(coords_final) >= 2:
                    # coords_final is list of [lat, lon]; convert to (lon, lat)
                    seg_start_ll = (coords_final[-2][1], coords_final[-2][0])
                    seg_end_ll   = (coords_final[-1][1], coords_final[-1][0])
                    dig_ll       = (lon, lat)
                    side = side_of_road(seg_start_ll, seg_end_ll, dig_ll)
                else:
                    # Fallback: use final approach bearing
                    side = "left" if not (90 < bearing < 270) else "right"
                narrative.extend([f"- Drive {c} for {d:.2f} miles" for c, d in consolidated])
                narrative.append(f"- The dig site will be located on your {side}.")
            else:
                if current_cardinal is None:
                    current_cardinal = cardinal
                    accum_dist = dist_mi
                elif cardinal == current_cardinal:
                    accum_dist += dist_mi
                else:
                    consolidated.append((current_cardinal, accum_dist))
                    current_cardinal = cardinal
                    accum_dist = dist_mi

        # 5) Map: full route, start marker (town), dig marker
        route_coords = polyline.decode(route["geometry"])
        m = folium.Map(location=[lat, lon], zoom_start=12)
        folium.Marker([lat, lon], tooltip="Dig Site", icon=folium.Icon(color="red")).add_to(m)
        folium.Marker([start_coords[1], start_coords[0]], tooltip="Start Intersection").add_to(m)
        folium.PolyLine(route_coords, color="blue", weight=3).add_to(m)

        st.session_state.narrative = narrative
        st.session_state.map_html = m._repr_html_()

    except Exception as e:
        st.error(f"Error: {e}")

# --- Display persisted outputs ---
if st.session_state.narrative:
    st.subheader("Turn‑by‑Turn Directions")
    st.write("\n".join(st.session_state.narrative))

if st.session_state.map_html:
    st.components.v1.html(st.session_state.map_html, height=500)

# Optional: Reset
if st.button("Clear results"):
    st.session_state.narrative = None
    st.session_state.map_html = None
