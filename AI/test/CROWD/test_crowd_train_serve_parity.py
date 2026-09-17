"""197 C부 — 학습 경로와 서빙 경로가 만드는 피처 행렬이 같은지 검증한다.

두 경로는 같은 함수(`features.add_derived_columns`)로 파생을 만들지만(설계 문서
`.claude/plans/S15P21A104-missing-data-policy.md` 3.1절), 그 뒤가 갈린다.

    학습: `dataset.load_or_build_derived` — 캐시가 있으면 **parquet에서 다시 읽는다**
    서빙: `predict.CrowdPredictor.predict` — 매 요청마다 **인메모리**로만 만든다

캐시 적중 시의 parquet 왕복이 dtype(특히 category)이나 결측 위치를 조용히 바꾸면, 학습 때
모델이 본 행렬과 서빙 때 넣는 행렬이 달라진다 — LightGBM은 학습 시점의 category 코드
매핑에 묶이므로 이 어긋남은 조용히 더 나쁜 예측으로만 드러난다. 이 테스트는 그 둘을
`build_matrix` 출력 단계에서 정확히 대조한다(컬럼·dtype·결측 위치).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.CROWD.pipeline.dataset import load_or_build_derived
from app.CROWD.pipeline.features import SLOT_ORDER, add_derived_columns, build_matrix
from app.CROWD.pipeline.lookup import DayTypeLookupBaseline
from app.CROWD.pipeline.topology import load_topology, resolve_segments

TOPOLOGY_YAML = "segments:\n  - line: L1\n    segment: 본선\n    stations: [1, 2]\n"


def _panel(days=10):
    """`station_no=3`은 어느 세그먼트에도 안 들었지만 이름이 1번과 같아 환승(xfer)만 만든다 —
    line 이웃(`nb_prev/next`)과 환승 이웃(`nb_xfer`)이 서로 다른 경로로 만들어지는 것까지 덮는다."""
    rows = []
    for d in range(days):
        date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
        for s in (1, 2, 3):
            for i, slot in enumerate(SLOT_ORDER[:3]):
                rows.append(
                    {
                        "date": date,
                        "station_no": s,
                        "station_name": {1: "A", 2: "B", 3: "A"}[s],
                        "line": {1: "L1", 2: "L1", 3: "L2"}[s],
                        "time_slot": slot,
                        "day_type": "평일" if date.dayofweek < 5 else "토요일",
                        "boarding": float(10 * s + i + d % 3),
                        "alighting": float(5 * s + i),
                        "game_count": int(d % 4 == 0),
                        "festival_count": 0,
                        "festival_short_count": 0,
                        "festival_long_count": 0,
                        "festival_min_duration_days": np.nan,
                    }
                )
    return pd.DataFrame(rows)


def test_train_and_serve_paths_build_identical_matrix(tmp_path):
    panel = _panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    feature_set = "festival_selflag_d1sd_d7_resid"  # 현재 배포 세트(93 B″)

    topology_path = tmp_path / "topology.yaml"
    topology_path.write_text(TOPOLOGY_YAML, encoding="utf-8")
    panel_path = tmp_path / "panel_stub.parquet"  # 캐시 메타 비교용 — 내용은 안 읽는다
    cache_path = tmp_path / "derived_cache.parquet"

    # 첫 호출은 캐시를 만들고 인메모리 프레임을 그대로 돌려준다(라운드트립 전).
    load_or_build_derived(
        panel, lookup, cache_path=cache_path, panel_path=panel_path, topology_path=topology_path
    )
    # 두 번째 호출이 실제 학습이 반복 실행될 때 타는 경로다 — parquet에서 다시 읽는다.
    train_derived = load_or_build_derived(
        panel, lookup, cache_path=cache_path, panel_path=panel_path, topology_path=topology_path
    )
    X_train = build_matrix(train_derived, feature_set)

    # 서빙 경로 — predict.CrowdPredictor.predict과 같은 호출 순서(add_derived_columns 직접 호출).
    segments, _ = resolve_segments(load_topology(topology_path), set(panel["station_no"].unique()))
    serve_derived = add_derived_columns(panel, lookup, segments)
    X_serve = build_matrix(serve_derived, feature_set)

    pd.testing.assert_frame_equal(X_train, X_serve)


def test_train_and_serve_paths_agree_on_full_derived_set_including_realtime_cols(tmp_path):
    """실시간 컬럼까지 포함한 세트에서도 parity가 유지되는지 — REALTIME_COLS 허용목록이
    학습 경로에서 캐시를 왕복해도 서빙 경로와 같은 결측 위치를 내는지 확인한다."""
    panel = _panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    feature_set = "festival_all_derived_resid"

    topology_path = tmp_path / "topology.yaml"
    topology_path.write_text(TOPOLOGY_YAML, encoding="utf-8")
    panel_path = tmp_path / "panel_stub.parquet"
    cache_path = tmp_path / "derived_cache.parquet"

    load_or_build_derived(
        panel, lookup, cache_path=cache_path, panel_path=panel_path, topology_path=topology_path
    )
    train_derived = load_or_build_derived(
        panel, lookup, cache_path=cache_path, panel_path=panel_path, topology_path=topology_path
    )
    X_train = build_matrix(train_derived, feature_set)

    segments, _ = resolve_segments(load_topology(topology_path), set(panel["station_no"].unique()))
    serve_derived = add_derived_columns(panel, lookup, segments)
    X_serve = build_matrix(serve_derived, feature_set)

    pd.testing.assert_frame_equal(X_train, X_serve)
