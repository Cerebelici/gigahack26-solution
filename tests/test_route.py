import math

import pytest
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from app.services.route import StartInsideObstacle, plan_route


def _enters_interior(line, ring) -> bool:
    return line.intersects(Polygon(ring).buffer(-1e-4))


def test_zero_targets_returns_a_degenerate_route_at_the_start():
    obstacle = [(0, 0), (1, 0), (1, 1), (0, 1)]
    plan = plan_route([obstacle], (5.0, 5.0), [])

    assert list(plan.route.coords) == pytest.approx([(5.0, 5.0), (5.0, 5.0)])
    assert plan.length_m == 0
    assert plan.unreachable == ()


def test_start_inside_an_obstacle_is_rejected():
    obstacle = [(0, 0), (10, 0), (10, 10), (0, 10)]
    with pytest.raises(StartInsideObstacle, match="inside"):
        plan_route([obstacle], (5, 5), [(20, 20)])


def test_route_starts_and_ends_at_the_start():
    plan = plan_route([], (0, 0), [(3, 4)])

    assert list(plan.route.coords) == pytest.approx([(0, 0), (3, 4), (0, 0)])
    assert plan.length_m == pytest.approx(2 * math.hypot(3, 4))
    assert plan.unreachable == ()


def test_wall_forces_the_walk_to_go_around():
    wall = [(1, 0), (2, 0), (2, 4), (1, 4)]
    start = (0, 2)
    target = (4, 2)

    plan = plan_route([wall], start, [target])

    assert plan.length_m > math.dist(start, target) * 2
    assert not _enters_interior(plan.route, wall)
    assert list(plan.route.coords)[0] == pytest.approx(start)
    assert list(plan.route.coords)[-1] == pytest.approx(start)
    assert plan.route.distance(Point(target)) == pytest.approx(0, abs=1e-6)
    assert plan.unreachable == ()


def test_target_deep_inside_an_obstacle_is_unreachable():
    obstacle = [(0, 0), (30, 0), (30, 30), (0, 30)]
    start = (-5.0, 15.0)
    target = (15.0, 15.0)

    plan = plan_route([obstacle], start, [target])

    assert plan.unreachable == (target,)
    assert plan.length_m == 0
    assert list(plan.route.coords) == pytest.approx([start, start])
    assert plan.route.distance(Point(target)) > 2


def test_target_just_inside_a_thin_obstacle_is_visited():
    thin = [(10, 0), (10.4, 0), (10.4, 20), (10, 20)]
    start = (0.0, 10.0)
    target = (10.2, 10.0)

    plan = plan_route([thin], start, [target])

    assert plan.unreachable == ()
    assert plan.route.distance(Point(target)) < 2
    assert plan.route.distance(Point(target)) == pytest.approx(0.2, abs=0.05)
    assert not _enters_interior(plan.route, thin)
    assert list(plan.route.coords)[0] == pytest.approx(start)
    assert list(plan.route.coords)[-1] == pytest.approx(start)


def test_two_targets_are_visited_and_the_walk_returns():
    start = (0, 0)
    east = (5, 0)
    north = (0, 5)

    plan = plan_route([], start, [east, north])

    assert plan.unreachable == ()
    assert plan.route.distance(Point(east)) == pytest.approx(0, abs=1e-6)
    assert plan.route.distance(Point(north)) == pytest.approx(0, abs=1e-6)
    assert list(plan.route.coords)[0] == pytest.approx(start)
    assert list(plan.route.coords)[-1] == pytest.approx(start)
    assert plan.length_m == pytest.approx(10 + math.hypot(5, 5))


def test_duplicate_ring_vertices_still_force_a_walk_around_the_wall():
    wall = [(1, 0), (1, 0), (2, 0), (2, 4), (1, 4), (1, 0)]
    plan = plan_route([wall], (0, 2), [(4, 2)])

    assert plan.length_m > 8
    assert not _enters_interior(plan.route, [(1, 0), (2, 0), (2, 4), (1, 4)])
    assert plan.unreachable == ()


def test_two_point_row_is_not_an_obstacle():
    plan = plan_route([[(1, -1), (1, 5)]], (0, 0), [(2, 0)])

    assert list(plan.route.coords) == pytest.approx([(0, 0), (2, 0), (0, 0)])
    assert plan.length_m == pytest.approx(4)


