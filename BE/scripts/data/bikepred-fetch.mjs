#!/usr/bin/env node
// AI EC2 의 재고 예측 산출물 중 최신 CSV 를 로컬로 내려받는다 (S15P21A104-172).
//
// 배치(AI/DATA_ENGINE 의 bike-avg-batch.timer)가 매일 03:00 KST 에 새 파일을 만든다:
//   <원격 저장소>/AI/data/BIKE/serving/bike_stock_pred_<YYYYMMDD>-<HHMMSS>.csv (+ .parquet, +.meta.json)
// 로더는 API 를 부르지 않고 이 파일만 읽는다. 받는 것과 읽는 것을 나눠 두면 적재가 망 상태에 매이지 않는다.
//
// 사용:
//   node BE/scripts/data/bikepred-fetch.mjs                      # 최신 CSV + meta.json 을 AI/data/BIKE/serving/ 로
//   node BE/scripts/data/bikepred-fetch.mjs --list               # 원격 목록만 보고 받지 않는다
//   node BE/scripts/data/bikepred-fetch.mjs --out <폴더> --host <호스트> --remote-dir <경로> --pem <키>
//
// 접속은 ssh/scp 를 그대로 쓴다. 키는 기본이 바탕화면 pem 이며 저장소에 넣지 않는다(.gitignore).
// 받은 파일도 AI/data/** 라 추적되지 않는다 — 29 MB 이고 배치가 매일 다시 만든다.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { latestArtifact, siblingMeta } from './lib/bikepred-fetch.mjs';

const BE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const REPO_ROOT = resolve(BE_ROOT, '..');

const DEFAULTS = {
  host: 'ubuntu@j15a104a.p.ssafy.io',
  remoteDir: '/home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI/data/BIKE/serving',
  pem: 'C:/Users/SSAFY/Desktop/J15A104T.pem',
  out: join(REPO_ROOT, 'AI', 'data', 'BIKE', 'serving'),
};

const USAGE = `사용법: node BE/scripts/data/bikepred-fetch.mjs [옵션]

옵션
  --list              원격 산출물 목록만 출력하고 받지 않는다
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

function main() {
  const { values: opt } = parseArgs({
    options: {
      list: { type: 'boolean', default: false },
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

  const remoteDir = opt['remote-dir'];
  console.log(`▶ ${opt.host}:${remoteDir}`);

  let names;
  try {
    names = ssh(opt.pem, opt.host, `ls -1 ${remoteDir}`).split(/\r?\n/).filter((n) => n.trim() !== '');
  } catch (err) {
    fail(`원격 목록을 읽지 못했습니다: ${err.message}`);
    return;
  }

  const latest = latestArtifact(names);
  if (opt.list) {
    names.forEach((n) => console.log(`  ${n}${n === latest ? '   ← 최신' : ''}`));
    return;
  }
  if (latest === null) {
    fail(`재고 예측 산출물이 없습니다: ${remoteDir} (bike_stock_pred_<시각>.csv)`);
    return;
  }

  mkdirSync(opt.out, { recursive: true });
  const target = join(opt.out, latest);
  if (existsSync(target) && !opt.force) {
    console.log(`  이미 있음 · 건너뜀  ${latest} (${statSync(target).size.toLocaleString()} bytes) — 다시 받으려면 --force`);
    return;
  }

  console.log(`  최신  ${latest}`);
  scp(opt.pem, opt.host, `${remoteDir}/${latest}`, opt.out);
  // meta.json 은 행 수 대조용이라 없어도 적재는 된다 (CsvBikeStockPredSource 가 경고만 낸다).
  try {
    scp(opt.pem, opt.host, `${remoteDir}/${siblingMeta(latest)}`, opt.out);
  } catch {
    console.log(`  meta.json 없음 · 건너뜀 (행 수 대조를 하지 않는다)`);
  }

  console.log(`  받음  ${target} (${statSync(target).size.toLocaleString()} bytes)`);
  console.log(`\n적재: cd BE && SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=bikepred'`);
}

main();
