"""재학습 루프(채점·통계·드리프트·리포트) 패키지.

- `score` — 예측 판을 실측으로 채점해 `monitoring/score_daily/dt=D/`에 남긴다.
- `stats` — 날짜 블록 부트스트랩·Diebold-Mariano 순수 함수(검증 스크립트에서 승격).
- `drift` — R0·R1'·R3 규칙으로 재학습 요청 파일을 만든다.
- `report` — 채점·드리프트 결과를 마크다운 리포트로 렌더한다.

설계 참조: 재학습 루프 설계 문서(`.claude/handoff/`)와 `AI/app/CROWD/SERVING_CONTRACT.md`.
"""
