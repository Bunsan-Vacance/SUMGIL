-- 구간(링크) 혼잡도 예측. AI CROWD 배치 산출물(S15P21A104-158, 통지 04 1.2절 확정 DDL)
CREATE TABLE congestion_pred (
  pred_date         DATE NOT NULL,          -- 대상 날짜 (KST)
  from_station_id   VARCHAR(24) NOT NULL,   -- 링크 시작 역 (station.station_id 표기)
  to_station_id     VARCHAR(24) NOT NULL,   -- 링크 끝 역 (station.station_id 표기)
  line_id           VARCHAR(16) NOT NULL,   -- line.line_id (원천 '1호선' → 매핑)
  direction         VARCHAR(8)  NOT NULL,   -- 상선|하선|내선|외선
  time_slot         INTEGER NOT NULL,       -- 30분 슬롯 0~47 (실제 39종)
  level             NUMERIC(5,1),           -- 보정 혼잡도 %. NULL 허용, 상한 없음
  data_status       VARCHAR(32) NOT NULL,   -- ok|calibration_fallback|segment_truncated|no_calibration|no_lookup
  pred_source       VARCHAR(32) NOT NULL,   -- model|lookup_negative
  predictor_version VARCHAR(32) NOT NULL,   -- 행 단위
  generated_at      TIMESTAMPTZ NOT NULL,   -- 산출물 meta.generated_at (재적재·캐시 판정)
  updated_at        TIMESTAMPTZ NOT NULL,   -- 적재 시각
  PRIMARY KEY (pred_date, from_station_id, to_station_id, line_id, direction, time_slot)
);
