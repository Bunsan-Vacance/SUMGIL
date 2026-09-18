"""145 후속 — 마스킹 학습 LightGBM 비교: 배포 LightGBM · GRU V3(3시드) · lookup, 가용성 4종.

## 왜 새 스크립트인가

145는 **현행** 배포 LightGBM(시차를 그대로 두고 학습, 143 마스킹은 평가에서만 적용)과 GRU V3를
비교했다. 이 스크립트가 새로 답하는 것은 "**학습 때부터** 시차 컬럼을 무작위로 NaN 처리하면(마스킹
학습) 결손·전무 시나리오에서 더 버티는가, 그러면서 `full`을 얼마나 내주는가"다. `family-check`가
계열·시나리오 예측·정렬·등급·부트스트랩을 이미 깔끔하게 함수로 쪼개 놨으므로 그 함수들을 그대로
가져다 쓰고, 이 스크립트가 새로 더하는 것만 짠다.

- **마스킹 LightGBM 후보** — `--masked 이름=경로`로 몇 개든 받는다. 시리즈 이름은
  `lgbm_masked_<이름>`이고, 예측은 `dl-resid-check/evaluate_dl.lgb_predictions`를 현행 LightGBM과
  **똑같이** 부른다 — 아티팩트만 다르고 마스킹·정렬 코드 경로가 같아야 "학습 방식"만 다른 조건이 된다
  (`AI/CLAUDE.md` "모델 비교는 동등 조건에서만").
- **GRU 기준 쌍차이 표(B2)** — 145의 표 B는 LightGBM 기준 쌍차이였다. 마스킹 후보를 결손·전무에서
  GRU 대신 쓸 수 있는지 보려면 **GRU를 기준으로 한** 같은 표가 필요하다. `stat-model-check/evaluate.py`
  의 `table_b`가 기준 계열을 `LIGHTGBM` 모듈 상수로 하드코딩하고 있어 `baseline` 키워드 인자를
  추가했다(이 파일에서 수정, 기본 동작은 바이트 동일 — 145 수치가 이미 공개돼 있어서다).
- **윈도우 라벨(`--window`)** — 같은 스크립트로 다른 패널·기간(`w2024`, `w2023`, …)을 돌려 결과를
  `data/CROWD/interim/validation/masking_check/<window>/`에 나눠 쌓는다. 채택 기준 4(아래)가
  기간을 바꿔 방향이 유지되는지를 요구해서다.
- **시나리오별 날짜 손실 저장(`losses_<scenario>.parquet`)** — 날짜별 SSE·SAE·n(충분통계)만 저장해
  두면, 다음에 후보를 더 넣을 때 예측을 다시 만들지 않고 그 표만 이어 붙일 수 있다
  (`AI/CLAUDE.md` "실험 실행 효율 — 같은 계산을 두 번 하지 않는다").

## 무엇을 그대로 재사용하는가(복붙 금지)

`family-check/compare.py`를 `_load_sibling`으로 읽어 `treat`(발산 처리) · `common_mask`(공통 행) ·
`scenario_frame`(시나리오별 `{계열}__{타깃}` 프레임) · `grade_table`(등급 일치율)을 그대로 부른다 —
이 함수들은 계열 이름에 대해 아무 가정도 하지 않아 마스킹 후보를 더해도 고칠 필요가 없었다.
`compare_tables`만 **표 B2**(GRU 기준)와 시나리오별 손실 저장이 추가로 필요해 이 파일에 다시 썼다.
예측·정렬은 `dl-resid-check/evaluate_dl.lgb_predictions`(LightGBM·마스킹 LightGBM 공용) ·
`dl_predictions`(GRU) · `align`을 그대로 쓴다. 표 조립은 `stat-model-check/evaluate.py`의
`daily_losses_multi` · `table_a` · `table_b`(위에서 `baseline` 인자 추가)를 그대로 쓴다.

## 채택 기준 4가지(다음 티켓이 이 표에서 읽을 것)

1. **결손 내성** — `d7_only`·`d1_only`·`no_lag` 세 시나리오 전부에서 표 A(lookup 대비) RMSE·MAE
   개선율 CI 하한이 0 위(lookup보다 유의하게 낫다).
2. **`full` 손실 한도** — 표 B(LightGBM 기준)에서 `full`의 point diff가 −1.0%p 이상이고 CI 상한이
   0 이상(마스킹 학습이 `full` 정확도를 크게 깎지 않는다는 근거가 통계적으로 남아 있다).
3. **GRU 대체 가능성** — 표 B2(`--gru-baseline` 기준, 기본 `gru_s42`)에서 결손·전무 시나리오의
   CI 상한이 0을 넘거나 point diff가 −2%p 이상(GRU보다 크게 나쁘지 않다).
4. **기간 재현** — `--window w2023`(다른 패널·파생 캐시)에서도 1~3의 부호(방향)가 유지된다.

## 연도 표본 가중·기상 실험 세트(227)

- `--year-weights`: `train.py --year-weights`와 같은 형식으로 `prepare()`의 단독 lookup을 같은
  가중으로 fit한다. 가중이 있으면 그 가중으로 만든 `--derived-cache`가 미리 있어야 한다(없으면
  `load_derived_slim`의 캐시 미스 폴백이 기본 패널로 평탄 파생을 다시 만들어 버린다).
- `--no-gru`: GRU 예측·표 B2·`--gru-baseline` 검증을 전부 생략한다(GRU 아티팩트 없이 마스킹
  후보끼리만, 또는 기상 후보를 빠르게 확인할 때).
- `--extra-cols`: `evaluate_dl.DERIVED_COLS` 뒤에 열을 추가해 읽는다 — 기상 후보(`features.WEATHER_COLS`)
  처럼 배포 세트에 없는 열로 학습한 아티팩트를 평가할 때 `build_matrix`가 `KeyError`로 죽지 않게 한다.

## 실행

아티팩트가 하이픈 폴더에 있어 파일 경로로 돈다(`family-check`와 같은 사정).

```bash
cd AI
# 스모크 — 실제 마스킹 아티팩트가 아직 없어 현행 배포로 배관만 확인(README 참고, 숫자는 무의미)
python validation/CROWD/masking-check/compare.py --window smoke \
    --masked stack=models/CROWD/festival_selflag_d1sd_d7_resid_20260913-0340 \
    --eval-days 3 --n-boot 20 --grades full

# 본 실행 — 마스킹 학습 아티팩트가 나오면
python validation/CROWD/masking-check/compare.py --window w2024 \
    --masked stack=models/CROWD/<마스킹_아티팩트> --grades full d7_only --out data/CROWD/interim/validation/masking_check/w2024/tables.md

# 채택 기준 4 — 다른 기간 패널로 재현
python validation/CROWD/masking-check/compare.py --window w2023 \
    --masked stack=models/CROWD/<마스킹_아티팩트> \
    --panel <2023 패널 파일> --derived-cache <2023 파생 캐시> --grades full
```
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for _p in (str(AI_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_sibling(rel_path: str, name: str):
    """다른 하이픈 폴더의 검증 스크립트를 파일 경로로 재사용한다(수정 금지, import만)."""
    spec = importlib.util.spec_from_file_location(name, AI_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# family-check가 이미 dl-resid-check·stat-model-check를 로드해 뒀으므로 그 인스턴스를 그대로 쓴다
# (같은 모듈을 두 번 로드하지 않는다).
family_compare = _load_sibling(
    "validation/CROWD/family-check/compare.py", "masking_check_family_compare"
)
evaluate_dl = family_compare.evaluate_dl
stat_eval = family_compare.stat_eval
stat_models = family_compare.stat_models

from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    EVENTS_NAME,
    PANEL_NAME,
    load_panel,
    resolved_segments,
    time_split,
)
from app.CROWD.pipeline.dl.dataset import load_derived_slim
from app.CROWD.pipeline.dl.train_dl import resolve_device
from app.CROWD.pipeline.features import FEATURE_SETS
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.predictor import latest_artifact
from app.CROWD.pipeline.train import parse_year_weights, year_weight_series, year_weights_label

EVAL_START = pd.Timestamp("2025-01-01")
DEPLOY_SET = evaluate_dl.DEPLOY_SET
MODELS_DIR = AI_ROOT / "models" / "CROWD"
VALIDATION_DIR = CROWD_INTERIM / "validation" / "masking_check"


# ── 경로 해석 ──
def _resolve_path(value: str, base: Path) -> Path:
    """비절대경로면 `base` 아래로 붙인다(CLI에서 파일명만 준 경우)."""
    p = Path(value)
    return p if p.is_absolute() else base / p


def _git_commit() -> str:
    """실행 조건 기록용 짧은 커밋 해시. 깃이 없거나 저장소 밖이면 `unknown`."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=AI_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _columns_with_extra(base: list[str], extra: list[str]) -> list[str]:
    """`base` 뒤에 `extra`를 중복 없이 순서대로 붙인다(`--extra-cols`, 기상 후보 등)."""
    seen = set(base)
    added = [c for c in extra if not (c in seen or seen.add(c))]
    return base + added


