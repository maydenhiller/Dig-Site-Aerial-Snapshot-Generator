import streamlit as st
import requests, polyline, folium

MAPBOX_TOKEN = st.secrets["mapbox"]["token"]

def bearing_to_cardinal(bearing):
    dirs = ["North","Northeast","East","Southeast","South","Southwest","West","Northwest"]
    return dirs[round(bearing/45) % 8]

def side_of_road(seg_start, seg_end, point):
    # seg_start, seg_end, point are (lon, lat)
    x1, y1 = seg_start
    x2, y2 = seg_end
    x, y = point
    # Vector cross product (2D)
    cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
    return "left" if cross > 0 else "right"

if st.button("Get Directions"):
    # ... (get town, intersection, directions as before) ...

    steps = dir_resp["routes"][0]["legs"][0]["steps"]

    narrative = [f"From the intersection of {intersection_label} in {town_name}, {state}, travel as follows:"]
    for i, step in enumerate(steps):
        dist_mi = step["distance"]/1609.34
        bearing = step["maneuver"].get("bearing_after",0)
        cardinal = bearing_to_cardinal(bearing)

        if i == len(steps)-1:
            # --- Improved left/right logic ---
            coords = polyline.decode(step["geometry"])
            if len(coords) >= 2:
                seg_start = (coords[-2][1], coords[-2][0])  # (lon, lat)
                seg_end   = (coords[-1][1], coords[-1][0])
                dig_point = (lon, lat)
                side = side_of_road(seg_start, seg_end, dig_point)
            else:
                side = "right"
            narrative.append(f"- The dig site will be located on your {side}.")
        else:
            narrative.append(f"- Drive {cardinal} for {dist_mi:.2f} miles")
