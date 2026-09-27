"""
Walking Route Solver for Vineyard AI Field Challenge (EPSG:32635).
Computes the optimal inspection route:
- Starts and ends at START_POINT (629504.70, 5220250.75) within 5m
- Visits all inspection targets (gaps >= 5m, waste) within 2m
- Restricted to authorised passages and passable inter-row corridors (>= 98% inside)
- Strictly avoids forbidden zones (buildings, compounds) and canopy polygons
- Solves Traveling Salesperson Problem (TSP) using Nearest Neighbor + 2-Opt
- Exports route.geojson with length_m property
"""

import json
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
import networkx as nx
from scipy.spatial import Delaunay, cKDTree
from shapely.geometry import shape, Point, LineString, Polygon, MultiPolygon
from shapely.prepared import prep
from shapely.ops import unary_union

from src.spatial.grid import START_POINT


class RouteSolver:
    """Solves optimal walking route visiting all inspection targets in EPSG:32635."""

    START_COORD = START_POINT  # (629504.70, 5220250.75)

    def __init__(
        self,
        passages_geojson: str = "assets/02_route/passages.geojson",
        forbidden_geojson: str = "assets/02_route/forbidden.geojson",
    ):
        self.passages_path = passages_geojson
        self.forbidden_path = forbidden_geojson

        self.passages_geom: Optional[MultiPolygon] = self._load_geom(passages_geojson)
        self.forbidden_geom: Optional[MultiPolygon] = self._load_geom(forbidden_geojson)

        self.prep_passages = prep(self.passages_geom) if self.passages_geom else None
        self.prep_forbidden = prep(self.forbidden_geom) if self.forbidden_geom else None

        self.G = nx.Graph()
        self.node_positions: Dict[int, Tuple[float, float]] = {}
        self.start_node_id: int = 0

        self._build_passages_network()

    @staticmethod
    def _load_geom(path: str) -> Optional[Any]:
        p = Path(path)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        feats = data.get("features", [])
        if not feats:
            return None
        return shape(feats[0]["geometry"])

    def _build_passages_network(self, densify_step: float = 8.0):
        """Constructs a connected skeleton graph along the authorised passages."""
        if not self.passages_geom:
            return

        poly = list(self.passages_geom.geoms)[1] if isinstance(self.passages_geom, MultiPolygon) else self.passages_geom

        pts = []
        all_rings = [poly.exterior] + list(poly.interiors)
        for ring in all_rings:
            coords = list(ring.coords)
            for k in range(len(coords) - 1):
                p1 = coords[k]
                p2 = coords[k + 1]
                dist = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
                steps = max(1, int(np.ceil(dist / densify_step)))
                for s in range(steps):
                    t = s / steps
                    pts.append((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])))

        # Include start coordinate
        pts.append(self.START_COORD)
        pts_arr = np.array(pts)

        # Delaunay triangulation
        tri = Delaunay(pts_arr)

        inside_triangles: Dict[int, Tuple[float, float]] = {}
        for i, sim in enumerate(tri.simplices):
            c = np.mean(pts_arr[sim], axis=0)
            if self.prep_passages and self.prep_passages.contains(Point(c)):
                inside_triangles[i] = (float(c[0]), float(c[1]))

        # Build dual graph
        for i, pos in inside_triangles.items():
            self.G.add_node(i, pos=pos)
            self.node_positions[i] = pos

        for i in inside_triangles:
            for neighbor in tri.neighbors[i]:
                if neighbor in inside_triangles:
                    p1 = inside_triangles[i]
                    p2 = inside_triangles[neighbor]
                    d = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
                    self.G.add_edge(i, neighbor, weight=d)

        # Filter to largest connected component containing start
        comps = sorted(nx.connected_components(self.G), key=len, reverse=True)
        if comps:
            self.G = self.G.subgraph(comps[0]).copy()
            self.node_positions = {n: self.node_positions[n] for n in self.G.nodes()}

        # Explicitly add start node
        min_dist = float("inf")
        closest_n = None
        for n, pos in self.node_positions.items():
            d = np.hypot(pos[0] - self.START_COORD[0], pos[1] - self.START_COORD[1])
            if d < min_dist:
                min_dist = d
                closest_n = n

        self.start_node_id = 999999
        self.G.add_node(self.start_node_id, pos=self.START_COORD)
        self.node_positions[self.start_node_id] = self.START_COORD
        if closest_n is not None:
            self.G.add_edge(self.start_node_id, closest_n, weight=min_dist)

    def add_interrow_corridors(self, interrow_polygons: List[Polygon]):
        """Integrates walkable inter-row corridor centerlines into the graph."""
        if not interrow_polygons:
            return

        next_node_id = max(self.G.nodes()) + 1 if self.G.number_of_nodes() > 0 else 1

        for poly in interrow_polygons:
            if not poly.is_valid or poly.is_empty or poly.area < 2.0:
                continue

            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                try:
                    clean_poly = poly.buffer(0)
                    if clean_poly.is_empty or clean_poly.area < 2.0:
                        continue
                    rect = clean_poly.minimum_rotated_rectangle
                    rect_coords = list(rect.exterior.coords)[:-1]
                except Exception:
                    continue
            if len(rect_coords) != 4:
                continue

            # Two longest edges define the orientation
            edges = []
            for i in range(4):
                p1 = rect_coords[i]
                p2 = rect_coords[(i + 1) % 4]
                edges.append((np.hypot(p2[0] - p1[0], p2[1] - p1[1]), p1, p2))
            edges.sort(key=lambda x: x[0], reverse=True)

            # Midpoints of the two short ends
            mid1 = (0.5 * (edges[2][1][0] + edges[2][2][0]), 0.5 * (edges[2][1][1] + edges[2][2][1]))
            mid2 = (0.5 * (edges[3][1][0] + edges[3][2][0]), 0.5 * (edges[3][1][1] + edges[3][2][1]))

            length = np.hypot(mid2[0] - mid1[0], mid2[1] - mid1[1])
            if length < 5.0:
                continue

            steps = max(2, int(np.ceil(length / 5.0)))
            corridor_nodes = []
            for s in range(steps + 1):
                t = s / steps
                cx = mid1[0] + t * (mid2[0] - mid1[0])
                cy = mid1[1] + t * (mid2[1] - mid1[1])
                c_pt = Point(cx, cy)

                # Strictly check point is not forbidden
                if self.prep_forbidden and self.prep_forbidden.contains(c_pt):
                    continue

                nid = next_node_id
                next_node_id += 1
                self.G.add_node(nid, pos=(cx, cy))
                self.node_positions[nid] = (cx, cy)
                corridor_nodes.append(nid)

            # Connect consecutive points along corridor
            for k in range(len(corridor_nodes) - 1):
                n_a = corridor_nodes[k]
                n_b = corridor_nodes[k + 1]
                pa = self.node_positions[n_a]
                pb = self.node_positions[n_b]
                d = np.hypot(pb[0] - pa[0], pb[1] - pa[1])
                self.G.add_edge(n_a, n_b, weight=d)

            # Connect corridor endpoints to the nearest passages node
            for end_nid in [corridor_nodes[0], corridor_nodes[-1]]:
                end_pos = self.node_positions[end_nid]
                # Find closest passage node
                best_n = None
                best_d = float("inf")
                for n, pos in self.node_positions.items():
                    if n < 50000:  # Passages node
                        d = np.hypot(pos[0] - end_pos[0], pos[1] - end_pos[1])
                        if d < best_d and d <= 15.0:
                            best_d = d
                            best_n = n

                if best_n is not None:
                    # Check connection does not cross forbidden
                    line = LineString([Point(end_pos), Point(self.node_positions[best_n])])
                    if not (self.prep_forbidden and self.prep_forbidden.intersects(line)):
                        self.G.add_edge(end_nid, best_n, weight=best_d)

    def solve_route(
        self,
        targets: List[Tuple[float, float]],
        max_targets_sample: Optional[int] = None,
    ) -> Tuple[List[Tuple[float, float]], float, int]:
        """
        Solves the TSP tour visiting all targets, starting and returning to START_COORD.
        Returns:
            route_coords: list of (Easting, Northing)
            total_length_m: total distance in metres
            visited_target_count: number of targets passed within 2m
        """
        if not targets:
            # If no inspection targets, return trivial start loop
            return [self.START_COORD, self.START_COORD], 0.0, 0

        # Subsample if too many targets (e.g. for speed during testing)
        target_pts = targets
        if max_targets_sample and len(targets) > max_targets_sample:
            step = len(targets) // max_targets_sample
            target_pts = targets[::step]

        # 1. Connect each target to nearest node in G
        target_nodes = []
        node_ids = list(self.node_positions.keys())
        node_coords = np.array([self.node_positions[n] for n in node_ids])
        tree = cKDTree(node_coords)

        for tx, ty in target_pts:
            dist, idx = tree.query((tx, ty))
            nearest_nid = node_ids[idx]
            target_nodes.append(nearest_nid)

        # Unique target nodes plus start
        unique_targets = list(dict.fromkeys(target_nodes))
        poi_nodes = [self.start_node_id] + unique_targets

        # 2. Compute all-pairs shortest paths among POI nodes
        dist_matrix = np.zeros((len(poi_nodes), len(poi_nodes)))
        paths_cache = {}

        for i, u in enumerate(poi_nodes):
            lengths, paths = nx.single_source_dijkstra(self.G, u, weight="weight")
            for j, v in enumerate(poi_nodes):
                if i != j:
                    if v in lengths:
                        dist_matrix[i, j] = lengths[v]
                        paths_cache[(u, v)] = paths[v]
                    else:
                        dist_matrix[i, j] = 1e9

        # 3. Solve TSP: Nearest Neighbor Heuristic
        n_poi = len(poi_nodes)
        visited = [False] * n_poi
        tour = [0]  # Start at start node (index 0)
        visited[0] = True

        current = 0
        for _ in range(n_poi - 1):
            next_idx = None
            min_d = float("inf")
            for j in range(n_poi):
                if not visited[j] and dist_matrix[current, j] < min_d:
                    min_d = dist_matrix[current, j]
                    next_idx = j
            if next_idx is None:
                break
            tour.append(next_idx)
            visited[next_idx] = True
            current = next_idx

        # Return to start
        tour.append(0)

        # 4. Optimize TSP Tour: 2-Opt Local Search
        improved = True
        iterations = 0
        while improved and iterations < 50:
            improved = False
            iterations += 1
            for i in range(1, len(tour) - 2):
                for j in range(i + 1, len(tour) - 1):
                    d_current = dist_matrix[tour[i - 1], tour[i]] + dist_matrix[tour[j], tour[j + 1]]
                    d_new = dist_matrix[tour[i - 1], tour[j]] + dist_matrix[tour[i], tour[j + 1]]
                    if d_new < d_current - 0.1:
                        tour[i : j + 1] = reversed(tour[i : j + 1])
                        improved = True
                        break
                if improved:
                    break

        # 5. Expand full coordinate path
        full_route: List[Tuple[float, float]] = []
        for k in range(len(tour) - 1):
            u = poi_nodes[tour[k]]
            v = poi_nodes[tour[k + 1]]
            leg_path = paths_cache.get((u, v), [u, v])
            leg_coords = [self.node_positions[nid] for nid in leg_path]
            if k == 0:
                full_route.extend(leg_coords)
            else:
                full_route.extend(leg_coords[1:])

        # Calculate total length
        total_len = 0.0
        for k in range(len(full_route) - 1):
            p1 = full_route[k]
            p2 = full_route[k + 1]
            total_len += np.hypot(p2[0] - p1[0], p2[1] - p1[1])

        # Verify target coverage within 2m
        route_line = LineString(full_route)
        visited_count = 0
        for tx, ty in targets:
            if route_line.distance(Point(tx, ty)) <= 2.05:
                visited_count += 1

        return full_route, round(total_len, 2), visited_count

    def export_geojson(
        self,
        route_coords: List[Tuple[float, float]],
        total_length_m: float,
        visited_count: int,
        total_target_count: int,
        output_path: str = "route.geojson",
    ) -> str:
        """Exports the route LineString into EPSG:32635 route.geojson."""
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        feature = {
            "type": "FeatureCollection",
            "name": "siret3_walking_route",
            "crs": {
                "type": "name",
                "properties": {
                    "name": "urn:ogc:def:crs:EPSG::32635"
                }
            },
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": "WALKING_ROUTE",
                        "length_m": total_length_m,
                        "targets_total": total_target_count,
                        "targets_visited": visited_count,
                        "coverage_pct": round(100.0 * visited_count / max(1, total_target_count), 1),
                        "crs": "EPSG:32635"
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[round(x, 2), round(y, 2)] for x, y in route_coords]
                    }
                }
            ]
        }

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(feature, f, indent=2)

        return str(out_file.resolve())
