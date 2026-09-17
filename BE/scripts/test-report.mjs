#!/usr/bin/env node
// Gradle 테스트 리포트(XML) 집계. 실패한 테스트 이름과 메시지를 정확히 짝지어 보여준다.
//
//   node BE/scripts/test-report.mjs              # BE/build/test-results/test 전체
//   node BE/scripts/test-report.mjs consume      # 클래스 이름에 consume 이 들어간 것만
//
// gradle 콘솔 출력은 실패 개수만 알려주고 어느 테스트인지 찾기 번거로워서 쓴다.
import { readdirSync, readFileSync, existsSync } from 'node:fs';

const DIR = 'BE/build/test-results/test';
const filter = process.argv[2] ?? '';

if (!existsSync(DIR)) {
  console.error(`리포트가 없다: ${DIR} — 먼저 ./gradlew test 를 돌린다`);
  process.exit(2);
}

function unescape(text) {
  return text
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'").replace(/&#10;/g, ' ').replace(/&#13;/g, '').replace(/&amp;/g, '&');
}

/** <testcase ...> 경계로 잘라서 읽는다 — 정규식 하나로 묶으면 실패가 옆 테스트에 붙는다. */
function testcases(xml) {
  const out = [];
  const parts = xml.split('<testcase ').slice(1);
  for (const part of parts) {
    const head = part.slice(0, part.indexOf('>') + 1);
    const body = part.slice(head.length);
    const end = body.indexOf('</testcase>');
    const inner = head.trimEnd().endsWith('/>') ? '' : body.slice(0, end < 0 ? body.length : end);
    const name = (head.match(/name="([^"]*)"/) || [])[1] ?? '?';
    const failure = inner.match(/<(failure|error)[^>]*message="([^"]*)"/);
    const skipped = /<skipped/.test(inner);
    out.push({ name: unescape(name), failed: Boolean(failure), skipped, message: failure ? unescape(failure[2]) : '' });
  }
  return out;
}

let tests = 0, failures = 0, skipped = 0, classes = 0;
const problems = [];

for (const file of readdirSync(DIR)) {
  if (!file.endsWith('.xml')) continue;
  const name = file.replace(/^TEST-/, '').replace(/\.xml$/, '');
  if (filter && !name.includes(filter)) continue;
  const xml = readFileSync(`${DIR}/${file}`, 'utf8');
  classes += 1;
  for (const tc of testcases(xml)) {
    tests += 1;
    if (tc.failed) {
      failures += 1;
      problems.push(`  ✖ ${name.split('.').pop()} › ${tc.name}\n     ${tc.message.slice(0, 300)}`);
    } else if (tc.skipped) {
      skipped += 1;
      problems.push(`  · (skip) ${name.split('.').pop()} › ${tc.name}`);
    }
  }
}

console.log(`클래스 ${classes} · 테스트 ${tests} · 실패 ${failures} · 스킵 ${skipped}`);
if (problems.length > 0) {
  console.log(problems.join('\n'));
} else {
  console.log('전부 통과, 스킵 없음');
}
process.exitCode = failures > 0 ? 1 : 0;