def test_inter_row_is_walked_down_the_middle():
    def strip(x):
        return list(LineString([(x, 0), (x, 40)]).buffer(0.6, cap_style="flat").exterior.coords)

    rows = [strip(0), strip(2.5), strip(5)]
    targets = [(0, 10), (2.5, 25), (0, 30)]
    plan = plan_route(rows, (-3.0, -2.0), targets)

    assert plan.unreachable == ()
    walls = unary_union([Polygon(ring).buffer(-1e-3) for ring in rows])
    assert not plan.route.intersects(walls)
    for target in targets:
        assert plan.route.distance(Point(target)) <= 2

    # Away from the mouths, the part of the walk inside this alley is its centre line.
    distance = 0.0
    while distance <= plan.route.length:
        point = plan.route.interpolate(distance)
        if 1.0 < point.y < 39.0 and -0.5 < point.x < 3.2:
            assert point.x == pytest.approx(1.25, abs=0.05)
        distance += 0.25


def test_diagonal_inter_row_is_walked_down_the_middle():
    axis = (1 / math.sqrt(2), 1 / math.sqrt(2))
    normal = (-axis[1], axis[0])

    def strip(shift):
        start = (normal[0] * shift, normal[1] * shift)
        end = (start[0] + 40, start[1] + 40)
        return list(LineString([start, end]).buffer(0.6, cap_style="flat").exterior.coords)

    rows = [strip(0), strip(2.5)]
    targets = [(10, 10), (20, 20), (20 + normal[0] * 2.5, 20 + normal[1] * 2.5)]
    plan = plan_route(rows, (-4.0, -4.0), targets)

    assert plan.unreachable == ()
    walls = unary_union([Polygon(ring).buffer(-1e-3) for ring in rows])
    assert not plan.route.intersects(walls)
    for target in targets:
        assert plan.route.distance(Point(target)) <= 2

    distance = 0.0
    while distance <= plan.route.length:
        x, y = plan.route.interpolate(distance).coords[0]
        along = x * axis[0] + y * axis[1]
        shift = x * normal[0] + y * normal[1]
        if 5.0 < along < 35.0 and -0.5 < shift < 3.0:
            assert shift == pytest.approx(1.25, abs=0.08)
        distance += 0.25


def test_target_sealed_off_by_obstacles_is_unreachable():
    # The bars overlap at the corners, so the pocket is closed. The target is
    # outside every bar; the start cannot reach it without crossing one.
    bars = [
        [(-1, 0), (21, 0), (21, 4), (-1, 4)],
        [(-1, 16), (21, 16), (21, 20), (-1, 20)],
        [(-2, -2), (4, -2), (4, 22), (-2, 22)],
        [(16, -2), (22, -2), (22, 22), (16, 22)],
    ]
    start = (-10.0, 10.0)
    target = (10.0, 10.0)
    assert not unary_union([Polygon(ring) for ring in bars]).contains(Point(target))

    plan = plan_route(bars, start, [target])

    assert plan.unreachable == (target,)
    assert plan.length_m == 0
    assert list(plan.route.coords) == pytest.approx([start, start])



# Row axes of the example tile siret3_r021_c012 (EPSG:32635, mm). Before planning around the start,
# pyvisgraph's float tolerances let edges cut through these rows and 7 of the 9 targets came back unreachable.
EXAMPLE_ROWS = [
    [(629657.6, 5220146.397), (629656.845, 5220147.2)], [(629657.6, 5220142.23), (629653.573, 5220147.2)],
    [(629657.6, 5220137.393), (629650.007, 5220147.2)], [(629657.6, 5220132.98), (629646.565, 5220147.2)],
    [(629657.6, 5220127.963), (629642.748, 5220147.2)], [(629657.6, 5220123.22), (629639.27, 5220147.2)],
    [(629657.6, 5220118.59), (629635.627, 5220147.2)], [(629657.6, 5220113.815), (629631.627, 5220147.2)],
    [(629657.6, 5220109.285), (629628.11, 5220147.2)], [(629657.6, 5220103.05), (629623.485, 5220147.2)],
    [(629657.6, 5220097.055), (629618.978, 5220147.2)], [(629655.252, 5220096), (629615.845, 5220147.2)],
    [(629651.807, 5220096), (629612.517, 5220147.2)], [(629648.175, 5220096), (629609.198, 5220147.2)],
    [(629644.907, 5220096), (629606.4, 5220146.428)], [(629641.575, 5220096), (629606.4, 5220142.118)],
    [(629638.147, 5220096), (629606.4, 5220137.657)], [(629634.345, 5220096), (629606.4, 5220132.57)],
    [(629630.625, 5220096), (629606.4, 5220127.645)], [(629627, 5220096), (629606.4, 5220123.058)],
    [(629623.575, 5220096), (629606.4, 5220118.565)], [(629620.235, 5220096), (629606.4, 5220113.777)],
    [(629616.47, 5220096), (629606.4, 5220109.375)], [(629613.188, 5220096), (629606.4, 5220105.07)],
    [(629610.095, 5220096), (629606.4, 5220100.803)],
]


