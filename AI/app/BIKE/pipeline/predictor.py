"""예측기 인터페이스와 레지스트리 — 배치 잡·API는 이 이음새 하나만 본다.

CROWD의 `predictor.py`와 같은 목적(모델 계열을 바꿔도 프로덕션 경로가 특정 모델에
안 묶이게)이지만, 출력 형태가 다르다 — CROWD는 시각별 승하차를, BIKE는 `bike_stock_pred`
행(rental_id·dow_type·time_slot·exp_bikes·p_empty·p_full) 자체를 낸다. 실시간 요청이
아니라 정적 표 전체를 한 번에 만드는 배치라서, `predict()`가 인자를 안 받고 표 전체를
반환한다.

| kind | 구현 | 상태 |
| --- | --- | --- |
| `avg` | station×dow_type×time_slot 실측 평균/빈도(`lookup.StockProfileBaseline`) | 사용 가능 — **기본값** |
| `lightgbm` | `target_net_flow` LightGBM(v3) 예측을 exp_bikes/p_empty/p_full로 변환 | **미구현** — B4 model 소스는 검증 없이 미룸(2026-09-14 결정) |

avg를 기본값으로 두는 이유는 CROWD의 lookup 우선 철학과 같다 — 정직한 baseline이 먼저
프로덕션에 들어가야, 나중에 lightgbm 소스를 완성했을 때 그것이 avg보다 실제로 나은지가
드러난다. LightGBM(v3) 자체는 `target_net_flow` 예측에서 이미 avg보다 우위가 검증됐지만
(`RESULTS.md`), 그 값을 dow_type×time_slot 정적 표의 exp_bikes/p_empty/p_full로 바꾸는
방법(대표 재고값 근사, 확률 산출)은 아직 설계·검증되지 않았다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from app.BIKE.pipeline.lookup import StockProfileBaseline

OUTPUT_COLS = ["rental_id", "dow_type", "time_slot", "exp_bikes", "p_empty", "p_full"]


@runtime_checkable
class Predictor(Protocol):
    """모든 예측기가 지키는 계약."""

    kind: str
    version: str

    def predict_all(self) -> pd.DataFrame:
        """전체 (rental_id, dow_type, time_slot) 표. OUTPUT_COLS + `source` 컬럼."""
        ...


class AvgPredictor:
    """station×dow_type×time_slot 실측 평균/빈도 조회(`StockProfileBaseline`)."""

    kind = "avg"

    def __init__(self, baseline: StockProfileBaseline, version: str = "avg") -> None:
        self.baseline = baseline
        self.version = version

    @classmethod
    def load(cls, path: Path) -> AvgPredictor:
        return cls(StockProfileBaseline.load(path), version=f"avg:{Path(path).parent.name}")

    def predict_all(self) -> pd.DataFrame:
        out = self.baseline.predict()
        out["source"] = "avg"
        return out.reindex(columns=[*OUTPUT_COLS, "source"])


class LightGBMPredictor:
    """target_net_flow LightGBM(v3) → exp_bikes/p_empty/p_full 변환 — 미구현.

    v3 자체(models/BIKE/v3-holiday-tuned_*/model.txt)는 이미 학습·검증됐다 — 변환
    방법(대표 재고값 근사 + 확률 산출)이 아직 없을 뿐이다. 구현 전까지는 명확한
    오류로 막는다(CROWD의 `LLMPredictor` 자리와 같은 성격).
    """

    kind = "lightgbm"
    version = "lightgbm:unimplemented"

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = model_dir

    def predict_all(self) -> pd.DataFrame:
        raise NotImplementedError(
            "lightgbm 예측기는 아직 연결되지 않았다 — target_net_flow를 dow_type×time_slot "
            "exp_bikes/p_empty/p_full로 바꾸는 방법이 미검증(B4 model 소스, 2026-09-14 보류). "
            "지금은 avg를 쓴다."
        )


def build_predictor(kind: str, **cfg) -> Predictor:
    """설정 문자열로 예측기를 만든다.

    - `avg`: `baseline_path`(parquet) 또는 `baseline`(StockProfileBaseline 인스턴스) 중 하나.
    - `lightgbm`: `model_dir`(선택, 아직 predict_all 호출 시 NotImplementedError).
    """
    if kind == "avg":
        if cfg.get("baseline_path"):
            return AvgPredictor.load(Path(cfg["baseline_path"]))
        if cfg.get("baseline") is not None:
            return AvgPredictor(cfg["baseline"])
        raise ValueError("avg 예측기는 baseline_path 또는 baseline이 필요하다")
    if kind == "lightgbm":
        return LightGBMPredictor(cfg.get("model_dir"))
    raise ValueError(f"알 수 없는 예측기: {kind} (가능: avg, lightgbm)")


def latest_artifact(models_dir: Path, prefix: str = "") -> Path | None:
    """`models/BIKE/` 아래 가장 최근(이름 기준 정렬) 아티팩트 디렉터리."""
    models_dir = Path(models_dir)
    if not models_dir.exists():
        return None
    dirs = sorted(
        p
        for p in models_dir.iterdir()
        if p.is_dir() and p.name.startswith(prefix) and (p / "meta.json").exists()
    )
    return dirs[-1] if dirs else None
