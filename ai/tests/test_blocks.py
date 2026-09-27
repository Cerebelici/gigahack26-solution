"""Block grouping: gaps under 5 m merge, a barrier splits, ids run north to south."""

import numpy as np

from src.blocks.cluster import build_territories, order_blocks_north_west


def test_gap_under_5m_merges_and_wider_gap_splits():
    gsd = 1.0
    vine = np.zeros((1, 12), dtype=bool)
    vine[0, 0] = True
    vine[0, 4] = True  # 3 m of empty ground between the pixels' edges; centres 4 m
    vine[0, 11] = True  # centres 7 m from column 4, outside the grow radius
    valid = np.ones_like(vine)
    barrier = np.zeros_like(vine)
    labels = build_territories(
        vine, barrier, valid, gsd, gap_m=5.0, min_vine_m2=0.5, min_territory_m2=0.5
    )
    assert labels[0, 0] != 0
    assert labels[0, 0] == labels[0, 4]
    assert labels[0, 11] != labels[0, 0]


def test_barrier_splits_a_narrow_gap():
    gsd = 1.0
    vine = np.zeros((1, 8), dtype=bool)
    vine[0, 0] = True
    vine[0, 4] = True
    valid = np.ones_like(vine)
    barrier = np.zeros_like(vine)
    barrier[0, 2] = True
    labels = build_territories(
        vine, barrier, valid, gsd, gap_m=5.0, min_vine_m2=0.5, min_territory_m2=0.5
    )
    assert labels[0, 0] != 0 and labels[0, 4] != 0
    assert labels[0, 0] != labels[0, 4]
    assert labels[0, 2] == 0


def test_ids_run_from_the_north():
    labels = np.zeros((6, 4), dtype=np.int32)
    labels[4:6, 0:2] = 1
    labels[0:2, 2:4] = 2
    ordered, ids = order_blocks_north_west(labels, origin_x=0.0, origin_y=6.0, gsd=1.0)
    assert ids == [1, 2]
    assert ordered[0, 2] == 1
    assert ordered[4, 0] == 2
