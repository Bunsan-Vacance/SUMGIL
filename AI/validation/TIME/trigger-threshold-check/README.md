# 재안내 트리거 임계값 실측 — S15P21A104-331

운영 전환(09-29) 뒤 잠정값이던 트리거 임계(`TIME_TRIGGER_P_EMPTY=0.7`, `TIME_TRIGGER_MIN_STOCK=1`)를
실스냅샷 분포로 확인한다. 규칙 자체는 `app/TIME/trigger.py`, 값은 `.env`에서 바꾼다(코드 무변경).

- `src/trigger_dist.py` — 실스냅샷 무작위 표본 × horizon 5/15/30분에 대해 `predict_eta_stock`을 직접 호출해
  `p_empty ≥ 0.5/0.6/0.7`, `predicted_stock < 1` 발동 비율과 `p_empty` 분위수를 출력한다.
- 결과·판정은 `RESULTS.md`.