# ── 준비 ──
def prepare(args) -> dict:
    t0 = time.time()
    panel_path = (
        _resolve_path(args.panel, CROWD_PROCESSED) if args.panel else CROWD_PROCESSED / PANEL_NAME
    )
    events_path = (
        _resolve_path(args.events, CROWD_PROCESSED)
        if args.events
        else CROWD_PROCESSED / EVENTS_NAME
    )
    panel = load_panel(with_events=True, panel_path=panel_path, events_path=events_path)
    train_raw, _ = time_split(panel)
    year_weights = parse_year_weights(args.year_weights)
    # 가중 lookup은 `--derived-cache`(train.py --year-weights가 만든 것)가 미리 있어야 한다 —
    # `load_derived_slim`의 캐시 미스 폴백이 기본 패널로 평탄 파생을 다시 만들어 버리기 때문이다.
    if year_weights and not (
        args.derived_cache and _resolve_path(args.derived_cache, CROWD_INTERIM).exists()
    ):
        raise SystemExit(
            "가중 lookup 비교는 train.py --year-weights가 만든 파생 캐시가 미리 있어야 한다"
        )
    weights = year_weight_series(train_raw["date"], year_weights) if year_weights else None
    lookup = DayTypeLookupBaseline().fit(train_raw, weights=weights)

    cols = _columns_with_extra(evaluate_dl.DERIVED_COLS, args.extra_cols)
    cache_path = None
    if args.derived_cache:
        cache_path = _resolve_path(args.derived_cache, CROWD_INTERIM)
        # `load_derived_slim`의 캐시 미스 폴백은 기본 패널(PANEL_NAME)로 파생을 다시 만든다 —
        # 지금 쓰는 패널이 기본이 아니면 그 폴백이 다른 패널로 캐시를 조용히 덮어써 버린다.
        # 그래서 비기본 패널에서는 캐시가 이미 있어야 한다(train.py가 만든다) — 없으면 바로 멈춘다.
        if not cache_path.exists():
            raise SystemExit(f"파생 캐시가 없다: {cache_path} — train.py로 먼저 만들 것.")
        derived = load_derived_slim(columns=cols, cache_path=cache_path)
    else:
        derived = load_derived_slim(columns=cols)

    train = derived[derived["date"] < EVAL_START]
    test = derived[derived["date"] >= EVAL_START]
    if args.eval_days:  # 스모크 — 평가 구간을 앞쪽 N일로 자른다
        test = test[test["date"] < EVAL_START + pd.Timedelta(days=args.eval_days)]
    test = test.reset_index(drop=True)
    missing = stat_models.missing_feature_columns(test.columns, FEATURE_SETS[DEPLOY_SET])
    if missing:  # 세트 피처가 비면 LightGBM만 조용히 약해진다(145 통계 파트에서 실제로 겪었다)
        raise SystemExit(f"평가 프레임에 배포 세트 피처가 없다: {missing}")
    window = panel[
        (panel["date"] >= EVAL_START - pd.Timedelta(days=args.window_days))
        & (panel["date"] <= test["date"].max())
    ].reset_index(drop=True)
    segments, _ = resolved_segments(panel)
    bounds = stat_models.divergence_bounds(train, TARGETS)
    print(
        f"[준비] 평가 {len(test):,}행 · DL 창 {len(window):,}행 · {time.time() - t0:.0f}s",
        flush=True,
    )
    return {
        "panel": panel,
        "lookup": lookup,
        "test": test,
        "window": window,
        "segments": segments,
        "bounds": bounds,
        "panel_path": panel_path,
        "events_path": events_path,
        "cache_path": cache_path,
        "year_weights": year_weights,
    }


