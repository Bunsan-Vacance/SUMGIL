#!/usr/bin/env node
// AI EC2 의 혼잡도 예측 산출물(CSV + 사이드카)을 로컬로 내려받는다 (S15P21A104-305 · 304).
//
// 배치(AI 데이터 엔진 저장소의 crowd-batch-predict.timer)가 워커 노드 j15a104a 에서 매일 09:30 KST
// (+랜덤 지연 ≤5분)에 오늘·내일 2일치를 만든다:
//   <원격 저장소>/AI/data/CROWD/serving/predictions_<YYYY-MM-DD>_<HHMMSS>.csv (+ .meta.json)
// 로더는 API 를 부르지 않고 이 파일만 읽는다. 받는 것과 읽는 것을 나눠 두면 적재가 망 상태에 매이지 않는다.
//
// 이 스크립트는 "최신 하나" 를 고르지 않는다 — 대상 날짜가 기준일(기본 오늘 KST) 이후인 산출물을 전부
// 받아 폴더를 동기화한다. 같은 날짜의 최신 회차 판정은 자바 로더(CsvCongestionPredSource) 가 사이드카
// generated_at 으로 한다(304). 파일명 _HHMMSS 는 UTC 시각만 있고 생성 날짜가 없어 이름으로는 못 가른다.
//
// 사용:
//   node BE/scripts/data/crowdpred-fetch.mjs                      # 오늘 이후 CSV + 사이드카 전부 → AI/data/CROWD/serving/
//   node BE/scripts/data/crowdpred-fetch.mjs --list               # 원격 목록만 보고 받지 않는다
//   node BE/scripts/data/crowdpred-fetch.mjs --since 2026-09-20   # 기준일 지정
//   node BE/scripts/data/crowdpred-fetch.mjs --all                # 날짜 제한 없이 전부
//   node BE/scripts/data/crowdpred-fetch.mjs --out <폴더> --host <호스트> --remote-dir <경로> --pem <키>
//
// 접속은 ssh/scp 를 그대로 쓴다. 키는 기본이 바탕화면 pem 이며 저장소에 넣지 않는다(.gitignore).
// 받은 파일도 AI/data/** 라 추적되지 않는다 — 하루치 2.9 MB 이고 배치가 매일 다시 만든다.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { ARTIFACT_PATTERN, artifactsSince, siblingMeta } from './lib/crowdpred-fetch.mjs';

const BE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const REPO_ROOT = resolve(BE_ROOT, '..');

const DEFAULTS = {
  host: 'ubuntu@j15a104a.p.ssafy.io',
  remoteDir: '/home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI/data/CROWD/serving',
  pem: 'C:/Users/SSAFY/Desktop/J15A104T.pem',
  out: join(REPO_ROOT, 'AI', 'data', 'CROWD', 'serving'),
};

const USAGE = `사용법: node BE/scripts/data/crowdpred-fetch.mjs [옵션]

옵션
  --list              원격 산출물 목록만 출력하고 받지 않는다 (받을 것에 ← 표시)
  --since <날짜>      이 날짜(YYYY-MM-DD) 이후 대상 날짜만 받는다 (기본 오늘, Asia/Seoul)
  --all               날짜 제한 없이 전부 받는다
  --out <폴더>        받을 위치 (기본 ${DEFAULTS.out})
  --host <user@host>  AI 배치가 도는 노드 (기본 ${DEFAULTS.host})
  --remote-dir <경로> 원격 산출물 폴더 (기본 ${DEFAULTS.remoteDir})
  --pem <파일>        SSH 키 (기본 ${DEFAULTS.pem})
  --force             같은 이름이 이미 있어도 다시 받는다
`;

function fail(message, code = 2) {
  console.error(message);
  process.exit(code);
}

function ssh(pem, host, command) {
  return execFileSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-i', pem, host, command],
    { encoding: 'utf8' });
}

function scp(pem, host, remotePath, outDir) {
  execFileSync('scp', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', '-i', pem,
    `${host}:${remotePath}`, outDir], { stdio: 'inherit' });
}

/** 오늘 날짜(YYYY-MM-DD, Asia/Seoul). 조회가 서울 기준 오늘 날짜로 하므로 기준일도 같은 시간대다. */
function todayInSeoul() {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date());
}

