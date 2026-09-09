// CSV 쓰기 규칙(RFC 4180 따옴표, LF) 을 고정하는 테스트. 로더의 CsvTable 이 같은 규칙으로 읽는다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { csvEscape, toCsv } from '../lib/csv.mjs';

describe('csvEscape', () => {
  test('쉼표·따옴표·줄바꿈이 없으면 그대로 둔다', () => {
    assert.equal(csvEscape('망원역 1번출구 앞'), '망원역 1번출구 앞');
  });

  test('쉼표가 있으면 따옴표로 감싼다 — 정류소명 18건이 해당', () => {
    assert.equal(csvEscape('구파발역,은평뉴타운'), '"구파발역,은평뉴타운"');
  });

  test('따옴표는 두 번 써서 이스케이프하고 전체를 감싼다', () => {
    assert.equal(csvEscape('12"인치'), '"12""인치"');
  });

  test('줄바꿈이 있으면 따옴표로 감싼다', () => {
    assert.equal(csvEscape('가\n나'), '"가\n나"');
  });

  test('null·undefined 는 빈 칸이다', () => {
    assert.equal(csvEscape(null), '');
    assert.equal(csvEscape(undefined), '');
  });
});

describe('toCsv', () => {
  test('헤더 한 줄 + 행, LF 줄바꿈, 마지막 줄바꿈 포함', () => {
    const got = toCsv(['id', 'name'], [['1', 'a'], ['2', 'b,c']]);
    assert.equal(got, 'id,name\n1,a\n2,"b,c"\n');
  });

  test('헤더보다 짧은 행은 빈 칸으로 채워 열 수를 맞춘다', () => {
    assert.equal(toCsv(['a', 'b', 'c'], [['1']]), 'a,b,c\n1,,\n');
  });

  test('헤더보다 긴 행은 오류다 — 열이 어긋난 파일을 조용히 넘기지 않는다', () => {
    assert.throws(() => toCsv(['a'], [['1', '2']]), /열 수/);
  });
});
