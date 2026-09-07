-- V1: 탐색용 테이블 9종 (마스터 5 + 산출 4, design.html 3절 기준).
-- 의존성 순: 정점·노선 마스터 → 엣지·지표.

CREATE TABLE station ( -- 역 마스터
  station_id VARCHAR(24) NOT NULL, -- 역 ID (원천 코드 그대로)
  name       VARCHAR(100) NOT NULL, -- 역 이름
  lat        DOUBLE PRECISION, -- 위도 (WGS84)
  lng        DOUBLE PRECISION, -- 경도 (WGS84)
  updated_at TIMESTAMPTZ, -- 적재 시각
  PRIMARY KEY (station_id)
);

CREATE TABLE bus_stop ( -- 버스 정류소 마스터
  stop_id VARCHAR(24) NOT NULL, -- 정류소 ID (원천 코드 그대로)
  name    VARCHAR(100) NOT NULL, -- 정류소 이름
  lat     DOUBLE PRECISION, -- 위도 (WGS84)
  lng     DOUBLE PRECISION, -- 경도 (WGS84)
  updated_at TIMESTAMPTZ, -- 적재 시각
  PRIMARY KEY (stop_id)
);

CREATE TABLE bike_station ( -- 따릉이 대여소 마스터
  rental_id VARCHAR(24) NOT NULL, -- 대여소 ID
  name      VARCHAR(100) NOT NULL, -- 대여소 이름
  lat       DOUBLE PRECISION, -- 위도 (WGS84)
  lng       DOUBLE PRECISION, -- 경도 (WGS84)
  dock_count INTEGER, -- 거치대 수
  updated_at TIMESTAMPTZ, -- 적재 시각
  PRIMARY KEY (rental_id)
);

CREATE TABLE line ( -- 지하철 노선 마스터
  line_id VARCHAR(16) NOT NULL, -- 노선 ID
  name    VARCHAR(50) NOT NULL, -- 노선 이름 (2호선)
  updated_at TIMESTAMPTZ, -- 적재 시각
  PRIMARY KEY (line_id)
);

CREATE TABLE bus_route ( -- 버스 노선 마스터
  route_id VARCHAR(24) NOT NULL, -- 노선 ID (원천 코드 그대로)
  name     VARCHAR(50) NOT NULL, -- 노선 번호·이름 (360)
  updated_at TIMESTAMPTZ, -- 적재 시각
  PRIMARY KEY (route_id)
);

CREATE TABLE edge_time ( -- 구간 소요시간 (탐색 그래프 엣지)
  from_node  VARCHAR(24) NOT NULL, -- 출발 노드 ID
  to_node    VARCHAR(24) NOT NULL, -- 도착 노드 ID
  mode       VARCHAR(8) NOT NULL, -- WALK|BIKE|BUS|SUBWAY|TRANSFER
  dow_type   INTEGER NOT NULL, -- 0 평일 / 1 토 / 2 일·공휴일
  time_slot  INTEGER NOT NULL, -- 30분 단위 슬롯 (0~47)
  travel_sec INTEGER NOT NULL, -- 구간 이동 초
  wait_sec   INTEGER NOT NULL DEFAULT 0, -- 대기 초 (버스·지하철)
  source     VARCHAR(8) NOT NULL, -- timetable|avg|model
  updated_at TIMESTAMPTZ NOT NULL, -- 적재 시각
  PRIMARY KEY (from_node, to_node, mode, dow_type, time_slot)
);

CREATE TABLE congestion ( -- 혼잡도 통계
  target_type VARCHAR(8) NOT NULL, -- STATION|LINE|ROUTE
  target_id   VARCHAR(24) NOT NULL, -- 대상 ID
  dow_type    INTEGER NOT NULL, -- 0 평일 / 1 토 / 2 일·공휴일
  time_slot   INTEGER NOT NULL, -- 30분 단위 슬롯 (0~47)
  level       NUMERIC(4,1) NOT NULL, -- 혼잡도 0.0~100.0
  source      VARCHAR(8) NOT NULL, -- stat|live
  updated_at  TIMESTAMPTZ NOT NULL, -- 적재 시각
  PRIMARY KEY (target_type, target_id, dow_type, time_slot)
);

CREATE TABLE bike_stock_pred ( -- 대여소 재고 예측 (도착 예상 시각 기준 조회)
  rental_id VARCHAR(24) NOT NULL, -- 대여소 ID
  dow_type   INTEGER NOT NULL, -- 0 평일 / 1 토 / 2 일·공휴일
  time_slot  INTEGER NOT NULL, -- 30분 단위 슬롯 (0~47)
  exp_bikes  NUMERIC(5,1) NOT NULL, -- 예상 잔여 대수
  p_empty    NUMERIC(4,3) NOT NULL, -- 0대 확률
  p_full     NUMERIC(4,3) NOT NULL, -- 만차 확률
  source     VARCHAR(8) NOT NULL, -- avg|model
  updated_at TIMESTAMPTZ NOT NULL, -- 적재 시각
  PRIMARY KEY (rental_id, dow_type, time_slot)
);

CREATE TABLE transfer_meta ( -- 환승 정보
  station_id   VARCHAR(24) NOT NULL, -- 역 ID
  from_line    VARCHAR(16) NOT NULL, -- 출발 노선
  to_line      VARCHAR(16) NOT NULL, -- 도착 노선
  walk_sec     INTEGER NOT NULL, -- 환승 도보 초
  stair_count  INTEGER, -- 계단 수
  has_elevator BOOLEAN, -- 엘리베이터 여부
  outdoor      BOOLEAN NOT NULL DEFAULT FALSE, -- 실외 노출 여부
  source       VARCHAR(8) NOT NULL, -- manual|extract
  PRIMARY KEY (station_id, from_line, to_line)
);
