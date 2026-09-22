// 예측 적재 CronJob 매니페스트 계약 (S15P21A104-307).
// kustomize 로 실제 렌더링한 결과를 본다 — 파일을 직접 읽으면 kustomization 에 등록을
// 빠뜨려도 통과하기 때문이다(배포되는 것은 렌더링 결과다).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const PROD = path.join(REPO, 'BE/k8s/prod');
const SECRET = path.join(PROD, 'be-secret.env');
const EXAMPLE = path.join(PROD, 'be-secret.env.example');

/** secretGenerator 가 env 파일을 요구한다. CI(manifests.yml)와 같은 방식으로 더미를 만든다. */
function render() {
  let made = false;
  if (!fs.existsSync(SECRET)) {
    const keys = fs.readFileSync(EXAMPLE, 'utf8')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
      .map((l) => l.split('=')[0]);
    fs.writeFileSync(SECRET, keys.map((k) => `${k}=dummy`).join('\n') + '\n');
    made = true;
  }
  try {
    return execFileSync('kubectl', ['kustomize', PROD], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  } finally {
    if (made) fs.rmSync(SECRET, { force: true });
  }
}

/** 렌더링 결과에서 CronJob 문서 하나만 떼어 낸다. */
function cronJobDoc(rendered) {
  const docs = rendered.split(/^---$/m);
  const found = docs.filter((d) => /^kind:\s*CronJob\s*$/m.test(d));
  assert.equal(found.length, 1, `CronJob 문서가 정확히 1개여야 한다 (실제 ${found.length}개)`);
  return found[0];
}

test('307-C1: 적재 CronJob 이 kustomize 결과에 포함된다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /name:\s*be-load-pred\b/, 'CronJob 이름이 be-load-pred 여야 한다');
});

test('307-C2: 매일 01:00 UTC(10:00 KST)에 돈다 — 두 AI 배치 뒤', () => {
  const doc = cronJobDoc(render());
  // 따옴표 유무는 kustomize 의 직렬화 방식이라 계약이 아니다 — 값만 본다.
  assert.match(doc, /schedule:\s*"?0 1 \* \* \*"?/, '일정이 0 1 * * * (01:00 UTC) 여야 한다');
});

test('307-C3: AI 산출물이 있는 워커 노드에 고정된다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /kubernetes\.io\/hostname:\s*ip-172-26-10-6/, '워커 노드에 nodeSelector 로 고정해야 한다');
});

test('307-C4: AI 폴더를 읽기 전용으로 마운트한다 — 산출물을 건드리지 않는다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /path:\s*\/home\/ubuntu\/Soomgil-INFRA-ai-data-monitoring\/AI\/data/, 'hostPath 가 AI data 폴더여야 한다');
  assert.match(doc, /readOnly:\s*true/, '읽기 전용이어야 한다');
});

test('307-C5: 따릉이·혼잡도 두 예측을 함께 적재한다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /--load\.sources=bikepred,crowdpred/, '두 소스를 모두 지정해야 한다');
});

test('307-C6: load 프로파일로 덮어 웹서버 없이 적재만 하고 끝난다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /name:\s*SPRING_PROFILES_ACTIVE\s*\n\s*value:\s*load/, 'be-config 의 prod 프로파일을 load 로 덮어야 한다');
});

test('307-C7: 읽을 경로를 마운트 지점으로 덮는다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /name:\s*LOAD_BIKEPRED_CSVPATH/, '따릉이 경로를 덮어야 한다');
  assert.match(doc, /name:\s*LOAD_CROWDPRED_PATH/, '혼잡도 경로를 덮어야 한다');
});

test('307-C8: 겹쳐 돌지 않고, 실패 기록이 남는다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /concurrencyPolicy:\s*Forbid/, '앞 실행이 안 끝났으면 건너뛴다');
  assert.match(doc, /failedJobsHistoryLimit:\s*[1-9]/, '실패 기록을 남겨야 원인을 볼 수 있다');
});

test('307-C9: DB 접속을 기존 설정에서 받는다 — 값을 새로 복제하지 않는다', () => {
  const doc = cronJobDoc(render());
  assert.match(doc, /configMapRef:\s*\n\s*name:\s*be-config/, 'be-config 를 물어야 한다');
  assert.match(doc, /secretRef:\s*\n\s*name:\s*data-secret/, 'data-secret 을 물어야 한다');
});
