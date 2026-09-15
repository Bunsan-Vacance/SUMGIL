"""예측기 인터페이스와 레지스트리 — 배치 잡·API는 이 이음새 하나만 본다.

모델 계열(ML / Transformer 시계열 / LLM API)을 바꿔 비교하려면 프로덕션 경로가 특정 모델에 묶이면
안 된다. 모든 예측기는 같은 입력(파생 전 패널 창: 대상 날짜 + 시차용 과거 행)을 받아 같은 출력
(date·station_no·time_slot·boarding_pred·alighting_pred, 선택적으로 `*_lookup`)을 낸다.

| kind | 구현 | 상태 |
| --- | --- | --- |
| `lookup` | 요일유형×역×시간대 평균만. 네이버·카카오와 같은 기준선 | 사용 가능 — **기본 placeholder** |
| `lightgbm` | 90 아티팩트(`train.py`) = lookup + LightGBM 잔차 | 사용 가능 — **운영 기본** |
| `dl` | 144 아티팩트(`dl/train_dl.py`) = lookup + GRU 시퀀스 잔차 | 사용 가능. 채택 판정은 145 |
| `llm` | 최근 시차·이벤트를 프롬프트로 주고 숫자를 받는 실험 축 | API 키 대기. 프로덕션 기본값으로는 쓰지 않는다 |

**이력 창 길이는 예측기가 정한다.** `required_history_days`로 필요한 과거 일수를 알리고 배치는
`max(HISTORY_DAYS, predictor.required_history_days)`로 창을 잡는다 — lookup·LightGBM은 7일(시차 피처가
전날·1주 전까지), DL은 `seq_days`(기본 14)다. 창이 그보다 짧게 와도 DL은 앞쪽이 마스크 0으로 동작한다.

**`auto`는 `model_kind == "lightgbm"` 아티팩트만 고른다**(`latest_artifact(kind=...)`). 폴더명 정렬에만
기대면 계열이 섞이는 순간 운영 기본값이 **이름 운**에 맡겨진다 — 지금은 `dl_` < `festival_`이라 우연히
lightgbm이 잡히지만, 폴더명 규칙이 바뀌면 배치가 말없이 다른 계열로 넘어간다. 옛 아티팩트에는
`model_kind`가 없어 lightgbm으로 본다.

placeholder를 무작위 값이 아니라 lookup으로 두는 이유: 정직한 기준선이 먼저 프로덕션에 들어가야
뒤에 붙는 모델이 그것보다 나은지가 그대로 드러난다. LLM은 하루 5,460행을 매일 채우기엔 느리고
비결정적이며 400만 행 이력을 못 먹어 수치 예측 자리에는 맞지 않는다 — 비교 실험(소량 표본)과
"왜 혼잡한가" 설명문 생성이 LLM의 자리다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline

OUTPUT_KEYS = ["date", "station_no", "time_slot"]
# lookup·LightGBM 시차 피처가 필요로 하는 과거 일수(전날·1주 전). 배치 `HISTORY_DAYS`와 같은 값이다.
DEFAULT_HISTORY_DAYS = 7


@runtime_checkable
class Predictor(Protocol):
    """모든 예측기가 지키는 계약."""

    kind: str
    version: str
    required_history_days: int

    def predict(self, panel_window: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        """`panel_window`(파생 전, 대상 날짜 + 과거 행) → OUTPUT_KEYS + `{target}_pred`.

        입력 행마다 한 행을 돌려준다(대상 날짜 자르기는 호출자가 한다). 값을 낼 수 없는 행은 NaN.
        """
        ...


class LookupPredictor:
    """요일유형×역×시간대 평균 조회. 학습 패널로 fit하거나 저장된 lookup.parquet을 읽는다."""

    kind = "lookup"
    required_history_days = DEFAULT_HISTORY_DAYS

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
    required_history_days = DEFAULT_HISTORY_DAYS

    def __init__(self, artifact_dir: Path) -> None:
        from app.CROWD.pipeline.predict import CrowdPredictor

        self._inner = CrowdPredictor(artifact_dir)
        self.version = f"lightgbm:{Path(artifact_dir).name}"
        self.feature_set = self._inner.feature_set

    def predict(self, panel_window: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        return self._inner.predict(panel_window, segments)


class DLPredictor:
    """144 아티팩트(lookup + GRU 시퀀스 잔차). torch는 생성 시점에 지연 import된다.

    `device`는 기본 `cpu`다 — 배치·API가 도는 EC2에 GPU가 없고, 학습(GPU)과 추론(CPU)이 같은
    state_dict를 쓰기 때문이다(`map_location`). `scenario`는 144 평가 전용 스위치다.
    """

    kind = "dl"

    def __init__(
        self, artifact_dir: Path, device: str = "cpu", scenario: str | None = None
    ) -> None:
        from app.CROWD.pipeline.dl.infer import DLResidualPredictor

        self._inner = DLResidualPredictor(artifact_dir, device=device, scenario=scenario)
        self.version = f"dl:{Path(artifact_dir).name}"
        self.required_history_days = self._inner.seq_days

    @property
    def scenario(self) -> str | None:
        return self._inner.scenario

    @scenario.setter
    def scenario(self, value: str | None) -> None:
        self._inner.scenario = value

    def predict(self, panel_window: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
        return self._inner.predict(panel_window, segments)


class LLMPredictor:
    """LLM API 실험 축 — API 키가 설정되면 구현한다. 지금은 명확한 오류로 막는다."""

    kind = "llm"
    version = "llm:unconfigured"
    required_history_days = DEFAULT_HISTORY_DAYS

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
    - `dl`: `artifact_dir`, 선택 `device`(기본 cpu)·`scenario`.
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
    if kind == "dl":
        return DLPredictor(
            Path(cfg["artifact_dir"]),
            device=cfg.get("device", "cpu"),
            scenario=cfg.get("scenario"),
        )
    if kind == "llm":
        return LLMPredictor(cfg.get("api_key"), cfg.get("model"))
    raise ValueError(f"알 수 없는 예측기: {kind} (가능: lookup, lightgbm, dl, llm)")


def artifact_kind(artifact_dir: Path) -> str:
    """아티팩트 `meta.json`의 `model_kind`. 없으면 `lightgbm`(144 이전 아티팩트)."""
    try:
        meta = json.loads((Path(artifact_dir) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(meta.get("model_kind", "lightgbm"))


def latest_artifact(models_dir: Path, prefix: str = "", kind: str | None = None) -> Path | None:
    """`models/CROWD/` 아래 가장 최근(이름 기준 정렬) 아티팩트 디렉터리.

    `kind`를 주면 `meta.json`의 `model_kind`가 그것인 폴더만 본다 — 배치의 `auto`가
    `kind="lightgbm"`으로 부르므로 DL 아티팩트가 섞여도 운영 기본값이 바뀌지 않는다.
    """
    models_dir = Path(models_dir)
    if not models_dir.exists():
        return None
    dirs = sorted(
        p
        for p in models_dir.iterdir()
        if p.is_dir()
        and p.name.startswith(prefix)
        and (p / "meta.json").exists()
        and (kind is None or artifact_kind(p) == kind)
    )
    return dirs[-1] if dirs else None
