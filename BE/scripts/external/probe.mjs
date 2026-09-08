#!/usr/bin/env node
// 외부 데이터 소스 1회 호출 probe.
//
// 인증키가 동작하는지, 응답 코드·행 수·필드·생성시각 후보가 무엇인지, 응답 시간과 크기가 얼마인지 본다.
// 반복 폴링용이 아니다. --repeat 는 응답 시간 분포를 보기 위한 소량 반복이다 (호출 사이 1초 대기).
//
// 실행 (저장소 루트에서):
//   node BE/scripts/external/probe.mjs subway                                  # 전체 역 일괄 첫 페이지 (0~1000)
//   node BE/scripts/external/probe.mjs subway --start 1000 --end 2000          # 두 번째 페이지 (전체는 3회)
//   node BE/scripts/external/probe.mjs subway --key sample --station 서울      # 승인 전 샘플키 검증
//   node BE/scripts/external/probe.mjs bike --start 1 --end 1000 --save
//   node BE/scripts/external/probe.mjs bus --st-id 123000001 --save
//   node BE/scripts/external/probe.mjs subway --repeat 5 --jsonl .claude/perf/raw/probe.jsonl
//
// 인증키는 BE/.env (Git 제외) 에서 읽는다. 키 이름은 BE/.env.example 참고. 실행 환경변수가 .env 보다 우선한다.
import { execSync } from 'node:child_process';
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { loadDotenv } from './lib/env.mjs';
import { SOURCES, buildUrl, parseResponse, redactKey, resolveKey, spec } from './lib/sources.mjs';
import { fieldNames, stats, timeFieldCandidates, trimSample } from './lib/summarize.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const BE_ROOT = resolve(HERE, '..', '..');
const SAMPLES_DIR = resolve(BE_ROOT, 'docs', 'external', 'samples');

const USAGE = `사용법: node BE/scripts/external/probe.mjs <${Object.keys(SOURCES).join('|')}> [옵션]

옵션
  --key <키>        인증키 직접 지정 (.env 보다 우선). 지하철은 'sample' 로 서울역만 조회 가능
  --station <역명>  subway: 전체 일괄 대신 역명 조회 (--count 기본 5)
  --start/--end     페이지 범위. subway 일괄 기본 0~1000, bike 기본 1~1000 (둘 다 1회 최대 1000행)
  --st-id <ID>      bus: 정류소 ID (필수)
  --repeat <N>      N회 반복 호출해 응답 시간 분포를 본다 (기본 1, 호출 사이 1초 대기)
  --timeout <ms>    호출 타임아웃 (기본 10000)
  --save            정상 응답을 앞 --keep 행(기본 20)만 남겨 BE/docs/external/samples/ 에 저장
  --jsonl <파일>    호출마다 결과 1줄(JSON)을 덧붙인다 — 성능 기록 원본용
  --env <파일>      .env 경로 (기본 BE/.env)
`;

function fail(message, code = 2) {
  console.error(message);
  process.exit(code);
}

