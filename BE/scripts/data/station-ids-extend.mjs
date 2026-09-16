#!/usr/bin/env node
// 역 ID 표(data/subway/conf/station-ids.csv)에 시각표 밖 노선의 역을 더한다 — 113 에서 9개 노선(경의중앙·수인분당·경춘·경강·서해·공항철도·신분당·우이신설·신림)을 넣을 때 씀.
// 기존 행의 ID 는 그대로 두고(임시 부여 9001~ 행만 표준데이터 역번호로 이관), 새 역은 전국도시철도역사정보표준데이터의 역번호를 station_id 로 쓴다.
// 표는 커밋되면 정본이다 — 이 도구는 표를 "늘리기만" 하고, 결과는 --report 로 검토한 뒤 커밋한다.
//
// 사용:
//   node BE/scripts/data/station-ids-extend.mjs \
//     --ids BE/src/main/resources/data/subway/conf/station-ids.csv \
//     --standard BE/src/main/resources/data/subway/kric-station-standard_20260630.csv \
//     --lines BE/src/main/resources/data/subway/molit-urban-lines_20251211.csv \
//     --aliases BE/src/main/resources/data/subway/conf/station-aliases.csv \
//     --extra "원종:1093" \
//     --out BE/src/main/resources/data/subway/conf/station-ids.csv
//   --extra 는 전체노선 파일에 없지만 KTDB 링크에는 있는 역(파일 갱신이 개통보다 늦은 경우). "역명:line_id" 를 쉼표로 잇는다.
import { readFileSync, writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';

import { parseCsv, toCsv } from './lib/csv.mjs';
import { extendStationIdTable } from './lib/station-ids-extend.mjs';

function fail(message, code = 2) {
  console.error(message);
  process.exitCode = code;
}

function main() {
  const { values: opt } = parseArgs({
    options: {
      ids: { type: 'string' }, standard: { type: 'string' }, lines: { type: 'string' }, aliases: { type: 'string' },
      extra: { type: 'string', default: '' }, out: { type: 'string' },
    },
  });
  if (!opt.ids || !opt.standard || !opt.lines || !opt.aliases || !opt.out) {
    fail('사용: --ids <csv> --standard <csv> --lines <csv> --aliases <csv> [--extra "역명:line_id,…"] --out <csv>');
    return;
  }
  const existing = parseCsv(readFileSync(opt.ids, 'utf8'));
  const standard = parseCsv(readFileSync(opt.standard, 'utf8'));
  const urban = parseCsv(readFileSync(opt.lines, 'utf8'));
  const aliases = new Map(parseCsv(readFileSync(opt.aliases, 'utf8')).map((r) => [r['원천표기'].trim(), r['정본표기'].trim()]));
  const extra = opt.extra.split(',').filter(Boolean).map((s) => {
    const [name, lineId] = s.split(':');
    return { name: name.trim(), lineId: lineId.trim() };
  });

  const { rows, report } = extendStationIdTable({ existing, standard, urban, extra, aliases });
  writeFileSync(opt.out, toCsv(['station_id', 'name', 'codes', 'source'], rows.map((r) => [r.station_id, r.name, r.codes, r.source])), 'utf8');

  console.log(`역 ${existing.length} → ${rows.length} (새 역 ${report.added.length} · 이관 ${report.migrated.length} · 기존 역에 노선 추가 ${report.patched.length}) → ${opt.out}`);
  console.log(`이관: ${report.migrated.map((m) => `${m.name} ${m.from}→${m.to}`).join(', ') || '없음'}`);
  console.log(`동명이역(별개 행): ${report.separate.map((s) => `${s.name} ${s.id} (기존 ${s.existing.join('/')})`).join(', ') || '없음'}`);
  console.log(`임시 부여: ${report.assigned.map((a) => `${a.name}=${a.id}`).join(', ') || '없음'}`);
  console.log(`표준데이터에 없음: ${report.missingStandard.join(', ') || '없음'}`);
  console.log(`이름만으로 기존 역에 병합(검토 필요): ${report.mergedByNameOnly.map((m) => `${m.name} → ${m.id} (${m.lineIds.join('/')})`).join(', ') || '없음'}`);
  console.log(`기존 역에 노선 추가 (${report.patched.length}): ${report.patched.map((p) => `${p.name} ${p.id} +${p.added.join(',')}`).join(' | ')}`);
}

try {
  main();
} catch (err) {
  fail(`생성 실패: ${err.message}`, 1);
}
