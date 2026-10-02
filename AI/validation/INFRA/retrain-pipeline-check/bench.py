"""crowd_panel_rebuild(Spark) vs pandas `to_long` 스케일 스윕 — 합성 raw 기준.

정확성(`--verify-against` 대조)을 먼저 보고 그다음 시간·피크 RSS를 잰다. 셀마다 서브프로세스를
띄우고(트리 RSS를 psutil로 0.2초 간격 샘플링 — Windows라 잡 내부 `peak_rss_mb`는 None),
끝나는 대로 `results.jsonl`에 한 줄 append한다. 이미 끝난 cell_id는 건너뛴다(`--force`로 재실행).

셀: `pandas_d<N>`(기준 롱 parquet 생성), `spark_d<N>`(local[3]·3g, `--full`, 기준과 대조),
`spark_d270_c8`(local[8]·6g 코어 확장), `spark_d1000_m6g`(1000일 6g 재시도). N 일수는 합성 마스터(2024-01-01~) 중 **끝에서 N일**
(270일 = 2026-01-01~, 2026 YTD 상당)이며 하드링크로 스케일별 입력 루트를 만든다.

실행:
    cd AI
    python validation/INFRA/retrain-pipeline-check/gen_raw.py --days 1000
    python validation/INFRA/retrain-pipeline-check/bench.py --scales 30,90,270,1000
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[2]
RESULTS_PATH = HERE / "results.jsonl"
SCRATCH = Path(
    r"C:\Users\SSAFY\AppData\Local\Temp\claude\C--Users-SSAFY-workspace-SUMGIL"
    r"\2374304a-6890-4029-8e97-88bd84662f9a\scratchpad\retrain-bench"
)
MASTER = SCRATCH / "master"
RAW_FILE_NAME = "getStnPsgr.parquet"
DEFAULT_SCALES = [30, 90, 270, 1000]
# 코어 확장 셀(270일) + 1000일 메모리 상향 셀(기본 3g가 OOM이면 6g로 재시도해 필요 메모리를 본다)
EXTRA_CELLS = [
    {"scale": 270, "cores": "8", "driver_memory": "6g", "suffix": "c8"},
    {"scale": 1000, "cores": "3", "driver_memory": "6g", "suffix": "m6g"},
]


class TreeSampler:
    """자식 프로세스 트리(JVM 포함) RSS 합의 피크(MB)."""

    def __init__(self, pid: int, interval: float = 0.2):
        self.pid, self.interval, self.peak_mb = pid, interval, 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _once(self) -> None:
        try:
            p = psutil.Process(self.pid)
            total = p.memory_info().rss
            for c in p.children(recursive=True):
                try:
                    total += c.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        self.peak_mb = max(self.peak_mb, total / 1048576)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._once()
            time.sleep(self.interval)

    def __enter__(self) -> TreeSampler:
        self._once()
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._t.join(timeout=2)


def load_done() -> dict:
    done: dict = {}
    if RESULTS_PATH.exists():
        for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("cell_id"):
                done[rec["cell_id"]] = rec
    return done


def append_result(rec: dict) -> None:
    rec["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(RESULTS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def scale_root(n: int) -> Path:
    """마스터의 끝 n일 파티션을 하드링크한 입력 루트(없으면 복사)."""
    root = SCRATCH / f"scale_{n}" / "raw"
    parts = sorted(MASTER.glob(f"dt=*/{RAW_FILE_NAME}"))[-n:]
    if len(parts) < n:
        raise SystemExit(f"마스터 파티션 {len(parts)}개 < 요청 {n}일 - gen_raw.py를 먼저 실행")
    for src in parts:
        dst = root / src.parent.name / RAW_FILE_NAME
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    return root


def baseline_path(n: int) -> Path:
    return SCRATCH / f"scale_{n}" / "pandas_long.parquet"


def run_sampled(argv: list[str], timeout: int) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        argv,
        cwd=AI_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    status = "ok"
    with TreeSampler(proc.pid) as s:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            status = "timeout"
    if status == "ok" and proc.returncode not in (0, 1):
        status = "crashed"  # 1은 verify 불일치(결과는 기록되므로 status는 ok 유지)
    return {
        "status": status,
        "returncode": proc.returncode,
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "peak_rss_mb": round(s.peak_mb, 1),
        "stdout_tail": out[-1500:],
        "stderr_tail": err[-1500:],
        "oom": "OutOfMemoryError" in err,
    }


def worker_pandas(input_root: Path, out_path: Path) -> None:
    """pandas 기준: 파티션별 to_long -> concat -> 기준 롱 parquet. 단계별 초를 stdout JSON으로."""
    import pandas as pd

    sys.path.insert(0, str(AI_ROOT))
    from DATA_ENGINE.collect.subway_ridership_daily import to_long

    t0 = time.perf_counter()
    files = sorted(input_root.glob(f"dt=*/{RAW_FILE_NAME}"))
    longs = [to_long(pd.read_parquet(f)) for f in files]
    df = pd.concat(longs, ignore_index=True)
    compute = time.perf_counter() - t0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(
        json.dumps(
            {
                "partitions": len(files),
                "long_rows": len(df),
                "compute_seconds": round(compute, 2),
                "write_seconds": round(time.perf_counter() - t0 - compute, 2),
            }
        )
    )


def last_json(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {}


def cell_pandas(n: int, timeout: int) -> dict:
    root = scale_root(n)
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "pandas",
        "--input-root",
        str(root),
        "--out",
        str(baseline_path(n)),
    ]
    rec = run_sampled(argv, timeout)
    rec.update(last_json(rec["stdout_tail"]))
    rec.update({"cell_id": f"pandas_d{n}", "engine": "pandas", "scale_days": n})
    return rec


def cell_spark(n: int, cores: str, mem: str, cell_id: str, timeout: int) -> dict:
    root = scale_root(n)
    out_root = SCRATCH / f"scale_{n}" / f"spark_out_c{cores}_{mem}"
    shutil.rmtree(out_root, ignore_errors=True)
    argv = [
        sys.executable,
        "-m",
        "DATA_ENGINE.spark.jobs.crowd_panel_rebuild",
        "--input-root",
        str(root),
        "--out-root",
        str(out_root),
        "--full",
        "--verify-against",
        str(baseline_path(n)),
        "--cores",
        cores,
        "--driver-memory",
        mem,
    ]
    rec = run_sampled(argv, timeout)
    meta_path = out_root / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rec.update(
            {
                "job_elapsed_sec": meta.get("elapsed_sec"),
                "panel_rows": meta.get("panel_rows"),
                "input_partitions": meta.get("input_partitions"),
                "verify": meta.get("verify", {}),
            }
        )
    rec.update(
        {
            "cell_id": cell_id,
            "engine": "spark",
            "scale_days": n,
            "cores": cores,
            "driver_memory": mem,
        }
    )
    shutil.rmtree(
        out_root, ignore_errors=True
    )  # 패널 parquet은 용량만 차지한다(meta는 results에 옮김)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scales", default=",".join(map(str, DEFAULT_SCALES)))
    ap.add_argument("--only", default=None, help="쉼표 구분 cell_id만 실행")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=int, default=1500, help="셀당 타임아웃(초)")
    ap.add_argument("--no-extra", action="store_true", help="코어 확장 셀 제외")
    ap.add_argument("--worker", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--input-root", type=Path, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--out", type=Path, default=None, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.worker == "pandas":
        worker_pandas(a.input_root, a.out)
        return

    scales = [int(s) for s in a.scales.split(",") if s]
    plan: list[tuple[str, object]] = []
    for n in scales:
        plan.append((f"pandas_d{n}", lambda n=n: cell_pandas(n, a.timeout)))
        plan.append((f"spark_d{n}", lambda n=n: cell_spark(n, "3", "3g", f"spark_d{n}", a.timeout)))
        for ex in EXTRA_CELLS:
            if n == ex["scale"] and not a.no_extra:
                cid = f"spark_d{n}_{ex['suffix']}"
                plan.append(
                    (
                        cid,
                        lambda n=n, ex=ex, cid=cid: cell_spark(
                            n, ex["cores"], ex["driver_memory"], cid, a.timeout
                        ),
                    )
                )
    only = set(a.only.split(",")) if a.only else None
    done = load_done()
    for cid, fn in plan:
        if only and cid not in only:
            continue
        if not a.force and cid in done:
            print(f"[bench] 건너뜀(완료): {cid} status={done[cid].get('status')}")
            continue
        print(f"[bench] 시작: {cid}", flush=True)
        rec = fn()
        append_result(rec)
        done[cid] = rec
        print(
            f"[bench] 종료: {cid} status={rec['status']} rc={rec['returncode']} "
            f"wall={rec['wall_seconds']}s rss={rec['peak_rss_mb']}MB",
            flush=True,
        )
    print(f"[bench] 전체 완료. 결과: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
