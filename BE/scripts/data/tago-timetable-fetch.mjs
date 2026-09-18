#!/usr/bin/env node
// TAGO 지하철정보(공공데이터포털 15098554)에서 시각표 밖 수도권 9개 노선의 역별 출발 시각표를 받아 CSV 로 만든다 (S15P21A104-243).
// 로더(TagoTimetableParser)는 이 CSV 만 읽고 API 를 부르지 않는다 — 원천 CSV 를 커밋한다.
//
// 두 단계:
//   A. 역 검색   conf/station-ids.csv 의 대상 노선 역 이름 → GetKwrdFndSubwaySttnList → conf/tago-station-ids.csv (station_id·line_id ↔ TAGO id)
//   B. 시각표    매핑 × 요일 3(01 평일·02 토·03 일) × 방향 2(U·D) → GetSubwaySttnAcctoSchdulList → data/subway/tago-timetable_<YYYYMMDD>.csv
//
// 사용:
//   node BE/scripts/data/tago-timetable-fetch.mjs --dry-run          # 호출 0회 — 역·조합 수와 예상 호출 수만 본다
//   node BE/scripts/data/tago-timetable-fetch.mjs --stations-only    # A 만 (≈ 역 이름 수만큼 호출)
//   node BE/scripts/data/tago-timetable-fetch.mjs                    # A(매핑 파일이 있으면 재사용) + B. 중간에 끊겨도 다시 실행하면 이어받는다
//   node BE/scripts/data/tago-timetable-fetch.mjs --limit 3          # 처음 3역만 — 전체를 쏘기 전 작게 시험
//
// 호출 수 = 역 이름 수(A) + 매핑 수 × 6(B). 대상 9개 노선은 역 210개·역×노선 233 → 약 210 + 1,398 = 1,600회.
// 공공데이터포털 개발계정 한도는 이 서비스 10,000/일 — 서울 열린데이터광장(1,000/일)과 다른 키·다른 한도다.
// 응답 오류 코드: 12 서비스 없음(경로) · 30 등록되지 않은 서비스키(미신청) · 22 한도 초과. 12/30 이 나오면 즉시 멈춘다.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { loadDotenv } from '../external/lib/env.mjs';
import { parseCsv, toCsv } from './lib/csv.mjs';
import {
  MAPPING_FIELDS, OP_STATIONS, OP_TIMETABLE, TIMETABLE_FIELDS,
  buildTagoUrl, comboKey, doneKeysFromRows, parseTagoResponse, pendingCombos, pickStationMatches,
  targetStations, toTimetableRows,
} from './lib/tago-timetable.mjs';

const BE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SUBWAY_DIR = resolve(BE_ROOT, 'src', 'main', 'resources', 'data', 'subway');
const PAGE_ROWS = 500;          // 양정 평일 상행 86행 — 한 페이지에 넉넉하다. totalCount 가 넘으면 다음 페이지를 이어 받는다
const STOP_CODES = new Set(['12', '30']);   // 경로 없음·미신청은 반복해도 같으니 바로 멈춘다
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fail(message, code = 2) {
  console.error(message);
  process.exitCode = code;
}

function kstStamp(date) {
  return new Date(date.getTime() + 9 * 3600 * 1000).toISOString().slice(0, 10).replace(/-/g, '');
}

function readCsvIfExists(path) {
  return existsSync(path) ? parseCsv(readFileSync(path, 'utf8')) : null;
}

async function callTago(op, key, params, timeoutMs) {
  const url = buildTagoUrl(op, key, params);
  const started = performance.now();
  const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs), headers: { accept: 'application/json' } });
  const text = await res.text();
  let body = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = null;
  }
  const parsed = parseTagoResponse(body);
  return { ...parsed, status: res.status, elapsedMs: Math.round(performance.now() - started) };
}

