"""서버 실측 래퍼 — 명령을 subprocess로 띄우고 프로세스 트리(Spark JVM 자식 포함) 피크 RSS·벽시계를 잰다.

`crowd_panel_rebuild.py`의 `peak_rss_mb`는 `ru_maxrss`라 Python 드라이버 프로세스만 재고 JVM 자식은
빠진다. 서버에서 "Spark 잡이 실제로 메모리를 얼마나 쓰나"를 보려면 바깥에서 트리 전체를 샘플링해야 한다
(spark-compare-check의 psutil 샘플러와 같은 원칙, 0.2초 간격).

사용:
    python measure.py <label> <out.jsonl> -- <cmd...>
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import psutil


def main() -> int:
    label, out_path = sys.argv[1], sys.argv[2]
    cmd = sys.argv[sys.argv.index("--") + 1 :]
    peak = {"rss": 0, "n": 0}
    stop = threading.Event()
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd)

    def sample() -> None:
        p = psutil.Process(proc.pid)
        while not stop.is_set():
            try:
                total = p.memory_info().rss
                for c in p.children(recursive=True):
                    try:
                        total += c.memory_info().rss
                    except psutil.Error:
                        pass
                peak["rss"] = max(peak["rss"], total)
                peak["n"] += 1
            except psutil.Error:
                break
            time.sleep(0.2)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    rc = proc.wait()
    stop.set()
    th.join(timeout=1)
    rec = {
        "label": label,
        "rc": rc,
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "peak_rss_mb": round(peak["rss"] / 1024 / 1024, 1),
        "samples": peak["n"],
        "cmd": " ".join(cmd),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("[measure]", json.dumps(rec, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
