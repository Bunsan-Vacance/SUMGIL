#!/usr/bin/env bash
# 대시보드 JSON 동기화 (S15P21A104-341). 정본은 AI/validation/INFRA/observability-check/grafana/dashboards/ 이고
# 이 디렉터리의 grafana/dashboards/ 는 복사본이다(kustomize는 루트 밖 파일을 읽지 못한다).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../../../AI/validation/INFRA/observability-check/grafana/dashboards"
dst="$here/grafana/dashboards"
mkdir -p "$dst"
cp -v "$src"/*.json "$dst"/
