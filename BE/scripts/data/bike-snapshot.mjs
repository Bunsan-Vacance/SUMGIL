#!/usr/bin/env node
// bikeList(서울시 공공자전거 실시간 대여정보) 전 페이지를 1회 호출해 대여소 마스터 스냅샷 CSV 를 만든다.
// bike_station.rental_id 는 이 응답의 stationId(ST-xxx) 를 그대로 쓴다 — API 명세·Redis 키(bike:stock:{rentalId})와 같은 값.
// 파일형 대여소 정보(OA-13252)에는 stationId 가 없어 이 스냅샷이 주 원천이다 (BE/docs/db/load-bus-bike.md).
//
// 사용:
//   node BE/scripts/data/bike-snapshot.mjs                       # 3페이지(1~3000) → data/bike/seoul-bike-stations-live_<YYYYMMDD>.csv
//   node BE/scripts/data/bike-snapshot.mjs --out 경로 --pages 3 --env BE/.env --timeout 10000
//
// 호출은 페이지 수만큼(기본 3회)이다. 하루 1,000건 한도에 비해 무시할 수준이지만 반복 실행용이 아니다.
// 실습실 망에서는 openapi.seoul.go.kr:8088 이 막혀 있어 핫스팟·EC2 에서 실행한다 (api-survey.md 함정 표).
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { loadDotenv } from '../external/lib/env.mjs';
import { buildUrl, parseResponse, redactKey, resolveKey } from '../external/lib/sources.mjs';
import { SNAPSHOT_FIELDS, mergePages } from './lib/bike-snapshot.mjs';
import { toCsv } from './lib/csv.mjs';

const BE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PAGE_SIZE = 1000;

function fail(message, code = 2) {
  console.error(message);
  process.exitCode = code;
}

function kstStamp(date) {
  // KST(UTC+9) 기준 YYYYMMDD — 파일명에 쓴다
  const kst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  return kst.toISOString().slice(0, 10).replace(/-/g, '');
}

async function fetchPage(url, timeoutMs) {
  const started = performance.now();
  const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs), headers: { accept: 'application/json' } });
  const text = await res.text();
  let body = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = null;
  }
  return { status: res.status, elapsedMs: Math.round(performance.now() - started), bytes: Buffer.byteLength(text, 'utf8'), body };
}

async function main() {
  const { values: opt } = parseArgs({
    options: {
      out: { type: 'string' },
      pages: { type: 'string', default: '3' },
      env: { type: 'string', default: resolve(BE_ROOT, '.env') },
      timeout: { type: 'string', default: '10000' },
    },
  });
  const pages = Number(opt.pages);
  const timeoutMs = Number(opt.timeout);
  const now = new Date();
  const out = opt.out ?? resolve(BE_ROOT, 'src', 'main', 'resources', 'data', 'bike', `seoul-bike-stations-live_${kstStamp(now)}.csv`);

  const env = { ...loadDotenv(opt.env), ...process.env };
  const key = resolveKey('bike', env);

  const collected = [];
  let total = null;
  for (let p = 1; p <= pages; p += 1) {
    const start = (p - 1) * PAGE_SIZE + 1;
    const end = p * PAGE_SIZE;
    const url = buildUrl('bike', key, { start, end });
    let call;
    try {
      call = await fetchPage(url, timeoutMs);
    } catch (err) {
      const reason = err.name === 'TimeoutError' ? `타임아웃 ${timeoutMs}ms — 실습실 망이면 8088 차단, 핫스팟·EC2 에서 실행` : err.message;
      fail(`페이지 ${p} (${start}~${end}) 호출 실패: ${reason}\n  URL ${redactKey(url, key)}`, 1);
      return;
    }
    const parsed = parseResponse('bike', call.body);
    if (!parsed.ok) {
      // 마지막 페이지를 넘어가면 INFO-200(데이터 없음)이 온다 — 대여소가 정확히 PAGE_SIZE 배수일 때
      if (parsed.code === 'INFO-200' && collected.length > 0) {
        console.log(`  페이지 ${p}  ${start}~${end}  데이터 없음 (${parsed.code}) — 끝`);
        break;
      }
      fail(`페이지 ${p} 응답 오류: HTTP ${call.status} · ${parsed.code ?? '-'} ${parsed.message ?? ''}`, 1);
      return;
    }
    total = parsed.total ?? total;
    console.log(`  페이지 ${p}  ${start}~${end}  HTTP ${call.status} · ${call.elapsedMs} ms · ${call.bytes.toLocaleString()} bytes · ${parsed.rows.length}행 · total ${total ?? '-'}`);
    collected.push(parsed.rows);
    if (parsed.rows.length < PAGE_SIZE) break;
  }

  const rows = mergePages(collected);
  if (total != null && rows.length !== Number(total)) {
    console.warn(`  경고: 합친 행 ${rows.length} ≠ list_total_count ${total}. 페이지 수(--pages)가 모자라거나 호출 사이에 목록이 바뀌었다`);
  }
  const csv = toCsv(SNAPSHOT_FIELDS, rows);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, csv, 'utf8');
  console.log(`대여소 ${rows.length.toLocaleString()}개 · ${SNAPSHOT_FIELDS.length}열 → ${out}`);
  console.log(`호출 시각 ${now.toISOString()} (UTC) · 호출 ${collected.length}회`);
}

main().catch((err) => fail(`스냅샷 실패: ${err.message}`, 1));
