"""예측기 인터페이스와 레지스트리 — 배치 잡·API는 이 이음새 하나만 본다.

모델 계열(ML / Transformer 시계열 / LLM API)을 바꿔 비교하려면 프로덕션 경로가 특정 모델에 묶이면
안 된다. 모든 예측기는 같은 입력(파생 전 패널 창: 대상 날짜 + 시차용 과거 행)을 받아 같은 출력
(date·station_no·time_slot·boarding_pred·alighting_pred, 선택적으로 `*_lookup`)을 낸다.

| kind | 구현 | 상태 |
| --- | --- | --- |
| `lookup` | 요일유형×역×시간대 평균만. 네이버·카카오와 같은 기준선 | 사용 가능 — **기본 placeholder** |
| `lightgbm` | 90 아티팩트(`train.py`) = lookup + LightGBM 잔차 | 사용 가능 |
| `llm` | 최근 시차·이벤트를 프롬프트로 주고 숫자를 받는 실험 축 | API 키 대기. 프로덕션 기본값으로는 쓰지 않는다 |

placeholder를 무작위 값이 아니라 lookup으로 두는 이유: 정직한 기준선이 먼저 프로덕션에 들어가야
뒤에 붙는 모델이 그것보다 나은지가 그대로 드러난다. LLM은 하루 5,460행을 매일 채우기엔 느리고
비결정적이며 400만 행 이력을 못 먹어 수치 예측 자리에는 맞지 않는다 — 비교 실험(소량 표본)과
"왜 혼잡한가" 설명문 생성이 LLM의 자리다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline

OUTPUT_KEYS = ["date", "station_no", "time_slot"]


@runtime_checkable
class Predictor(Protocol):
    """모든 예측기가 지키는 계약."""

    kind: str
    version: str

    def predict(self, panel_window: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        """`panel_window`(파생 전, 대상 날짜 + 과거 행) → OUTPUT_KEYS + `{target}_pred`.

        입력 행마다 한 행을 돌려준다(대상 날짜 자르기는 호출자가 한다). 값을 낼 수 없는 행은 NaN.
        """
        ...


class LookupPredictor:
    """요일유형×역×시간대 평균 조회. 학습 패널로 fit하거나 저장된 lookup.parquet을 읽는다."""

    kind = "lookup"

    def __init__(self, lookup: DayTypeLookupBaseline, version: str = "lookup") -> None:
        self.lookup = lookup
        self.version = version

    @classmethod
    def fit(cls, train_panel: pd.DataFrame, version: str = "lookup") -> LookupPredictor:
        return cls(DayTypeLookupBaseline().fit(train_panel), version)

    @classmethod
    def load(cls, path: Path) -> LookupPredictor:
        return cls(DayTypeLookupBaseline.load(path), version=f"lookup:{Path(path).parent.name}")

    def predict(self, panel_window: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        pred = self.lookup.predict(panel_window)
        out = panel_window[OUTPUT_KEYS].copy()
        for t in TARGETS:
            out[f"{t}_lookup"] = pred[t].to_numpy()
            out[f"{t}_pred"] = pred[t].to_numpy()
        return out


class LightGBMPredictor:
    """90 아티팩트(lookup + LightGBM 잔차). lightgbm은 생성 시점에 지연 import된다."""

    kind = "lightgbm"

    def __init__(self, artifact_dir: Path) -> None:
        from app.CROWD.pipeline.predict import CrowdPredictor

        self._inner = CrowdPredictor(artifact_dir)
        self.version = f"lightgbm:{Path(artifact_dir).name}"
        self.feature_set = self._inner.feature_set

    def predict(self, panel_window: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        return self._inner.predict(panel_window, segments)


class LLMPredictor:
    """LLM API 실험 축 — API 키가 설정되면 구현한다. 지금은 명확한 오류로 막는다."""

    kind = "llm"
    version = "llm:unconfigured"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model

    def predict(self, panel_window: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        raise NotImplementedError(
            "LLM 예측기는 아직 연결되지 않았다. CROWD_LLM_API_KEY 설정 후 구현 예정 — 프로덕션 기본값은 "
            "lookup 또는 lightgbm을 쓴다."
        )


def build_predictor(kind: str, **cfg) -> Predictor:
    """설정 문자열로 예측기를 만든다.

    - `lookup`: `lookup_path`(parquet) 또는 `train_panel`(DataFrame) 중 하나.
    - `lightgbm`: `artifact_dir`.
    - `llm`: `api_key`, `model`.
    """
    if kind == "lookup":
        if cfg.get("lookup_path"):
            return LookupPredictor.load(Path(cfg["lookup_path"]))
        if cfg.get("train_panel") is not None:
            return LookupPredictor.fit(cfg["train_panel"])
        raise ValueError("lookup 예측기는 lookup_path 또는 train_panel이 필요하다")
    if kind == "lightgbm":
        return LightGBMPredictor(Path(cfg["artifact_dir"]))
    if kind == "llm":
        return LLMPredictor(cfg.get("api_key"), cfg.get("model"))
    raise ValueError(f"알 수 없는 예측기: {kind} (가능: lookup, lightgbm, llm)")


def latest_artifact(models_dir: Path, prefix: str = "") -> Path | None:
    """`models/CROWD/` 아래 가장 최근(이름 기준 정렬) 아티팩트 디렉터리."""
    models_dir = Path(models_dir)
    if not models_dir.exists():
        return None
    dirs = sorted(
        p
        for p in models_dir.iterdir()
        if p.is_dir() and p.name.startswith(prefix) and (p / "meta.json").exists()
    )
    return dirs[-1] if dirs else None
