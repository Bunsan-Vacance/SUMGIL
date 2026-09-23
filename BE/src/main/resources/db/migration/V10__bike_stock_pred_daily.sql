-- V10: 따릉이 재고 예측 날짜축 표 (S15P21A104-309).
--
-- AI LightGBM 예측기(195)는 날짜마다 다른 값을 낸다 — 그 날의 요일·공휴일·날씨·KBO 를 반영하기 때문이다.
-- 기존 bike_stock_pred 는 (rental_id, dow_type, time_slot) 정적 표라 "9월 23일" 을 적을 칸이 없어서
-- 모델 산출물을 서빙하지 못하고 있었다(AI batch_predict.py 주석 "BE 스키마 동의 전까지 보류", 2026-09-14).
--
-- 기존 표를 바꾸지 않고 하나 더 둔다. 조회는 이 표에 (대여소, 도착 날짜, 슬롯) 행이 있으면 모델 값을,
-- 없으면 기존 평균표를 쓴다. 그래서
--   · 이 표가 비어 있으면 응답은 지금과 같다 — 배포 순서가 자유롭다
--   · AI 가 날짜축 산출물을 멈추면 평균표로 돌아간다 — 되돌리기가 조회 한 곳이다
--   · 배치가 만들지 않은 날짜(멀리 떨어진 미래)도 평균표 값이 나간다 — 화면이 비지 않는다
--
-- generated_at 은 산출물 사이드카 값이다. congestion_pred(V7)와 같은 이유로 적재 시각(updated_at)과 분리한다 —
-- 응답의 predictedAt 이 "언제 만든 예측인가" 여야 하는데, 기존 표는 적재 시각을 그대로 내보내고 있다.
--
-- 열 폭·정밀도는 bike_stock_pred(V1·V2·V5)와 같다. prediction_source 는 lightgbm 산출물에 없는 열이라
-- 지금은 전부 NULL 이지만, 예측기가 대체값을 표시하기 시작하면 같은 의미로 받는다(V5 주석).
CREATE TABLE bike_stock_pred_daily (
  rental_id         VARCHAR(24)  NOT NULL, -- 대여소 ID (ST-xxx). 마스터에 없는 신설 대여소가 섞일 수 있다
  pred_date         DATE         NOT NULL, -- 대상 날짜 (KST). 사이드카 target_date 와 같다
  time_slot         INTEGER      NOT NULL, -- 30분 단위 슬롯 (0~47)
  exp_bikes         NUMERIC(5,1) NOT NULL, -- 예상 잔여 대수
  p_empty           NUMERIC(4,3) NOT NULL, -- 0대 확률
  p_full            NUMERIC(4,3) NOT NULL, -- 만차 확률
  source            VARCHAR(16)  NOT NULL, -- 예측기 (model)
  prediction_source VARCHAR(32),           -- 관측/대체 등급. lightgbm 산출물에는 없어 NULL
  generated_at      TIMESTAMPTZ  NOT NULL, -- 산출물 meta.generated_at (응답 predictedAt)
  updated_at        TIMESTAMPTZ  NOT NULL, -- 적재 시각
  PRIMARY KEY (rental_id, pred_date, time_slot)
);

COMMENT ON TABLE bike_stock_pred_daily IS
  '따릉이 재고 예측 — 날짜축(모델). 조회는 이 표를 먼저 보고 없으면 bike_stock_pred(요일축 평균)로 떨어진다';
COMMENT ON COLUMN bike_stock_pred_daily.generated_at IS
  '예측 산출 시각(사이드카 generated_at). 적재 시각 updated_at 과 다르다 — 응답 predictedAt 으로 나간다';