# ── 계열×시나리오 예측 ──
def series_predictions(args, data: dict) -> tuple[dict, dict[str, str]]:
    """`lightgbm` · `lgbm_masked_<이름>` · GRU 시드의 시나리오별 예측. 아티팩트 폴더명도 함께 돌려준다."""
    test, scenarios = data["test"], args.scenarios
    lgb = Path(args.lightgbm) if args.lightgbm else latest_artifact(MODELS_DIR, kind="lightgbm")
    if lgb is None:
        raise SystemExit("LightGBM 아티팩트가 없다 — `python -m app.CROWD.pipeline.train` 먼저.")
    print(f"[아티팩트] lightgbm={lgb.name}", flush=True)
    aligned: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    artifacts: dict[str, str] = {"lightgbm": lgb.name}
    for sc, frame in evaluate_dl.lgb_predictions(lgb, test, scenarios).items():
        aligned[("lightgbm", sc)] = evaluate_dl.align(test, frame)

    for name, path in args.masked.items():
        series_name = f"lgbm_masked_{name}"
        artifact = Path(path)
        if not artifact.exists():
            raise SystemExit(f"마스킹 LightGBM 아티팩트가 없다: {artifact}")
        artifacts[series_name] = artifact.name
        print(f"[아티팩트] {series_name}={artifact.name}", flush=True)
        # 마스킹 후보도 현행 LightGBM과 같은 함수로 예측한다 — 아티팩트만 다르고 마스킹·정렬 경로가
        # 같아야 "학습 방식 차이"만 재는 비교가 된다.
        for sc, frame in evaluate_dl.lgb_predictions(artifact, test, scenarios).items():
            aligned[(series_name, sc)] = evaluate_dl.align(test, frame)

    if args.no_gru:  # GRU 예측·기준 검증을 통째로 건너뛴다
        return aligned, artifacts

    device = resolve_device(args.device)
    gru_paths = args.gru or {
        name: MODELS_DIR / folder for name, folder in family_compare.GRU_SEEDS.items()
    }
    if args.gru_baseline not in gru_paths:
        raise SystemExit(
            f"--gru-baseline {args.gru_baseline!r}가 GRU 목록에 없다: {list(gru_paths)}"
        )
    for name, path in gru_paths.items():
        artifact = Path(path)
        if not artifact.exists():
            raise SystemExit(f"GRU 아티팩트가 없다: {artifact}")
        artifacts[name] = artifact.name
        print(f"[아티팩트] {name}={artifact.name} (device={device})", flush=True)
        runs = evaluate_dl.dl_predictions(
            artifact, data["window"], scenarios, device, data["segments"]
        )
        for sc, frame in runs.items():
            aligned[(name, sc)] = evaluate_dl.align(test, frame)
    return aligned, artifacts


