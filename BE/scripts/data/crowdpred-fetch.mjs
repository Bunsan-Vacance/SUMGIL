#!/usr/bin/env node
// AI EC2 의 혼잡도 예측 산출물 중 최신 CSV 와 사이드카를 로컬로 내려받는다 (S15P21A104-305).
//
// 배치(AI/DATA_ENGINE 의 crowd-batch-predict.timer)가 매일 09:30 KST 에 오늘·내일 2일치를 만든다:
//   <원격 저장소>/AI/data/CROWD/serving/predictions_<YYYY-MM-DD>_<HHMMSS>.csv (+ .meta.json)
// 로더는 API 를 부르지 않고 이 파일만 읽는다. 받는 것과 읽는 것을 나눠 두면 적재가 망 상태에 매이지 않는다.
//
// ⚠️ 2026-09-21 기준 서버에 배치가 아직 배포되지 않았다 — 폴더 자체가 없어 --list 가 실패한다.
//    AI 통지 07 C-5 회신 대기 중이며, 그전까지는 받은 파일을 직접 AI/data/CROWD/serving/ 에 두고 적재한다.
//
// 사용:
//   node BE/scripts/data/crowdpred-fetch.mjs                      # 최신 CSV + 사이드카를 AI/data/CROWD/serving/ 로
//   node BE/scripts/data/crowdpred-fetch.mjs --list               # 원격 목록만 보고 받지 않는다
//   node BE/scripts/data/crowdpred-fetch.mjs --out <폴더> --host <호스트> --remote-dir <경로> --pem <키>
//
// 접속은 ssh/scp 를 그대로 쓴다. 키는 기본이 바탕화면 pem 이며 저장소에 넣지 않는다(.gitignore).
// 받은 파일도 AI/data/** 라 추적되지 않는다 — 하루치 2.9 MB 이고 배치가 매일 다시 만든다.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { latestArtifact, siblingMeta } from './lib/crowdpred-fetch.mjs';

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
    fail(`원격 목록을 읽지 못했습니다: ${err.message}\n`
      + `  폴더가 없다면 AI 배치(crowd-batch-predict.timer)가 아직 서버에 배포되지 않은 것입니다 (통지 07 C-5).`);
    return;
  }

  const latest = latestArtifact(names);
  if (opt.list) {
    names.forEach((n) => console.log(`  ${n}${n === latest ? '   ← 최신' : ''}`));
    return;
  }
  if (latest === null) {
    fail(`혼잡도 예측 산출물이 없습니다: ${remoteDir} (predictions_<날짜>_<시각>.csv)`);
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
  // 사이드카는 선택이 아니다 — generated_at 이 NOT NULL 열이라 없으면 로더가 멈춘다.
  try {
    scp(opt.pem, opt.host, `${remoteDir}/${siblingMeta(latest)}`, opt.out);
  } catch (err) {
    fail(`사이드카 meta 를 받지 못했습니다: ${siblingMeta(latest)} — generated_at 이 없으면 적재할 수 없습니다.\n  ${err.message}`);
    return;
  }

  console.log(`  받음  ${target} (${statSync(target).size.toLocaleString()} bytes)`);
  console.log(`\n적재: cd BE && SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=crowdpred'`);
}

main();
