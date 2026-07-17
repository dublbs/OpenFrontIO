#!/usr/bin/env python3
"""
Generate terrain images for OpenFront.io map-generator from OpenStreetMap data.

Fetches coastline data from OSM (Overpass API), rasterizes it,
computes synthetic elevation, and outputs a PNG compatible with the
OpenFront map-generator format.

Usage:
    python3 generate_map.py --region chiloe
    python3 generate_map.py --region chiloe --width 1200 --height 1800

Output PNG format (consumed by map-generator):
    - Transparent pixel (alpha < 20)  -> Water
    - Black pixel #000000 (alpha >= 20) -> Impassable terrain
    - RGB pixel with B in [140..200]  -> Land, elevation = (B - 140) / 2
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

# ── Overpass API endpoint ────────────────────────────────────────────────────
OVERPASS_URL = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"

# ── Snap tolerance in pixels ────────────────────────────────────────────────
# Coastline way endpoints within this distance are merged.
SNAP_TOLERANCE = 30

# ── Impassable terrain threshold ─────────────────────────────────────────────
IMPASSABLE_ELEVATION = 55

# ── Region definitions ───────────────────────────────────────────────────────
REGIONS = {
    "chiloe": {
        "lat_min": -44.0, "lat_max": -41.4,
        "lon_min": -75.0, "lon_max": -72.5,
    },
}


# ── Overpass API ─────────────────────────────────────────────────────────────

def fetch_json(query, timeout=60):
    for attempt in range(3):
        try:
            r = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=timeout,
                headers={"User-Agent": "openfront-map-gen/1.0"},
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                print(f"  Retry {attempt+1}/3 in {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def fetch_coastline_ways(bbox):
    """Fetch coastline ways from Overpass for a bounding box."""
    lat_min, lat_max, lon_min, lon_max = bbox
    query = f"""
