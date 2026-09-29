-- V9: congestion_pred.predictor_version 폭 확대 (S15P21A104-305).
--
-- V7 은 통지 04 1.2절 DDL 대로 VARCHAR(32) 로 뒀는데, AI 가 실제로 보내는 값이 67자다:
--   lightgbm:festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025   (67자)
--   lookup:line9_2025_2026                                               (22자)
-- 2026-09-21 에 받은 하루치 CSV(21,684행)를 적재하려 하면 첫 행부터
-- "value too long for type character varying(32)" 로 실패한다 — V2 가 edge_time.source(8→16)에서
-- 겪은 것과 같은 종류다.
--
-- 128 로 잡는 이유: 값이 "예측기:피처조합-학습기간" 구조라 피처가 늘면 그대로 길어진다.
-- 지금 67자에서 2배 가까운 여유를 두고, 그래도 넘으면 로더 검증기가 적재 전에 먼저 막는다
-- (MasterValidator.validateCongestionPred 의 길이 검사 — DB 오류로 중간에 끊기지 않게 한다).
--
-- pred_source 는 넓히지 않는다. 같은 CSV 에서 최대 15자(`lookup_negative`)이고 32 안에 든다.
-- 다만 V7 주석이 2종만 적고 있어 실제 3종으로 고친다 — 제약이 아니라 주석이라 값은 이미 들어간다.
ALTER TABLE congestion_pred ALTER COLUMN predictor_version TYPE VARCHAR(128);

COMMENT ON COLUMN congestion_pred.predictor_version IS
  '그 행을 만든 예측기. 행 단위 열이다 — 같은 날짜 표 안에서도 노선마다 다르다. 예: lightgbm:<피처>-stack_train<기간>(모델) · lookup:line9_<기간>(9호선 기준선)';

COMMENT ON COLUMN congestion_pred.pred_source IS
  'model | lookup_negative | lookup_line9. lookup_* 는 모델 예측을 그대로 쓰지 않은 셀이다 — negative 는 인원 예측이 음수라 기준선으로 대체, line9 는 9호선 2·3단계라 전날 승하차 원천이 없어 기준선만 쓴다(AI 통지 07 3절)';
