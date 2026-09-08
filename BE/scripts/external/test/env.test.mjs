// BE/.env 파일을 의존성 없이 읽는 파서의 규칙을 고정하는 테스트.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { loadDotenv, parseDotenv } from '../lib/env.mjs';

describe('loadDotenv', () => {
  test('파일이 있으면 파싱해 돌려준다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'probe-env-'));
    try {
      const path = join(dir, '.env');
      writeFileSync(path, 'A=1\n# 주석\nB="2"\n', 'utf8');
      assert.deepEqual(loadDotenv(path), { A: '1', B: '2' });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test('파일이 없으면 빈 객체다 (키는 --key 나 환경변수로도 올 수 있다)', () => {
    assert.deepEqual(loadDotenv(join(tmpdir(), 'probe-env-없는-디렉터리', '.env')), {});
  });
});

describe('parseDotenv', () => {
  test('KEY=VALUE 줄을 객체로 읽는다', () => {
    assert.deepEqual(parseDotenv('A=1\nB=two'), { A: '1', B: 'two' });
  });

  test('주석과 빈 줄은 무시한다', () => {
    assert.deepEqual(parseDotenv('# c\n\nA=1\n  # d\n'), { A: '1' });
  });

  test('양쪽 따옴표는 벗긴다', () => {
    assert.deepEqual(parseDotenv(`A="x y"\nB='z'`), { A: 'x y', B: 'z' });
  });

  test('값 안의 =는 보존한다 (공공데이터포털 디코딩 키에 =가 들어간다)', () => {
    assert.deepEqual(parseDotenv('K=abc==/+x'), { K: 'abc==/+x' });
  });

  test('앞뒤 공백과 CRLF를 정리한다', () => {
    assert.deepEqual(parseDotenv(' A = 1 \r\nB=2\r\n'), { A: '1', B: '2' });
  });

  test('빈 값은 빈 문자열로 둔다', () => {
    assert.deepEqual(parseDotenv('A=\nB=1'), { A: '', B: '1' });
  });

  test('=가 없는 줄은 무시한다', () => {
    assert.deepEqual(parseDotenv('garbage\nA=1'), { A: '1' });
  });
});
