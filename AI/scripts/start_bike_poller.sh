#!/usr/bin/env bash
# 따릉이 실시간 재고 폴러를 nohup 백그라운드로 시작한다.
# 사전조건: AI/.env에 SEOUL_API_KEY(또는 SEOUL_BIKE_KEY) 입력 완료, requirements-dev.txt 설치 완료.
set -euo pipefail

cd "$(dirname "$0")/.."  # AI/ 로 이동

mkdir -p logs
nohup python -m src.collect.bike_realtime >> logs/bike_realtime.log 2>&1 &
echo $! > logs/bike_realtime.pid

echo "시작됨 (pid=$(cat logs/bike_realtime.pid)). 로그: AI/logs/bike_realtime.log"
echo "중지: kill \$(cat logs/bike_realtime.pid)"
