"""Shortest closed walk outside obstacle polygons, visiting every reachable target.

Obstacles are solid rings in EPSG:32635 metres. Ground outside those rings is walkable,
including ground outside the vineyard. A target inside a ring is moved to the nearest
point just outside it. It is left out when that point is more than 2 m away, or when
no walk from the start reaches it without entering an obstacle.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from pyvisgraph import Point, VisGraph
from shapely import union_all
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

SIMPLIFY_M = 0.05
VISIT_LIMIT_M = 2.0
OUTSIDE_GAP_M = 0.001
# Ignore a crossing shorter than this. A walk may run along an edge; float noise is smaller.
CROSSING_M = 1e-6
CENTIMETRES_PER_METRE = 100
# Guided local search runs until this budget is spent. Without a limit it does not return.
SOLVER_LIMIT_MS = 200

Coordinate = tuple[float, float]


class StartInsideObstacle(Exception):
    """The start point lies inside an obstacle polygon."""

    def __init__(self) -> None:
        super().__init__("Start lies inside an obstacle.")


@dataclass(frozen=True)
class RoutePlan:
    route: LineString
    length_m: float
    unreachable: tuple[Coordinate, ...]


@dataclass
class _Candidate:
    original: Coordinate
    point: Point | None
    path: list[Point] | None = None


def plan_route(
    obstacles: Sequence[Sequence[Sequence[float]]],
    start: Sequence[float],
    targets: Sequence[Sequence[float]],
) -> RoutePlan:
    origin = _coordinate(start)
    polygons = _clean_polygons(obstacles)
    blocked = _obstacle_union(polygons)
    if blocked is not None and blocked.contains(ShapelyPoint(*origin)):
        raise StartInsideObstacle()
    if not targets:
        return _degenerate(origin, ())

    candidates = []
    for target in targets:
        original = _coordinate(target)
        candidates.append(_Candidate(original, _place_target(original, blocked)))
    origin_point = Point(*origin)
    placed = [candidate.point for candidate in candidates if candidate.point is not None]
    if placed:
        graph = _visibility_graph(polygons, [origin_point, *placed])
        for candidate in candidates:
            if candidate.point is not None:
                candidate.path = _shortest(graph, origin_point, candidate.point, blocked)
    else:
        graph = None

    unreachable = tuple(candidate.original for candidate in candidates if candidate.path is None)
    reachable = [candidate for candidate in candidates if candidate.path is not None and candidate.point is not None]
    if not reachable or graph is None:
        return _degenerate(origin, unreachable)

    line = _closed_walk(origin_point, reachable, graph, blocked)
    return RoutePlan(route=line, length_m=float(line.length), unreachable=unreachable)


def _coordinate(point: Sequence[float]) -> Coordinate:
    return (float(point[0]), float(point[1]))


def _degenerate(origin: Coordinate, unreachable: tuple[Coordinate, ...]) -> RoutePlan:
    return RoutePlan(route=LineString([origin, origin]), length_m=0.0, unreachable=unreachable)


def _clean_polygons(obstacles: Sequence[Sequence[Sequence[float]]]) -> list[Polygon]:
    polygons: list[Polygon] = []
    for ring in obstacles:
        cleaned = _dedupe(ring)
        if len(cleaned) < 3:
            continue
        polygon = Polygon(cleaned)
        if polygon.is_empty:
            continue
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        simplified = polygon.simplify(SIMPLIFY_M, preserve_topology=True)
        for piece in _polygon_parts(simplified):
            exterior = _open_ring(piece)
            if len(exterior) >= 3:
                polygons.append(Polygon(exterior))
    return polygons


def _dedupe(ring: Sequence[Sequence[float]]) -> list[Coordinate]:
    cleaned: list[Coordinate] = []
    for point in ring:
        xy = _coordinate(point)
        if cleaned and cleaned[-1] == xy:
            continue
        cleaned.append(xy)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    return cleaned


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return [part for part in geometry.geoms if isinstance(part, Polygon)]
    return []


def _open_ring(polygon: Polygon) -> list[Coordinate]:
    coords = [(float(x), float(y)) for x, y in polygon.exterior.coords]
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords.pop()
    return _dedupe(coords)


def _obstacle_union(polygons: list[Polygon]) -> BaseGeometry | None:
    if not polygons:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return union_all(polygons)


def _place_target(original: Coordinate, blocked: BaseGeometry | None) -> Point | None:
    if blocked is None:
        return Point(*original)
    origin = ShapelyPoint(*original)
    if not blocked.intersects(origin):
        return Point(*original)
    # A point on the ring is not inside, but pyvisgraph cannot route to an edge.
    # Nudge it 1 mm outside; that stays well within the 2 m visit.
    spot = _just_outside(origin, blocked)
    if spot is None:
        return None
    return Point(spot.x, spot.y)


def _just_outside(origin: ShapelyPoint, blocked: BaseGeometry) -> ShapelyPoint | None:
    nearest = nearest_points(origin, blocked.boundary)[1]
    distance = origin.distance(nearest)
    if distance > 0:
        scale = OUTSIDE_GAP_M / distance
        candidate = ShapelyPoint(
            nearest.x + (nearest.x - origin.x) * scale,
            nearest.y + (nearest.y - origin.y) * scale,
        )
        if not blocked.covers(candidate):
            if origin.distance(candidate) > VISIT_LIMIT_M:
                return None
            return candidate
        if distance + OUTSIDE_GAP_M > VISIT_LIMIT_M:
            return None
    candidate = _push_out(nearest, blocked)
    if candidate is None or origin.distance(candidate) > VISIT_LIMIT_M:
        return None
    return candidate


def _push_out(nearest: ShapelyPoint, blocked: BaseGeometry) -> ShapelyPoint | None:
    boundary = _boundary_line(nearest, blocked)
    if boundary is None or boundary.length == 0:
        return None
    along = boundary.project(nearest)
    step = min(0.01, boundary.length / 4)
    before = boundary.interpolate((along - step) % boundary.length)
    after = boundary.interpolate((along + step) % boundary.length)
    dx = after.x - before.x
    dy = after.y - before.y
    norm = math.hypot(dx, dy)
    if norm == 0:
        return None
    px, py = -dy / norm, dx / norm
    for sign in (1.0, -1.0):
        candidate = ShapelyPoint(nearest.x + sign * px * OUTSIDE_GAP_M, nearest.y + sign * py * OUTSIDE_GAP_M)
        if not blocked.covers(candidate):
            return candidate
    return None


def _boundary_line(nearest: ShapelyPoint, blocked: BaseGeometry) -> LineString | None:
    boundary = blocked.boundary
    if isinstance(boundary, LineString):
        return boundary
    lines = [line for line in getattr(boundary, "geoms", ()) if isinstance(line, LineString)]
    if not lines:
        return None
    return min(lines, key=lambda line: line.distance(nearest))


def _visibility_graph(polygons: list[Polygon], stops: list[Point]) -> VisGraph:
    rings = []
    for polygon in polygons:
        ring = _open_ring(polygon)
        if len(ring) >= 3:
            rings.append([Point(x, y) for x, y in ring])
    graph = VisGraph()
    graph.build(rings, status=False)
    if stops:
        graph.update(stops)
    return graph


def _shortest(graph: VisGraph, origin: Point, destination: Point, blocked: BaseGeometry | None) -> list[Point] | None:
    if origin == destination:
        return [origin]
    # update() connects stops to polygon corners, not to each other. A free straight
    # segment is the shortest walk, so use it before asking the visibility graph.
    straight = [(origin.x, origin.y), (destination.x, destination.y)]
    if not _enters_obstacle(straight, blocked):
        return [origin, destination]
    try:
        path = graph.shortest_path(origin, destination)
    except (KeyError, ValueError):
        return None
    if _enters_obstacle([(point.x, point.y) for point in path], blocked):
        return None
    return path


def _enters_obstacle(coords: list[Coordinate], blocked: BaseGeometry | None) -> bool:
    if blocked is None or len(coords) < 2:
        return False
    line = LineString(coords)
    if line.length == 0:
        return False
    overlap = line.intersection(blocked)
    if overlap.is_empty:
        return False
    interior = overlap.difference(blocked.boundary)
    return not interior.is_empty and interior.length > CROSSING_M


def _closed_walk(
    origin: Point,
    reachable: list[_Candidate],
    graph: VisGraph,
    blocked: BaseGeometry | None,
) -> LineString:
    points = [origin] + [target.point for target in reachable]
    paths: list[list[list[Point]]] = [[[] for _ in points] for _ in points]
    distances = [[0 for _ in points] for _ in points]
    for index, target in enumerate(reachable, start=1):
        if target.path is None or target.point is None:
            raise RuntimeError("A reachable stop is missing its path.")
        paths[0][index] = target.path
        paths[index][0] = list(reversed(target.path))
        distances[0][index] = distances[index][0] = _centimetres(target.path)
    for left in range(1, len(points)):
        paths[left][left] = [points[left]]
        for right in range(left + 1, len(points)):
            path = _shortest(graph, points[left], points[right], blocked)
            if path is None:
                path = list(reversed(paths[0][left])) + paths[0][right][1:]
            paths[left][right] = path
            paths[right][left] = list(reversed(path))
            centimetres = _centimetres(path)
            distances[left][right] = distances[right][left] = centimetres
    paths[0][0] = [origin]
    return _line_from(_tour(distances), paths)


def _centimetres(path: list[Point]) -> int:
    if len(path) < 2:
        return 0
    metres = LineString([(point.x, point.y) for point in path]).length
    return int(round(metres * CENTIMETRES_PER_METRE))


def _tour(distances: list[list[int]]) -> list[int]:
    count = len(distances)
    manager = pywrapcp.RoutingIndexManager(count, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index: int, to_index: int) -> int:
        return int(distances[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(transit))
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parameters.time_limit.FromMilliseconds(SOLVER_LIMIT_MS)
    solution = routing.SolveWithParameters(parameters)
    if solution is None:
        raise RuntimeError("The route solver could not order the stops.")

    index = routing.Start(0)
    order = []
    while not routing.IsEnd(index):
        order.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    order.append(manager.IndexToNode(index))
    return order


def _line_from(order: list[int], paths: list[list[list[Point]]]) -> LineString:
    coords: list[Coordinate] = []
    for depart, arrive in zip(order, order[1:]):
        for point in paths[depart][arrive]:
            xy = (point.x, point.y)
            if not coords or coords[-1] != xy:
                coords.append(xy)
    if len(coords) < 2:
        coords = [coords[0], coords[0]]
    return LineString(coords)
