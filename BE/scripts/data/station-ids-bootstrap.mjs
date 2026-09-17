#!/usr/bin/env node
// 역 ID 매핑 표 초안 생성 — data/subway/conf/station-ids.csv 가 없을 때 한 번 쓰는 도구.
// 시각표(gzip)의 (호선, 역사코드, 역사명)에서 물리 역별 번호를 만들고, 시각표에 없는 코레일 전용 역은 --extra 로 받아 9001부터 부여한다.
// 표는 커밋되면 정본이다. 새 역이 생기면 이 도구를 다시 돌리지 말고 표에 행을 추가한다(기존 ID 가 바뀌지 않게).
//
// 사용:
//   node BE/scripts/data/station-ids-bootstrap.mjs \
//     --timetable BE/src/main/resources/data/subway/seoul-train-timetable_20260616.csv.gz \
//     --aliases BE/src/main/resources/data/subway/conf/station-aliases.csv \
//     --extra "가천대:1075,개포동:1075,대모산입구:1075,서현:1075,수내:1075,야탑:1075,이매:1075,태평:1075,한티:1075,서빙고:1063,응봉:1063,한남:1063" \
//     --out BE/src/main/resources/data/subway/conf/station-ids.csv
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { gunzipSync } from 'node:zlib';

import { parseCsv, toCsv } from './lib/csv.mjs';
import { buildStationIdTable } from './lib/station-ids.mjs';

function fail(message, code = 2) {
  console.error(message);
  process.exitCode = code;
}

// 로더의 StationNameNormalizer 와 같은 규칙: 괄호 부기 제거 → 별칭 표
function normalizer(aliasRows) {
  const aliases = new Map(aliasRows.map((r) => [r['원천표기'].trim(), r['정본표기'].trim()]));
  return (raw) => {
    const stripped = raw.replace(/\(.*?\)/g, '').trim();
    return aliases.get(stripped) ?? aliases.get(raw.trim()) ?? stripped;
  };
}

function main() {
  const { values: opt } = parseArgs({
    options: { timetable: { type: 'string' }, aliases: { type: 'string' }, extra: { type: 'string', default: '' }, out: { type: 'string' } },
  });
  if (!opt.timetable || !opt.aliases || !opt.out) {
    fail('사용: --timetable <gz> --aliases <csv> [--extra "역:노선,…"] --out <csv>');
    return;
  }
  if (existsSync(opt.out)) {
    fail(`${opt.out} 가 이미 있다. 표는 정본이라 덮어쓰지 않는다 — 새 역은 행으로 추가한다`, 1);
    return;
  }
  const norm = normalizer(parseCsv(readFileSync(opt.aliases, 'utf8')));
  const timetable = parseCsv(gunzipSync(readFileSync(opt.timetable)).toString('utf8'));
  const rows = timetable.map((r) => ({ line: `100${r['호선'].trim()}`, code: r['역사코드'].trim(), name: norm(r['역사명']) }));
  const extra = opt.extra.split(',').filter(Boolean).map((s) => {
    const [name, line] = s.split(':');
    return { name: norm(name), line: line.trim() };
  });
  const table = buildStationIdTable(rows, extra);
  writeFileSync(opt.out, toCsv(['station_id', 'name', 'codes', 'source'], table.map((r) => [r.station_id, r.name, r.codes, r.source])), 'utf8');

  const assigned = table.filter((r) => r.source === 'assigned');
  console.log(`역 ${table.length}개 (시각표 ${table.length - assigned.length} · 부여 ${assigned.length}) → ${opt.out}`);
  console.log(`부여: ${assigned.map((r) => `${r.station_id}=${r.name}`).join(', ')}`);
}

try {
  main();
} catch (err) {
  fail(`생성 실패: ${err.message}`, 1);
}
