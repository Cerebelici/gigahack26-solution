"""Shortest closed walk that visits every reachable target and does not enter an obstacle.

Obstacles are solid rings in EPSG:32635 metres. Any other ground is walkable, including
headlands and ground that is not an inter-row. A target inside a ring is moved to the
nearest point just outside it. It is left out when that point is more than 2 m away, or
when every walk from the start enters an obstacle.

Canopies are separate rings. The walk is planned around the row obstacles, then bent
around any canopy it would otherwise cross. A stop it already reached stays within 2 m.

A narrow gap between two parallel obstacles is an inter-row. Stops in that gap are
placed on its centre line, and a walk that stays in the gap follows that middle.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from pyvisgraph import Point, VisGraph
from shapely import union_all
from shapely.affinity import translate
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

SIMPLIFY_M = 0.05
VISIT_LIMIT_M = 2.0
OUTSIDE_GAP_M = 0.001
# Ignore a crossing shorter than this. A walk may run along an edge; float noise is smaller.
CROSSING_M = 1e-6
CENTIMETRES_PER_METRE = 100
# Guided local search runs until this budget is spent. Without a limit it does not return.
SOLVER_LIMIT_MS = 200
# Walkable width of a gap that is still an inter-row. Wider ground is a headland.
MIN_CORRIDOR_M = 0.4
MAX_CORRIDOR_M = 4.0
# Centre-to-centre distance beyond which two row strips do not share an inter-row.
MAX_AXIS_SPACING_M = 6.0
# |cos| of the angle between two strip axes. About 20 degrees.
PARALLEL_DOT = 0.94
# A point this far past a centre line's end is on the headland, not in the inter-row.
PAST_END_M = 0.15
# Two centre lines this close count as the same distance, so the nearer index wins.
CENTRE_TIE_M = 1e-3

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


@dataclass(frozen=True)
class _Corridor:
    """Centre line of one inter-row, and half the walkable width of that gap."""

    line: LineString
    half_m: float


def plan_route(
    obstacles: Sequence[Sequence[Sequence[float]]],
    start: Sequence[float],
    targets: Sequence[Sequence[float]],
    canopies: Sequence[Sequence[Sequence[float]]] = (),
) -> RoutePlan:
    # pyvisgraph compares floats with fixed tolerances. At UTM magnitudes (~10^6 m) its visibility test
    # lets edges cut through thin obstacles, so the walk is planned around the start and moved back.
    ox, oy = _coordinate(start)
    originals = [_coordinate(target) for target in targets]
    local_targets = [(x - ox, y - oy) for x, y in originals]
    local_obstacles = [[(float(p[0]) - ox, float(p[1]) - oy) for p in ring] for ring in obstacles]
    local_canopies = [[(float(p[0]) - ox, float(p[1]) - oy) for p in ring] for ring in canopies]
    plan = _plan_local(local_obstacles, (0.0, 0.0), local_targets, local_canopies)
    by_local = dict(zip(local_targets, originals))
    return RoutePlan(
        route=translate(plan.route, ox, oy),
        length_m=plan.length_m,
        unreachable=tuple(by_local[point] for point in plan.unreachable),
    )


def _plan_local(
    obstacles: Sequence[Sequence[Sequence[float]]],
    start: Sequence[float],
    targets: Sequence[Sequence[float]],
    canopies: Sequence[Sequence[Sequence[float]]] = (),
) -> RoutePlan:
    origin = _coordinate(start)
    polygons = _clean_polygons(obstacles)
    # Keep the drawn canopy outline. Simplifying it pulls the boundary inward, and the
    # walk would still cross the foliage the map shows.
    canopy_polygons = _clean_polygons(canopies, simplify_m=0)
    blocked = _obstacle_union(polygons)
    canopy_blocked = _obstacle_union(canopy_polygons)
    if (blocked is not None and blocked.contains(ShapelyPoint(*origin))) or (
        canopy_blocked is not None and canopy_blocked.contains(ShapelyPoint(*origin))
    ):
        raise StartInsideObstacle()
    if not targets:
        return _degenerate(origin, ())

    corridors = _corridors(polygons, blocked)
    candidates = []
    for target in targets:
        original = _coordinate(target)
        candidates.append(_Candidate(original, _place_target(original, blocked, corridors)))
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

    line = _straighten(_closed_walk(origin_point, reachable, graph, blocked), corridors, blocked)
    line = _avoid_canopies(line, canopy_polygons, blocked, [candidate.original for candidate in reachable])
    return RoutePlan(route=line, length_m=float(line.length), unreachable=unreachable)


def _coordinate(point: Sequence[float]) -> Coordinate:
    return (float(point[0]), float(point[1]))


def _degenerate(origin: Coordinate, unreachable: tuple[Coordinate, ...]) -> RoutePlan:
    return RoutePlan(route=LineString([origin, origin]), length_m=0.0, unreachable=unreachable)


def _clean_polygons(obstacles: Sequence[Sequence[Sequence[float]]], simplify_m: float = SIMPLIFY_M) -> list[Polygon]:
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
        simplified = polygon if simplify_m <= 0 else polygon.simplify(simplify_m, preserve_topology=True)
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


def _corridors(polygons: list[Polygon], blocked: BaseGeometry | None) -> list[_Corridor]:
    if blocked is None or len(polygons) < 2:
        return []
    axes = [(polygon, axis) for polygon in polygons if (axis := _strip_axis(polygon)) is not None]
    corridors: list[_Corridor] = []
    for index, (poly_a, axis_a) in enumerate(axes):
        for poly_b, axis_b in axes[index + 1 :]:
            if axis_a.distance(axis_b) > MAX_AXIS_SPACING_M:
                continue
            corridor = _gap_corridor(axis_a, axis_b, poly_a, poly_b, blocked)
            if corridor is not None:
                corridors.append(corridor)
    return corridors


def _strip_axis(polygon: Polygon) -> LineString | None:
    ring = _open_ring(polygon)
    if len(ring) < 4:
        return None
    longest = 0.0
    direction = (1.0, 0.0)
    for start, end in zip(ring, ring[1:] + ring[:1]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length > longest:
            longest = length
            direction = (dx / length, dy / length)
    if longest < 1.0:
        return None
    ux, uy = direction
    cx = sum(point[0] for point in ring) / len(ring)
    cy = sum(point[1] for point in ring) / len(ring)
    along = [(point[0] - cx) * ux + (point[1] - cy) * uy for point in ring]
    across = [(point[0] - cx) * -uy + (point[1] - cy) * ux for point in ring]
    span = max(along) - min(along)
    width = max(across) - min(across)
    if span < max(width * 1.5, 1.0):
        return None
    axis = LineString(
        [
            (cx + ux * min(along), cy + uy * min(along)),
            (cx + ux * max(along), cy + uy * max(along)),
        ]
    )
    if axis.length < 1.0 or not polygon.buffer(0.02).covers(axis):
        return None
    return axis


def _gap_corridor(
    axis_a: LineString,
    axis_b: LineString,
    poly_a: Polygon,
    poly_b: Polygon,
    blocked: BaseGeometry,
) -> _Corridor | None:
    ux, uy = _line_direction(axis_a)
    vx, vy = _line_direction(axis_b)
    dot = ux * vx + uy * vy
    if abs(dot) < PARALLEL_DOT:
        return None
    if dot < 0:
        vx, vy = -vx, -vy
        dot = -dot
    lo, hi = _overlap(axis_a, axis_b, (ux, uy))
    if hi - lo < 1.0:
        return None
    samples: list[Coordinate] = []
    halves: list[float] = []
    steps = 4
    for index in range(steps + 1):
        station = lo + (hi - lo) * index / steps
        point_a = _at_station(axis_a.coords[0], (ux, uy), station, (ux, uy))
        point_b = _at_station(axis_b.coords[0], (vx, vy), station, (ux, uy))
        middle = _free_middle(point_a, point_b, poly_a, poly_b, blocked)
        if middle is None:
            continue
        samples.append(middle[0])
        halves.append(middle[1] / 2)
    if len(samples) < 2:
        return None
    line = LineString(samples).simplify(SIMPLIFY_M, preserve_topology=False)
    if line.is_empty or line.geom_type != "LineString" or line.length < 1.0:
        return None
    if _enters_obstacle([(float(x), float(y)) for x, y in line.coords], blocked):
        return None
    return _Corridor(line, min(halves))


def _line_direction(line: LineString) -> tuple[float, float]:
    start, end = line.coords[0], line.coords[-1]
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    return (dx / length, dy / length)


def _overlap(axis_a: LineString, axis_b: LineString, direction: tuple[float, float]) -> tuple[float, float]:
    ux, uy = direction

    def project(point: Coordinate) -> float:
        return point[0] * ux + point[1] * uy

    a_lo, a_hi = sorted((project(axis_a.coords[0]), project(axis_a.coords[-1])))
    b_lo, b_hi = sorted((project(axis_b.coords[0]), project(axis_b.coords[-1])))
    return max(a_lo, b_lo), min(a_hi, b_hi)


def _at_station(
    origin: Coordinate, step: tuple[float, float], station: float, axis: tuple[float, float]
) -> Coordinate:
    """Point on the line through `origin` along `step`, whose projection on `axis` is `station`."""
    ax, ay = axis
    sx, sy = step
    scale = sx * ax + sy * ay
    if abs(scale) < 1e-9:
        return origin
    distance = (station - (origin[0] * ax + origin[1] * ay)) / scale
    return (origin[0] + sx * distance, origin[1] + sy * distance)


def _free_middle(
    point_a: Coordinate,
    point_b: Coordinate,
    poly_a: Polygon,
    poly_b: Polygon,
    blocked: BaseGeometry,
) -> tuple[Coordinate, float] | None:
    if poly_a.distance(ShapelyPoint(*point_a)) > 0.05 or poly_b.distance(ShapelyPoint(*point_b)) > 0.05:
        return None
    segment = LineString([point_a, point_b])
    if segment.length < MIN_CORRIDOR_M:
        return None
    hits_a = _hit_distances(segment, segment.intersection(poly_a.boundary))
    hits_b = _hit_distances(segment, segment.intersection(poly_b.boundary))
    if not hits_a or not hits_b:
        return None
    facing = [(left, right) for left in hits_a for right in hits_b if right - left >= MIN_CORRIDOR_M]
    if not facing:
        return None
    exit_a, enter_b = min(facing, key=lambda pair: pair[1] - pair[0])
    width = enter_b - exit_a
    if width > MAX_CORRIDOR_M:
        return None
    gap = LineString([segment.interpolate(exit_a), segment.interpolate(enter_b)])
    middle = gap.interpolate(0.5, normalized=True)
    if blocked.covers(middle) or _enters_obstacle([(float(x), float(y)) for x, y in gap.coords], blocked):
        return None
    return (float(middle.x), float(middle.y)), width


def _hit_distances(segment: LineString, geometry: BaseGeometry) -> list[float]:
    if geometry.is_empty:
        return []
    kind = geometry.geom_type
    if kind == "Point":
        return [float(segment.project(geometry))]
    if kind in {"LineString", "LinearRing"}:
        return [float(segment.project(ShapelyPoint(xy))) for xy in (geometry.coords[0], geometry.coords[-1])]
    if not hasattr(geometry, "geoms"):
        return []
    found: list[float] = []
    for part in geometry.geoms:
        found.extend(_hit_distances(segment, part))
    return found


def _snap_to_centre(
    original: Coordinate, corridors: Sequence[_Corridor], blocked: BaseGeometry | None
) -> Point | None:
    if not corridors:
        return None
    origin = ShapelyPoint(*original)
    best: tuple[float, int, ShapelyPoint] | None = None
    for index, corridor in enumerate(corridors):
        along = float(corridor.line.project(origin))
        snapped = corridor.line.interpolate(along)
        distance = float(origin.distance(snapped))
        if distance > VISIT_LIMIT_M or _past_end(origin, corridor.line, along):
            continue
        if blocked is not None and blocked.covers(snapped):
            continue
        if best is None or distance < best[0] - CENTRE_TIE_M or (distance <= best[0] + CENTRE_TIE_M and index < best[1]):
            best = (distance, index, snapped)
    if best is None:
        return None
    return Point(best[2].x, best[2].y)


def _past_end(point: ShapelyPoint, line: LineString, along: float) -> bool:
    if 1e-4 < along < line.length - 1e-4:
        return False
    if along <= 1e-4:
        end, other = line.coords[0], line.coords[1]
    else:
        end, other = line.coords[-1], line.coords[-2]
    dx, dy = end[0] - other[0], end[1] - other[1]
    norm = math.hypot(dx, dy) or 1.0
    past = ((point.x - end[0]) * dx + (point.y - end[1]) * dy) / norm
    return past > PAST_END_M


def _straighten(route: LineString, corridors: Sequence[_Corridor], blocked: BaseGeometry | None) -> LineString:
    if not corridors or blocked is None:
        return route
    coords = [(float(x), float(y)) for x, y in route.coords]
    if len(coords) < 3:
        return route
    assigned = [_corridor_index(point, corridors) for point in coords]
    straightened: list[Coordinate] = []
    index = 0
    while index < len(coords):
        corridor_index = assigned[index]
        end = index + 1
        if corridor_index is not None:
            while end < len(coords) and assigned[end] == corridor_index:
                end += 1
        run = coords[index:end]
        if corridor_index is not None and len(run) >= 2:
            previous = straightened[-1] if straightened else None
            following = coords[end] if end < len(coords) else None
            replaced = _replace_run(run, corridors[corridor_index], blocked, previous, following)
            if replaced is not None:
                run = replaced
        for point in run:
            if not straightened or math.hypot(straightened[-1][0] - point[0], straightened[-1][1] - point[1]) > 1e-6:
                straightened.append(point)
        index = end
    if len(straightened) < 2 or _enters_obstacle(straightened, blocked):
        return route
    return LineString(straightened)


def _corridor_index(point: Coordinate, corridors: Sequence[_Corridor]) -> int | None:
    best: tuple[float, int] | None = None
    for index, corridor in enumerate(corridors):
        located = _locate(point, corridor)
        if located is None:
            continue
        distance = located[1]
        if best is None or distance < best[0]:
            best = (distance, index)
    return None if best is None else best[1]


def _locate(point: Coordinate, corridor: _Corridor) -> tuple[float, float] | None:
    place = ShapelyPoint(*point)
    along = float(corridor.line.project(place))
    snapped = corridor.line.interpolate(along)
    distance = float(place.distance(snapped))
    if distance > min(corridor.half_m + 0.05, VISIT_LIMIT_M) or _past_end(place, corridor.line, along):
        return None
    return along, distance


def _replace_run(
    run: list[Coordinate],
    corridor: _Corridor,
    blocked: BaseGeometry,
    previous: Coordinate | None,
    following: Coordinate | None,
) -> list[Coordinate] | None:
    located = []
    for point in run:
        found = _locate(point, corridor)
        if found is None:
            return None
        located.append(found)
    if max(distance for _, distance in located) <= 0.05:
        return None
    lo = min(along for along, _ in located)
    hi = max(along for along, _ in located)
    if hi - lo < 0.05:
        return None
    near_first = lo if abs(located[0][0] - lo) <= abs(located[0][0] - hi) else hi
    near_last = lo if abs(located[-1][0] - lo) <= abs(located[-1][0] - hi) else hi
    if near_first == near_last:
        other = hi if near_first == lo else lo
        span = _dedupe_coords(_span(corridor.line, near_first, other) + _span(corridor.line, other, near_last))
    else:
        span = _span(corridor.line, near_first, near_last)
    full = _dedupe_coords([run[0], *span, run[-1]])
    # A stop already on the centre line has to stay there. A wall hook may move as
    # far as the centre, which is how far it already sits from that line.
    allowances = [distance for _, distance in located]
    trimmed = list(full)
    if previous is not None and len(trimmed) >= 2 and not _enters_obstacle([previous, trimmed[1]], blocked):
        trimmed = trimmed[1:]
    if following is not None and len(trimmed) >= 2 and not _enters_obstacle([trimmed[-2], following], blocked):
        trimmed = trimmed[:-1]
    trimmed = _dedupe_coords(trimmed)
    if trimmed != full and _keeps_stops(trimmed, run, allowances, blocked):
        return trimmed
    if _keeps_stops(full, run, allowances, blocked):
        return full
    return None


def _keeps_stops(
    replacement: list[Coordinate],
    stops: list[Coordinate],
    allowances: list[float],
    blocked: BaseGeometry,
) -> bool:
    if len(replacement) < 2 or _enters_obstacle(replacement, blocked):
        return False
    line = LineString(replacement)
    return all(
        line.distance(ShapelyPoint(*stop)) <= allowance + 1e-4
        for stop, allowance in zip(stops, allowances)
    )


def _span(line: LineString, start: float, end: float) -> list[Coordinate]:
    reverse = start > end
    lo, hi = (end, start) if reverse else (start, end)
    coords = [_point_at(line, lo)]
    for x, y in line.coords:
        along = float(line.project(ShapelyPoint(x, y)))
        if lo + 1e-6 < along < hi - 1e-6:
            coords.append((float(x), float(y)))
    coords.append(_point_at(line, hi))
    if reverse:
        coords.reverse()
    return coords


def _point_at(line: LineString, distance: float) -> Coordinate:
    point = line.interpolate(distance)
    return (float(point.x), float(point.y))


def _dedupe_coords(coords: list[Coordinate]) -> list[Coordinate]:
    cleaned: list[Coordinate] = []
    for point in coords:
        xy = (float(point[0]), float(point[1]))
        if cleaned and math.hypot(cleaned[-1][0] - xy[0], cleaned[-1][1] - xy[1]) <= 1e-6:
            continue
        cleaned.append(xy)
    return cleaned


def _place_target(
    original: Coordinate, blocked: BaseGeometry | None, corridors: Sequence[_Corridor] = ()
) -> Point | None:
    # A stop on the side of an inter-row pulls the walk across the gap. The middle
    # is within the 2 m visit, so stand there instead.
    centred = _snap_to_centre(original, corridors, blocked)
    if centred is not None:
        return centred
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
    # The visibility sweep marks some segments as clear when they cut through another
    # row. Those are not walkable. What remains goes around the obstacles.
    _drop_blocked_edges(graph, polygons)
    return graph


def _drop_blocked_edges(graph: VisGraph, polygons: Sequence[Polygon]) -> None:
    if graph.visgraph is None or not polygons:
        return
    solids = [polygon for polygon in polygons if not polygon.is_empty]
    if not solids:
        return
    tree = STRtree(solids)
    blocked_edges = []
    for edge in graph.visgraph.edges:
        coords = [(edge.p1.x, edge.p1.y), (edge.p2.x, edge.p2.y)]
        line = LineString(coords)
        if line.length == 0:
            continue
        for index in tree.query(line, predicate="intersects"):
            if _enters_obstacle(coords, solids[int(index)]):
                blocked_edges.append(edge)
                break
    vis = graph.visgraph
    for edge in blocked_edges:
        vis.edges.discard(edge)
        vis.graph[edge.p1].discard(edge)
        vis.graph[edge.p2].discard(edge)


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


def _avoid_canopies(
    line: LineString,
    canopies: Sequence[Polygon],
    blocked: BaseGeometry | None,
    targets: Sequence[Coordinate],
) -> LineString:
    """Bend a finished walk around canopy rings without giving up a stop it already reached."""
    solids = [polygon for polygon in canopies if isinstance(polygon, Polygon) and not polygon.is_empty]
    if not solids or line.length == 0:
        return line
    coords = _dedupe_coords([(float(x), float(y)) for x, y in line.coords])
    if len(coords) < 2:
        return line
    tree = STRtree(solids)
    coords = _snap_off_canopies(coords, solids, tree, blocked, targets, line)
    # A long alley segment can cross many vines. Clear every one of them before
    # judging the walk, including the return trip over the same ground.
    updated = _skirt_walk(coords, solids, tree, blocked, targets, line)
    if updated is not None:
        coords = updated
    result = LineString(coords)
    if blocked is not None and _enters_obstacle(coords, blocked):
        return line
    if not _visits_kept(line, result, targets):
        return line
    return result


def _snap_off_canopies(
    coords: list[Coordinate],
    canopies: Sequence[Polygon],
    tree: STRtree,
    blocked: BaseGeometry | None,
    targets: Sequence[Coordinate],
    before: LineString,
) -> list[Coordinate]:
    """Move a vertex that sits inside a canopy onto the nearest free edge."""
    snapped = list(coords)
    last = len(coords) - 1
    for index, point in enumerate(coords):
        if index == 0 or index == last:
            continue
        place = ShapelyPoint(*point)
        polygon = _containing_canopy(place, canopies, tree)
        if polygon is None:
            continue
        free: BaseGeometry = polygon.exterior
        if blocked is not None:
            free = polygon.exterior.difference(blocked)
        if free.is_empty:
            continue
        nearest = nearest_points(place, free)[1]
        if place.distance(nearest) > VISIT_LIMIT_M:
            continue
        nudged = _nudge_outside(nearest, polygon, blocked)
        trial = list(snapped)
        trial[index] = (float(nudged.x), float(nudged.y))
        trial_coords = _dedupe_coords(trial)
        if len(trial_coords) < 2:
            continue
        if blocked is not None and _enters_obstacle(trial_coords, blocked):
            continue
        if not _visits_kept(before, LineString(trial_coords), targets):
            continue
        snapped = trial
    return _dedupe_coords(snapped)


def _containing_canopy(place: ShapelyPoint, canopies: Sequence[Polygon], tree: STRtree) -> Polygon | None:
    for index in tree.query(place):
        polygon = canopies[int(index)]
        if polygon.contains(place):
            return polygon
    return None


def _nudge_outside(point: ShapelyPoint, polygon: Polygon, blocked: BaseGeometry | None) -> ShapelyPoint:
    dx = point.x - polygon.centroid.x
    dy = point.y - polygon.centroid.y
    norm = math.hypot(dx, dy) or 1.0
    nudged = ShapelyPoint(point.x + dx / norm * OUTSIDE_GAP_M, point.y + dy / norm * OUTSIDE_GAP_M)
    if polygon.contains(nudged):
        return point
    if blocked is not None and blocked.covers(nudged):
        return point
    return nudged


def _skirt_walk(
    coords: list[Coordinate],
    canopies: Sequence[Polygon],
    tree: STRtree,
    blocked: BaseGeometry | None,
    targets: Sequence[Coordinate],
    before: LineString,
) -> list[Coordinate]:
    """Repeat until a pass no longer removes a canopy crossing.

    An arc around one vine can cut the next one. The next pass bends around that too.
    """
    current = coords
    crossings = _crossing_segments(current, canopies, tree)
    for _ in range(8):
        if crossings == 0:
            break
        walked: list[Coordinate] = []
        for index in range(len(current) - 1):
            cleared = _clear_segment(current[index], current[index + 1], canopies, tree, blocked)
            walked.extend(cleared if not walked else cleared[1:])
        walked = _dedupe_coords(walked)
        if len(walked) < 2:
            break
        if blocked is not None and _enters_obstacle(walked, blocked):
            break
        if not _visits_kept(before, LineString(walked), targets):
            break
        updated = _crossing_segments(walked, canopies, tree)
        if updated >= crossings:
            break
        current = walked
        crossings = updated
    return current


def _crossing_segments(coords: list[Coordinate], canopies: Sequence[Polygon], tree: STRtree) -> int:
    hits = 0
    for index in range(len(coords) - 1):
        segment = [coords[index], coords[index + 1]]
        if math.hypot(segment[1][0] - segment[0][0], segment[1][1] - segment[0][1]) <= 1e-6:
            continue
        seg_line = LineString(segment)
        for found in tree.query(seg_line, predicate="intersects"):
            if _enters_obstacle(segment, canopies[int(found)]):
                hits += 1
                break
    return hits


def _clear_segment(
    start: Coordinate,
    end: Coordinate,
    canopies: Sequence[Polygon],
    tree: STRtree,
    blocked: BaseGeometry | None,
) -> list[Coordinate]:
    """Walk from `start` to `end`, bending around each canopy the straight segment enters."""
    points = [start]
    cursor = start
    for _ in range(len(canopies) + 1):
        if math.hypot(end[0] - cursor[0], end[1] - cursor[1]) <= 1e-6:
            break
        segment = [cursor, end]
        hit = _earliest_canopy(segment, canopies, tree)
        if hit is None:
            break
        polygon, part = hit
        arc = _free_arc(polygon, part, blocked)
        if arc is None:
            break
        piece = _dedupe_coords([cursor, *arc])
        if len(piece) < 2 or _enters_obstacle(piece, polygon):
            break
        if blocked is not None and _enters_obstacle(piece, blocked):
            break
        if math.hypot(piece[-1][0] - cursor[0], piece[-1][1] - cursor[1]) <= 1e-6:
            break
        points.extend(piece[1:])
        cursor = points[-1]
    if math.hypot(points[-1][0] - end[0], points[-1][1] - end[1]) > 1e-6:
        points.append(end)
    return points


def _earliest_canopy(
    segment: list[Coordinate], canopies: Sequence[Polygon], tree: STRtree
) -> tuple[Polygon, LineString] | None:
    seg_line = LineString(segment)
    best: tuple[float, Polygon, LineString] | None = None
    for index in tree.query(seg_line, predicate="intersects"):
        polygon = canopies[int(index)]
        if not _enters_obstacle(segment, polygon):
            continue
        parts = _line_parts(seg_line.intersection(polygon))
        if not parts:
            continue
        part = min(parts, key=lambda item: float(seg_line.project(ShapelyPoint(item.coords[0]))))
        if float(seg_line.project(ShapelyPoint(part.coords[-1]))) < float(seg_line.project(ShapelyPoint(part.coords[0]))):
            part = LineString(list(reversed(part.coords)))
        distance = float(seg_line.project(ShapelyPoint(part.coords[0])))
        if best is None or distance < best[0] - 1e-9:
            best = (distance, polygon, part)
    if best is None:
        return None
    return best[1], best[2]


def _line_parts(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > CROSSING_M else []
    if not hasattr(geometry, "geoms"):
        return []
    parts: list[LineString] = []
    for part in geometry.geoms:
        parts.extend(_line_parts(part))
    return parts


def _free_arc(polygon: Polygon, part: LineString, blocked: BaseGeometry | None) -> list[Coordinate] | None:
    ends = (
        (float(part.coords[0][0]), float(part.coords[0][1])),
        (float(part.coords[-1][0]), float(part.coords[-1][1])),
    )
    if any(_deep_inside(polygon, point) for point in ends):
        return None
    ring = LineString(polygon.exterior.coords)
    if ring.length == 0:
        return None
    start = float(ring.project(ShapelyPoint(*ends[0])))
    end = float(ring.project(ShapelyPoint(*ends[1])))
    candidates = [_ring_arc(ring, start, end), list(reversed(_ring_arc(ring, end, start)))]
    free: list[tuple[float, list[Coordinate]]] = []
    for arc in candidates:
        cleaned = _dedupe_coords(arc)
        # A chord of the outline can sit just inside the foliage. Step out only then.
        if len(cleaned) >= 2 and _enters_obstacle(cleaned, polygon):
            cleaned = _step_outside(cleaned, polygon)
        if len(cleaned) < 2 or _enters_obstacle(cleaned, polygon):
            continue
        if blocked is not None and _enters_obstacle(cleaned, blocked):
            continue
        free.append((float(LineString(cleaned).length), cleaned))
    if not free:
        return None
    free.sort(key=lambda item: item[0])
    return free[0][1]


# Far enough to clear a boundary chord, and still short of the next vine.
CANOPY_CLEARANCE_M = 0.03


def _step_outside(arc: list[Coordinate], polygon: Polygon, gap: float = CANOPY_CLEARANCE_M) -> list[Coordinate]:
    centre = polygon.centroid
    stepped: list[Coordinate] = []
    for x, y in arc:
        dx, dy = x - centre.x, y - centre.y
        norm = math.hypot(dx, dy) or 1.0
        outward = (x + dx / norm * gap, y + dy / norm * gap)
        if polygon.contains(ShapelyPoint(*outward)):
            outward = (x - dx / norm * gap, y - dy / norm * gap)
        stepped.append(outward)
    return _dedupe_coords(stepped)


def _deep_inside(polygon: Polygon, point: Coordinate) -> bool:
    place = ShapelyPoint(*point)
    return polygon.contains(place) and polygon.boundary.distance(place) > 1e-3


def _ring_arc(ring: LineString, start: float, end: float) -> list[Coordinate]:
    length = float(ring.length)
    if length == 0:
        return []
    start %= length
    end %= length
    span = (end - start) % length
    begin = ring.interpolate(start)
    finish = ring.interpolate(end)
    if span < 1e-9:
        return [(float(begin.x), float(begin.y))]
    coords = [(float(x), float(y)) for x, y in ring.coords]
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    travelled = 0.0
    mids: list[tuple[float, Coordinate]] = []
    previous: Coordinate | None = None
    for point in coords:
        if previous is not None:
            travelled += math.hypot(point[0] - previous[0], point[1] - previous[1])
        delta = (travelled - start) % length
        if 1e-6 < delta < span - 1e-6:
            mids.append((delta, point))
        previous = point
    mids.sort()
    return [(float(begin.x), float(begin.y)), *[point for _, point in mids], (float(finish.x), float(finish.y))]


def _visits_kept(before: LineString, after: LineString, targets: Sequence[Coordinate]) -> bool:
    for target in targets:
        place = ShapelyPoint(*target)
        if before.distance(place) <= VISIT_LIMIT_M + 1e-6 and after.distance(place) > VISIT_LIMIT_M + 1e-3:
            return False
    return True


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
