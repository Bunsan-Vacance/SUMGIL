-- 탑승 확인 이벤트(S15P21A104-313, BE/docs/api/boarding-check-api-design.md). 로그인이 없어 사용자 식별 없이
-- "어떤 구간에 탑승 이벤트가 있었다"만 기록한다. AI·다른 BE 도메인은 이 테이블을 직접 읽어 쓴다.
CREATE TABLE boarding_event (
  id              BIGSERIAL PRIMARY KEY,
  mode            VARCHAR(16) NOT NULL,   -- WALK|BIKE|BUS|SUBWAY|TRANSFER (TravelMode)
  from_node_id    VARCHAR(24) NOT NULL,   -- 승차 지점 ID (역/정류장)
  from_node_name  VARCHAR(64),
  to_node_id      VARCHAR(24) NOT NULL,   -- 하차 지점 ID
  to_node_name    VARCHAR(64),
  route_id        VARCHAR(32),            -- 노선 ID (line_id, 버스 노선 ID 등)
  route_name      VARCHAR(64),
  status          VARCHAR(16) NOT NULL,   -- BOARDED|UNKNOWN
  departure_time  VARCHAR(8),             -- 사용자가 고른 열차/버스 출발 시각 "HH:mm", UNKNOWN이면 NULL
  reported_at     TIMESTAMPTZ NOT NULL,   -- 클라이언트에서 이벤트가 발생한 시각
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()  -- 서버 적재 시각
);

CREATE INDEX idx_boarding_event_from_to ON boarding_event (from_node_id, to_node_id);
