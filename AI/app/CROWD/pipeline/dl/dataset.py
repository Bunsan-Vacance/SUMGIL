"""잔차 시퀀스 데이터셋 — (역, 날짜) 표본을 GRU 입력 텐서로 만든다(144).

파생 캐시(`dataset.load_or_build_derived`)의 `boarding_resid / alighting_resid`를 (역 × 날짜 × 20슬롯)
밀집 배열로 한 번 pivot해 두고, 표본 `(역 s, 대상일 t)`마다 직전 `seq_days`일 창을 **인덱싱으로**
잘라낸다. 표본마다 텐서를 미리 만들면 2년 20만 표본 × 14 × 20 × 7 float32 ≈ 780MB지만, 밀집 배열은
273 × 731 × 20 × 3 ≈ 50MB라 창은 배치 때마다 만든다. torch를 쓰지 않으므로 CI에서도 돈다.

## 텐서 규약

```
z      [S, D, 20, 2]   z-잔차 = resid / std(역, 슬롯)   없는 자리 0
mask   [S, D, 20]      1 있음 / 0 없음                    (0은 결측 표시일 뿐 값이 아니다 — 원칙 8)
x_seq  [B, N, 20, C]   채널 = z 2 + mask 1 + 그 날 요일유형 one-hot 4 (+ 입력 안별 추가)  N = seq_days, i=0이 D−N
x_stat [B, 9]          대상일 요일유형 one-hot 4 + 대상일 이벤트 5(학습 구간 표준화, 없음=0)
station[B]             역 인덱스(임베딩용, `station_ids` 순서)
y      [B, 20, 2]      대상일 z-잔차,  y_mask [B, 20]
```

- **스케일**: 역×슬롯별 학습 구간 잔차 표준편차(`fit_scale`). 역마다 잔차 규모가 30배 차이라 NN에 필수.
  하한 `min_std`로 0 나눗셈·폭주를 막는다. 예측 복원은 `lookup + z × std`.
- **요일유형**: 패널에 있는 날은 패널 값, 패널에 없는 날(연초 결측·수집 누락)은 달력(`attach_calendar`)으로
  채운다. 이력 채널에서 마스크 0인 날의 요일유형은 모델에 "그 날이 무슨 날이었는지"만 알려준다.
- **이벤트**: 개수 컬럼과 `festival_min_duration_days`. 축제가 없는 날의 최단 기간은 원본이 NaN인데
  `festival_count=0`이 이미 "없음"을 말하므로 표준화 전에 0으로 둔다(입력 텐서에 NaN을 둘 수 없다).
- 분할 경계는 144 계획대로 고정한 것이 **기본값**이다: 2024-01~10 학습 / 2024-11~12 검증 / 2025 평가
  (`SPLITS`). 학습 창을 늘리는 실험(145 후속)은 `splits_with_train_start`로 학습 시작일만 당기고
  검증·평가 경계는 그대로 둔다 — `SequencePanel.build(..., splits=...)`/`split_index`가 그 값을 쓴다.

## 입력 설계 변형(198)

`seq_features`·`use_static_events`로 채널 구성을 고른다. 144는 `base` + 정적 이벤트 하나만 썼는데,
LightGBM 쪽은 87·89·90·93에서 피처 세트 7개를 비교해 고른 것이라 `full` 격차가 "시퀀스 모델의 한계"인지
"입력 1안의 한계"인지 구분이 안 됐다.

| `seq_features` | 채널 | 추가되는 것 |
| --- | --- | --- |
| `base` | 7 | (144 그대로) |
| `neighbor` | 16 | 이웃 잔차 z 6(prev·next·xfer × 승하) + 이웃 mask 3 |
| `events_hist` | 12 | 이력 각 날의 이벤트 5(정적 이벤트와 같은 표준화 값을 그 날 채널로) |

- 이웃 잔차는 파생 캐시의 `nb_{side}_{target}_resid`(같은 날·같은 슬롯 이웃 잔차 평균)를 쓰고,
  **이웃 역 자신의 std**로 나눈다(`neighbor_scale`). 한 side에 이웃이 여럿이면(분기점·환승 다중)
  잔차가 이미 평균이므로 std도 같은 이웃 집합의 평균을 쓴다. 이웃이 없으면 값 0 + mask 0.
- **이력 날(D−1…D−14)의 이웃 잔차는 D−1 시점에 확정된 과거 값**이라 D−1 원천 전제를 깨지 않는다.
  대상일 이웃 값은 넣지 않는다(창이 `t−N…t−1`이라 구조적으로 들어갈 자리가 없다).
- 이력 절단·시나리오 마스킹은 **관측에서 온 채널만** 지운다(`observed_channels`). 요일유형·이벤트는
  달력 정보라 이력이 없어도 알 수 있으므로 남긴다.

## 이벤트 인코딩(198 후속)

198 1차는 이벤트 5열을 **z-점수**로 넣었는데, 99%가 0인 희소 카운트라 학습 구간 std가 0.07~0.13이었다.
이벤트가 있는 날은 입력이 z 12.8~38.5(2025의 `festival_min_duration_days`는 최대 88.0)로 튀고,
`festival_count`의 z>5인 (역, 날)이 2025에 6.2%다 — 정적 이벤트를 넣은 안(V0)이 무너진 것도,
시드 표준편차가 ±7%p였던 것도 이 스케일 폭발로 설명된다. 그래서 `event_encoding`을 둔다.

| `event_encoding` | 개수 4열 | `festival_min_duration_days` | 범위(학습 구간) |
| --- | --- | --- | --- |
| `zscore` | `(x − mean) / std` | 같음(없음 → 0을 표준화) | 무제한(희소열에서 폭발) |
| `log1p_max` | `log1p(x) / log1p(학습 최대)` | `log1p(일수) / log1p(학습 최대)`, 없으면 0 | **0~1** |

`log1p_max`는 학습 구간을 넘는 값(2025의 더 큰 이벤트)도 로그로 눌러 1을 조금 넘는 선에서 멈춘다.
스케일 표(`event_stats.parquet`)에 `log1p_max`(나눈 값)와 `encoding`(실제로 쓴 인코딩)을 같이 남겨
아티팩트만 보고 복원할 수 있게 한다. 없음(NaN)은 두 인코딩 모두 0으로 두는데, `log1p_max`에서는
0이 곧 "값 0"이라 `festival_count=0`과 같은 자리를 가리켜 의미가 어긋나지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.lookup import TARGETS
from app.CROWD.pipeline.masking import apply_scenario, truncate_history

DAY_TYPES = ["평일", "토요일", "일요일", "휴일"]
EVENT_STATIC_COLS = [
    "game_count",
    "festival_count",
    "festival_short_count",
    "festival_long_count",
    "festival_min_duration_days",
]
RESID_COLS = [f"{t}_resid" for t in TARGETS]
STD_COLS = [f"{t}_std" for t in TARGETS]
N_SLOTS = len(SLOT_ORDER)
N_TARGETS = len(TARGETS)
SEQ_CHANNELS = N_TARGETS + 1 + len(DAY_TYPES)  # z 2 + mask 1 + 요일유형 4 = 7 (base)
STAT_FEATURES = len(DAY_TYPES) + len(EVENT_STATIC_COLS)  # 9

# ── 입력 설계 변형(198) ──
NEIGHBOR_SIDES = ("prev", "next", "xfer")
NEIGHBOR_RESID_COLS = [f"nb_{side}_{t}_resid" for side in NEIGHBOR_SIDES for t in TARGETS]
SEQ_FEATURE_SETS = ("base", "neighbor", "events_hist")
N_NEIGHBOR_CHANNELS = len(NEIGHBOR_RESID_COLS) + len(NEIGHBOR_SIDES)  # z 6 + mask 3 = 9

# ── 이벤트 인코딩(198 후속) ──
EVENT_ENCODINGS = ("zscore", "log1p_max")


def seq_channels_for(seq_features: str = "base") -> int:
    """입력 안별 시퀀스 채널 수. `model.ResidualGRU(seq_channels=…)`에 그대로 넣는다."""
    if seq_features not in SEQ_FEATURE_SETS:
        raise ValueError(f"모르는 seq_features {seq_features!r} — {list(SEQ_FEATURE_SETS)} 중 하나")
    if seq_features == "neighbor":
        return SEQ_CHANNELS + N_NEIGHBOR_CHANNELS
    if seq_features == "events_hist":
        return SEQ_CHANNELS + len(EVENT_STATIC_COLS)
    return SEQ_CHANNELS


def stat_features_for(use_static_events: bool = True) -> int:
    """정적 피처 폭 — 이벤트 스위치를 끄면 대상일 요일유형 one-hot 4만 남는다."""
    return len(DAY_TYPES) + (len(EVENT_STATIC_COLS) if use_static_events else 0)


def seq_feature_columns(seq_features: str = "base") -> list[str]:
    """입력 안이 파생 프레임에서 **추가로** 요구하는 열(`load_derived_slim(columns=…)`용)."""
    return list(NEIGHBOR_RESID_COLS) if seq_features == "neighbor" else []


def observed_channels(seq_features: str = "base") -> list[int]:
    """실측에서 온 채널 인덱스(값 + mask). 이력 절단·시나리오 마스킹이 지우는 대상이다.

    요일유형(3~6)·이력 이벤트(`events_hist`의 7~11)는 달력에서 오는 값이라 이력이 없어도 알 수 있고,
    지우면 "그 날이 무슨 날이었는지"까지 모르게 만든다 — 144 `apply_truncation`과 같은 판단이다.
    """
    idx = [0, 1, 2]
    if seq_features == "neighbor":
        idx += list(range(SEQ_CHANNELS, SEQ_CHANNELS + N_NEIGHBOR_CHANNELS))
    return idx


def _mask_observed(x_seq: np.ndarray, seq_features: str, fn) -> np.ndarray:
    """관측 채널만 골라 `fn(values, dummy_mask)`을 먹이고 되돌려 놓는다.

    마스크 채널도 "값"으로 넘겨 같은 keep로 0이 되게 한다(마스크 0 = 없음).
    """
    idx = observed_channels(seq_features)
    dummy = np.ones(x_seq.shape[:-1], dtype=x_seq.dtype)  # [B, N, 20]
    new_obs, _ = fn(x_seq[..., idx], dummy)
    out = x_seq.copy()
    out[..., idx] = new_obs
    return out


def truncate_seq(x_seq: np.ndarray, k, seq_features: str = "base") -> np.ndarray:
    """이력 앞쪽 `k`일 절단(표본별 배열 가능)을 시퀀스 텐서의 관측 채널에 적용한다."""
    return _mask_observed(x_seq, seq_features, lambda v, m: truncate_history(v, m, k, axis=1))


def scenario_seq(x_seq: np.ndarray, scenario: str, seq_features: str = "base") -> np.ndarray:
    """`masking.SCENARIOS` 시나리오를 시퀀스 텐서의 관측 채널에 적용한다."""
    return _mask_observed(x_seq, seq_features, lambda v, m: apply_scenario(v, m, scenario, axis=1))


# 144 계획의 시간 분할(포함 구간). 2025는 평가 전용 — early stopping에 쓰지 않는다.
SPLITS: dict[str, tuple[str, str]] = {
    "train": ("2024-01-01", "2024-10-31"),
    "valid": ("2024-11-01", "2024-12-31"),
    "eval": ("2025-01-01", "2025-12-31"),
}


def splits_with_train_start(
    train_start: str, base: Mapping[str, tuple[str, str]] = SPLITS
) -> dict[str, tuple[str, str]]:
    """`base`(기본 `SPLITS`)를 복사해 **학습 시작일만** 당긴다 — 검증·평가 경계는 그대로(145 후속 학습 창 확장).

    `base`는 바꾸지 않는다(항상 새 dict를 돌려준다). 학습 시작일이 학습 종료일 이상이면 학습
    구간이 비거나 뒤집히므로 막는다.
    """
    train_end = base["train"][1]
    if pd.Timestamp(train_start) >= pd.Timestamp(train_end):
        raise ValueError(f"train_start({train_start})는 학습 종료일({train_end})보다 앞서야 한다")
    return {**base, "train": (train_start, train_end)}


def parse_splits(
    text: str, base: Mapping[str, tuple[str, str]] = SPLITS
) -> dict[str, tuple[str, str]]:
    """`--splits` JSON 문자열 → `{train, valid, eval: (시작일, 종료일)}`(200 B부, 학습 창 전체 재정의).

    `splits_with_train_start`가 학습 시작일 하나만 당기는 것과 달리, 이 함수는 세 구간 경계를
    **전부** 새로 받는다 — 예: 2024~2025로 학습·검증하고 2026(아직 없는 미래)을 평가 구간으로 비워
    두는 재학습. `text`는 다음 형식의 JSON이어야 한다(`base`는 오늘 기본값 참고용 — 부분 지정은
    지원하지 않고 세 키를 전부 줘야 한다)::

        {"train": ["2024-01-01", "2025-10-31"],
         "valid": ["2025-11-01", "2025-12-31"],
         "eval": ["2026-01-01", "2026-12-31"]}

    키는 정확히 `{"train", "valid", "eval"}`여야 하고, 각 값은 `[YYYY-MM-DD, YYYY-MM-DD]` 2원소
    리스트다. 경계는 `train[0] <= train[1] < valid[0] <= valid[1] < eval[0] <= eval[1]`을 지켜야
    한다 — 구간이 뒤집히거나 겹치면(다음 구간 통계가 스며드는 누수) `ValueError`(한국어 메시지)를
    낸다. 평가 구간이 실제 패널 범위 밖(미래)이라 표본이 0개가 되는 것은 정상이다 — 그건
    `SequencePanel.split_index("eval")`이 빈 배열을 돌려주는 것으로 나타나고, `train_dl.run`이
    그 경우를 감지해 평가를 건너뛴다(빈 딕셔너리 자체는 여기서 막지 않는다).
    """
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--splits는 올바른 JSON이어야 한다: {exc}") from exc
    # CLI 입력 검증이라 타입·값 오류를 구분하지 않고 전부 ValueError로 통일한다(noqa: TRY004).
    if not isinstance(obj, dict):
        raise ValueError(f"--splits는 딕셔너리(JSON 객체)여야 한다: {obj!r}")  # noqa: TRY004
    required = {"train", "valid", "eval"}
    if set(obj) != required:
        raise ValueError(
            f"--splits의 키는 정확히 {sorted(required)}이어야 한다 — 받은 키: {sorted(obj)}"
        )

    parsed: dict[str, tuple[str, str]] = {}
    bounds: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for name in ("train", "valid", "eval"):
        value = obj[name]
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"--splits의 {name!r}은 [시작일, 종료일] 2개짜리 리스트여야 한다")
        start, end = value
        try:
            ts_start, ts_end = pd.Timestamp(start), pd.Timestamp(end)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"--splits의 {name!r} 날짜를 해석할 수 없다: {value!r}") from exc
        if ts_start > ts_end:
            raise ValueError(f"--splits의 {name!r} 구간이 뒤집혔다: {start} > {end}")
        parsed[name] = (str(start), str(end))
        bounds[name] = (ts_start, ts_end)

    if not bounds["train"][1] < bounds["valid"][0]:
        raise ValueError(
            f"학습 종료일({parsed['train'][1]})은 검증 시작일({parsed['valid'][0]})보다 앞서야 한다"
        )
    if not bounds["valid"][1] < bounds["eval"][0]:
        raise ValueError(
            f"검증 종료일({parsed['valid'][1]})은 평가 시작일({parsed['eval'][0]})보다 앞서야 한다"
        )
    return parsed


# ── 스케일·표준화 표 ──
def fit_scale(train_derived: pd.DataFrame, min_std: float = 1.0) -> pd.DataFrame:
    """역×슬롯별 잔차 표준편차 표 `[station_no, time_slot, boarding_std, alighting_std]`.

    학습 구간만 넣는다(평가 구간 통계가 스며들면 누수). 표본이 1개뿐이거나 상수인 셀은 `min_std`로 막는다.
    """
    g = train_derived.groupby(["station_no", "time_slot"], observed=True)[RESID_COLS]
    std = g.std(ddof=0).reset_index()
    std = std.rename(columns={f"{t}_resid": f"{t}_std" for t in TARGETS})
    for c in STD_COLS:
        std[c] = std[c].fillna(min_std).clip(lower=min_std).astype("float64")
    return std


def fit_event_stats(train_derived: pd.DataFrame, encoding: str = "zscore") -> pd.DataFrame:
    """이벤트 정적 피처의 (역, 날짜) 단위 스케일 표. 셀(슬롯) 중복을 빼고 잰다.

    두 인코딩의 상수를 **같이** 담는다 — `zscore`는 평균·표준편차, `log1p_max`는 `log1p(학습 최대)`.
    `encoding` 열은 그 표로 실제 학습한 인코딩이고, 아티팩트(`event_stats.parquet`)만 보고
    복원할 수 있게 하려고 남긴다. 학습 구간에 한 번도 안 나온 열(최대 0)은 나눗셈을 1.0으로 막는다.
    """
    if encoding not in EVENT_ENCODINGS:
        raise ValueError(f"모르는 event_encoding {encoding!r} — {list(EVENT_ENCODINGS)} 중 하나")
    daily = train_derived.drop_duplicates(["date", "station_no"])[EVENT_STATIC_COLS].fillna(0.0)
    mean = daily.mean()
    std = daily.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    log1p_max = np.log1p(daily.clip(lower=0.0).max()).replace(0.0, 1.0).fillna(1.0)
    return pd.DataFrame(
        {
            "feature": EVENT_STATIC_COLS,
            "mean": mean.values,
            "std": std.values,
            "log1p_max": log1p_max.values,
            "encoding": encoding,
        }
    )


def encode_events(
    raw: np.ndarray, event_stats: pd.DataFrame, encoding: str = "zscore"
) -> np.ndarray:
    """이벤트 원값 `[n, 5]`(열 순서 `EVENT_STATIC_COLS`, NaN은 0) → 입력 값 `[n, 5]`.

    `zscore`는 144·198 1차 그대로, `log1p_max`는 `log1p(x) / log1p(학습 최대)`로 학습 구간에서
    0~1에 들어간다(모듈 docstring "이벤트 인코딩"). 표에 `log1p_max` 열이 없는 옛 스케일 표로
    `log1p_max`를 요구하면 복원할 수 없으므로 막는다.
    """
    if encoding not in EVENT_ENCODINGS:
        raise ValueError(f"모르는 event_encoding {encoding!r} — {list(EVENT_ENCODINGS)} 중 하나")
    stats = event_stats.set_index("feature")
    raw = np.asarray(raw, dtype="float32")
    out = np.zeros_like(raw, dtype="float32")
    for j, c in enumerate(EVENT_STATIC_COLS):
        if encoding == "zscore":
            out[:, j] = (raw[:, j] - stats.loc[c, "mean"]) / stats.loc[c, "std"]
        else:
            if "log1p_max" not in stats.columns:
                raise ValueError(
                    "event_encoding='log1p_max'는 스케일 표에 log1p_max 열이 필요하다"
                    " — zscore로 학습한 옛 아티팩트다"
                )
            out[:, j] = np.log1p(np.clip(raw[:, j], 0.0, None)) / float(stats.loc[c, "log1p_max"])
    return out


def neighbor_scale(neighbor_map: pd.DataFrame, scale: pd.DataFrame) -> pd.DataFrame:
    """`(station_no, side, time_slot)` → **이웃 역 자신의** 잔차 std.

    `scale`은 `fit_scale` 결과(역×슬롯). 이웃 역 번호로 조인해 그 역의 std를 가져온다 —
    파생 캐시의 `nb_*_resid`는 "이웃 역 잔차의 평균"이라 이 역의 std로 나누면 규모가 어긋난다.
    한 side에 이웃이 여럿이면(분기점·다중 환승) 잔차와 같은 집합의 std 평균을 쓴다.
    """
    pairs = neighbor_map[["station_no", "side", "neighbor_station_no"]].drop_duplicates()
    joined = pairs.merge(
        scale.rename(columns={"station_no": "neighbor_station_no"}),
        on="neighbor_station_no",
        how="inner",
    )
    out = joined.groupby(["station_no", "side", "time_slot"], observed=True)[STD_COLS].mean()
    return out.reset_index()


def _date_index(dates: pd.Series | pd.DatetimeIndex, start: pd.Timestamp) -> np.ndarray:
    return ((pd.DatetimeIndex(dates).normalize() - start).days).to_numpy()


@dataclass
class SequencePanel:
    """(역 × 날짜 × 슬롯) 밀집 배열과, 거기서 창을 잘라 배치를 만드는 메서드."""

    station_ids: np.ndarray  # [S] 정렬된 station_no
    dates: pd.DatetimeIndex  # [D] 연속 일자(빠진 날도 자리를 가진다 — 마스크 0)
    z: np.ndarray  # [S, D, 20, 2] float32
    mask: np.ndarray  # [S, D, 20] float32
    day_type: np.ndarray  # [D] int8 — DAY_TYPES 인덱스
    events: np.ndarray  # [S, D, 5] float32 표준화
    std: np.ndarray  # [S, 20, 2] float32 — 역변환용
    seq_features: str = "base"
    use_static_events: bool = True
    event_encoding: str = "zscore"  # 198 후속 — "zscore" | "log1p_max"
    splits: dict[str, tuple[str, str]] = field(default_factory=lambda: dict(SPLITS))  # 145 후속
    nb_z: np.ndarray | None = None  # [S, D, 20, 6] float32 — `neighbor`일 때만
    nb_mask: np.ndarray | None = None  # [S, D, 20, 3] float32 — side별 1 있음 / 0 없음

    @property
    def seq_channels(self) -> int:
        return seq_channels_for(self.seq_features)

    # ── 생성 ──
    @classmethod
    def build(
        cls,
        derived: pd.DataFrame,
        scale: pd.DataFrame,
        event_stats: pd.DataFrame,
        holidays: pd.DataFrame | None = None,
        station_ids: Sequence[int] | None = None,
        seq_features: str = "base",
        use_static_events: bool = True,
        neighbor_map: pd.DataFrame | None = None,
        event_encoding: str = "zscore",
        splits: Mapping[str, tuple[str, str]] | None = None,
    ) -> SequencePanel:
        """파생 프레임(학습·검증·평가 전부 포함 가능)을 밀집 배열로 pivot한다.

        `station_ids`를 주면 그 순서를 강제한다(학습 때 저장한 순서로 추론 패널을 만들 때).
        표에 없는 (역, 슬롯)은 std가 없어 z를 만들 수 없으므로 마스크 0으로 남긴다.
        `seq_features="neighbor"`면 `derived`에 `nb_*_resid` 6열이, `neighbor_map`에 이웃 표가 필요하다
        (`adjacency.build_neighbor_map`/`build_transfer_map`을 concat한 것).
        `splits`를 주면 `split_index`가 그 경계를 쓴다(기본은 `SPLITS`) — 145 후속 학습 창 확장에서
        학습 시작일만 당길 때 `splits_with_train_start`로 만든 값을 넘긴다.
        """
        if seq_features not in SEQ_FEATURE_SETS:
            raise ValueError(
                f"모르는 seq_features {seq_features!r} — {list(SEQ_FEATURE_SETS)} 중 하나"
            )
        if event_encoding not in EVENT_ENCODINGS:
            raise ValueError(
                f"모르는 event_encoding {event_encoding!r} — {list(EVENT_ENCODINGS)} 중 하나"
            )
        extra = seq_feature_columns(seq_features)
        present = [c for c in extra if c in derived.columns]
        if extra and not present:
            raise ValueError(f"seq_features={seq_features!r}에 필요한 열이 없다: {extra}")
        df = derived[["date", "station_no", "time_slot", "day_type", *RESID_COLS, *present]].copy()
        # side 하나가 통째로 없는 토폴로지(환승 없는 노선 등)는 그 side만 NaN → 마스크 0
        for c in extra:
            if c not in present:
                df[c] = np.nan
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        if station_ids is None:
            station_ids = np.sort(df["station_no"].unique())
        station_ids = np.asarray(station_ids, dtype="int64")
        s_lookup = pd.Series(np.arange(len(station_ids)), index=station_ids)
        df = df[df["station_no"].isin(station_ids)]

        start, end = df["date"].min(), df["date"].max()
        dates = pd.date_range(start, end, freq="D")
        S, D = len(station_ids), len(dates)

        # std [S, 20, 2] — 표에 없는 셀은 NaN → 그 셀은 마스크 0
        std = np.full((S, N_SLOTS, N_TARGETS), np.nan, dtype="float32")
        sc = scale[scale["station_no"].isin(station_ids)]
        std[
            s_lookup.loc[sc["station_no"]].to_numpy(),
            pd.Categorical(sc["time_slot"], categories=SLOT_ORDER).codes,
        ] = sc[STD_COLS].to_numpy(dtype="float32")

        s_idx = s_lookup.loc[df["station_no"]].to_numpy()
        d_idx = _date_index(df["date"], start)
        slot_idx = pd.Categorical(df["time_slot"], categories=SLOT_ORDER).codes.astype("int64")
        if (slot_idx < 0).any():
            bad = sorted(set(df.loc[slot_idx < 0, "time_slot"]))
            raise ValueError(f"SLOT_ORDER에 없는 슬롯: {bad}")

        resid = df[RESID_COLS].to_numpy(dtype="float32")
        cell_std = std[s_idx, slot_idx]  # [rows, 2]
        with np.errstate(invalid="ignore", divide="ignore"):
            z_rows = resid / cell_std
        ok = np.isfinite(z_rows).all(axis=1)

        z = np.zeros((S, D, N_SLOTS, N_TARGETS), dtype="float32")
        mask = np.zeros((S, D, N_SLOTS), dtype="float32")
        z[s_idx[ok], d_idx[ok], slot_idx[ok]] = z_rows[ok]
        mask[s_idx[ok], d_idx[ok], slot_idx[ok]] = 1.0

        # 이웃 잔차 z [S, D, 20, 6] · side 마스크 [S, D, 20, 3] — `neighbor`일 때만
        nb_z = nb_mask = None
        if seq_features == "neighbor":
            if neighbor_map is None or not len(neighbor_map):
                raise ValueError("seq_features='neighbor'는 neighbor_map이 필요하다")
            nb_std = np.full((S, N_SLOTS, len(NEIGHBOR_RESID_COLS)), np.nan, dtype="float32")
            ns = neighbor_scale(neighbor_map, scale)
            ns = ns[ns["station_no"].isin(station_ids)]
            for i, side in enumerate(NEIGHBOR_SIDES):
                part = ns[ns["side"] == side]
                if not len(part):
                    continue
                nb_std[
                    s_lookup.loc[part["station_no"]].to_numpy(),
                    pd.Categorical(part["time_slot"], categories=SLOT_ORDER).codes,
                    slice(2 * i, 2 * i + N_TARGETS),
                ] = part[STD_COLS].to_numpy(dtype="float32")
            nb_resid = df[NEIGHBOR_RESID_COLS].to_numpy(dtype="float32")
            with np.errstate(invalid="ignore", divide="ignore"):
                nb_rows = nb_resid / nb_std[s_idx, slot_idx]
            # side 하나는 승·하차가 같은 이웃 행에서 오므로 둘 다 유한할 때만 있음으로 본다
            side_ok = np.isfinite(nb_rows).reshape(-1, len(NEIGHBOR_SIDES), N_TARGETS).all(axis=2)
            nb_rows = np.nan_to_num(nb_rows, nan=0.0, posinf=0.0, neginf=0.0)
            nb_rows = (
                nb_rows.reshape(-1, len(NEIGHBOR_SIDES), N_TARGETS) * side_ok[..., None]
            ).reshape(nb_rows.shape)
            nb_z = np.zeros((S, D, N_SLOTS, len(NEIGHBOR_RESID_COLS)), dtype="float32")
            nb_mask = np.zeros((S, D, N_SLOTS, len(NEIGHBOR_SIDES)), dtype="float32")
            nb_z[s_idx, d_idx, slot_idx] = nb_rows
            nb_mask[s_idx, d_idx, slot_idx] = side_ok.astype("float32")

        # 요일유형 [D] — 패널 값 우선, 빈 날은 달력
        day_type = _day_type_index(df, dates, holidays)

        # 이벤트 [S, D, 5] — 인코딩(zscore | log1p_max), 없는 (역, 날짜)는 0
        events = np.zeros((S, D, len(EVENT_STATIC_COLS)), dtype="float32")
        ev_cols = [c for c in EVENT_STATIC_COLS if c in derived.columns]
        if ev_cols:
            daily = derived.drop_duplicates(["date", "station_no"])[
                ["date", "station_no", *ev_cols]
            ].copy()
            daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
            daily = daily[daily["station_no"].isin(station_ids)]
            raw = np.zeros((len(daily), len(EVENT_STATIC_COLS)), dtype="float32")
            for j, c in enumerate(EVENT_STATIC_COLS):
                if c in ev_cols:
                    raw[:, j] = daily[c].fillna(0.0).to_numpy(dtype="float32")
            vals = encode_events(raw, event_stats, event_encoding)
            # 파생 프레임에 없는 열은 원값 0 자리에 남는다 — zscore는 "학습 평균과의 거리 0"이 아니라
            # 그 열의 평균 위치가 되므로, 없는 열이 있으면 그 자리를 0으로 되돌린다(정보 없음).
            for j, c in enumerate(EVENT_STATIC_COLS):
                if c not in ev_cols:
                    vals[:, j] = 0.0
            events[
                s_lookup.loc[daily["station_no"]].to_numpy(), _date_index(daily["date"], start)
            ] = vals

        return cls(
            station_ids=station_ids,
            dates=dates,
            z=z,
            mask=mask,
            day_type=day_type,
            events=events,
            std=np.nan_to_num(std, nan=1.0),
            seq_features=seq_features,
            use_static_events=use_static_events,
            event_encoding=event_encoding,
            splits=dict(splits or SPLITS),
            nb_z=nb_z,
            nb_mask=nb_mask,
        )

    # ── 표본 인덱스 ──
    def sample_index(
        self, start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """대상일 슬롯이 하나라도 있는 (역 인덱스, 날짜 인덱스) 쌍. `start~end`(포함)로 자른다."""
        present = self.mask.any(axis=2)  # [S, D]
        if start is not None:
            present &= (self.dates >= pd.Timestamp(start))[None, :]
        if end is not None:
            present &= (self.dates <= pd.Timestamp(end))[None, :]
        s_idx, d_idx = np.nonzero(present)
        return s_idx.astype("int64"), d_idx.astype("int64")

    def split_index(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        start, end = self.splits[name]
        return self.sample_index(start, end)

    # ── 배치 ──
    def make_batch(
        self, s_idx: np.ndarray, d_idx: np.ndarray, seq_days: int
    ) -> dict[str, np.ndarray]:
        """`(s, t)` 표본 배치의 입력·타깃. 창은 `t−N … t−1`, 배열 범위 밖(패널 시작 전)은 마스크 0."""
        s_idx = np.asarray(s_idx, dtype="int64")
        d_idx = np.asarray(d_idx, dtype="int64")
        offsets = d_idx[:, None] - np.arange(seq_days, 0, -1)[None, :]  # [B, N], 마지막 열이 D−1
        valid = offsets >= 0
        off_c = np.clip(offsets, 0, len(self.dates) - 1)
        s_b = np.broadcast_to(s_idx[:, None], offsets.shape)

        z_hist = self.z[s_b, off_c] * valid[..., None, None]  # [B, N, 20, 2]
        m_hist = self.mask[s_b, off_c] * valid[..., None]  # [B, N, 20]
        dt_hist = np.eye(len(DAY_TYPES), dtype="float32")[self.day_type[off_c]]  # [B, N, 4]
        dt_hist = np.broadcast_to(dt_hist[:, :, None, :], (*m_hist.shape, len(DAY_TYPES)))
        parts = [z_hist, m_hist[..., None], dt_hist]
        if self.seq_features == "neighbor":
            parts.append(self.nb_z[s_b, off_c] * valid[..., None, None])  # [B, N, 20, 6]
            parts.append(self.nb_mask[s_b, off_c] * valid[..., None, None])  # [B, N, 20, 3]
        elif self.seq_features == "events_hist":
            ev_hist = self.events[s_b, off_c] * valid[..., None]  # [B, N, 5]
            parts.append(
                np.broadcast_to(ev_hist[:, :, None, :], (*m_hist.shape, len(EVENT_STATIC_COLS)))
            )
        x_seq = np.concatenate(parts, axis=-1).astype("float32")

        dt_target = np.eye(len(DAY_TYPES), dtype="float32")[self.day_type[d_idx]]  # [B, 4]
        stat_parts = [dt_target]
        if self.use_static_events:
            stat_parts.append(self.events[s_idx, d_idx])
        x_stat = np.concatenate(stat_parts, axis=-1).astype("float32")
        return {
            "x_seq": x_seq,
            "x_stat": x_stat,
            "station": s_idx,
            "y": self.z[s_idx, d_idx],
            "y_mask": self.mask[s_idx, d_idx],
        }

    # ── 복원 ──
    def inverse(self, z_pred: np.ndarray, s_idx: np.ndarray) -> np.ndarray:
        """z-잔차 `[B, 20, 2]` → 잔차(명) `[B, 20, 2]`. `lookup + 이 값`이 최종 예측."""
        return np.asarray(z_pred, dtype="float32") * self.std[np.asarray(s_idx, dtype="int64")]

    def to_frame(
        self, s_idx: np.ndarray, d_idx: np.ndarray, resid_pred: np.ndarray
    ) -> pd.DataFrame:
        """배치 예측 `[B, 20, 2]`(명)을 롱 포맷 `[station_no, date, time_slot, {t}_resid_pred]`로 푼다."""
        B = len(s_idx)
        out = pd.DataFrame(
            {
                "station_no": np.repeat(self.station_ids[np.asarray(s_idx)], N_SLOTS),
                "date": np.repeat(self.dates.to_numpy()[np.asarray(d_idx)], N_SLOTS),
                "time_slot": np.tile(np.array(SLOT_ORDER, dtype=object), B),
            }
        )
        flat = np.asarray(resid_pred, dtype="float32").reshape(B * N_SLOTS, N_TARGETS)
        for j, t in enumerate(TARGETS):
            out[f"{t}_resid_pred"] = flat[:, j]
        return out

    # ── 아티팩트 ──
    def save_scale(self, out_dir: Path) -> Path:
        """`scale.parquet` — 역변환용 std 표(역 순서 포함)를 아티팩트에 남긴다."""
        rows = pd.DataFrame(
            {
                "station_no": np.repeat(self.station_ids, N_SLOTS),
                "time_slot": np.tile(np.array(SLOT_ORDER, dtype=object), len(self.station_ids)),
            }
        )
        flat = self.std.reshape(-1, N_TARGETS)
        for j, t in enumerate(TARGETS):
            rows[f"{t}_std"] = flat[:, j]
        path = Path(out_dir) / "scale.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows.to_parquet(path, index=False)
        return path


def _day_type_index(
    df: pd.DataFrame, dates: pd.DatetimeIndex, holidays: pd.DataFrame | None
) -> np.ndarray:
    from app.CROWD.pipeline.calendar import attach_calendar

    per_date = df.drop_duplicates("date").set_index("date")["day_type"]
    cal = pd.DataFrame({"date": dates})
    known = cal["date"].map(per_date)
    if known.isna().any():
        filled = attach_calendar(cal[known.isna()], holidays)["day_type"].to_numpy()
        known = known.to_numpy(dtype=object)
        known[pd.isna(known)] = filled
    codes = pd.Categorical(known, categories=DAY_TYPES).codes
    if (codes < 0).any():
        raise ValueError(f"DAY_TYPES에 없는 요일유형: {sorted(set(np.asarray(known)[codes < 0]))}")
    return codes.astype("int8")


# ── 파생 캐시 부분 읽기 ──
SLIM_COLS = ["date", "station_no", "time_slot", "day_type", *RESID_COLS, *EVENT_STATIC_COLS]


def load_derived_slim(
    columns: Sequence[str] | None = None,
    cache_path: Path | None = None,
    panel_path: Path | None = None,
    events_path: Path | None = None,
    split_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """파생 캐시(398.7만 행 × 64열, 575MB)에서 **필요한 열만** 읽는다.

    시퀀스 모델은 잔차·요일유형·이벤트만 쓰므로 64열을 전부 올릴 이유가 없다(메모리·시간 모두 절약).
    캐시가 없거나 `derived_version`이 다르면 `load_or_build_derived`로 만든 뒤 열을 자른다 —
    파생 재계산 조건은 그 함수가 판정하는 그대로다(`AI/CLAUDE.md` "실험 실행 효율").

    `panel_path`/`events_path`/`split_date`를 주면 캐시 미스일 때 그 패널로 파생을 새로 만든다
    (145 후속 학습 창 확장 — 예: 2023~2025 패널). 캐시 히트 경로는 그대로다(요청한 열이 이미
    캐시에 있으면 패널을 읽지 않는다). `panel_path`를 바꾸면서 `cache_path`를 생략하면 기본
    파생 캐시(`crowd_panel_derived_2024_2025.parquet`)를 덮어쓰게 되므로 막는다.
    """
    from app.CROWD.pipeline.dataset import (
        CROWD_PROCESSED,
        DERIVED_CACHE,
        PANEL_NAME,
        SPLIT_DATE,
        load_or_build_derived,
        load_panel,
    )
    from app.CROWD.pipeline.dataset import time_split as _time_split
    from app.CROWD.pipeline.features import DERIVED_VERSION
    from app.CROWD.pipeline.lookup import DayTypeLookupBaseline

    if panel_path is not None and cache_path is None:
        raise ValueError(
            "panel_path를 바꾸면 cache_path도 따로 줘야 한다 — 기본 파생 캐시를 덮어쓴다"
        )

    cols = list(columns or SLIM_COLS)
    cache_path = Path(cache_path or DERIVED_CACHE)
    meta_path = cache_path.with_suffix(".meta.json")
    if cache_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("derived_version") == DERIVED_VERSION and set(cols) <= set(
            meta.get("columns", [])
        ):
            out = pd.read_parquet(cache_path, columns=cols)
            print(
                f"[파생 캐시] 부분 읽기: {cache_path.name} ({len(out):,}행, {len(cols)}열)",
                flush=True,
            )
            out["date"] = pd.to_datetime(out["date"]).dt.normalize()
            return out
    load_kwargs: dict[str, Path] = {}
    if panel_path is not None:
        load_kwargs["panel_path"] = panel_path
    if events_path is not None:
        load_kwargs["events_path"] = events_path
    panel = load_panel(with_events=True, **load_kwargs)
    train_raw, _ = _time_split(panel, split_date or SPLIT_DATE)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    out = load_or_build_derived(
        panel,
        lookup,
        cache_path=cache_path,
        panel_path=panel_path or CROWD_PROCESSED / PANEL_NAME,
    )[cols].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out