def test_buffered_rows_at_utm_coordinates_do_not_leak_through_the_visibility_graph():
    lines = [LineString(row) for row in EXAMPLE_ROWS]
    obstacles = [list(line.buffer(0.6, cap_style="flat").exterior.coords) for line in lines]
    start = (629603.8, 5220149.8)
    targets = [line.interpolate(0.5, normalized=True).coords[0] for line in lines[::3]]

    plan = plan_route(obstacles, start, targets)

    assert plan.unreachable == ()
    assert list(plan.route.coords)[0] == pytest.approx(start)
    assert list(plan.route.coords)[-1] == pytest.approx(start)
    walls = unary_union([Polygon(ring).buffer(-1e-3) for ring in obstacles])
    assert not plan.route.intersects(walls)
    for target in targets:
        assert plan.route.distance(Point(target)) <= 2.0


# Row axes from vineyard V08, the forty closest to the sample start. The visibility
# graph's shortest path cuts through these rows; a walk around them still reaches
# every axis.
V08_ROWS = [
    [(629515.573, 5220252.12), (629517.613, 5220249.6)],
    [(629504.0, 5220239.657), (629535.09, 5220198.4)],
    [(629515.665, 5220248.035), (629553.068, 5220198.4)],
    [(629514.448, 5220244.65), (629549.3, 5220198.4)],
    [(629513.65, 5220241.312), (629545.988, 5220198.4)],
    [(629517.79, 5220249.6), (629555.2, 5220199.955)],
    [(629518.9, 5220252.8), (629521.493, 5220249.6)],
    [(629521.085, 5220249.6), (629555.2, 5220204.328)],
    [(629521.435, 5220254.067), (629524.005, 5220250.893)],
    [(629515.052, 5220234.34), (629542.135, 5220198.4)],
    [(629524.225, 5220254.865), (629528.448, 5220249.65)],
    [(629524.74, 5220249.6), (629555.2, 5220209.177)],
    [(629513.588, 5220231.95), (629538.743, 5220198.57)],
    [(629528.188, 5220249.6), (629554.56, 5220214.603)],
    [(629529.458, 5220256.585), (629535.113, 5220249.6)],
    [(629511.21, 5220225.878), (629531.915, 5220198.4)],
    [(629531.78, 5220249.6), (629555.2, 5220218.523)],
    [(629534.93, 5220249.6), (629555.2, 5220222.7)],
    [(629534.99, 5220258.613), (629541.945, 5220250.02)],
    [(629519.517, 5220282.595), (629546.238, 5220249.6)],
    [(629538.225, 5220249.6), (629555.2, 5220227.072)],
    [(629528.243, 5220277.843), (629551.113, 5220249.6)],
    [(629541.795, 5220249.6), (629555.2, 5220231.81)],
    [(629530.188, 5220279.593), (629554.475, 5220249.6)],
    [(629545.405, 5220249.6), (629553.762, 5220238.508)],
    [(629522.56, 5220294.185), (629555.2, 5220253.878)],
    [(629546.598, 5220249.6), (629555.2, 5220238.182)],
    [(629550.113, 5220249.6), (629555.2, 5220242.848)],
    [(629551.145, 5220249.6), (629555.2, 5220244.22)],
    [(629551.588, 5220245.46), (629554.797, 5220241.197)],
    [(629529.27, 5220296.457), (629539.652, 5220283.633)],
    [(629551.608, 5220263.018), (629555.2, 5220258.58)],
    [(629528.255, 5220300.8), (629539.935, 5220286.375)],
    [(629555.2, 5220247.805), (629593.8, 5220198.4)],
    [(629555.2, 5220253.808), (629558.257, 5220249.6)],
    [(629555.2, 5220258.295), (629561.517, 5220249.6)],
    [(629555.2, 5220242.733), (629589.835, 5220198.4)],
    [(629555.2, 5220263.07), (629564.985, 5220249.6)],
    [(629555.2, 5220236.758), (629585.17, 5220198.4)],
    [(629557.637, 5220249.35), (629597.443, 5220198.4)],
]


def test_targets_between_rows_are_reached_by_walking_around_them():
    lines = [LineString(row) for row in V08_ROWS]
    obstacles = [list(line.buffer(0.6, cap_style="flat").exterior.coords) for line in lines]
    start = (629504.7, 5220250.75)
    targets = [tuple(line.interpolate(0.5, normalized=True).coords[0]) for line in lines]

    plan = plan_route(obstacles, start, targets)

    assert plan.unreachable == ()
    walls = unary_union([Polygon(ring).buffer(-1e-3) for ring in obstacles])
    assert not plan.route.intersects(walls)
    for target in targets:
        assert plan.route.distance(Point(target)) <= 2.0
    assert list(plan.route.coords)[0] == pytest.approx(start)
    assert list(plan.route.coords)[-1] == pytest.approx(start)