[out:json][timeout:60];
(
  way["natural"="coastline"]({lat_min},{lon_min},{lat_max},{lon_max});
);
out body;
node(w);
out skel;
"""
    print("Fetching coastline ways from OpenStreetMap...", file=sys.stderr)
    data = fetch_json(query, timeout=120)

    elements = data.get("elements", [])

    # Two-pass: collect all nodes first, then resolve ways
    nodes = {}
    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])

    ways = []
    for el in elements:
        if el["type"] == "way":
            coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
            if len(coords) >= 2:
                ways.append(coords)

    print(f"  Found {len(ways)} coastline ways", file=sys.stderr)
    return ways


# ── Coordinate conversion ────────────────────────────────────────────────────

def geo_to_pixel(lon, lat, width, height, bbox):
    """Convert geographic coordinates to pixel coordinates."""
    lat_min, lat_max, lon_min, lon_max = bbox
    x = (lon - lon_min) / (lon_max - lon_min) * width
    y = (lat_max - lat) / (lat_max - lat_min) * height
    return round(x), round(y)


# ── Chain assembly with snapping ─────────────────────────────────────────────

def assemble_chains_geo(ways, bbox, width, height, snap_tolerance_px=SNAP_TOLERANCE):
    """
    Assemble coastline ways into chains with pixel-space snapping.

    Uses coordinate rounding: all endpoints within snap_tolerance are rounded
    to the same integer position, so they automatically group together.
    """
    # Step 1: Convert all ways to pixel coordinates
    pixel_ways = []
    for way in ways:
        px_way = [geo_to_pixel(lon, lat, width, height, bbox) for lon, lat in way]
        pixel_ways.append(px_way)

    # Step 2: Snap endpoints by rounding to grid
    # Endpoints within snap_tolerance pixels will round to the same position
    def snap(x, y):
        return (int(round(x / snap_tolerance_px) * snap_tolerance_px),
                int(round(y / snap_tolerance_px) * snap_tolerance_px))

    # Map each way's start/end to snapped positions
    way_start_pos = {}
    way_end_pos = {}
    for i, way in enumerate(pixel_ways):
        way_start_pos[i] = snap(way[0][0], way[0][1])
        way_end_pos[i] = snap(way[-1][0], way[-1][1])

    # Build adjacency: for each snapped position, which ways start/end there
    pos_starting = defaultdict(list)
    pos_ending = defaultdict(list)
    for i in range(len(pixel_ways)):
        pos_starting[way_start_pos[i]].append(i)
        pos_ending[way_end_pos[i]].append(i)

    # Step 3: Assemble chains by following the graph
    way_used = [False] * len(pixel_ways)
    chains = []

    for seed_idx in range(len(pixel_ways)):
        if way_used[seed_idx]:
            continue

        way_used[seed_idx] = True
        chain_pixels = list(pixel_ways[seed_idx])

        # Extend backward from start
        for _ in range(5000):
            start_pos = snap(chain_pixels[0][0], chain_pixels[0][1])
            found = False
            for wj in pos_ending.get(start_pos, []):
                if not way_used[wj]:
                    chain_pixels = pixel_ways[wj][:-1] + chain_pixels
                    way_used[wj] = True
                    found = True
                    break
            if not found:
                break

        # Extend forward from end
        for _ in range(5000):
            end_pos = snap(chain_pixels[-1][0], chain_pixels[-1][1])
            found = False
            for wj in pos_starting.get(end_pos, []):
                if not way_used[wj]:
                    chain_pixels = chain_pixels + pixel_ways[wj][1:]
                    way_used[wj] = True
                    found = True
                    break
            if not found:
                break

        chains.append(chain_pixels)

    print(f"  Assembled {len(chains)} chains (from {len(pixel_ways)} ways)", file=sys.stderr)
    chain_sizes = sorted([len(c) for c in chains], reverse=True)
    print(f"  Chain sizes: {chain_sizes[:10]}...", file=sys.stderr)

    return chains


# ── Rasterization ────────────────────────────────────────────────────────────

def rasterize_ways(ways, bbox, width, height, coast_width=4):
    """
    Draw coastline ways directly on a grid (no chain assembly needed).
    Returns a set of coastline (x, y) pixels.
    """
    img = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(img)

    for way in ways:
        px_way = [geo_to_pixel(lon, lat, width, height, bbox) for lon, lat in way]
        for i in range(len(px_way) - 1):
            x0, y0 = px_way[i]
            x1, y1 = px_way[i + 1]
            draw.line([(x0, y0), (x1, y1)], fill=255, width=coast_width)

    pixels = np.array(img)
    ys, xs = np.where(pixels > 0)
    coastline = set(zip(xs.tolist(), ys.tolist()))

    return coastline


# ── Flood fill (vectorized BFS) ─────────────────────────────────────────────

def flood_fill_water(coastline_set, width, height):
    """Flood fill from edges to identify water. Uses numpy grid for speed."""
    grid = np.zeros((height, width), dtype=np.uint8)

    # Mark coastline as 1
    for cx, cy in coastline_set:
        if 0 <= cx < width and 0 <= cy < height:
            grid[cy, cx] = 1

    # Seed: all edge pixels that are not coastline
    queue = []
    for x in range(width):
        if grid[0, x] == 0:
            queue.append(x)
            grid[0, x] = 2  # water
        if grid[height - 1, x] == 0:
            queue.append((height - 1) * width + x)
            grid[height - 1, x] = 2
    for y in range(height):
        if grid[y, 0] == 0:
            queue.append(y * width)
            grid[y, 0] = 2
        if grid[y, width - 1] == 0:
            queue.append(y * width + (width - 1))
            grid[y, width - 1] = 2

    head = 0
    while head < len(queue):
        idx = queue[head]
        head += 1
        py = idx // width
        px = idx % width

        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = px + dx, py + dy
            if 0 <= nx < width and 0 <= ny < height:
                nidx = ny * width + nx
                if grid[ny, nx] == 0:
                    grid[ny, nx] = 2  # water
                    queue.append(nidx)

    water = set()
    for y in range(height):
        for x in range(width):
            if grid[y, x] == 2:
                water.add((x, y))

    return water


# ── Elevation ────────────────────────────────────────────────────────────────

def compute_elevation(water_set, coastline_set, width, height, max_elev=60):
    """Compute elevation via BFS distance from water."""
    dist = np.full((height, width), -1, dtype=np.int32)
    queue = []

    for wx, wy in water_set:
        if dist[wy, wx] == -1:
            dist[wy, wx] = 0
            queue.append(wy * width + wx)

    for cx, cy in coastline_set:
        if 0 <= cx < width and 0 <= cy < height and dist[cy, cx] == -1:
            dist[cy, cx] = 0
            queue.append(cy * width + cx)

    head = 0
    while head < len(queue):
        idx = queue[head]
        head += 1
        py = idx // width
        px = idx % width
        d = dist[py, px]

        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = px + dx, py + dy
            if 0 <= nx < width and 0 <= ny < height and dist[ny, nx] == -1:
                dist[ny, nx] = d + 1
                queue.append(ny * width + nx)

    # Convert distance to elevation
    max_dist = max(1, dist.max())
    elev = np.zeros((height, width), dtype=np.float32)
    mask = dist >= 0
    norm = dist.astype(np.float32) / max_dist
    elev[mask] = max_elev * (norm[mask] ** 0.7)

    return elev


def add_noise(elev, water_set, coastline_set, width, height):
    """Add multi-octave value noise for natural terrain variation."""
    np.random.seed(42)

    noise = np.zeros((height, width), dtype=np.float32)
    xs = np.arange(width, dtype=np.float32)
    ys = np.arange(height, dtype=np.float32)

    for freq, amp in [
        (0.005, 12.0),
        (0.015, 6.0),
        (0.04, 3.0),
        (0.1, 1.5),
    ]:
        gw = max(2, int(width * freq) + 2)
        gh = max(2, int(height * freq) + 2)
        random_grid = np.random.randn(gh, gw).astype(np.float32)

        gx = np.outer(np.ones(height), xs) / width * (gw - 1)
        gy = np.outer(ys, np.ones(width)) / height * (gh - 1)

        x0 = gx.astype(np.int32)
        y0 = gy.astype(np.int32)
        x1 = np.minimum(x0 + 1, gw - 1)
        y1 = np.minimum(y0 + 1, gh - 1)
        fx = gx - x0
        fy = gy - y0

        v = (
            random_grid[y0, x0] * (1 - fx) * (1 - fy) +
            random_grid[y0, x1] * fx * (1 - fy) +
            random_grid[y1, x0] * (1 - fx) * fy +
            random_grid[y1, x1] * fx * fy
        )
        noise += v * amp

    elev = elev + noise

    # Zero out water, clamp coastline
    for wx, wy in water_set:
        elev[wy, wx] = 0
    for cx, cy in coastline_set:
        if 0 <= cx < width and 0 <= cy < height:
            elev[cy, cx] = min(elev[cy, cx], 3)

    elev = np.clip(elev, 0, 60)
    return elev


# ── PNG generation (vectorized) ─────────────────────────────────────────────

def elevation_to_png(elev, water_set, coastline_set, width, height, output_path):
    """Convert elevation array to PNG in OpenFront format using numpy (fast)."""
    # Build water mask
    water_mask = np.zeros((height, width), dtype=bool)
    for wx, wy in water_set:
        water_mask[wy, wx] = True

    # Build coast mask
    coast_mask = np.zeros((height, width), dtype=bool)
    for cx, cy in coastline_set:
        if 0 <= cx < width and 0 <= cy < height:
            coast_mask[cy, cx] = True

    # Land mask = not water and not coastline
    land_mask = ~water_mask & ~coast_mask

    # Start with transparent
    img_arr = np.zeros((height, width, 4), dtype=np.uint8)

    # Impassable: black
    impassable = land_mask & (elev >= IMPASSABLE_ELEVATION)
    passable_land = land_mask & (elev < IMPASSABLE_ELEVATION)

    # Fill passable land with elevation-based coloring
    passable_indices = np.where(passable_land)
    land_elev = elev[passable_land]

    b_vals = np.clip(140 + land_elev * 1.0, 140, 200).astype(np.uint8)
    r_vals = np.where(
        land_elev < 20,
        160 + land_elev * 1.0,
        180 + (land_elev - 20) * 0.8
    ).clip(0, 255).astype(np.uint8)
    g_vals = np.where(
        land_elev < 20,
        180 + land_elev * 0.5,
        190 + (land_elev - 20) * 0.3
    ).clip(0, 255).astype(np.uint8)

    img_arr[passable_indices[0], passable_indices[1], 0] = r_vals
    img_arr[passable_indices[0], passable_indices[1], 1] = g_vals
    img_arr[passable_indices[0], passable_indices[1], 2] = b_vals
    img_arr[passable_indices[0], passable_indices[1], 3] = 255

    # Fill impassable (black, fully opaque)
    impassable_indices = np.where(impassable)
    img_arr[impassable_indices[0], impassable_indices[1], :] = [0, 0, 0, 255]

    # Coastline pixels: low elevation (sand-like)
    coast_indices = np.where(coast_mask)
    img_arr[coast_indices[0], coast_indices[1], :] = [190, 190, 150, 255]

    # Water pixels stay transparent (already 0,0,0,0)

    img = Image.fromarray(img_arr, "RGBA")
    img.save(output_path, "PNG")
    print(f"Saved PNG to {output_path}", file=sys.stderr)


# ── Tiny island removal ──────────────────────────────────────────────────────

def remove_tiny_islands(coastline_set, width, height, min_size=30):
    """
    Remove land fragments smaller than min_size pixels.
    Does a flood fill on land and converts tiny fragments to coastline (water boundary).
    """
    # Build grid: 0 = water/coast, 1 = land
    grid = np.zeros((height, width), dtype=np.uint8)
    for cx, cy in coastline_set:
        if 0 <= cx < width and 0 <= cy < height:
            grid[cy, cx] = 1  # treat coast as barrier

    # Everything not coastline starts as "unvisited land"
    # We'll flood-fill from coastline outward to find land fragments

    # Actually: flood fill land regions
    land_grid = np.ones((height, width), dtype=np.uint8)
    for cx, cy in coastline_set:
        if 0 <= cx < width and 0 <= cy < height:
            land_grid[cy, cx] = 0  # coast = not land

    # Mark water (not needed - just skip for now)
    # We work with: 1 = potential land, 0 = coast/barrier

    labeled = np.zeros((height, width), dtype=np.int32)
    label_id = 0
    sizes = []

    for y in range(height):
        for x in range(width):
            if land_grid[y, x] == 1 and labeled[y, x] == 0:
                label_id += 1
                # BFS flood fill
                queue = [(y, x)]
                labeled[y, x] = label_id
                size = 0
                while queue:
                    cy, cx = queue.pop()
                    size += 1
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= nx < width and 0 <= ny < height:
                            if land_grid[ny, nx] == 1 and labeled[ny, nx] == 0:
                                labeled[ny, nx] = label_id
                                queue.append((ny, nx))
                sizes.append((size, label_id))

    removed = 0
    new_coastline = set(coastline_set)
    for size, lid in sizes:
        if size < min_size:
            # Convert this fragment's pixels to coastline (they become water boundary)
            pixels = np.where(labeled == lid)
            for py, px in zip(pixels[0], pixels[1]):
                new_coastline.add((int(px), int(py)))
            removed += 1

    print(f"  Removed {removed} tiny islands (< {min_size}px)", file=sys.stderr)
    return new_coastline


# ── Nation coordinates ───────────────────────────────────────────────────────

def print_nation_coords(width, height, bbox):
    """Print approximate pixel coordinates for Chiloé cities."""
    cities = [
        ("Puerto Montt", -72.943, -41.470),
        ("Ancud", -73.845, -41.868),
        ("Castro", -73.763, -42.466),
        ("Chonchi", -73.750, -42.617),
        ("Dalcahue", -73.650, -42.378),
        ("Quellon", -73.621, -43.118),
        ("Curaco de Velez", -73.586, -42.438),
        ("Quemchi", -73.473, -42.146),
        ("Calbuco", -73.062, -41.770),
        ("Maullin", -73.150, -41.608),
    ]

    print("\n=== Approximate nation coordinates ===", file=sys.stderr)
    print(f"  {'City':<22} {'Lon':>8}  {'Lat':>8}  ->  [x, y]", file=sys.stderr)
    print("  " + "-" * 55, file=sys.stderr)
    for name, lon, lat in cities:
        px, py = geo_to_pixel(lon, lat, width, height, bbox)
        in_bounds = 0 <= px < width and 0 <= py < height
        mark = "" if in_bounds else " (OUTSIDE!)"
        print(f"  {name:<22} {lon:>8.3f}  {lat:>8.3f}  ->  [{px}, {py}]{mark}", file=sys.stderr)
    print("", file=sys.stderr)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate terrain PNG for OpenFront.io from OSM data"
    )
    parser.add_argument("--region", type=str, default="chiloe",
                        choices=list(REGIONS.keys()),
                        help="Region to generate (default: chiloe)")
    parser.add_argument("--width", type=int, default=1000,
                        help="Output image width (default: 1000)")
    parser.add_argument("--height", type=int, default=1500,
                        help="Output image height (default: 1500)")
    parser.add_argument("--output", type=str, default="image.png",
                        help="Output file path (default: image.png)")
    parser.add_argument("--snap", type=int, default=SNAP_TOLERANCE,
                        help=f"Snap tolerance in pixels (default: {SNAP_TOLERANCE})")
    parser.add_argument("--min-island", type=int, default=30,
                        help="Remove land fragments smaller than this (default: 30)")
    args = parser.parse_args()

    region = REGIONS[args.region]
    bbox = (region["lat_min"], region["lat_max"], region["lon_min"], region["lon_max"])
    width = args.width
    height = args.height
    output = Path(args.output)

    print(f"=== Generating {args.region} map: {width}x{height} ===", file=sys.stderr)
    print(f"    Bounding box: ({bbox[2]},{bbox[0]}) -> ({bbox[3]},{bbox[1]})", file=sys.stderr)

    # 1. Fetch coastline
    ways = fetch_coastline_ways(bbox)
    if not ways:
        print("ERROR: No coastline data found.", file=sys.stderr)
        sys.exit(1)

    # 2. Rasterize coastline directly (no chain assembly needed)
    print("\nRasterizing coastline...", file=sys.stderr)
    coastline = rasterize_ways(ways, bbox, width, height)
    print(f"  Coastline pixels: {len(coastline)}", file=sys.stderr)

    # 4. Remove tiny islands
    if args.min_island > 0:
        print("Removing tiny islands...", file=sys.stderr)
        coastline = remove_tiny_islands(coastline, width, height, min_size=args.min_island)
        print(f"  Coastline pixels after cleanup: {len(coastline)}", file=sys.stderr)

    # 5. Flood fill water
    print("Flood filling water...", file=sys.stderr)
    water = flood_fill_water(coastline, width, height)
    land_count = width * height - len(water) - len(coastline)
    print(f"  Water: {len(water)} ({100*len(water)/(width*height):.1f}%)", file=sys.stderr)
    print(f"  Land:  {land_count} ({100*land_count/(width*height):.1f}%)", file=sys.stderr)
    print(f"  Coast: {len(coastline)}", file=sys.stderr)

    if land_count < 1000:
        print("WARNING: Very few land pixels! Coastline data may be incomplete.", file=sys.stderr)

    # 6. Compute elevation
    print("Computing elevation...", file=sys.stderr)
    elev = compute_elevation(water, coastline, width, height)

    # 7. Add noise
    print("Adding terrain noise...", file=sys.stderr)
    elev = add_noise(elev, water, coastline, width, height)

    # 8. Generate PNG
    print("Generating PNG...", file=sys.stderr)
    elevation_to_png(elev, water, coastline, width, height, output)

    # 9. Print coordinates
    print_nation_coords(width, height, bbox)

    print("=== Done! ===", file=sys.stderr)


if __name__ == "__main__":
    main()