function main() {
  const { values: opt } = parseArgs({
    options: {
      list: { type: 'boolean', default: false },
      since: { type: 'string' },
      all: { type: 'boolean', default: false },
      out: { type: 'string', default: DEFAULTS.out },
      host: { type: 'string', default: DEFAULTS.host },
      'remote-dir': { type: 'string', default: DEFAULTS.remoteDir },
      pem: { type: 'string', default: DEFAULTS.pem },
      force: { type: 'boolean', default: false },
      help: { type: 'boolean', default: false },
    },
  });
  if (opt.help) {
    console.log(USAGE);
    return;
  }
  if (!existsSync(opt.pem)) {
    fail(`SSH 키가 없습니다: ${opt.pem} — --pem 으로 지정하세요.`);
  }
  if (opt.since !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(opt.since)) {
    fail(`--since 는 YYYY-MM-DD 형식입니다: ${opt.since}`);
  }
  const since = opt.all ? undefined : (opt.since ?? todayInSeoul());

  const remoteDir = opt['remote-dir'];
  console.log(`▶ ${opt.host}:${remoteDir}`);
  let names;
  try {
    names = ssh(opt.pem, opt.host, `ls -1 ${remoteDir}`).split(/\r?\n/).filter((n) => n.trim() !== '');
  } catch (err) {
    fail(`원격 목록을 읽지 못했습니다: ${err.message}\n`
      + `  폴더가 없다면 AI 배치(crowd-batch-predict.timer)가 그 노드에 없는 것입니다 — --host 를 확인하세요.`);
    return;
  }

  const wanted = artifactsSince(names, since);
  const sinceLabel = since ?? '(없음 · 전부)';
  if (opt.list) {
    const wantedSet = new Set(wanted);
    names.forEach((n) => console.log(`  ${n}${wantedSet.has(n) ? '   ← 받음' : ''}`));
    console.log(`\n기준일 ${sinceLabel} · 받을 산출물 ${wanted.length}개`);
    return;
  }
  if (wanted.length === 0) {
    const anyArtifact = names.some((n) => ARTIFACT_PATTERN.test(n));
    fail(`받을 혼잡도 예측 산출물이 없습니다: ${remoteDir} (predictions_<날짜>_<시각>.csv, 기준일 ${sinceLabel})`
      + (anyArtifact ? '\n  산출물은 있지만 전부 기준일 이전입니다 — --since 로 앞당기거나 --all 로 전부 받으세요.' : ''));
    return;
  }

  mkdirSync(opt.out, { recursive: true });
  console.log(`  기준일 ${sinceLabel} · 대상 ${wanted.length}개`);
  let fetched = 0;
  let skipped = 0;
  for (const name of wanted) {
    const target = join(opt.out, name);
    const metaTarget = join(opt.out, siblingMeta(name));
    // CSV 와 사이드카가 둘 다 있어야 건너뛴다 — 한쪽만 있으면 이전 수집이 끊긴 것이라 다시 받는다.
    if (existsSync(target) && existsSync(metaTarget) && !opt.force) {
      console.log(`  이미 있음 · 건너뜀  ${name} (${statSync(target).size.toLocaleString()} bytes)`);
      skipped += 1;
      continue;
    }
    scp(opt.pem, opt.host, `${remoteDir}/${name}`, opt.out);
    // 사이드카는 선택이 아니다 — generated_at 이 NOT NULL 열이라 없으면 로더가 멈춘다.
    try {
      scp(opt.pem, opt.host, `${remoteDir}/${siblingMeta(name)}`, opt.out);
    } catch (err) {
      fail(`사이드카 meta 를 받지 못했습니다: ${siblingMeta(name)} — generated_at 이 없으면 적재할 수 없습니다.\n  ${err.message}`);
      return;
    }
    console.log(`  받음  ${target} (${statSync(target).size.toLocaleString()} bytes)`);
    fetched += 1;
  }

  console.log(`\n받음 ${fetched} · 건너뜀 ${skipped}${skipped > 0 ? ' — 다시 받으려면 --force' : ''}`);
  console.log(`적재: cd BE && SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=crowdpred'`);
}

main();
