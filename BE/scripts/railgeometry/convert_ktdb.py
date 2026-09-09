"""KTDB 철도망 shp -> BE 정적 데이터 CSV 변환 (1회성 전처리).

원본: KTDB 철도망 다운로드 페이지(https://www.ktdb.go.kr/www/selectPbldataChargerWebList.do?key=12)
      "2025-TM-GR-MR-AML 철도망(2024년 기준_세계)" — 01.철도교차점(node), 02.철도중심선(link) shp 세트.
문서: KTDB_지하철_선로_연동_백엔드_공유.md (FE 인수인계).

좌표계: 원본 .prj의 WKT("Korea 2000 Katech(TM128)")를 그대로 읽어 EPSG:4326으로 변환한다
(하드코딩한 EPSG 코드를 쓰지 않는다 — .prj가 정본이다). always_xy=True로 [경도, 위도] 순서를 보장한다.
DBF는 CP949로 인코딩되어 있다.

실행 (miniforge3 ai_env 등 pyproj·pyshp가 설치된 환경):
    pip install pyproj pyshp
    python convert_ktdb.py --input "<압축 해제한 폴더>" --output "../../src/main/resources/data/railgeometry"
"""
import argparse
import csv
import json
from pathlib import Path

import pyproj
import shapefile


def convert(input_dir: Path, output_dir: Path) -> None:
    node_shp = input_dir / "01. 철도교차점" / "af0302_2024_GR"
    link_shp = input_dir / "02. 철도중심선" / "af0022_2024_GR"

    wkt = (node_shp.with_suffix(".prj")).read_text(encoding="utf-8").strip()
    transformer = pyproj.Transformer.from_crs(wkt, "EPSG:4326", always_xy=True)

    def to_wgs84(x, y):
        lng, lat = transformer.transform(x, y)
        return round(lng, 8), round(lat, 8)

    nodes = []
    sf = shapefile.Reader(str(node_shp), encoding="cp949")
    for sr in sf.shapeRecords():
        d = sr.record.as_dict()
        if len(sr.shape.points) != 1:
            print("WARN node with != 1 point:", d.get("RAILNODE_I"), len(sr.shape.points))
        x, y = sr.shape.points[0]
        lng, lat = to_wgs84(x, y)
        nodes.append({
            "node_id": d.get("RAILNODE_I"),
            "lat": lat,
            "lng": lng,
            "station_name_raw": (d.get("STATION_NA") or "").strip(),
        })

    links = []
    multipart = 0
    sf = shapefile.Reader(str(link_shp), encoding="cp949")
    for sr in sf.shapeRecords():
        d = sr.record.as_dict()
        shape = sr.shape
        parts = list(shape.parts) + [len(shape.points)]
        if len(parts) > 2:
            multipart += 1
        coords = []
        for i in range(len(parts) - 1):
            segment_points = shape.points[parts[i]:parts[i + 1]]
            coords.extend(to_wgs84(x, y) for x, y in segment_points)
        links.append({
            "link_id": d.get("RAILLINK_I"),
            "from_node_id": d.get("FROM_RAILN"),
            "to_node_id": d.get("TO_RAILNOD"),
            # RAILLINEN3 = 지하철·도시철도 서비스명(예: 서울2호선). RAILLINE_N = 물리 선로명(예: 경부선).
            # 같은 서비스명이 여러 물리 선로에 걸쳐 나타날 수 있어(예: 서울1호선 = 경부선+경원선+경인선+장항선),
            # 서비스 매칭은 반드시 line_name_raw(RAILLINEN3) 기준으로 한다.
            "line_name_raw": (d.get("RAILLINEN3") or "").strip(),
            "physical_line_name_raw": (d.get("RAILLINE_N") or "").strip(),
            "length_km": d.get("LENGTH"),
            "geometry_geojson": json.dumps(
                {"type": "LineString", "coordinates": [[c[0], c[1]] for c in coords]},
                ensure_ascii=False,
            ),
        })
    print(f"multi-part link shapes: {multipart} / {len(links)} (그대로 이어붙여 처리함)")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "ktdb-rail-node_2024.csv", nodes,
               ["node_id", "lat", "lng", "station_name_raw"])
    _write_csv(output_dir / "ktdb-rail-link_2024.csv", links,
               ["link_id", "from_node_id", "to_node_id", "line_name_raw",
                "physical_line_name_raw", "length_km", "geometry_geojson"])


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                         help="압축 해제한 'YYYY-TM-GR-MR-AML 철도망(...)' 폴더 경로")
    parser.add_argument("--output", required=True, type=Path,
                         help="CSV를 저장할 폴더 (BE/src/main/resources/data/railgeometry)")
    args = parser.parse_args()
    convert(args.input, args.output)
