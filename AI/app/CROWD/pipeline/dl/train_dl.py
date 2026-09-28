"""GRU/LSTM 잔차 모델 학습 → 아티팩트 저장(144).

    최종 예측 = lookup(요일유형×역×시간대 평균) + GRU가 낸 z-잔차 × scale(역, 슬롯)

LightGBM 아티팩트(`train.py`)와 같은 자리(`models/CROWD/`)에 같은 관례로 저장하되, 폴더명은
`dl_<model>_s<seq_days>_<YYYYMMDD-HHMM>`이고 `meta.json`에 `model_kind="dl"`을 남긴다 —
배치의 `--predictor auto`는 `model_kind == "lightgbm"`만 고르므로(`predictor.latest_artifact`)
DL 아티팩트를 만들어도 운영 기본값이 조용히 바뀌지 않는다.

## 학습 구성

- 표본 = (역, 대상일) 하나. 입력은 직전 `seq_days`일 × 20슬롯 × C채널, 출력은 대상일 20슬롯 × 2.
  C는 `--seq-features`가 정한다(198): `base` 7 · `events_hist` 12 · `neighbor` 16
  (`dl/dataset.seq_channels_for`).
- **정적 이벤트는 기본이 꺼짐이다(198 판정 1).** 144는 대상일 이벤트 5열을 정적 피처로 넣었는데,
  2025 평가에서 그것을 빼면 `full` RMSE 개선율이 시드 3회 평균 +8.29 → **+20.17**(승), +16.43 → +22.60(하)로
  오르고 `no_lag`도 −8.13 → +1.05로 뒤집힌다. 이벤트 표준화가 2024 분포에 묶여 2025에서 해로웠다는 뜻이다.
  144 구성을 재현하려면 `--static-events`.
- **이벤트 인코딩**(`--event-encoding`, 198 후속): 이벤트 5열을 z-점수로 넣으면 99%가 0인 희소 카운트라
  학습 std가 0.07~0.13이고 이벤트 날 입력이 z 12.8~38.5로 튄다. `log1p_max`는 `log1p(x)/log1p(학습 최대)`로
  학습 구간에서 0~1에 넣는다(`dl/dataset` "이벤트 인코딩"). 정적 이벤트를 끈 안에서는 이력 이벤트
  채널(`--seq-features events_hist`)에만 영향이 있다.
- 분할은 `dl/dataset.SPLITS`: 2024-01~10 학습 / 2024-11~12 검증(early stopping) / 2025 평가.
  검증으로 에폭만 고르고 **2024 전체로 재학습하지 않는다**(144 계획 4번 — 단순화, 기록).
- **이력 절단 증강**: 표본마다 `k ~ U{0..seq_days}`로 앞쪽 k일을 마스크(`masking.sample_truncation`
  + `truncate_history`). 143에서 LightGBM은 시차가 전부 NaN이면 lookup보다 −37%였는데, 절단을
  학습 분포에 넣으면 "이력이 짧다"가 모르는 상황이 아니게 된다. `--no-truncation`이 대조군이다.
- 검증 손실은 **절단 없는 full 이력**으로 잰다. 증강 여부가 다른 두 모델을 같은 잣대로 비교하고
  early stopping을 결정적으로 만들기 위해서다. 참고용으로 절단 섞인 손실(`valid_loss_trunc`,
  고정 시드)도 `history.json`에 같이 남긴다.

## 학습 창 확장(145 후속) · 전체 재정의(200 B부)

기본 구성은 `dl/dataset.SPLITS`(2024-01~10 학습)로 고정이다. `--train-start`를 주면
`splits_with_train_start`로 **학습 시작일만** 당기고 검증(2024-11~12)·평가(2025) 경계는 그대로 둔다.
다른 패널·파생 캐시(예: 2023~2025로 늘린 패널)로 학습하려면 `--panel`/`--events`/`--derived-cache`를
같이 준다 — `--panel`만 주고 `--derived-cache`를 생략하면 기본 파생 캐시를 덮어쓰므로 막는다
(`train.py`와 같은 가드).

**`--splits`**(200 B부)는 세 구간 경계를 전부 새로 받는다(`dl/dataset.parse_splits`) — 예:
2024~2025를 학습·검증으로 쓰고 아직 데이터가 없는 2026을 평가로 비워 두는 재학습(다음 프로덕션
아티팩트가 이 창을 쓴다, `MODEL_REGISTRY.md` "4b. 아티팩트 승격 절차"). `--train-start`와는
**동시에 줄 수 없다**(`SystemExit`) — 하나는 시작일만 옮기고 다른 하나는 전체를 새로 받아 같이
쓰면 어느 쪽이 이겼는지 모호하다. 평가 구간이 실제 패널 범위 밖(미래)이면 표본이 0개인 것이
정상이다 — `run()`이 그 경우 `[안내] 평가 구간 표본 0 — 평가 생략`을 찍고 학습·검증(early
stopping)은 그대로 진행한다. `meta.json`에는 `eval_rows`로 남는다.

## 재현성

`torch.manual_seed` + `use_deterministic_algorithms(True, warn_only=True)`를 건다. cuDNN RNN은
완전 결정적이지 않을 수 있어 **같은 시드로 짧게 2회 학습**해 검증 손실 차이를 재고(`--determinism-probe`
에폭) `meta.json["determinism"]`에 남긴다. 허용 0.5%이며 넘어도 기록만 하고 진행한다(144 계획).

실행:
    cd AI
    python -m app.CROWD.pipeline.dl.train_dl --model gru                      # 전체(GPU 몇 분)
    python -m app.CROWD.pipeline.dl.train_dl --model gru --no-truncation      # 대조군
    python -m app.CROWD.pipeline.dl.train_dl --stations 20 --epochs 2         # 소표본 스모크
    python -m app.CROWD.pipeline.dl.train_dl --seq-features neighbor          # 198 V1
    python -m app.CROWD.pipeline.dl.train_dl --static-events                  # 198 V0(144 구성)
    python -m app.CROWD.pipeline.dl.train_dl --huber-delta 3                  # 198 손실 실험
    python -m app.CROWD.pipeline.dl.train_dl --train-start 2023-01-01
        --panel crowd_panel_2023_2025.parquet --events crowd_station_events_2023_2025.parquet
        --derived-cache crowd_panel_derived_2023_2025.parquet
        --out-root models/CROWD/_experiments/masking --name w2023_gru_s42   # 145 후속 창 확장(한 줄로)
    python -m app.CROWD.pipeline.dl.train_dl
        --splits '{"train": ["2024-01-01", "2025-10-31"], "valid": ["2025-11-01", "2025-12-31"],
                   "eval": ["2026-01-01", "2026-12-31"]}'
        --out-root models/CROWD/_experiments/ops --name w2024_2025_gru_s42   # 200 B부 전체 재정의
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# cuBLAS 결정적 경로. torch를 import하기 전에 설정해야 효과가 있다.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

from app.CROWD.pipeline.dataset import CROWD_INTERIM, CROWD_PROCESSED, time_split
from app.CROWD.pipeline.dl.dataset import (
    EVENT_ENCODINGS,
    SEQ_FEATURE_SETS,
    SLIM_COLS,
    SPLITS,
    SequencePanel,
    fit_event_stats,
    fit_scale,
    load_derived_slim,
    parse_splits,
    seq_channels_for,
    seq_feature_columns,
    splits_with_train_start,
    stat_features_for,
    truncate_seq,
)
from app.CROWD.pipeline.features import DERIVED_VERSION
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.masking import sample_truncation

AI_ROOT = Path(__file__).resolve().parents[4]
MODELS_DIR = AI_ROOT / "models" / "CROWD"


# ── 장치 ──
def resolve_device(name: str = "auto") -> str:
    """`auto`면 cuda가 있을 때 GPU, 없으면 CPU(`AI/CLAUDE.md` "딥러닝 학습 — GPU 우선")."""
    import torch

    if name == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return name


# ── 데이터 ──
def build_train_panel(
    stations: int | None = None,
    seq_features: str = "base",
    use_static_events: bool = True,
    event_encoding: str = "zscore",
    splits: Mapping[str, tuple[str, str]] = SPLITS,
    panel_path: Path | None = None,
    events_path: Path | None = None,
    derived_cache: Path | None = None,
) -> tuple[SequencePanel, pd.DataFrame, pd.DataFrame]:
    """파생(잔차·요일유형·이벤트 + 입력 안이 요구하는 열)만 읽어 밀집 패널·스케일·통계를 만든다.

    스케일·이벤트 통계는 **`splits["train"]`만**으로 fit한다 — 검증·평가 구간 통계가 스며들면 누수다.
    `seq_features="neighbor"`면 파생 캐시의 `nb_*_resid` 6열을 더 읽고(재계산 없음) 이웃 표를 만든다.
    `splits`(기본 `SPLITS`)로 학습 구간을 고르고, `panel_path`/`events_path`/`derived_cache`를 주면
    그 패널·파생 캐시를 쓴다(145 후속 학습 창 확장). 기본은 오늘과 동일하게 2024/2025 패널이다.
    """
    load_kwargs: dict[str, Path] = {}
    if panel_path is not None:
        load_kwargs["panel_path"] = panel_path
    if events_path is not None:
        load_kwargs["events_path"] = events_path
    derived = load_derived_slim(
        columns=[*SLIM_COLS, *seq_feature_columns(seq_features)],
        cache_path=derived_cache,
        **load_kwargs,
    )
    derived = derived[derived["date"] < pd.Timestamp(splits["eval"][0])]
    if stations:
        keep = np.sort(derived["station_no"].unique())[:stations]
        derived = derived[derived["station_no"].isin(keep)]
    tr_start, tr_end = splits["train"]
    train_d = derived[(derived["date"] >= tr_start) & (derived["date"] <= tr_end)]
    scale = fit_scale(train_d)
    stats = fit_event_stats(train_d, encoding=event_encoding)
    sp = SequencePanel.build(
        derived,
        scale,
        stats,
        seq_features=seq_features,
        use_static_events=use_static_events,
        neighbor_map=panel_neighbor_map() if seq_features == "neighbor" else None,
        event_encoding=event_encoding,
        splits=splits,
    )
    return sp, scale, stats


def panel_neighbor_map() -> pd.DataFrame:
    """노선 앞뒤(`prev`·`next`) + 환승(`xfer`) 이웃 표 — 파생 캐시의 `nb_*` 정의와 같은 조합."""
    from app.CROWD.pipeline.adjacency import build_neighbor_map, build_transfer_map
    from app.CROWD.pipeline.dataset import load_panel, resolved_segments

    panel = load_panel(with_events=False)
    segments, _ = resolved_segments(panel)
    nodes = panel[["station_no", "station_name", "line"]].drop_duplicates("station_no")
    return pd.concat([build_neighbor_map(segments), build_transfer_map(nodes)], ignore_index=True)


# ── 배치 ──
def _tensors(batch: dict[str, np.ndarray], device: str):
    import torch

    return (
        torch.from_numpy(batch["x_seq"]).to(device),
        torch.from_numpy(batch["x_stat"]).to(device),
        torch.from_numpy(batch["station"]).to(device),
        torch.from_numpy(batch["y"]).to(device),
        torch.from_numpy(batch["y_mask"]).to(device),
    )


def apply_truncation(
    x_seq: np.ndarray,
    rng: np.random.Generator,
    seq_days: int,
    p_full: float,
    seq_features: str = "base",
) -> np.ndarray:
    """배치의 **관측 채널**(자기 z·마스크, 이웃 z·마스크)에 표본별 이력 절단을 적용한다.

    요일유형·이력 이벤트 채널은 달력 정보라 남긴다(`dataset.observed_channels`).
    """
    k = sample_truncation(rng, len(x_seq), seq_days, p_full)
    return truncate_seq(x_seq, k, seq_features)


def _epoch_loss(
    model,
    sp: SequencePanel,
    idx: tuple[np.ndarray, np.ndarray],
    seq_days: int,
    batch_size: int,
    device: str,
    rng: np.random.Generator | None = None,
    p_full: float = 0.0,
    huber_delta: float = 1.0,
) -> float:
    """평가용 손실(가중 평균). `rng`를 주면 절단 증강을 섞은 손실을 잰다."""
    import torch

    from app.CROWD.pipeline.dl.model import masked_huber

    s_all, d_all = idx
    model.eval()
    total, n = 0.0, 0
    with torch.no_grad():
        for start in range(0, len(s_all), batch_size):
            sl = slice(start, start + batch_size)
            batch = sp.make_batch(s_all[sl], d_all[sl], seq_days)
            if rng is not None:
                batch["x_seq"] = apply_truncation(
                    batch["x_seq"], rng, seq_days, p_full, sp.seq_features
                )
            x_seq, x_stat, station, y, y_mask = _tensors(batch, device)
            loss = masked_huber(model(x_seq, x_stat, station), y, y_mask, delta=huber_delta)
            w = float(y_mask.sum())
            total += float(loss) * w
            n += w
    return total / n if n else float("nan")


# ── 학습 ──
def train_one(
    sp: SequencePanel,
    idx_train: tuple[np.ndarray, np.ndarray],
    idx_valid: tuple[np.ndarray, np.ndarray],
    *,
    model_kind: str,
    seq_days: int,
    hidden: int,
    epochs: int,
    patience: int,
    seed: int,
    device: str,
    batch_size: int,
    lr: float,
    p_full: float,
    truncation: bool,
    huber_delta: float = 1.0,
    quiet: bool = False,
) -> tuple[object, list[dict], int]:
    """한 번 학습하고 (best 상태를 담은 모델, 에폭별 기록, best 에폭)을 돌려준다."""
    import torch

    from app.CROWD.pipeline.dl.model import ResidualGRU, masked_huber

    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    rng = np.random.default_rng(seed)

    model = ResidualGRU(
        len(sp.station_ids),
        model=model_kind,
        hidden=hidden,
        seq_channels=sp.seq_channels,
        stat_features=stat_features_for(sp.use_static_events),
    ).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    s_tr, d_tr = idx_train

    history: list[dict] = []
    best = (float("inf"), 0, copy.deepcopy(model.state_dict()))
    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        order = rng.permutation(len(s_tr))
        total, n = 0.0, 0
        for start in range(0, len(order), batch_size):
            sel = order[start : start + batch_size]
            batch = sp.make_batch(s_tr[sel], d_tr[sel], seq_days)
            if truncation:
                batch["x_seq"] = apply_truncation(
                    batch["x_seq"], rng, seq_days, p_full, sp.seq_features
                )
            x_seq, x_stat, station, y, y_mask = _tensors(batch, device)
            loss = masked_huber(model(x_seq, x_stat, station), y, y_mask, delta=huber_delta)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            w = float(y_mask.sum())
            total += float(loss.detach()) * w
            n += w
        train_loss = total / n if n else float("nan")
        valid_loss = _epoch_loss(
            model, sp, idx_valid, seq_days, batch_size, device, huber_delta=huber_delta
        )
        valid_trunc = _epoch_loss(
            model,
            sp,
            idx_valid,
            seq_days,
            batch_size,
            device,
            rng=np.random.default_rng(1234),
            p_full=p_full,
            huber_delta=huber_delta,
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": round(train_loss, 6),
                "valid_loss": round(valid_loss, 6),
                "valid_loss_trunc": round(valid_trunc, 6),
                "seconds": round(time.time() - t0, 1),
            }
        )
        if not quiet:
            print(
                f"[학습] 에폭 {epoch:2d} train {train_loss:.5f} · valid {valid_loss:.5f}"
                f" · valid(절단) {valid_trunc:.5f} · {history[-1]['seconds']}s",
                flush=True,
            )
        if valid_loss < best[0] - 1e-6:
            best = (valid_loss, epoch, copy.deepcopy(model.state_dict()))
        elif epoch - best[1] >= patience:
            if not quiet:
                print(f"[학습] early stop — {patience}에폭 개선 없음(best {best[1]})", flush=True)
            break
    model.load_state_dict(best[2])
    return model, history, best[1]


# ── 아티팩트 ──
def save_artifact(out_dir: Path, model, sp: SequencePanel, lookup, stats, meta, history) -> Path:
    import torch

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_dir / "model.pt")
    sp.save_scale(out_dir)
    lookup.save(out_dir / "lookup.parquet")
    stats.to_parquet(out_dir / "event_stats.parquet", index=False)
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out_dir / "history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out_dir


def prepare(
    args,
    splits: Mapping[str, tuple[str, str]] = SPLITS,
    panel_path: Path | None = None,
    events_path: Path | None = None,
    derived_cache: Path | None = None,
) -> tuple[SequencePanel, pd.DataFrame, DayTypeLookupBaseline]:
    """밀집 패널·이벤트 통계·lookup — 한 안의 시드·손실 반복이 **공유하는** 준비물(198).

    시드마다 새로 만들면 400만 행 읽기·pivot을 반복하게 된다(`AI/CLAUDE.md` "실험 실행 효율").
    lookup은 LightGBM 아티팩트와 같은 기준선(패널 전체 fit) — 파생 캐시의 잔차 정의와 같아야 한다.
    `splits`/`panel_path`/`events_path`/`derived_cache`는 145 후속 학습 창 확장 — 기본값은 오늘과
    동일한 144 구성이다. lookup도 같은 패널로 fit해야 파생 캐시의 잔차 정의와 어긋나지 않는다.
    """
    from app.CROWD.pipeline.dataset import load_panel

    sp, _scale, stats = build_train_panel(  # scale은 sp.save_scale이 아티팩트에 쓴다
        args.stations,
        seq_features=args.seq_features,
        use_static_events=args.static_events,
        event_encoding=args.event_encoding,
        splits=splits,
        panel_path=panel_path,
        events_path=events_path,
        derived_cache=derived_cache,
    )
    load_kwargs: dict[str, Path] = {}
    if panel_path is not None:
        load_kwargs["panel_path"] = panel_path
    if events_path is not None:
        load_kwargs["events_path"] = events_path
    panel = load_panel(with_events=True, **load_kwargs)
    train_raw, _ = time_split(panel)
    return sp, stats, DayTypeLookupBaseline().fit(train_raw)


def run(args, prepared=None) -> Path:
    import torch

    device = resolve_device(args.device)
    t0 = time.time()

    panel_path = getattr(args, "panel", None)
    events_path = getattr(args, "events", None)
    derived_cache = getattr(args, "derived_cache", None)
    if panel_path is not None and derived_cache is None:
        raise SystemExit(
            "--panel을 바꾸면 --derived-cache도 따로 줘야 한다 — 기본 캐시"
            "(crowd_panel_derived_2024_2025)를 덮어쓴다"
        )
    splits_json = getattr(args, "splits", None)
    train_start = getattr(args, "train_start", None)
    if splits_json and train_start:
        raise SystemExit("--splits와 --train-start는 함께 쓸 수 없다 — 하나만 골라라")
    if splits_json:
        splits = parse_splits(splits_json)
    else:
        splits = splits_with_train_start(train_start or SPLITS["train"][0])

    sp, stats, lookup = (
        prepared
        if prepared is not None
        else prepare(
            args,
            splits=splits,
            panel_path=panel_path,
            events_path=events_path,
            derived_cache=derived_cache,
        )
    )
    idx_train = sp.split_index("train")
    idx_valid = sp.split_index("valid")
    # `--splits`로 평가 구간을 아직 데이터가 없는 미래(예: 2026)에 두면 표본이 0개다 — 학습·early
    # stopping은 train/valid만 쓰므로 크래시 없이 진행하고, 정보용으로만 기록한다(200 B부).
    idx_eval = sp.split_index("eval")
    eval_rows = len(idx_eval[0])
    print(
        f"[준비] 역 {len(sp.station_ids)} · 학습 표본 {len(idx_train[0]):,} · 검증 {len(idx_valid[0]):,}"
        f" · 평가 {eval_rows:,} · 채널 {sp.seq_channels}({args.seq_features})"
        f" · 정적 {stat_features_for(sp.use_static_events)}"
        f" · {time.time() - t0:.0f}s · 장치 {device}",
        flush=True,
    )
    if eval_rows == 0:
        print("[안내] 평가 구간 표본 0 — 평가 생략", flush=True)

    common = {
        "model_kind": args.model,
        "seq_days": args.seq_days,
        "hidden": args.hidden,
        "patience": args.patience,
        "seed": args.seed,
        "device": device,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "p_full": args.p_full,
        "truncation": not args.no_truncation,
        "huber_delta": args.huber_delta,
    }

    # 결정성 점검 — 같은 시드로 짧게 2회 학습해 검증 손실 차이를 잰다.
    determinism = None
    if args.determinism_probe > 0:
        probes = []
        for _ in range(2):
            _, hist, _ = train_one(
                sp,
                idx_train,
                idx_valid,
                epochs=args.determinism_probe,
                quiet=True,
                **common,
            )
            probes.append(hist[-1]["valid_loss"])
        diff = abs(probes[0] - probes[1])
        determinism = {
            "probe_epochs": args.determinism_probe,
            "valid_loss_run1": probes[0],
            "valid_loss_run2": probes[1],
            "abs_diff": round(diff, 8),
            "rel_diff_pct": round(diff / probes[0] * 100, 6) if probes[0] else None,
            "tolerance_pct": 0.5,
            "within_tolerance": bool(probes[0] and diff / probes[0] * 100 <= 0.5),
        }
        print(
            f"[결정성] 같은 시드 2회 검증 손실 {probes} → {determinism['rel_diff_pct']}%",
            flush=True,
        )

    t1 = time.time()
    model, history, best_epoch = train_one(sp, idx_train, idx_valid, epochs=args.epochs, **common)
    train_seconds = round(time.time() - t1, 1)

    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M")
    meta = {
        "model_kind": "dl",
        "model": args.model,
        "seq_days": args.seq_days,
        "hidden": args.hidden,
        "emb_dim": 16,
        "mlp_hidden": 128,
        "channels": seq_channels_for(args.seq_features),
        "seq_features": args.seq_features,
        "use_static_events": args.static_events,
        "event_encoding": args.event_encoding,
        "stat_features": stat_features_for(args.static_events),
        "huber_delta": args.huber_delta,
        "targets": TARGETS,
        "lookup_keys": lookup.keys,
        "station_ids": [int(s) for s in sp.station_ids],
        "n_stations": len(sp.station_ids),
        "derived_version": DERIVED_VERSION,
        "splits": {k: list(v) for k, v in sp.splits.items()},
        "panel_file": Path(panel_path).name if panel_path else "기본",
        "derived_cache": Path(derived_cache).name if derived_cache else "기본",
        "n_train_samples": len(idx_train[0]),
        "n_valid_samples": len(idx_valid[0]),
        # 200 B부 — --splits로 평가 구간을 미래(데이터 없음)에 두면 0. dl/infer.py·evaluate_dl.py는
        # 이 키를 읽지 않으므로(meta.get 방식) 추가해도 기존 리더를 깨지 않는다.
        "eval_rows": eval_rows,
        "seed": args.seed,
        "epochs": args.epochs,
        "epochs_run": len(history),
        "best_epoch": best_epoch,
        "best_valid_loss": history[best_epoch - 1]["valid_loss"] if history else None,
        "patience": args.patience,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "truncation": not args.no_truncation,
        "p_full": args.p_full,
        "train_seconds": train_seconds,
        "device": device,
        "torch_version": torch.__version__,
        "determinism": determinism,
        "created_at": stamp,
    }
    tag = "" if args.seq_features == "base" else f"_{args.seq_features}"
    if not args.static_events:
        tag += "_noev"
    elif args.event_encoding != "zscore":
        tag += "_evfix"
    if args.huber_delta != 1.0:
        tag += f"_hd{args.huber_delta:g}"
    name = args.name or f"dl_{args.model}_s{args.seq_days}{tag}_s{args.seed}_{stamp}"
    out_dir = save_artifact(
        Path(args.out_root or MODELS_DIR) / name, model, sp, lookup, stats, meta, history
    )
    print(
        f"[학습] 저장: {out_dir} (best 에폭 {best_epoch}/{len(history)}, {train_seconds}s, {device})",
        flush=True,
    )
    return out_dir


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--model", default="gru", choices=["gru", "lstm"])
    ap.add_argument("--seq-days", type=int, default=14)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="auto", help="auto|cuda|cpu")
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--p-full", type=float, default=0.0, help="절단 없음(k=0)을 뽑을 추가 확률")
    ap.add_argument(
        "--seq-features",
        default="base",
        choices=list(SEQ_FEATURE_SETS),
        help="시퀀스 채널 구성(198): base 7 · neighbor 16 · events_hist 12",
    )
    ap.add_argument(
        "--static-events",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="대상일 이벤트 5열을 정적 피처로 쓴다. **기본은 끔**(198 판정 1: 켜면 2025 full RMSE −11.9%%p)",
    )
    ap.add_argument(
        "--event-encoding",
        default="zscore",
        choices=list(EVENT_ENCODINGS),
        help="정적·이력 이벤트 값의 인코딩(198 후속): zscore(144) · log1p_max(0~1)",
    )
    ap.add_argument(
        "--huber-delta", type=float, default=1.0, help="masked_huber의 δ(z 단위, 198 손실 실험)"
    )
    ap.add_argument(
        "--no-truncation", action="store_true", help="이력 절단 증강 없음(대조군 gru_no_trunc)"
    )
    ap.add_argument(
        "--determinism-probe",
        type=int,
        default=2,
        help="같은 시드 2회 학습 점검 에폭 수(0이면 생략)",
    )
    ap.add_argument("--stations", type=int, default=None, help="앞쪽 N개 역만(스모크)")
    ap.add_argument(
        "--train-start",
        default=None,
        help=(
            "학습 시작일 YYYY-MM-DD(145 후속 학습 창 확장). 검증·평가 경계는 그대로."
            f" 기본 {SPLITS['train'][0]}. --splits와 함께 쓸 수 없다"
        ),
    )
    ap.add_argument(
        "--splits",
        default=None,
        help=(
            "세 구간 경계를 전부 새로 주는 JSON(200 B부, 예: "
            '\'{"train": ["2024-01-01", "2025-10-31"], "valid": ["2025-11-01", "2025-12-31"],'
            ' "eval": ["2026-01-01", "2026-12-31"]}\''
            "). --train-start와 함께 쓸 수 없다(dl/dataset.parse_splits)"
        ),
    )
    ap.add_argument(
        "--panel", default=None, help=f"패널 파일명 — 상대경로면 {CROWD_PROCESSED} 기준"
    )
    ap.add_argument(
        "--events", default=None, help=f"이벤트 파일명 — 상대경로면 {CROWD_PROCESSED} 기준"
    )
    ap.add_argument(
        "--derived-cache", default=None, help=f"파생 캐시 파일명 — 상대경로면 {CROWD_INTERIM} 기준"
    )
    ap.add_argument("--name", default=None, help="아티팩트 폴더명 고정")
    ap.add_argument("--out-root", default=None)
    args = ap.parse_args(argv)

    def _resolve(value: str | None, base: Path) -> Path | None:
        if value is None:
            return None
        p = Path(value)
        return p if p.is_absolute() else base / p

    args.panel = _resolve(args.panel, CROWD_PROCESSED)
    args.events = _resolve(args.events, CROWD_PROCESSED)
    args.derived_cache = _resolve(args.derived_cache, CROWD_INTERIM)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
