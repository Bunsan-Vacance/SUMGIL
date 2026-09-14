#!/usr/bin/env bash
# Kafka 토픽 3개 생성·설정 맞춤 (S15P21A104-168).
#
# 평소에는 필요 없다 — 수집기(collect 프로파일)가 기동할 때 같은 일을 AdminClient 로 한다(CollectTopics.java).
# 수집기를 올리기 전에 prod 에 토픽만 먼저 두거나, 값이 코드와 같은지 눈으로 볼 때 쓴다.
# 값은 BE/src/main/resources/application-collect.yml · CollectTopics.java 와 같아야 한다 — 바꿀 때 두 곳 함께.
#
#   로컬 compose : bash BE/scripts/kafka/topics.sh
#   prod (k3s)   : KAFKA_EXEC="kubectl -n prod exec kafka-0 --" bash BE/scripts/kafka/topics.sh
#   확인만       : bash BE/scripts/kafka/topics.sh describe
#
# 근거·용량 계산은 BE/docs/infra/kafka.md 4절.

set -euo pipefail

export MSYS_NO_PATHCONV=1   # Git Bash(Windows)가 /opt/... 를 윈도우 경로로 바꾸는 것을 막는다

KAFKA_EXEC="${KAFKA_EXEC:-docker exec sumgil-kafka}"
BIN=/opt/kafka/bin
BOOTSTRAP=localhost:9092     # 컨테이너/파드 안에서 자기 자신에게 붙는 주소

RETENTION_MS=172800000       # 48h
SEGMENT_MS=21600000          # 6h  — 삭제는 닫힌 세그먼트 단위라 이게 없으면 48h 가 지나도 안 지워진다
SEGMENT_BYTES=134217728      # 128MiB
declare -A RETENTION_BYTES=(
  [subway.arrival]=1610612736   # 1.5GiB
  [bike.stock]=1073741824       # 1GiB
  [weather.nowcast]=67108864    # 64MiB
)

MODE="${1:-apply}"
existing="$($KAFKA_EXEC $BIN/kafka-topics.sh --bootstrap-server $BOOTSTRAP --list)"

for topic in subway.arrival bike.stock weather.nowcast; do
  config="cleanup.policy=delete,retention.ms=$RETENTION_MS,retention.bytes=${RETENTION_BYTES[$topic]},segment.ms=$SEGMENT_MS,segment.bytes=$SEGMENT_BYTES"
  if [ "$MODE" = "apply" ]; then
    if grep -qx "$topic" <<<"$existing"; then
      $KAFKA_EXEC $BIN/kafka-configs.sh --bootstrap-server $BOOTSTRAP --entity-type topics --entity-name "$topic" \
        --alter --add-config "$config" >/dev/null
      echo "설정 맞춤  $topic"
    else
      # shellcheck disable=SC2046
      $KAFKA_EXEC $BIN/kafka-topics.sh --bootstrap-server $BOOTSTRAP --create --topic "$topic" \
        --partitions 1 --replication-factor 1 $(for kv in ${config//,/ }; do printf -- '--config %s ' "$kv"; done) >/dev/null
      echo "생성       $topic"
    fi
  fi
  # synonyms={...} 에는 브로커 기본값(retention.bytes=-1 등)이 같이 들어 있어 지우고 본다. 남는 건 토픽에 실제로 걸린 값이다.
  $KAFKA_EXEC $BIN/kafka-configs.sh --bootstrap-server $BOOTSTRAP --entity-type topics --entity-name "$topic" --describe \
    | sed 's/ sensitive=.*//' \
    | grep -oE "(cleanup.policy|retention.ms|retention.bytes|segment.ms|segment.bytes)=[^ ,}]+" | sort | tr '\n' ' '
  echo " <- $topic"
done
