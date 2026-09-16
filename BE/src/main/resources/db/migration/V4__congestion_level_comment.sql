-- congestion.level 의 범위 설명을 바로잡는다 (S15P21A104-174).
--
-- V1__init.sql 의 인라인 주석이 "혼잡도 0.0~100.0" 으로 돼 있는데 틀렸다.
-- level 은 정원 대비 %라 100 을 넘는다 — 실측 STATION 0.0~144.6 · LINE 0.0~92.4 (docs/db/load-congestion.md).
-- 읽는 쪽이 0~100 을 가정하고 정규화하거나 잘라내면 혼잡한 역일수록 값이 뭉개진다.
--
-- V1 파일 자체는 고치지 않는다. 이미 prod 에 적용돼 있어 내용을 바꾸면 Flyway 체크섬이 달라지고
-- (FlywayConfig 가 기본값 validateOnMigrate=true 를 쓴다) 다음 기동에서 검증 실패로 앱이 뜨지 않는다.
-- 그래서 새 마이그레이션으로 COMMENT 를 단다 — DB 메타데이터에 남아 psql 에서도 보인다.

COMMENT ON COLUMN congestion.level IS
  '혼잡도. 정원 대비 % 이며 100 을 넘을 수 있다 (실측 STATION 최대 144.6 · LINE 최대 92.4). 0~100 으로 가정하지 말 것';

COMMENT ON COLUMN congestion.target_type IS 'STATION | LINE | ROUTE';
COMMENT ON COLUMN congestion.source IS 'stat(통계) | live(실시간)';
