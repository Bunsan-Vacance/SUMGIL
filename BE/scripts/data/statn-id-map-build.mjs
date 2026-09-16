#!/usr/bin/env node
// 실시간 도착 API 의 statnId → station_id 매핑 표를 만든다 (S15P21A104-171).
// 입력은 prod Kafka 덤프라 외부 API 호출이 0회다 — 하루 1,000회 예산을 쓰지 않는다.
//
// 덤프 뜨는 법 (노드에서. 이미 쌓인 걸 읽는 것이라 호출 0회):
//   ssh a104 "sudo kubectl exec -n prod sts/kafka -- /opt/kafka/bin/kafka-console-consumer.sh \
//     --bootstrap-server localhost:9092 --topic subway.arrival --max-messages 6500 --timeout-ms 180000" > dump.jsonl
//
// 사용:
//   node BE/scripts/data/statn-id-map-build.mjs \
//     --dump .claude/perf/raw/subway-dump-2026-09-16.jsonl \
//     --ids BE/src/main/resources/data/subway/conf/station-ids.csv \
//     --aliases BE/src/main/resources/data/subway/conf/station-aliases.csv \
//     --out BE/src/main/resources/data/subway/conf/statn-id-map.csv \
//     --report
//
// 규칙·근거는 lib/statn-id-map.mjs 주석. 표는 커밋되면 정본이다 — --report 로 미매핑을 확인한 뒤 커밋한다.
import { readFileSync, writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';

import { parseCsv, toCsv } from './lib/csv.mjs';
import { buildStatnIdMap } from './lib/statn-id-map.mjs';

function fail(message, code = 2) {
  console.error(message);
  process.exitCode = code;
}

/** JSONL 덤프 → 이벤트 payload 배열. JSON 이 아닌 줄(콘솔 경고 등)은 세어서 보고만 한다. */
function readDump(path) {
  const events = [];
  let skipped = 0;
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const text = line.trim();
    if (!text) continue;
    let event;
    try {
      event = JSON.parse(text);
    } catch {
      skipped += 1;
      continue;
    }
    const payload = event?.payload;
    if (!payload?.statnId) {
      skipped += 1;
      continue;
    }
    events.push({ subwayId: payload.subwayId, statnNm: payload.statnNm, statnId: payload.statnId });
  }
  return { events, skipped };
}

function main() {
  const { values: opt } = parseArgs({
    options: {
      dump: { type: 'string' },
      ids: { type: 'string' },
      aliases: { type: 'string' },
      out: { type: 'string' },
      report: { type: 'boolean', default: false },
    },
  });
  if (!opt.dump || !opt.ids || !opt.aliases) {
    return fail('사용법: --dump <jsonl> --ids <station-ids.csv> --aliases <station-aliases.csv> [--out <csv>] [--report]');
  }

  const { events, skipped } = readDump(opt.dump);
  const idRows = parseCsv(readFileSync(opt.ids, 'utf8'));
  const aliasRows = parseCsv(readFileSync(opt.aliases, 'utf8'));
  const { rows, unmapped } = buildStatnIdMap(events, idRows, aliasRows);

  const runs = new Set();
  for (const line of readFileSync(opt.dump, 'utf8').split('\n')) {
    const text = line.trim();
    if (!text) continue;
    try {
      const run = JSON.parse(text).poll_run_at;
      if (run) runs.add(run);
    } catch { /* readDump 가 이미 셌다 */ }
  }

  console.error(`덤프 ${events.length}건 (회차 ${runs.size}개${skipped ? `, 건너뜀 ${skipped}줄` : ''})`);
  console.error(`매핑 ${rows.length}역 · 미매핑 ${unmapped.length}역`);
  if (unmapped.length > 0) {
    console.error('');
    console.error('안 붙은 역 — 이 역들은 Redis 에 올라가지 않는다:');
    for (const u of unmapped) {
      console.error(`  ${u.statn_id}  노선 ${u.line_id}  ${u.name}  (${u.count}건)`);
    }
    console.error('');
  }
  if (opt.report) {
    const byLine = new Map();
    for (const row of rows) byLine.set(row.line_id, (byLine.get(row.line_id) ?? 0) + 1);
    console.error('노선별 매핑 역 수:');
    for (const [line, count] of [...byLine].sort()) console.error(`  ${line}  ${count}역`);
  }

  if (opt.out) {
    const cells = rows.map((r) => [r.statn_id, r.station_id, r.line_id, r.name]);
    writeFileSync(opt.out, toCsv(['statn_id', 'station_id', 'line_id', 'name'], cells), 'utf8');
    console.error(`\n썼다: ${opt.out}`);
  }
}

main();
