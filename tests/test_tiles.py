import numpy as np

from app.services.tiles import _erase_source_frames


def _rgb(height: int, width: int, color: tuple[int, int, int]) -> np.ndarray:
    image = np.empty((3, height, width), dtype=np.uint8)
    image[0], image[1], image[2] = color
    return image


def _paint(image: np.ndarray, rows: slice, cols: slice, color: tuple[int, int, int]) -> None:
    image[0, rows, cols] = color[0]
    image[1, rows, cols] = color[1]
    image[2, rows, cols] = color[2]


def test_vertical_magenta_frame_is_filled_from_both_sides():
    image = _rgb(5, 7, (20, 80, 30))
    _paint(image, slice(None), slice(0, 3), (20, 80, 30))
    _paint(image, slice(None), slice(4, 7), (180, 60, 40))
    _paint(image, slice(None), 3, (255, 0, 255))
    mask = np.full((5, 7), 255, dtype=np.uint8)

    rgb, valid = _erase_source_frames(image, mask)

    assert not ((rgb[0] == 255) & (rgb[1] == 0) & (rgb[2] == 255)).any()
    assert valid.min() == 255
    # The missing column is filled from the imagery on the left.
    assert tuple(rgb[:, 2, 3]) == (20, 80, 30)
    assert tuple(rgb[:, 2, 0]) == (20, 80, 30)
    assert tuple(rgb[:, 2, 6]) == (180, 60, 40)


def test_horizontal_frame_and_crossing_are_removed():
    image = _rgb(7, 7, (30, 90, 40))
    _paint(image, 3, slice(None), (255, 0, 255))
    _paint(image, slice(None), 3, (255, 0, 255))
    mask = np.full(image.shape[1:], 255, dtype=np.uint8)

    rgb, valid = _erase_source_frames(image, mask)

    assert not ((rgb[0] > 200) & (rgb[2] > 200) & (rgb[1] < 40)).any()
    assert valid.min() == 255
    assert tuple(rgb[:, 0, 0]) == (30, 90, 40)


def test_frame_beside_empty_space_copies_the_imagery():
    image = _rgb(4, 6, (0, 0, 0))
    _paint(image, slice(None), slice(3, 6), (40, 120, 50))
    _paint(image, slice(None), slice(1, 3), (255, 0, 255))
    mask = np.zeros(image.shape[1:], dtype=np.uint8)
    mask[:, 1:] = 255

    rgb, valid = _erase_source_frames(image, mask)

    assert (valid[:, 1:] == 255).all()
    assert np.all(rgb[1, :, 1:3] == 120)
    assert (valid[:, 0] == 0).all()


def test_ordinary_colors_stay_put():
    image = _rgb(6, 8, (40, 110, 50))
    _paint(image, slice(1, 4), slice(2, 5), (190, 40, 45))
    mask = np.full(image.shape[1:], 255, dtype=np.uint8)
    before = image.copy()

    rgb, valid = _erase_source_frames(image, mask)

    assert np.array_equal(rgb, before)
    assert np.array_equal(valid, mask)


def test_averaged_overview_line_is_removed():
    image = _rgb(8, 6, (110, 120, 80))
    _paint(image, slice(None), 2, (174, 85, 160))
    _paint(image, slice(None), 3, (167, 79, 152))
    mask = np.full(image.shape[1:], 255, dtype=np.uint8)

    rgb, _valid = _erase_source_frames(image, mask)

    assert rgb[0, 4, 2] < 150
    assert rgb[2, 4, 2] < 140
    assert tuple(rgb[:, 0, 0]) == (110, 120, 80)
