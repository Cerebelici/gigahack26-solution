import math

import pytest
from shapely.geometry import Point, Polygon
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
