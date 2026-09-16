"""pandas vs PySpark 실측 벤치마크 오케스트레이터.

셀(OP x 스케일 x 엔진, 또는 정확성/세션/병렬도/셔플 실험) 하나마다 `worker.py`를 별도
서브프로세스로 띄우고, 끝나는 대로 `results.jsonl`에 한 줄씩 append한다. 이미 끝난
cell_id는 기본적으로 건너뛴다(`--force`로 재실행 가능) — 중간에 중단돼도 끝난 셀은
다시 돌리지 않기 위해서다.

실행 예:
    cd AI
    conda run -n SUMGIL python validation/INFRA/spark-compare-check/bench.py
    conda run -n SUMGIL python validation/INFRA/spark-compare-check/bench.py --only A_accuracy
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "results.jsonl"

DEFAULT_SCALES = [1, 4, 16, 64]
PHYSICAL_CORES = 16


def load_done_cells() -> dict:
    done = {}
    if RESULTS_PATH.exists():
        with open(RESULTS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = rec.get("cell_id")
                if cid:
                    done[cid] = rec
    return done


def append_result(rec: dict) -> None:
    rec["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(RESULTS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        f.flush()


def run_cell(cell: dict, timeout: int) -> dict:
    """cell dict의 인자로 worker.py를 서브프로세스로 실행하고 결과를 반환한다."""
    cell_id = cell["cell_id"]
    print(f"[bench] 시작: {cell_id} ({cell.get('mode', 'bench')}) ...", flush=True)
    t0 = time.time()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "out.json"
        argv = [
            sys.executable,
            str(HERE / "worker.py"),
            "--mode",
            cell.get("mode", "bench"),
            "--cell-id",
            cell_id,
            "--out",
            str(out_path),
        ]
        if "op" in cell:
            argv += ["--op", cell["op"]]
        if "engine" in cell:
            argv += ["--engine", cell["engine"]]
        if "scale" in cell:
            argv += ["--scale", str(cell["scale"])]
        if "master" in cell:
            argv += ["--master", cell["master"]]
        if "shuffle_partitions" in cell:
            argv += ["--shuffle-partitions", str(cell["shuffle_partitions"])]
        if "pivot_variant" in cell:
            argv += ["--pivot-variant", cell["pivot_variant"]]

        env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}

        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, env=env, check=False
            )
            elapsed = time.time() - t0
            if out_path.exists():
                result = json.loads(out_path.read_text(encoding="utf-8"))
            else:
                result = {
                    "cell_id": cell_id,
                    "status": "crashed",
                    "returncode": proc.returncode,
                    "stderr_tail": proc.stderr[-3000:],
                }
            result["orchestrator_elapsed_seconds"] = elapsed
        except subprocess.TimeoutExpired as exc:
            elapsed = time.time() - t0
            result = {
                "cell_id": cell_id,
                "status": "timeout",
                "timeout_seconds": timeout,
                "orchestrator_elapsed_seconds": elapsed,
                "stderr_tail": (
                    (exc.stderr or b"")[-3000:]
                    if isinstance(exc.stderr, bytes)
                    else str(exc.stderr)[-3000:]
                ),
            }
    result.update({k: v for k, v in cell.items() if k not in result})
    print(
        f"[bench] 종료: {cell_id} status={result.get('status')} "
        f"elapsed={result.get('orchestrator_elapsed_seconds', 0):.1f}s",
        flush=True,
    )
    return result


def build_main_sweep(scales: list[int]) -> list[dict]:
    cells = []
    for scale in scales:
        for op in ["A", "B", "C"]:
            for engine in ["pandas", "spark"]:
                cells.append(
                    {
                        "cell_id": f"{op}_x{scale}_{engine}",
                        "mode": "bench",
                        "op": op,
                        "engine": engine,
                        "scale": scale,
                        **(
                            {"master": "local[*]", "shuffle_partitions": 200}
                            if engine == "spark"
                            else {}
                        ),
                    }
                )
    return cells


def build_accuracy_cells() -> list[dict]:
    return [
        {
            "cell_id": f"{op}_accuracy",
            "mode": "accuracy",
            "op": op,
            "scale": 1,
            "master": "local[*]",
            "shuffle_partitions": 200,
        }
        for op in ["A", "B", "C"]
    ]


def build_session_cell() -> dict:
    return {
        "cell_id": "spark_session_startup",
        "mode": "session",
        "master": "local[*]",
        "shuffle_partitions": 200,
    }


def largest_ok_scale(done: dict, prefix_fmt: str, scales: list[int]) -> int | None:
    ok_scales = [
        s for s in scales if done.get(prefix_fmt.format(scale=s), {}).get("status") == "ok"
    ]
    return max(ok_scales) if ok_scales else None


def build_dependent_cells(done: dict, scales: list[int]) -> list[dict]:
    cells = []

    # 병렬도 스케일링: OP-A가 성공한 가장 큰 스케일에서 local[1]/[4]/[16] 비교
    scale_a = largest_ok_scale(done, "A_x{scale}_spark", scales) or min(scales)
    for n in [1, 4, 16]:
        cells.append(
            {
                "cell_id": f"A_x{scale_a}_spark_local{n}",
                "mode": "bench",
                "op": "A",
                "engine": "spark",
                "scale": scale_a,
                "master": f"local[{n}]",
                "shuffle_partitions": 200,
            }
        )

    # shuffle.partitions 200(기본) vs 32(코어수x2) — OP-B가 성공한 가장 큰 스케일
    scale_b = largest_ok_scale(done, "B_x{scale}_spark", scales) or min(scales)
    cells.append(
        {
            "cell_id": f"B_x{scale_b}_spark_shuffle32",
            "mode": "bench",
            "op": "B",
            "engine": "spark",
            "scale": scale_b,
            "master": "local[*]",
            "shuffle_partitions": PHYSICAL_CORES * 2,
        }
    )

    # pivot 값 자동탐지(auto, 중복 스캔 유발) vs 명시(explicit) — OP-C가 성공한 가장 큰 스케일
    scale_c = largest_ok_scale(done, "C_x{scale}_spark", scales) or min(scales)
    cells.append(
        {
            "cell_id": f"C_x{scale_c}_spark_pivot_explicit",
            "mode": "bench",
            "op": "C",
            "engine": "spark",
            "scale": scale_c,
            "master": "local[*]",
            "shuffle_partitions": 200,
            "pivot_variant": "explicit",
        }
    )
    return cells


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scales", default=",".join(str(s) for s in DEFAULT_SCALES), help="예: 1,4,16,64"
    )
    parser.add_argument("--cell-timeout", type=int, default=900, help="일반 셀 타임아웃(초)")
    parser.add_argument(
        "--big-cell-timeout", type=int, default=2400, help="scale>=64 셀 타임아웃(초)"
    )
    parser.add_argument("--force", action="store_true", help="이미 끝난 셀도 다시 실행")
    parser.add_argument(
        "--only", default=None, help="쉼표로 구분한 cell_id만 실행(재실행/디버깅용)"
    )
    parser.add_argument(
        "--skip-dependent",
        action="store_true",
        help="병렬도/셔플/pivot 부가 실험을 건너뛴다(메인 스윕+정확성만)",
    )
    args = parser.parse_args()

    scales = [int(s) for s in args.scales.split(",") if s]

    done = load_done_cells()

    plan: list[dict] = []
    plan += build_accuracy_cells()
    plan += [build_session_cell()]
    plan += build_main_sweep(scales)

    if args.only:
        only_ids = set(args.only.split(","))
        plan = [c for c in plan if c["cell_id"] in only_ids]

    for cell in plan:
        cid = cell["cell_id"]
        if not args.force and cid in done:
            print(f"[bench] 건너뜀(이미 완료): {cid} status={done[cid].get('status')}")
            continue
        timeout = args.big_cell_timeout if cell.get("scale", 0) >= 64 else args.cell_timeout
        result = run_cell(cell, timeout=timeout)
        append_result(result)
        done[cid] = result

    if not args.only and not args.skip_dependent:
        dependent = build_dependent_cells(done, scales)
        for cell in dependent:
            cid = cell["cell_id"]
            if not args.force and cid in done:
                print(f"[bench] 건너뜀(이미 완료): {cid} status={done[cid].get('status')}")
                continue
            timeout = args.big_cell_timeout if cell.get("scale", 0) >= 64 else args.cell_timeout
            result = run_cell(cell, timeout=timeout)
            append_result(result)
            done[cid] = result

    print(f"[bench] 전체 완료. 결과: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