async function main() {
  const { values: opt } = parseArgs({
    options: {
      'dry-run': { type: 'boolean', default: false },
      'stations-only': { type: 'boolean', default: false },
      'refresh-stations': { type: 'boolean', default: false },
      limit: { type: 'string' },
      lines: { type: 'string' },
      mapping: { type: 'string', default: resolve(SUBWAY_DIR, 'conf', 'tago-station-ids.csv') },
      out: { type: 'string' },
      stamp: { type: 'string' },
      env: { type: 'string', default: resolve(BE_ROOT, '.env') },
      timeout: { type: 'string', default: '15000' },
      delay: { type: 'string', default: '100' },
    },
  });
  const timeoutMs = Number(opt.timeout);
  const delayMs = Number(opt.delay);
  const now = new Date();
  const stamp = opt.stamp ?? kstStamp(now);
  const out = opt.out ?? resolve(SUBWAY_DIR, `tago-timetable_${stamp}.csv`);
  const onlyLines = opt.lines ? new Set(opt.lines.split(',').map((s) => s.trim())) : null;

  // 우리 역 목록·별칭 (로더와 같은 원천)
  const aliases = Object.fromEntries(
    parseCsv(readFileSync(resolve(SUBWAY_DIR, 'conf', 'station-aliases.csv'), 'utf8')).map((r) => [r['원천표기'], r['정본표기']]),
  );
  let stations = targetStations(parseCsv(readFileSync(resolve(SUBWAY_DIR, 'conf', 'station-ids.csv'), 'utf8')));
  if (onlyLines) {
    stations = stations.map((s) => ({ ...s, lineIds: s.lineIds.filter((l) => onlyLines.has(l)) })).filter((s) => s.lineIds.length);
  }
  if (opt.limit) {
    stations = stations.slice(0, Number(opt.limit));
  }
  const pairs = stations.reduce((n, s) => n + s.lineIds.length, 0);

  // A 단계 매핑 — 파일이 있으면 재사용한다 (--refresh-stations 로 다시 받는다)
  const existingMapping = opt['refresh-stations'] ? null : readCsvIfExists(opt.mapping);
  const mappingsToUse = existingMapping
    ? existingMapping.filter((m) => (!onlyLines || onlyLines.has(m.line_id)) && stations.some((s) => s.stationId === m.station_id))
    : null;

  // B 단계 이어받기 — 이미 받은 조합은 건너뛴다
  const existingRows = readCsvIfExists(out) ?? [];
  const doneKeys = doneKeysFromRows(existingRows);
  // 응답이 0행인 조합(종점 한쪽 방향·토요일 없는 노선 등)은 CSV 에 흔적이 없어 이어받기 때문에 따로 적어 둔다.
  // resources 밖(BE/build, gitignore)에 둔다 — 커밋·jar 에 들어갈 파일이 아니다. 지워지면 그 조합만 다시 부른다(2026-09-18 기준 530콜).
  const emptyFile = resolve(BE_ROOT, 'build', 'tago', `${basename(out)}.empty.txt`);
  mkdirSync(dirname(emptyFile), { recursive: true });
  const emptyDone = existsSync(emptyFile) ? new Set(readFileSync(emptyFile, 'utf8').split('\n').filter(Boolean)) : new Set();
  emptyDone.forEach((k) => doneKeys.add(k));

  const stationCalls = mappingsToUse ? 0 : stations.length;
  const timetableCalls = opt['stations-only'] ? 0 : pendingCombos(mappingsToUse ?? stations.flatMap((s) => s.lineIds.map((l) => ({ tago_station_id: `?${s.stationId}|${l}` }))), doneKeys).length;
  console.log(`대상 역 ${stations.length} · 역×노선 ${pairs}${onlyLines ? ` · 노선 ${[...onlyLines].join(',')}` : ''}`);
  console.log(`A 역 검색 ${mappingsToUse ? `재사용 (${opt.mapping}, ${mappingsToUse.length}건)` : `${stationCalls}회 호출`}`);
  console.log(`B 시각표 ${opt['stations-only'] ? '건너뜀' : `${timetableCalls}회 호출 (이미 받은 조합 ${doneKeys.size}개 제외)`} → ${out}`);
  console.log(`예상 호출 ${stationCalls + timetableCalls}회 · 한도 10,000/일`);
  if (opt['dry-run']) {
    console.log('\ndry-run — 호출하지 않았다.');
    return;
  }

  const env = { ...loadDotenv(opt.env), ...process.env };
  const key = env.DATA_GO_KR_KEY?.trim();
  if (!key) {
    fail('DATA_GO_KR_KEY 가 없다. BE/.env 에 공공데이터포털 디코딩 키를 넣는다 (TAGO 지하철정보 활용신청이 승인된 계정).');
    return;
  }
  let calls = 0;

  // ── A. 역 검색 ────────────────────────────────────────────────────────────────
  let mappings = mappingsToUse;
  if (!mappings) {
    const rows = [];
    const missing = [];
    const ignoredRoutes = new Map();
    for (let i = 0; i < stations.length; i += 1) {
      const s = stations[i];
      const r = await callTago(OP_STATIONS, key, { subwayStationName: s.name, numOfRows: 50, pageNo: 1 }, timeoutMs);
      calls += 1;
      if (!r.ok) {
        console.error(`  ${s.name}: 오류 ${r.code ?? '-'} ${r.message ?? ''} (HTTP ${r.status})`);
        if (STOP_CODES.has(r.code)) {
          fail('경로 또는 활용신청 문제 — 멈춘다 (12 서비스 없음 · 30 미신청).', 1);
          return;
        }
        missing.push(`${s.name}: 호출 오류 ${r.code}`);
        continue;
      }
      const picked = pickStationMatches(s, r.rows, aliases);
      rows.push(...picked.matched);
      picked.missingLineIds.forEach((l) => missing.push(`${s.name}(${l})`));
      picked.ignored.forEach((x) => {
        const route = x.slice(x.lastIndexOf('(') + 1, -1);
        ignoredRoutes.set(route, (ignoredRoutes.get(route) ?? 0) + 1);
      });
      if ((i + 1) % 25 === 0 || i + 1 === stations.length) {
        console.log(`  A ${i + 1}/${stations.length} · 매핑 ${rows.length} · 못 찾음 ${missing.length} · 호출 ${calls}`);
      }
      if (i + 1 < stations.length) await sleep(delayMs);
    }
    mkdirSync(dirname(opt.mapping), { recursive: true });
    writeFileSync(opt.mapping, toCsv(MAPPING_FIELDS, rows), 'utf8');
    console.log(`A 완료: 매핑 ${rows.length}건 → ${opt.mapping}`);
    if (missing.length) {
      console.warn(`  못 찾은 역×노선 ${missing.length}건 — 이름 차이면 conf/station-aliases.csv 에 별칭을 더한다:\n    ${missing.join('\n    ')}`);
    }
    const seen = [...ignoredRoutes.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}×${v}`).join(' · ');
    if (seen) console.log(`  버린 항목의 노선 표기(대상 밖 또는 이름 불일치): ${seen}`);
    mappings = parseCsv(toCsv(MAPPING_FIELDS, rows));
    if (opt['stations-only']) {
      console.log(`호출 ${calls}회`);
      return;
    }
  }

  // ── B. 시각표 ─────────────────────────────────────────────────────────────────
  const combos = pendingCombos(mappings, doneKeys);
  const collected = existingRows.map((r) => TIMETABLE_FIELDS.map((f) => r[f] ?? ''));
  const emptyCombos = [...emptyDone];
  const errors = [];
  const flush = () => {
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(out, toCsv(TIMETABLE_FIELDS, collected), 'utf8');
    writeFileSync(emptyFile, emptyCombos.length ? `${emptyCombos.join('\n')}\n` : '', 'utf8');
  };
  console.log(`B 시작: 조합 ${combos.length}개`);
  for (let i = 0; i < combos.length; i += 1) {
    const { mapping, dailyType, upDown } = combos[i];
    let page = 1;
    let got = 0;
    let stop = false;
    for (;;) {
      const r = await callTago(OP_TIMETABLE, key, {
        subwayStationId: mapping.tago_station_id, dailyTypeCode: dailyType, upDownTypeCode: upDown, numOfRows: PAGE_ROWS, pageNo: page,
      }, timeoutMs);
      calls += 1;
      if (!r.ok) {
        errors.push(`${mapping.name}(${mapping.line_id}) ${dailyType}/${upDown}: ${r.code ?? '-'} ${r.message ?? ''} HTTP ${r.status}`);
        if (STOP_CODES.has(r.code)) stop = true;
        break;
      }
      collected.push(...toTimetableRows(mapping, dailyType, upDown, r.rows));
      got += r.rows.length;
      if (r.rows.length < PAGE_ROWS || (r.total != null && got >= r.total)) break;
      page += 1;
      await sleep(delayMs);
    }
    if (got === 0 && !stop) emptyCombos.push(comboKey(mapping.tago_station_id, dailyType, upDown));
    if (stop) {
      flush();
      fail(`경로 또는 활용신청 문제 — 멈춘다. 지금까지 ${collected.length}행 저장.`, 1);
      return;
    }
    if ((i + 1) % 20 === 0 || i + 1 === combos.length) {
      flush();
      console.log(`  B ${i + 1}/${combos.length} · 행 ${collected.length.toLocaleString()} · 빈 조합 ${emptyCombos.length} · 오류 ${errors.length} · 호출 ${calls}`);
    }
    if (i + 1 < combos.length) await sleep(delayMs);
  }
  flush();

  // 요약 — 노선별 역·행, 운행 없는 조합
  const byLine = new Map();
  for (const row of collected) {
    const k = row[0];
    const acc = byLine.get(k) ?? { stations: new Set(), rows: 0 };
    acc.stations.add(row[1]);
    acc.rows += 1;
    byLine.set(k, acc);
  }
  console.log('\n노선별: ' + [...byLine.entries()].sort().map(([l, a]) => `${l} 역 ${a.stations.size} · ${a.rows.toLocaleString()}행`).join(' | '));
  console.log(`시각표 ${collected.length.toLocaleString()}행 → ${out}`);
  console.log(`빈 조합(운행 없음) ${emptyCombos.length}개 → ${emptyFile}`);
  if (errors.length) console.warn(`오류 ${errors.length}건:\n  ${errors.slice(0, 20).join('\n  ')}${errors.length > 20 ? '\n  …' : ''}`);
  console.log(`호출 ${calls}회 · ${new Date().toISOString()} (UTC)`);
}

main().catch((err) => fail(`수집 실패: ${err.message}`, 1));
