#!/usr/bin/env node
// 버스 노선별 배차간격을 도착정보 API 로 모아 CSV 로 만든다 (S15P21A104-228).
//
// 원천은 **도착정보(공공데이터포털 15000314)** 다. 노선정보조회(15000193)는 우리 키로 안 열린다
// (401 등록되지 않은 서비스키 — 포털은 서비스마다 활용신청이 따로다).
// 도착정보는 정류소 단위 호출인데 응답에 그 정류소를 지나는 노선이 모두 딸려 오므로,
// 노선-정류소 표(72 적재 원천)로 **노선을 다 덮는 최소 정류소 집합**을 골라 호출 수를 줄인다.
//
// 사용:
//   node BE/scripts/data/bus-headway-fetch.mjs --dry-run     # 호출 0회 — 정류소 수·예상 호출 수만 본다
//   node BE/scripts/data/bus-headway-fetch.mjs               # 실제 수집 → data/bus/seoul-bus-headway_<YYYYMMDD>.csv
//   node BE/scripts/data/bus-headway-fetch.mjs --merge <기존CSV>   # 다른 시간대 수집분과 합친다
//
// **실행 전 호출 수를 확인한다.** 개발계정 한도가 1,000회/일이다 (api-survey.md 4절).
// term 이 0 인 노선은 그 시각에 운행 중이 아니라는 뜻이라 낮 1회로는 심야·새벽 노선이 빈다.
// 커버율을 올리려면 다른 시간대에 한 번 더 돌리고 --merge 로 합친다.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { loadDotenv } from '../external/lib/env.mjs';
import { buildUrl, parseResponse, redactKey, resolveKey } from '../external/lib/sources.mjs';
import { GENERAL_STOP, HEADWAY_FIELDS, coverStops, mergeByRoute, oneStopPerRoute, toHeadwayRows } from './lib/bus-headway.mjs';
import { parseCsv, toCsv } from './lib/csv.mjs';

const BE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const BUS_DIR = resolve(BE_ROOT, 'src', 'main', 'resources', 'data', 'bus');
const ROUTE_STOPS_FILE = resolve(BUS_DIR, 'seoul-bus-route-stops_20260902.csv');
/** 한도(1,000회/일)에 비해 과한 호출을 막는 안전장치. 넘으면 멈추고 사용자에게 묻는다. */
const CALL_LIMIT = 400;
const TERM_IDX = HEADWAY_FIELDS.indexOf('term');

function fail(message, code = 2) {
  console.error(message);
  process.exit(code);
}

