#!/usr/bin/env bash
# J15A104A 실데이터 실측 — Spark 패널 재집계 잡(crowd_panel_rebuild) vs pandas to_long.
#
# 전제(2026-10-02 확인): 서버 AI 사본 /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI,
#   .venv에 pyspark 4.2.0·pandas 3.0.5·psutil, Java 21, raw 17일(dt=2026-09-15~10-01, 하루 약 6.4만 행),
#   recent_long 185,386행, 고정 패널 2024-2025 와이드 3,987,000행(롱으로 펼치면 7,974,000행), 여유 메모리 약 12GB.
# 쓰는 곳은 data/CROWD/interim/spark_exp/panel_check/ 하나뿐(격리 경로). 운영 파일은 읽기만 한다.
#
# 실행(로컬에서, 이 저장소 AI/ 기준):
#   bash validation/INFRA/retrain-pipeline-check/server/run_server_check.sh
# 끝나면 results.jsonl·meta.json을 로컬 validation/INFRA/retrain-pipeline-check/server/results/ 로 받아온다.
set -euo pipefail

KEY="${KEY:-$HOME/workspace/J15A104T.pem}"
HOST="${HOST:-ubuntu@j15a104a.p.ssafy.io}"
R=/home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI
X=data/CROWD/interim/spark_exp/panel_check
HERE="$(cd "$(dirname "$0")" && pwd)"
AI_ROOT="$(cd "$HERE/../../../.." && pwd)"

echo "[1/3] 잡·측정 스크립트 전송"
ssh -i "$KEY" "$HOST" "mkdir -p $R/$X"
scp -q -i "$KEY" "$AI_ROOT/DATA_ENGINE/spark/jobs/crowd_panel_rebuild.py" "$HOST:$R/DATA_ENGINE/spark/jobs/"
scp -q -i "$KEY" "$HERE/measure.py" "$HERE/pandas_baseline.py" "$HOST:$R/$X/"

echo "[2/3] 서버 실행(pandas 기준선 → Spark 3코어·3g → Spark 2코어·2g)"
ssh -i "$KEY" "$HOST" 'bash -s' <<EOF
set -uo pipefail
cd $R
export PYTHONIOENCODING=utf-8
PY=.venv/bin/python
X=$X
rm -f \$X/results.jsonl \$X/pandas_long.parquet   # 이전 실행 기록·기준 파일이 섞이지 않게 비운다
echo "=== pandas_baseline"
# 파일 경로로 실행하면 sys.path[0]이 스크립트 폴더라 DATA_ENGINE을 못 찾는다 -> PYTHONPATH로 AI 루트를 넣는다
PYTHONPATH=. nice -n 10 \$PY \$X/measure.py pandas_baseline \$X/results.jsonl -- \$PY \$X/pandas_baseline.py data/CROWD/raw/ridership_daily \$X/pandas_long.parquet
if [ ! -s \$X/pandas_long.parquet ]; then
  echo "pandas 기준선 실패 - Spark 대조 단계를 건너뛴다" >&2
  cat \$X/results.jsonl
  exit 1
fi
for cfg in "3 3g" "2 2g"; do
  set -- \$cfg; cores=\$1; mem=\$2; run="c\${cores}_\${mem}"
  echo "=== spark_\$run (2026 증분 ∪ 2024-2025 고정 패널, pandas 롱과 대조)"
  nice -n 10 \$PY \$X/measure.py spark_\$run \$X/results.jsonl -- \$PY -m DATA_ENGINE.spark.jobs.crowd_panel_rebuild \
    --input-root data/CROWD/raw/ridership_daily \
    --base-panel data/CROWD/processed/crowd_panel_2024_2025.parquet \
    --out-root \$X/spark_\$run --run \$run --cores \$cores --driver-memory \$mem \
    --verify-against \$X/pandas_long.parquet 2>&1 | grep -vE "WARN|SLF4J|log4j" | tail -8
  echo "--- meta"; cat \$X/spark_\$run/meta.json
done
echo "=== results.jsonl"; cat \$X/results.jsonl
free -m | head -2
EOF

echo "[3/3] 결과 회수"
mkdir -p "$HERE/results"
scp -q -i "$KEY" "$HOST:$R/$X/results.jsonl" "$HERE/results/"
for run in c3_3g c2_2g; do
  scp -q -i "$KEY" "$HOST:$R/$X/spark_$run/meta.json" "$HERE/results/meta_$run.json" || true
done
echo "완료: $HERE/results/"
