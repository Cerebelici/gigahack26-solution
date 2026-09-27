"""CVAT 1.1 annotations for a Marcaj Detection task. Waste boxes only.

Marcaj task types are classification, detection, polygon, and polyline.
Waste is detection, written as a <box>. vineyard_id stays empty: this model
does not know the block. Tiles with no box are omitted.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

LABELS = """<meta><task><name>Vineyard AI Field Challenge — waste</name><labels>
<label><name>waste</name><type>detection</type><attributes>
  <attribute><name>vineyard_id</name><mutable>False</mutable><input_type>text</input_type><default_value></default_value><values></values></attribute></attributes></label>
</labels></task></meta>"""


def waste_box(box: dict) -> str:
    return (
        '<box label="waste" source="manual" occluded="0" '
        f'xtl="{box["xtl"]:.2f}" ytl="{box["ytl"]:.2f}" '
        f'xbr="{box["xbr"]:.2f}" ybr="{box["ybr"]:.2f}" z_order="0">'
        '<attribute name="vineyard_id"></attribute></box>'
    )


def annotations_xml(records: list) -> str:
    images = []
    for record in records:
        if not record["boxes"]:
            continue
        boxes = "".join(waste_box(box) for box in record["boxes"])
        name = escape(record["image"])
        images.append(
            f'<image id="{len(images)}" name="{name}" width="{record["width"]}" height="{record["height"]}">'
            f"{boxes}</image>"
        )
    body = "\n".join(images)
    images_xml = f"{body}\n" if body else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<annotations>\n"
        "<version>1.1</version>\n"
        f"{LABELS}\n"
        f"{images_xml}"
        "</annotations>\n"
    )