function kstStamp(date) {
  return new Date(date.getTime() + 9 * 3600e3).toISOString().slice(0, 10).replace(/-/g, '');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 노선-정류소 표에서 (ROUTE_ID, NODE_ID) 쌍만 뽑는다. parseCsv 는 헤더를 키로 한 객체 배열을 돌려준다. */
function readPairs() {
  const rows = parseCsv(readFileSync(ROUTE_STOPS_FILE, 'utf8'));
  if (rows.length === 0 || !('ROUTE_ID' in rows[0]) || !('NODE_ID' in rows[0])) {
    fail(`노선-정류소 표에 ROUTE_ID·NODE_ID 가 없다: ${ROUTE_STOPS_FILE} (열: ${Object.keys(rows[0] ?? {}).join(', ')})`);
  }
  return rows.map((r) => ({ routeId: (r.ROUTE_ID ?? '').trim(), stopId: (r.NODE_ID ?? '').trim() }));
}

async function main() {
  const { values: opt } = parseArgs({
    options: {
      'dry-run': { type: 'boolean', default: false },
      merge: { type: 'string' },
      'skip-stops': { type: 'string' },
      'per-route': { type: 'boolean', default: false },
      'general-stops-only': { type: 'boolean', default: false },
      limit: { type: 'string' },
      out: { type: 'string' },
      env: { type: 'string', default: resolve(BE_ROOT, '.env') },
      timeout: { type: 'string', default: '10000' },
      'max-calls': { type: 'string', default: String(CALL_LIMIT) },
      help: { type: 'boolean', default: false },
    },
  });
  if (opt.help) {
    console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 18).join('\n'));
    return;
  }

  const pairs = readPairs();
  const routes = new Set(pairs.map((p) => p.routeId).filter(Boolean));

  // 2차 수집: 이미 받은 노선은 빼고 못 받은 것만 다시 덮는다. 빈 응답이었던 정류소도 제외한다.
  // 한 번으로 다 받을 수 없다 — API 는 "지금 운행 중인" 노선만 주기 때문이다 (coverStops javadoc).
  let only = null;
  let skipStops = [];
  if (opt.merge) {
    const prev = parseCsv(readFileSync(resolve(opt.merge), 'utf8'));
    const have = new Set(prev.filter((r) => Number(r.term) > 0).map((r) => r.busRouteId));
    only = [...routes].filter((r) => !have.has(r));
    skipStops = opt['skip-stops'] ? readFileSync(resolve(opt['skip-stops']), 'utf8').split(/\r?\n/).map((s) => s.trim()).filter(Boolean) : [];
    console.log(`2차 수집      기존 ${prev.length}행 중 배차간격 있는 노선 ${have.size} · 다시 받을 노선 ${only.length}`);
    if (skipStops.length > 0) console.log(`              빈 응답이었던 정류소 ${skipStops.length} 곳 제외`);
  }

  const pick = opt['per-route'] ? oneStopPerRoute : coverStops;
  const pickOpts = only ? { only, skipStops } : {};
  if (opt['general-stops-only']) pickOpts.stopFilter = GENERAL_STOP;
  let { stops, uncovered } = pick(pairs, pickOpts);
  // --limit 은 가설을 작게 시험하는 용도다. 전체를 쏘기 전에 효과를 확인한다.
  if (opt.limit) {
    const n = Number(opt.limit);
    console.log(`시험 실행      앞 ${n} 곳만 부른다 (전체 ${stops.length})`);
    stops = stops.slice(0, n);
  }
  if (opt['per-route']) console.log('선택 방식      노선당 정류소 1곳 (그리디는 큰 거점만 골라 짧은 노선이 빠진다)');
  const target = only ? only.length : routes.size;

  console.log(`노선-정류소 표  ${pairs.length.toLocaleString()}행 · 노선 ${routes.size} · 정류소 ${new Set(pairs.map((p) => p.stopId).filter(Boolean)).size.toLocaleString()}`);
  console.log(`덮기 결과      정류소 ${stops.length} 곳으로 노선 ${target - uncovered.length} 개를 덮는다 (대상 ${target})`);
  if (uncovered.length > 0) {
    console.log(`  덮지 못한 노선 ${uncovered.length}: ${uncovered.slice(0, 10).join(', ')}${uncovered.length > 10 ? ', …' : ''}`);
  }
  console.log(`예상 호출      ${stops.length} 회 (개발계정 한도 1,000회/일)`);

  if (opt['dry-run']) {
    console.log('\ndry-run — 호출하지 않았다. 실제 수집은 --dry-run 없이 실행한다.');
    return;
  }

  const maxCalls = Number(opt['max-calls']);
  if (stops.length > maxCalls) {
    fail(`예상 호출 ${stops.length} 회가 상한 ${maxCalls} 회를 넘는다 — 의도한 것이면 --max-calls 로 올린다.`);
  }

  const env = { ...loadDotenv(opt.env), ...process.env };
  const key = resolveKey('bus', env);
  const timeoutMs = Number(opt.timeout);
  const started = Date.now();

  const collected = [];
  const failures = [];
  for (let i = 0; i < stops.length; i += 1) {
    const stId = stops[i];
    const url = buildUrl('bus', key, { stId });
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs), headers: { accept: 'application/json' } });
      const body = await res.json();
      const parsed = parseResponse('bus', body);
      if (!parsed.ok) {
        failures.push(`${stId}: HTTP ${res.status} · ${parsed.code ?? '-'} ${parsed.message ?? ''}`);
      } else {
        collected.push(...toHeadwayRows(parsed.rows, stId));
      }
    } catch (err) {
      const reason = err.name === 'TimeoutError' ? `타임아웃 ${timeoutMs}ms` : err.message;
      failures.push(`${stId}: ${reason}`);
    }
    if ((i + 1) % 20 === 0 || i + 1 === stops.length) {
      console.log(`  ${i + 1}/${stops.length} 정류소 · 노선 행 ${collected.length} · 실패 ${failures.length}`);
    }
    // 연속 호출 간격. 서버 부담과 순간 폭주를 피한다.
    if (i + 1 < stops.length) await sleep(120);
  }

  let rowsIn = collected;
  if (opt.merge) {
    const prevObjects = parseCsv(readFileSync(resolve(opt.merge), 'utf8'));
    const prevHeader = Object.keys(prevObjects[0] ?? {});
    if (prevHeader.join(',') !== HEADWAY_FIELDS.join(',')) {
      fail(`--merge 대상의 열이 다르다: ${opt.merge}\n  기대 ${HEADWAY_FIELDS.join(',')}\n  실제 ${prevHeader.join(',')}`);
    }
    // 기존 파일을 앞에 둔다 — 충돌 시 "먼저 본 값" 이 기존 값이 된다.
    const prevRows = prevObjects.map((o) => HEADWAY_FIELDS.map((f) => o[f] ?? ''));
    rowsIn = [...prevRows, ...collected];
    console.log(`\n병합  기존 ${prevRows.length}행 + 이번 ${collected.length}행`);
  }

  const { rows, conflicts } = mergeByRoute(rowsIn);
  const withTerm = rows.filter((r) => Number(r[HEADWAY_FIELDS.indexOf('term')]) > 0).length;

  const out = opt.out ?? resolve(BUS_DIR, `seoul-bus-headway_${kstStamp(new Date())}.csv`);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, toCsv(HEADWAY_FIELDS, rows), 'utf8');

  console.log(`\n노선 ${rows.length} 행 → ${out}`);
  console.log(`  배차간격 있음 ${withTerm} · 0(운행 중 아님) ${rows.length - withTerm}`);
  console.log(`  호출 ${stops.length}회 · 실패 ${failures.length} · ${Math.round((Date.now() - started) / 1000)}초`);
  if (conflicts.length > 0) {
    console.log(`  충돌 ${conflicts.length}건:`);
    conflicts.slice(0, 10).forEach((c) => console.log(`    ${c}`));
  }
  if (failures.length > 0) {
    // 빈 응답이었던 정류소를 남긴다 — 다음 회차에 --skip-stops 로 넘겨 다시 고르지 않게 한다.
    const emptyStopsFile = `${out.replace(/\.csv$/, '')}_empty-stops.txt`;
    writeFileSync(emptyStopsFile, `${failures.map((f) => f.split(':')[0]).join('\n')}\n`, 'utf8');
    console.log(`  빈 응답·실패 정류소 ${failures.length} → ${emptyStopsFile}`);
    failures.slice(0, 5).forEach((f) => console.log(`    ${f}`));
    console.log(`  URL 형식: ${redactKey(buildUrl('bus', key, { stId: stops[0] }), key)}`);
  }
  if (only) {
    const stillMissing = only.filter((r) => !rows.some((row) => row[0] === r && Number(row[TERM_IDX]) > 0));
    console.log(`  아직 못 받은 노선 ${stillMissing.length} / 대상 ${only.length}`);
  }
}

main().catch((err) => fail(`수집 실패: ${err.message}`, 1));
