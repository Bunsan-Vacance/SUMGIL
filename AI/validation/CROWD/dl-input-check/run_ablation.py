"""198 — GRU 입력 설계 변형 학습 실행기: 안 × 시드 × 손실을 **한 프로세스에서** 순차로 돈다.

144는 입력 1안(`base`, 시드 42) 하나만 학습했다. 198은 그 위에 세 가지 축을 얹는다.

| 안 | 계열 | `--seq-features` | 정적 이벤트 | 인코딩 | 채널 | 가설 |
| --- | --- | --- | --- | --- | --- | --- |
| `base`(V0) | gru | base | 있음 | zscore | 7 | 144 기준(아티팩트 재사용, 시드 43·44만 새로) |
| `neighbor`(V1) | gru | neighbor | 있음 | zscore | 16 | 89에서 인접역 **잔차**가 원본값의 4배 효과였다 — 시퀀스에서도 나는가 |
| `events_hist`(V2) | gru | events_hist | 있음 | zscore | 12 | "지난 경기·축제 날 잔차"를 이벤트로 설명하면 대상일 반응이 좋아지는가 |
| `no_events`(V3) | gru | base | **없음** | — | 7 | 대조군 — 이벤트 5열이 실제로 기여하는가. **1차 채택**(198 판정 1) |
| `neighbor_no_events` | gru | neighbor | **없음** | — | 16 | 계획 밖 1회 — V1·V3 효과가 겹치는가(겹치지 않았다) |
| `no_events_lstm` | **lstm** | base | **없음** | — | 7 | 후속 A — 계열(GRU/LSTM)이 채택 구성에서 구분되는가 |
| `events_fixed` | gru | base | 있음 | **log1p_max** | 7 | 후속 B — 이벤트가 해로운 게 아니라 **z 인코딩**이 해로웠던 것인가 |
| `events_fixed_lstm` | **lstm** | base | 있음 | **log1p_max** | 7 | 후속 C — B가 채택되면 그 구성에서도 계열 비교를 1행 남긴다 |

## 후속(198 재실행) — 왜 인코딩을 고쳤나

1차 결론은 "이벤트 5열이 해롭다"였는데, 표준화를 점검하니 99%가 0인 희소 카운트를 z-점수로 넣어
학습 std가 0.07~0.13이었다. 이벤트가 있는 날 입력이 z 12.8~38.5, 2025의 `festival_min_duration_days`는
최대 88.0이다. 그래서 "이벤트가 해롭다"와 "이 인코딩으로는 해롭다"가 구분되지 않는다 —
`events_fixed`(= `--static-events --event-encoding log1p_max`)가 그 둘을 가른다.

## 왜 한 프로세스인가

한 안의 준비물(파생 400만 행 읽기 → 밀집 pivot → lookup fit)은 30~60초인데 학습은 80~90초다.
시드마다 프로세스를 새로 띄우면 준비가 학습만큼 든다. 안이 같으면 `train_dl.prepare`의 결과를
그대로 재사용한다(`AI/CLAUDE.md` "실험 실행 효율"). 그래서 실행 순서는 **안으로 묶어** 정렬된다.

## 중단 재시작

끝난 학습은 `runs.jsonl`에 한 줄씩 append한다. 같은 키(`<안>|s<시드>|hd<δ>`)가 이미 있으면 건너뛴다 —
GPU 15분짜리 묶음이 중간에 끊겨도 남은 것만 돈다. `--force`로 무시하고 다시 돌릴 수 있다.

실행:
    cd AI
    python validation/CROWD/dl-input-check/run_ablation.py --runs neighbor,events_hist,no_events
    python validation/CROWD/dl-input-check/run_ablation.py --runs base:43,base:44,neighbor:43
    python validation/CROWD/dl-input-check/run_ablation.py --runs base --huber-delta 3
    python validation/CROWD/dl-input-check/run_ablation.py --runs no_events_lstm:42,no_events_lstm:43
    python validation/CROWD/dl-input-check/run_ablation.py --runs events_fixed --stations 20 --epochs 2  # 스모크
예상: 전체 안 1개 = 준비 1분 + 학습 1.5분(GPU). 안 3 + 시드 4 + 손실 2 ≈ 20분.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from argparse import Namespace
from pathlib import Path

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from app.CROWD.pipeline.dl.dataset import seq_channels_for, stat_features_for
from app.CROWD.pipeline.dl.train_dl import prepare, run

# 안 이름 → 학습 구성. 안 이름이 곧 계열명(`runs.jsonl`·평가 `--models`의 접두)이라
# 계열(gru/lstm)과 이벤트 인코딩도 이름으로 갈라 둔다 — 키 형식(`<안>|s<시드>|hd<δ>`)을 바꾸지 않아
# 1차 9회의 `runs.jsonl`이 그대로 "끝난 것"으로 읽힌다.
VARIANTS: dict[str, dict] = {
    "base": {"seq_features": "base", "static_events": True},
    "neighbor": {"seq_features": "neighbor", "static_events": True},
    "events_hist": {"seq_features": "events_hist", "static_events": True},
    "no_events": {"seq_features": "base", "static_events": False},
    # 계획 밖 1회 탐색(V1+V3): V1·V3이 각각 판정 1을 통과해 두 효과가 겹치는지 본다.
    "neighbor_no_events": {"seq_features": "neighbor", "static_events": False},
    # ── 후속(A·B·C) ──
    "no_events_lstm": {"seq_features": "base", "static_events": False, "model": "lstm"},
    "events_fixed": {
        "seq_features": "base",
        "static_events": True,
        "event_encoding": "log1p_max",
    },
    "events_fixed_lstm": {
        "seq_features": "base",
        "static_events": True,
        "event_encoding": "log1p_max",
        "model": "lstm",
    },
}
VARIANT_DEFAULTS = {"model": "gru", "event_encoding": "zscore"}


def variant_config(name: str) -> dict:
    """안 이름 → `{model, seq_features, static_events, event_encoding}`(기본값 채운 것)."""
    return {**VARIANT_DEFAULTS, **VARIANTS[name]}


RUNS_PATH = _HERE / "runs.jsonl"


def parse_runs(spec: str, default_seed: int, huber_delta: float) -> list[dict]:
    """`neighbor,base:43,base:44` → 실행 목록. `:` 뒤가 시드이고 생략하면 `default_seed`."""
    out = []
    for item in (x.strip() for x in spec.split(",") if x.strip()):
        name, _, seed = item.partition(":")
        if name not in VARIANTS:
            raise SystemExit(f"모르는 안 {name!r} — {list(VARIANTS)} 중 하나")
        out.append(
            {
                "variant": name,
                "seed": int(seed) if seed else default_seed,
                "huber_delta": huber_delta,
            }
        )
    return out


def run_key(run_spec: dict) -> str:
    return f"{run_spec['variant']}|s{run_spec['seed']}|hd{run_spec['huber_delta']:g}"


def done_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            keys.add(json.loads(line)["key"])
    return keys


def build_args(run_spec: dict, cli) -> Namespace:
    """`train_dl.main`이 만드는 것과 같은 네임스페이스(144 고정 구성 + 안별 채널 스위치)."""
    cfg = variant_config(run_spec["variant"])
    return Namespace(
        model=cfg["model"],
        seq_days=cli.seq_days,
        hidden=cli.hidden,
        epochs=cli.epochs,
        patience=cli.patience,
        seed=run_spec["seed"],
        device=cli.device,
        batch_size=cli.batch_size,
        lr=cli.lr,
        p_full=0.0,
        no_truncation=False,
        seq_features=cfg["seq_features"],
        static_events=cfg["static_events"],
        event_encoding=cfg["event_encoding"],
        huber_delta=run_spec["huber_delta"],
        determinism_probe=0,  # 144에서 0.000%로 확인됨 — 반복 실험에서는 GPU 시간만 먹는다
        stations=cli.stations,
        name=None,
        out_root=cli.out_root,
    )


def append_run(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--runs",
        default="neighbor,events_hist,no_events",
        help="쉼표 목록. `안` 또는 `안:시드` (예: neighbor,base:43)",
    )
    ap.add_argument("--seed", type=int, default=42, help="시드를 안 적은 항목의 기본 시드")
    ap.add_argument("--huber-delta", type=float, default=1.0)
    ap.add_argument("--seq-days", type=int, default=14)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--stations", type=int, default=None, help="앞쪽 N개 역만(스모크)")
    ap.add_argument("--out-root", default=None)
    ap.add_argument("--runs-file", default=str(RUNS_PATH))
    ap.add_argument("--force", action="store_true", help="이미 끝난 키도 다시 돌린다")
    cli = ap.parse_args(argv)

    specs = parse_runs(cli.runs, cli.seed, cli.huber_delta)
    runs_file = Path(cli.runs_file)
    done = set() if cli.force else done_keys(runs_file)
    todo = [s for s in specs if run_key(s) not in done]
    skipped = [run_key(s) for s in specs if run_key(s) in done]
    if skipped:
        print(f"[건너뜀] 이미 끝난 실행 {len(skipped)}개: {', '.join(skipped)}", flush=True)
    if not todo:
        print("[완료] 돌릴 실행이 없다.", flush=True)
        return

    # 같은 안끼리 묶어 준비물(패널·lookup)을 재사용한다. 순서는 처음 나온 안 순.
    order: list[str] = []
    for s in todo:
        if s["variant"] not in order:
            order.append(s["variant"])
    todo.sort(key=lambda s: (order.index(s["variant"]), s["seed"], s["huber_delta"]))

    t_all = time.time()
    prepared, prepared_for = None, None
    for i, spec in enumerate(todo, 1):
        args = build_args(spec, cli)
        if prepared_for != spec["variant"]:
            t0 = time.time()
            prepared = prepare(args)
            prepared_for = spec["variant"]
            print(f"[준비] {spec['variant']} · {time.time() - t0:.0f}s", flush=True)
        print(f"\n=== [{i}/{len(todo)}] {run_key(spec)} ===", flush=True)
        t0 = time.time()
        out_dir = run(args, prepared=prepared)
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        append_run(
            runs_file,
            {
                "key": run_key(spec),
                "variant": spec["variant"],
                "seed": spec["seed"],
                "huber_delta": spec["huber_delta"],
                "model": args.model,
                "seq_features": args.seq_features,
                "use_static_events": args.static_events,
                "event_encoding": args.event_encoding,
                "channels": seq_channels_for(args.seq_features),
                "stat_features": stat_features_for(args.static_events),
                "artifact": str(out_dir),
                "artifact_name": out_dir.name,
                "best_epoch": meta["best_epoch"],
                "epochs_run": meta["epochs_run"],
                "best_valid_loss": meta["best_valid_loss"],
                "train_seconds": meta["train_seconds"],
                "device": meta["device"],
                "n_train_samples": meta["n_train_samples"],
                "wall_seconds": round(time.time() - t0, 1),
                "created_at": meta["created_at"],
            },
        )
        print(f"[기록] {runs_file.name} ← {run_key(spec)}", flush=True)
    print(f"\n[완료] {len(todo)}회 학습 · {time.time() - t_all:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
