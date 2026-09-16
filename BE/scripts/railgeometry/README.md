# KTDB 철도망 geometry 전처리

FE 요청(`KTDB_지하철_선로_연동_백엔드_공유.md`)에 따라 KTDB 철도망 shp를 CSV로 1회 변환한다.

## 원본

- [KTDB 철도망 다운로드](https://www.ktdb.go.kr/www/selectPbldataChargerWebList.do?key=12&searchClStepCode=106) — "2025-TM-GR-MR-AML 철도망(2024년 기준_세계)"
- `01. 철도교차점`(node, 1,652개), `02. 철도중심선`(link, 1,728개) — 각각 `.shp`/`.shx`/`.dbf`/`.prj` 세트
- 원본 파일은 용량·라이선스 문제로 레포에 포함하지 않는다. 재실행하려면 위 페이지에서 다시 받는다.

## 실행

```bash
# pyproj·pyshp가 설치된 파이썬 환경 필요 (예: miniforge3 ai_env)
pip install pyproj pyshp

python convert_ktdb.py \
  --input "<압축 해제한 '2025-TM-GR-MR-AML 철도망(...)' 폴더>" \
  --output "../../src/main/resources/data/railgeometry"
```

## 산출물

`BE/src/main/resources/data/railgeometry/`에 커밋됨:

- `ktdb-rail-node_2024.csv` — `node_id, lat, lng, station_name_raw`
- `ktdb-rail-link_2024.csv` — `link_id, from_node_id, to_node_id, line_name_raw, physical_line_name_raw, length_km, geometry_geojson`

`line_name_raw`는 KTDB의 `RAILLINEN3`(지하철·도시철도 서비스명, 예: `서울2호선`)이다. `RAILLINE_N`(물리 선로명, 예: `경부선`)과 다르다 — `서울1호선` 서비스는 `경부선`·`경원선`·`경인선`·`장항선` 등 여러 물리 선로에 걸쳐 있어서, 우리 노선(`line_id`)과 매칭할 때는 반드시 `line_name_raw` 기준으로 한다(`domain/route/geometry`의 line 별칭 테이블 참고).

좌표계 변환은 원본 `.prj`의 WKT(`Korea 2000 Katech(TM128)`)를 그대로 읽어 EPSG:4326으로 변환한다(`pyproj`, `always_xy=True`). DBF는 CP949로 읽는다.

## 알려진 제약

- link 1,728개 중 2개는 multi-part 도형이다 — 좌표를 그대로 이어붙였다(경고 로그로만 남김).
- `length_km` 단위는 원본 필드명 그대로 가정한 것이다(문서에 단위 명시 없음, 좌표 기반 거리와 대조해 km로 추정).
- PoC가 검증한 건 2호선(역삼→선릉→삼성→종합운동장역)·9호선(종합운동장역→당산역) 구간뿐이다. 전체 노선을 다 변환해서 테이블엔 넣지만, 우리 자체 노선 데이터(`line` 테이블, 17개)와 매칭되는 것만 실제로 쓰인다 — 나머지는 매칭 안 돼서 자연히 `unavailable`로 빠진다.