function gitCommit() {
  try {
    return execSync('git rev-parse --short HEAD', { cwd: BE_ROOT, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim();
  } catch {
    return null;
  }
}

async function callOnce(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = performance.now();
  try {
    const res = await fetch(url, { signal: controller.signal, headers: { accept: 'application/json' } });
    const text = await res.text();
    const elapsedMs = Math.round(performance.now() - started);
    let body = null;
    let parseError = null;
    try {
      body = JSON.parse(text);
    } catch (err) {
      parseError = err.message;
    }
    return { status: res.status, elapsedMs, bytes: Buffer.byteLength(text, 'utf8'), body, text, parseError };
  } finally {
    clearTimeout(timer);
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const { values: opt, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      key: { type: 'string' },
      station: { type: 'string' },
      count: { type: 'string' },
      start: { type: 'string' },
      end: { type: 'string' },
      'st-id': { type: 'string' },
      repeat: { type: 'string', default: '1' },
      timeout: { type: 'string', default: '10000' },
      keep: { type: 'string', default: '20' },
      save: { type: 'boolean', default: false },
      jsonl: { type: 'string' },
      env: { type: 'string', default: resolve(BE_ROOT, '.env') },
      help: { type: 'boolean', default: false },
    },
  });

  if (opt.help || positionals.length === 0) fail(USAGE, opt.help ? 0 : 2);
  const source = positionals[0];
  const { label } = spec(source);

  const env = { ...loadDotenv(opt.env), ...process.env };
  const key = resolveKey(source, env, opt.key);
  const url = buildUrl(source, key, {
    station: opt.station,
    count: opt.count ? Number(opt.count) : undefined,
    start: opt.start ? Number(opt.start) : undefined,
    end: opt.end ? Number(opt.end) : undefined,
    stId: opt['st-id'],
  });
  const safeUrl = redactKey(url, key);
  const repeat = Math.max(1, Number(opt.repeat) || 1);
  const timeoutMs = Number(opt.timeout) || 10000;
  const commit = gitCommit();

  console.log(`▶ ${source} — ${label}`);
  console.log(`  URL   ${safeUrl}`);
  console.log(`  curl  curl -sS -m ${Math.ceil(timeoutMs / 1000)} "${safeUrl}"   ({KEY} 를 실제 키로)`);
  console.log(`  반복  ${repeat}회 · 타임아웃 ${timeoutMs}ms · 커밋 ${commit ?? '-'}`);

  const results = [];
  for (let i = 1; i <= repeat; i += 1) {
    if (i > 1) await sleep(1000);
    let call;
    try {
      call = await callOnce(url, timeoutMs);
    } catch (err) {
      const reason = err.name === 'AbortError' ? `타임아웃 ${timeoutMs}ms` : err.message;
      console.log(`  #${i}  실패 · ${reason}`);
      results.push({ ok: false, status: null, code: null, rows: 0, total: null, elapsedMs: null, bytes: null });
      continue;
    }
    const parsed = call.parseError
      ? { ok: false, code: null, message: `JSON 파싱 실패: ${call.parseError}`, rows: [], total: null }
      : parseResponse(source, call.body);
    const line = [
      `#${i}`,
      `HTTP ${call.status}`,
      `${call.elapsedMs} ms`,
      `${call.bytes.toLocaleString()} bytes`,
      `code ${parsed.code ?? '-'}`,
      `rows ${parsed.rows.length}`,
      `total ${parsed.total ?? '-'}`,
      parsed.ok ? 'OK' : `FAIL ${parsed.message ?? ''}`,
    ];
    console.log(`  ${line.join(' · ')}`);
    if (call.parseError) console.log(`     응답 앞부분: ${call.text.slice(0, 200).replace(/\s+/g, ' ')}`);
    results.push({ ...parsed, status: call.status, elapsedMs: call.elapsedMs, bytes: call.bytes, body: call.body });
  }

  const okResults = results.filter((r) => r.ok);
  if (repeat > 1) {
    const t = stats(results.map((r) => r.elapsedMs).filter((v) => v != null));
    const b = stats(results.map((r) => r.bytes).filter((v) => v != null));
    console.log(`  응답시간(ms) n=${t.n} min ${t.min} median ${t.median} p95 ${t.p95} max ${t.max}`);
    console.log(`  크기(bytes)  n=${b.n} min ${b.min} median ${b.median} p95 ${b.p95} max ${b.max}`);
  }

  const last = okResults.at(-1);
  if (last) {
    console.log(`  필드(${fieldNames(last.rows).length}) ${fieldNames(last.rows).join(', ')}`);
    const times = timeFieldCandidates(last.rows);
    console.log(
      `  시각 후보 ${times.length ? times.map((c) => `${c.field}=${JSON.stringify(c.sample)}`).join(', ') : '없음 — 수신시각을 신선도 기준으로 써야 함'}`,
    );
  }

  if (opt.jsonl) {
    mkdirSync(dirname(resolve(opt.jsonl)), { recursive: true });
    for (const r of results) {
      const record = {
        ts: new Date().toISOString(),
        source,
        url: safeUrl,
        commit,
        status: r.status,
        ok: r.ok,
        code: r.code,
        rows: r.rows?.length ?? r.rows ?? 0,
        total: r.total,
        elapsedMs: r.elapsedMs,
        bytes: r.bytes,
      };
      appendFileSync(resolve(opt.jsonl), `${JSON.stringify(record)}\n`, 'utf8');
    }
    console.log(`  기록  ${opt.jsonl} (+${results.length}줄)`);
  }

  if (opt.save) {
    if (!last) {
      console.log('  저장  건너뜀 — 정상 응답이 없다');
    } else {
      const suffix = opt.station ? '-station' : opt['st-id'] ? `-${opt['st-id']}` : '';
      const path = resolve(SAMPLES_DIR, `${source}${suffix}.json`);
      mkdirSync(SAMPLES_DIR, { recursive: true });
      const sample = trimSample(source, last.body, Number(opt.keep) || 20);
      writeFileSync(path, `${JSON.stringify(sample, null, 2)}\n`, 'utf8');
      console.log(`  저장  ${path} (${sample._probe.keptRowCount}/${sample._probe.originalRowCount}행)`);
    }
  }

  process.exit(last ? 0 : 1);
}

main().catch((err) => fail(`오류: ${err.message}`, 1));
