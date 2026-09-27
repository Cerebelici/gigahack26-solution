"""
Global block clustering module for Vineyard AI Field Challenge (EPSG:32635).
Clusters canopies into agronomic blocks (vineyard_id):
- Connects plants closer than 5m (via 2.5m buffer)
- Cuts with passages.geojson (a road always separates blocks)
- Numbers blocks consistently (V01, V02, ...)
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import numpy as np
from shapely.geometry import Point, Polygon, MultiPolygon, shape
from shapely.ops import unary_union

from src.spatial.grid import pixel_to_map


def load_passages_geometry(passages_geojson_path: str = "assets/02_route/passages.geojson") -> Optional[MultiPolygon]:
    """Load authorized passages / roads MultiPolygon from GeoJSON."""
    p = Path(passages_geojson_path)
    if not p.exists():
        return None

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("features", [])
        geoms = []
        for feat in features:
            g = shape(feat["geometry"])
            if g.is_valid and not g.is_empty:
                geoms.append(g)

        if geoms:
            u = unary_union(geoms)
            return u if isinstance(u, (Polygon, MultiPolygon)) else None
    except Exception as e:
        print(f"Warning: Failed to load passages geometry: {e}")

    return None


class GlobalBlockClusterer:
    """Clusters all canopy points across tiles into persistent global blocks."""

    def __init__(self, passages_geojson: str = "assets/02_route/passages.geojson"):
        self.passages = load_passages_geometry(passages_geojson)
        self.blocks: Dict[str, Polygon] = {}  # block_id -> Polygon/MultiPolygon

    def cluster_blocks(
        self,
        tile_canopies: Dict[str, List[Tuple[float, float]]],  # tile_name -> list of (px, py)
        buffer_distance_m: float = 2.5,  # 2.5m buffer connects vines within 5m
        min_area_m2: float = 50.0,
    ) -> Dict[str, Polygon]:
        """
        Takes canopy points from all tiles, projects to EPSG:32635,
        buffers and cuts with roads, and assigns V01, V02...
        """
        global_points = []
        point_origins = []  # (tile_name, local_idx)

        # 1. Project all local pixels to EPSG:32635
        for tile_name, points in tile_canopies.items():
            from src.spatial.grid import parse_tile_indices
            try:
                r, c = parse_tile_indices(tile_name)
            except Exception:
                continue

            for idx, (px, py) in enumerate(points):
                east, north = pixel_to_map(r, c, px, py)
                global_points.append(Point(east, north))
                point_origins.append((tile_name, idx))

        if not global_points:
            return {}

        # 2. Buffer points by 2.5m (creating 5m connection between neighboring vines)
        buffered_pts = [pt.buffer(buffer_distance_m) for pt in global_points]
        unified_canopy = unary_union(buffered_pts)

        # 3. Cut with road/passages polygons (a road always splits blocks)
        if self.passages is not None and not self.passages.is_empty:
            try:
                split_canopy = unified_canopy.difference(self.passages)
            except Exception:
                split_canopy = unified_canopy
        else:
            split_canopy = unified_canopy

        # 4. Extract distinct connected components
        if isinstance(split_canopy, Polygon):
            components = [split_canopy]
        elif isinstance(split_canopy, MultiPolygon):
            components = list(split_canopy.geoms)
        else:
            components = []

        # Filter out tiny noise polygons (< min_area_m2)
        valid_components = [poly for poly in components if poly.area >= min_area_m2]

        # 5. Sort blocks geographically: North-to-South (descending Y centroid), then West-to-East
        valid_components.sort(key=lambda p: (-p.centroid.y, p.centroid.x))

        # Assign persistent IDs V01, V02, ...
        self.blocks = {}
        for idx, poly in enumerate(valid_components, start=1):
            block_id = f"V{idx:02d}"
            self.blocks[block_id] = poly

        return self.blocks

    def get_block_id_for_point(self, easting: float, northing: float) -> str:
        """Find the block ID that contains this global point, or nearest within 10m."""
        pt = Point(easting, northing)
        for block_id, poly in self.blocks.items():
            if poly.contains(pt):
                return block_id

        # If not strictly inside, find nearest block within 10m
        best_block = "V01"  # Default fallback
        min_dist = float("inf")
        for block_id, poly in self.blocks.items():
            d = poly.distance(pt)
            if d < min_dist:
                min_dist = d
                best_block = block_id

        return best_block if min_dist <= 10.0 else "V01"
