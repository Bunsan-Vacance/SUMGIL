#!/usr/bin/env node
// prod Kafka 덤프를 N배로 불려 부하 시험 입력을 만든다 (S15P21A104-171). 외부 API 호출 0회.
//
// 왜 그냥 복제하면 안 되는지, 어떤 규칙으로 미는지는 lib/replay.mjs 주석 참고.
// 요약: event_id 가 같으면 컨슈머 중복 제거에, 시각이 같으면 멱등 규칙에 걸려 아무것도 못 잰다.
//
// 사용 — 반드시 로컬 compose 에만 쏜다:
//   node BE/scripts/kafka/replay.mjs --dump .claude/perf/raw/subway-dump-2026-09-16.jsonl --times 100 \
//     | docker exec -i sumgil-kafka /opt/kafka/bin/kafka-console-producer.sh \
//         --bootstrap-server localhost:9092 --topic subway.arrival \
//         --property parse.key=true --property key.separator=$'\t'
//
// prod 에 쏘면 가짜 재고·도착이 실제 Redis 에 들어가고 AI 의 ai-spark 컨슈머도 그것을 먹는다. 하지 말 것.
import { readFileSync } from 'node:fs';
import { parseArgs } from 'node:util';

import { replay } from './lib/replay.mjs';

function fail(message, code = 2) {
  console.error(message);
  process.exitCode = code;
}

function main() {
  const { values: opt } = parseArgs({
    options: {
      dump: { type: 'string' },
      times: { type: 'string', default: '10' },
      interval: { type: 'string', default: '60' },
      round: { type: 'boolean', default: false },
    },
  });
  if (!opt.dump) {
    return fail('사용법: --dump <jsonl> [--times 10] [--interval 60] [--round]\n'
      + '  --round  덤프에서 가장 큰 회차 하나만 쓴다 (건수를 고정하고 싶을 때)');
  }

  const times = Number(opt.times);
  const interval = Number(opt.interval);
  if (!Number.isFinite(times) || times < 1 || !Number.isFinite(interval) || interval < 1) {
    return fail('--times 와 --interval 은 1 이상의 수여야 한다');
  }

  const events = [];
  let skipped = 0;
  for (const line of readFileSync(opt.dump, 'utf8').split('\n')) {
    const text = line.trim();
    if (!text) continue;
    try {
      const event = JSON.parse(text);
      if (!event.entity_id || !event.source) {
        skipped += 1;
        continue;
      }
      events.push(event);
    } catch {
      skipped += 1;
    }
  }
  if (events.length === 0) {
    return fail(`덤프에서 읽을 이벤트가 없다: ${opt.dump}`);
  }

  let input = events;
  if (opt.round) {
    const byRun = new Map();
    for (const event of events) {
      if (!byRun.has(event.poll_run_at)) byRun.set(event.poll_run_at, []);
      byRun.get(event.poll_run_at).push(event);
    }
    input = [...byRun.values()].reduce((a, b) => (b.length > a.length ? b : a));
    console.error(`회차 ${byRun.size}개 중 가장 큰 것 ${input.length}건을 쓴다`);
  }

  const out = replay(input, times, interval);
  const ids = new Set(out.map((r) => JSON.parse(r.value).event_id));
  console.error(`입력 ${input.length}건${skipped ? ` (건너뜀 ${skipped}줄)` : ''} × ${times}회 = ${out.length}건 · `
    + `고유 event_id ${ids.size}개 · 시각 간격 ${interval}초`);
  if (ids.size < out.length) {
    console.error(`  ⚠ 중복 event_id 가 ${out.length - ids.size}건 있다 — 컨슈머가 그만큼 걸러낸다 `
      + '(덤프에 페이지 경계 중복이 섞여 있으면 정상)');
  }

  // 한 줄씩 쓰면 수백만 건에서 느리다. 적당히 모아 내보낸다.
  const CHUNK = 5000;
  for (let i = 0; i < out.length; i += CHUNK) {
    process.stdout.write(out.slice(i, i + CHUNK).map((r) => `${r.key}\t${r.value}`).join('\n') + '\n');
  }
}

main();
