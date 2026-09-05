#!/usr/bin/env bash
# 초단기실황/예보 폴러를 nohup 백그라운드로 시작한다.
# 사전조건: AI/.env에 KMA_API_KEY 입력 완료, API허브에서 초단기실황/예보 활용신청 승인 완료.
set -euo pipefail

cd "$(dirname "$0")/../.."  # AI/ 로 이동

mkdir -p logs
nohup python -m DATA_ENGINE.collect.weather_nowcast >> logs/weather_nowcast.log 2>&1 &
echo $! > logs/weather_nowcast.pid

echo "시작됨 (pid=$(cat logs/weather_nowcast.pid)). 로그: AI/logs/weather_nowcast.log"
echo "중지: kill \$(cat logs/weather_nowcast.pid)"
