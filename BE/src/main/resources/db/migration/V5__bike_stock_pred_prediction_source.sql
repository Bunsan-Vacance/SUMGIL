-- V5: bike_stock_pred 에 prediction_source 열 추가 (S15P21A104-172).
--
-- AI 재고 예측 배치는 대여소마다 요일 3 × 슬롯 48 격자를 채우는데, 표본이 없는 칸은 같은 대여소 안의 평균으로 메운다
-- (다른 대여소 값은 끌어오지 않는다). 그 칸이 실제 관측인지 대체값인지를 행마다 표시한 것이 prediction_source 다.
--   observed_avg            그 대여소·요일·슬롯의 실제 관측 평균
--   station_time_fallback   같은 대여소·같은 슬롯의 다른 요일 평균으로 메움
--   station_global_fallback 같은 대여소 전체 평균으로 메움
-- 2026-09-17 산출물 실측 비율: 관측 92.3% · 시간 대체 7.7%(대여소 864곳) · 전체 대체 0.0%(4곳).
--
-- 기존 source 열에 섞지 않고 열을 따로 두는 이유는 축이 다르기 때문이다 —
-- source 는 "어떤 예측기인가"(avg|model), prediction_source 는 "그 값이 관측인가 대체인가"다.
-- 예측기를 model 로 바꿔도 대체값은 계속 생기므로 한 열에 섞으면 값 조합이 복잡해진다 (S15P21A104-172 회신, 2026-09-14).
--
-- 폭 32 는 가장 긴 값 station_global_fallback(23자)에 여유를 둔 것이다. source 열이 폭 부족으로
-- V2 에서 한 번 넓어진 전례가 있어(timetable 9자 > VARCHAR(8)) 처음부터 넉넉히 잡는다.
--
-- NULL 을 허용한다. 이 열이 없던 시절의 산출물을 적재할 수 있어야 하고, "라벨 없음"과 "관측"은 다르다.
ALTER TABLE bike_stock_pred ADD COLUMN prediction_source VARCHAR(32);

COMMENT ON COLUMN bike_stock_pred.prediction_source IS
  '예측값의 출처 등급: observed_avg(실제 관측) | station_time_fallback(같은 대여소 다른 요일) | station_global_fallback(같은 대여소 전체). NULL 은 라벨 없는 옛 산출물';
