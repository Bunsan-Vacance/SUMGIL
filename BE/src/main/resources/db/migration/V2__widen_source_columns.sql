-- V2: source 열 폭 확대.
-- V1 은 edge_time.source 를 VARCHAR(8) 로 두고 값을 timetable|avg|model 로 정의했지만 'timetable' 은 9자라 들어가지 않는다
-- (정적 적재 통합 테스트에서 "value too long for type character varying(8)" 로 발견, S15P21A104-69).
-- 같은 성격의 source 열을 모두 16자로 맞춘다. 값 규약은 바뀌지 않는다.

ALTER TABLE edge_time       ALTER COLUMN source TYPE VARCHAR(16);
ALTER TABLE congestion      ALTER COLUMN source TYPE VARCHAR(16);
ALTER TABLE bike_stock_pred ALTER COLUMN source TYPE VARCHAR(16);
ALTER TABLE transfer_meta   ALTER COLUMN source TYPE VARCHAR(16);
