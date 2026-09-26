from app.services.cvat_annotations import annotations_for_filename, parse_annotations

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <version>1.1</version>
  <image id="0" name="tile.tif" width="100" height="80">
    <box id="w1" label="waste" xtl="1.5" ytl="2" xbr="4" ybr="6.25">
      <attribute name="vineyard_id">V09</attribute>
    </box>
    <polygon label="vineyard" points="0,0;1.25,2;3,0.5">
      <attribute name="vineyard_id">V09</attribute>
    </polygon>
    <polyline label="row" points="10,1;20,2;30.5,4"/>
    <polygon label="interrow_area" points="0,0;1,0;0,1" id="gap"/>
  </image>
  <image id="1" name="other.tif" width="2" height="2">
    <polygon label="vineyard" points="0,0;1,0;0,1"/>
  </image>
</annotations>
"""


def test_rectangle_becomes_four_points_and_polygon_parses():
    images = parse_annotations(SAMPLE)
    items = images["tile.tif"]["items"]
    assert images["tile.tif"]["width"] == 100
    assert images["tile.tif"]["height"] == 80

    box, polygon, row, interrow = items
    assert box == {
        "id": "w1",
        "label": "waste",
        "shape": "rectangle",
        "points": [[1.5, 2.0], [4.0, 2.0], [4.0, 6.25], [1.5, 6.25]],
        "attributes": {"vineyard_id": "V09"},
    }
    assert polygon == {
        "label": "vineyard",
        "shape": "polygon",
        "points": [[0.0, 0.0], [1.25, 2.0], [3.0, 0.5]],
        "attributes": {"vineyard_id": "V09"},
    }
    assert "id" not in row
    assert row["shape"] == "polyline"
    assert row["points"] == [[10.0, 1.0], [20.0, 2.0], [30.5, 4.0]]
    assert row["attributes"] == {}
    assert interrow["id"] == "gap"
    assert interrow["shape"] == "polygon"
    assert images["other.tif"]["items"][0]["label"] == "vineyard"
    assert len(images["other.tif"]["items"]) == 1


def test_filename_match_is_basename_exact():
    first = annotations_for_filename(r"mosaic\siret3_r021_c012.tif")
    second = annotations_for_filename("dir/siret3_r006_c004.tif")
    assert first is not None and second is not None
    assert first["image"] == "siret3_r021_c012.tif"
    assert second["image"] == "siret3_r006_c004.tif"
    assert first["items"] != second["items"]
    assert annotations_for_filename("siret3_r021_c012.tiff") is None
    assert annotations_for_filename("siret3_r021_c012.tif.bak") is None
    assert annotations_for_filename("not_siret3_r021_c012.tif") is None
    assert annotations_for_filename(None) is None
