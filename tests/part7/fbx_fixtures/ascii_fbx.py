"""A synthetic text (ASCII) FBX 7.3 file with one static box figure (TICKET-341).

Blender's importer refuses text FBX, so this file exercises the FBX2glTF fallback. Stdlib only; the tests import
`write(path)`.
"""

from __future__ import annotations

from pathlib import Path

HEIGHT_CM = 175.0  # FBX's default unit is the centimetre


def _box() -> tuple[list[float], list[int]]:
    w, d, h = 40.0, 20.0, HEIGHT_CM
    corners = [(x, y, z) for z in (0.0, h) for y in (-d / 2, d / 2) for x in (-w / 2, w / 2)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    verts = [c for corner in corners for c in corner]
    index: list[int] = []
    for face in faces:
        index.extend(face[:-1])
        index.append(-face[-1] - 1)  # FBX marks the last corner of a polygon with a negated index minus one
    return verts, index


def text() -> str:
    verts, index = _box()
    return f"""; FBX 7.3.0 project file
; ----------------------------------------------------

FBXHeaderExtension:  {{
\tFBXHeaderVersion: 1003
\tFBXVersion: 7300
}}
GlobalSettings:  {{
\tVersion: 1000
\tProperties70:  {{
\t\tP: "UpAxis", "int", "Integer", "",2
\t\tP: "UpAxisSign", "int", "Integer", "",1
\t\tP: "FrontAxis", "int", "Integer", "",1
\t\tP: "FrontAxisSign", "int", "Integer", "",-1
\t\tP: "CoordAxis", "int", "Integer", "",0
\t\tP: "CoordAxisSign", "int", "Integer", "",1
\t\tP: "UnitScaleFactor", "double", "Number", "",1
\t}}
}}
Definitions:  {{
\tVersion: 100
\tCount: 2
\tObjectType: "Model" {{
\t\tCount: 1
\t}}
\tObjectType: "Geometry" {{
\t\tCount: 1
\t}}
}}
Objects:  {{
\tGeometry: 1000, "Geometry::Body", "Mesh" {{
\t\tVertices: *{len(verts)} {{
\t\t\ta: {",".join(f"{v:g}" for v in verts)}
\t\t}}
\t\tPolygonVertexIndex: *{len(index)} {{
\t\t\ta: {",".join(str(i) for i in index)}
\t\t}}
\t\tGeometryVersion: 124
\t}}
\tModel: 2000, "Model::Body", "Mesh" {{
\t\tVersion: 232
\t\tProperties70:  {{
\t\t}}
\t}}
}}
Connections:  {{
\tC: "OO",1000,2000
\tC: "OO",2000,0
}}
"""


def write(path: str | Path) -> Path:
    path = Path(path)
    path.write_text(text(), encoding="ascii")
    return path


if __name__ == "__main__":
    import sys

    write(sys.argv[1])
