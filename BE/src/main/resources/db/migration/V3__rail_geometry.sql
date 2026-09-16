-- KTDB 철도망 geometry (node/link). 기존 station/line/edge_time과는 별도 좌표 그래프다 —
-- ID 체계가 다르고(KTDB RAILNODE_I/RAILLINK_I) 시간이 아니라 "모양"만 담는다.
-- BE/docs/api/api-spec.md, BE/scripts/railgeometry/README.md 참고.

CREATE TABLE rail_node ( -- KTDB 철도교차점(node) 마스터
  node_id          VARCHAR(24) NOT NULL, -- KTDB RAILNODE_I
  lat              DOUBLE PRECISION NOT NULL, -- 위도 (WGS84, 원본 TM128에서 변환)
  lng              DOUBLE PRECISION NOT NULL, -- 경도 (WGS84)
  station_name_raw VARCHAR(100), -- KTDB STATION_NA 원본 표기 (참고용, 우리 station.name과 다를 수 있음)
  updated_at       TIMESTAMPTZ,
  PRIMARY KEY (node_id)
);

CREATE TABLE rail_link_geometry ( -- KTDB 철도중심선(link) — 역 사이 실제 선로 좌표
  link_id                 VARCHAR(24) NOT NULL, -- KTDB RAILLINK_I
  from_node_id            VARCHAR(24) NOT NULL, -- KTDB FROM_RAILN (저장 방향, 탐색 방향과 다를 수 있음)
  to_node_id              VARCHAR(24) NOT NULL, -- KTDB TO_RAILNOD
  line_name_raw           VARCHAR(100) NOT NULL, -- KTDB RAILLINEN3 (지하철·도시철도 서비스명, 예: 서울2호선)
  physical_line_name_raw  VARCHAR(100), -- KTDB RAILLINE_N (물리 선로명, 예: 경부선). 참고·디버깅용
  line_id                 VARCHAR(16), -- line.line_id 매칭 결과. 못 찾으면 NULL(우리 노선표 밖 — 정상)
  length_km               NUMERIC(10, 3),
  geometry                JSONB NOT NULL, -- GeoJSON LineString {"type","coordinates":[[lng,lat],...]}
  updated_at              TIMESTAMPTZ,
  PRIMARY KEY (link_id)
);

CREATE INDEX idx_rail_link_geometry_line_id ON rail_link_geometry (line_id);
CREATE INDEX idx_rail_link_geometry_nodes ON rail_link_geometry (from_node_id, to_node_id);