# ── 시나리오별 표(A · B · B2) + 손실 저장 ──
def compare_tables(
    args, common, common_lookup, aligned, finite, masked_names, out_dir: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """시나리오마다 표 A(lookup 대비)·B(LightGBM 쌍차이)·B2(마스킹 후보 대 GRU 기준 쌍차이)를 낸다.

    `family_compare.scenario_frame`으로 만든 시나리오별 프레임에서 날짜별 손실 충분통계
    (`losses_<시나리오>.parquet`)도 같이 저장한다 — 다음에 후보를 더할 때 예측을 다시 만들지 않아도
    되게 하려는 것이다(`AI/CLAUDE.md` "실험 실행 효율").

    `--no-gru`면 `aligned`에 GRU 계열이 없어 B2(GRU 기준 쌍차이)를 낼 수 없다 — 그 표는
    `None`으로 돌려준다(호출부가 결과 표에서 뺀다).
    """
    a_all, b_all, b2_all = [], [], []
    for sc in args.scenarios:
        frame, names = family_compare.scenario_frame(common, common_lookup, aligned, finite, sc)
        losses = stat_eval.daily_losses_multi(frame, names)
        losses.to_parquet(out_dir / f"losses_{sc}.parquet", index=False)
        candidates = [n for n in names if n != "lookup"]
        a = stat_eval.table_a(losses, candidates, args.n_boot, args.seed).assign(scenario=sc)
        b = stat_eval.table_b(
            losses, [n for n in candidates if n != "lightgbm"], args.n_boot, args.seed
        ).assign(scenario=sc)
        a_all.append(a)
        b_all.append(b)

        tot = a[a["axis"] == "전체"].set_index(["series", "target"])
        for n in candidates:
            print(
                f"[{sc}] {n}: RMSE 개선율 승 {tot.loc[(n, 'boarding'), 'RMSE_개선율_%']:+.2f} "
                f"[{tot.loc[(n, 'boarding'), 'RMSE_CI_low']:+.2f}] / "
                f"하 {tot.loc[(n, 'alighting'), 'RMSE_개선율_%']:+.2f} "
                f"[{tot.loc[(n, 'alighting'), 'RMSE_CI_low']:+.2f}]",
                flush=True,
            )

        if args.no_gru:
            continue
        b2 = stat_eval.table_b(
            losses, masked_names, args.n_boot, args.seed, baseline=args.gru_baseline
        ).assign(scenario=sc)
        b2_all.append(b2)
        diff_col = f"point_diff_RMSE_%p(계열-{args.gru_baseline})"
        tot_b2 = b2[b2["axis"] == "전체"].set_index(["series", "target"])
        for n in masked_names:
            print(
                f"[{sc}] {n} vs {args.gru_baseline}: "
                f"RMSE 차 승 {tot_b2.loc[(n, 'boarding'), diff_col]:+.2f} "
                f"[{tot_b2.loc[(n, 'boarding'), 'diff_RMSE_CI_low']:+.2f}] / "
                f"하 {tot_b2.loc[(n, 'alighting'), diff_col]:+.2f} "
                f"[{tot_b2.loc[(n, 'alighting'), 'diff_RMSE_CI_low']:+.2f}]",
                flush=True,
            )
    return (
        pd.concat(a_all, ignore_index=True),
        pd.concat(b_all, ignore_index=True),
        pd.concat(b2_all, ignore_index=True) if b2_all else None,
    )


# ── 실행 ──
def run(args) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    data = prepare(args)
    test, lookup = data["test"], data["lookup"]
    lookup_pred = lookup.predict(test)
    aligned, artifacts = series_predictions(args, data)
    masked_names = [f"lgbm_masked_{n}" for n in args.masked]
    treatment = family_compare.treat(aligned, data["bounds"], args.treatment)
    finite = family_compare.common_mask(test, lookup_pred, aligned)
    common = test[finite].reset_index(drop=True)
    common_lookup = lookup_pred[finite].reset_index(drop=True)

    out_dir = VALIDATION_DIR / args.window
    out_dir.mkdir(parents=True, exist_ok=True)

    a, b, b2 = compare_tables(args, common, common_lookup, aligned, finite, masked_names, out_dir)
    tables = {"A_lookup_대비_개선율_CI": a, "B_lightgbm_쌍차이": b}
    if b2 is not None:
        tables["B2_masked_GRU쌍차이"] = b2
    tables["C_발산처리_적용행"] = treatment
    for sc in args.grades or []:
        g = family_compare.grade_table(common, common_lookup, aligned, finite, sc)
        if g is not None:
            tables[f"D_등급_일치율_{sc}"] = g

    conditions = {
        "window": args.window,
        "panel_file": data["panel_path"].name,
        "events_file": data["events_path"].name,
        "derived_cache": data["cache_path"].name if data["cache_path"] else "기본",
        "git_commit": _git_commit(),
        "n_boot": args.n_boot,
        "seed": args.seed,
        "scenarios": ",".join(args.scenarios),
        "artifacts": json.dumps(artifacts, ensure_ascii=False),
        "treatment": args.treatment,
        "year_weights": (
            year_weights_label(data["year_weights"]) if data["year_weights"] else "none"
        ),
        "no_gru": args.no_gru,
        "extra_cols": ",".join(args.extra_cols) if args.extra_cols else "none",
    }
    for title, tbl in tables.items():
        tbl = tbl.assign(**conditions)
        tables[title] = tbl
        tbl.to_parquet(out_dir / f"masking_check_{title}.parquet", index=False)
        print(f"\n### {title}\n{tbl.round(3).to_string(index=False)}")

    if args.out:
        gru_note = "GRU 생략(--no-gru)" if args.no_gru else f"GRU 기준 `{args.gru_baseline}`"
        head = (
            f"윈도우: `{args.window}` · 발산 처리 `{args.treatment}` · "
            f"부트스트랩 {args.n_boot}회(seed {args.seed}) · 시나리오 {args.scenarios} · "
            f"{gru_note} · 연도 가중 `{conditions['year_weights']}` · "
            f"커밋 `{conditions['git_commit']}` · 아티팩트 {artifacts}\n"
        )
        chunks = [head] + [
            f"### {title}\n\n{stat_eval.to_markdown(tbl.round(3))}\n"
            for title, tbl in tables.items()
        ]
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"[저장] {args.out}", flush=True)
    print(f"[완료] {time.time() - t0:.0f}s", flush=True)
    return tables


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--window", required=True, help="출력 폴더 라벨(예: w2024, w2023, smoke)")
    ap.add_argument(
        "--lightgbm",
        default=None,
        help=(
            "현행 배포 LightGBM 아티팩트. 생략 시 latest_artifact — 지금은 `…_train2024-2025`"
            "(2025 포함 학습)라 2025 평가에 누수된다. 창 비교에서는 반드시 명시."
        ),
    )
    ap.add_argument(
        "--masked",
        nargs="+",
        required=True,
        type=evaluate_dl._name_path,
        action=evaluate_dl._MergePairs,
        metavar="이름=경로",
        help="마스킹 학습 LightGBM 후보. 계열 이름은 lgbm_masked_<이름>",
    )
    ap.add_argument(
        "--gru",
        nargs="+",
        default=None,
        type=evaluate_dl._name_path,
        action=evaluate_dl._MergePairs,
        metavar="이름=경로",
        help="GRU 시드(생략 시 family-check GRU_SEEDS, models/CROWD 아래)",
    )
    ap.add_argument("--gru-baseline", default="gru_s42", help="표 B2 기준 GRU 시드")
    ap.add_argument("--panel", default=None, help="패널 파일(생략 시 기본 24/25 패널)")
    ap.add_argument("--events", default=None, help="이벤트 파일(생략 시 기본)")
    ap.add_argument(
        "--derived-cache",
        default=None,
        help="파생 캐시(생략 시 기본. 비기본 패널이면 미리 있어야 함)",
    )
    ap.add_argument("--scenarios", nargs="+", default=list(evaluate_dl.SCENARIOS))
    ap.add_argument("--eval-days", type=int, default=None, help="스모크용 — 평가 앞쪽 N일만")
    ap.add_argument("--window-days", type=int, default=14)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="auto", help="GRU 대량 추론 장치(auto=cuda 있으면 GPU)")
    ap.add_argument(
        "--treatment",
        default="raw",
        choices=["raw", "clip", "drop"],
        help="발산 예측 처리(기본 raw)",
    )
    ap.add_argument(
        "--grades", nargs="+", default=None, help="등급 일치율을 낼 시나리오들(예: full)"
    )
    ap.add_argument(
        "--year-weights",
        default=None,
        help=(
            "227 연도별 표본 가중(train.py --year-weights와 같은 형식). 주면 그 가중으로 만든 "
            "--derived-cache가 미리 있어야 한다(캐시 미스 폴백이 평탄 파생을 만들기 때문)"
        ),
    )
    ap.add_argument(
        "--no-gru", action="store_true", help="GRU 계열 예측·표 B2·GRU 기준 검사를 전부 생략"
    )
    ap.add_argument(
        "--extra-cols",
        nargs="*",
        default=[],
        help="파생 캐시에서 추가로 읽을 열(예: 기상 후보 5열) — evaluate_dl.DERIVED_COLS 뒤에 붙는다",
    )
    ap.add_argument("--out", default=None, help="표를 마크다운으로 저장할 경로")
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
