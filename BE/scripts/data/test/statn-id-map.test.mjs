// 실시간 도착 API 의 statnId 를 우리 station_id 로 붙이는 규칙을 고정하는 테스트 (S15P21A104-171).
// 규칙: (subwayId, statnNm) 로 찾는다 — statnId 자체로는 못 찾는다(1호선이 다른 체계).
// 이름만으로도 안 된다(동명이역 신촌·양평). 반드시 노선 + 정규화된 이름 두 개를 함께 쓴다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { buildStatnIdMap, normalizeName, parseCodes } from '../lib/statn-id-map.mjs';

// station-ids.csv 의 실제 행 모양 (codes = "노선:역사코드" 를 세미콜론으로)
const ID_ROWS = [
  { station_id: '150', name: '서울', codes: '1001:0150;1004:0426;1065:A01;1063:1251' },
  { station_id: '222', name: '역삼', codes: '1002:0222' },
  { station_id: '240', name: '신촌', codes: '1002:0240' },
  { station_id: '1252', name: '신촌', codes: '1063:1252' },
  { station_id: '2523', name: '양평', codes: '1005:2523' },
  { station_id: '1217', name: '양평', codes: '1063:1217' },
  { station_id: '432', name: '총신대입구', codes: '1004:0432;1007:2738' },
  { station_id: '2611', name: '응암', codes: '1006:2611' },
];

const ALIAS_ROWS = [
  { 원천표기: '서울역', 정본표기: '서울' },
  { 원천표기: '이수', 정본표기: '총신대입구' },
  { 원천표기: '응암순환', 정본표기: '응암' },
];

function event(subwayId, statnNm, statnId) {
  return { subwayId, statnNm, statnId };
}

describe('parseCodes', () => {
  test('"노선:코드" 를 세미콜론으로 가른다', () => {
    assert.deepEqual(parseCodes('1002:0222'), [{ line_id: '1002', code: '0222' }]);
    assert.deepEqual(parseCodes('1001:0150;1004:0426'), [
      { line_id: '1001', code: '0150' },
      { line_id: '1004', code: '0426' },
    ]);
  });

  test('비어 있으면 빈 배열', () => {
    assert.deepEqual(parseCodes(''), []);
    assert.deepEqual(parseCodes(undefined), []);
  });
});

describe('normalizeName', () => {
  const aliases = new Map(ALIAS_ROWS.map((r) => [r.원천표기, r.정본표기]));

  test('별칭은 정본 표기로 바꾼다 — 서울역 → 서울', () => {
    assert.equal(normalizeName('서울역', aliases), '서울');
    assert.equal(normalizeName('이수', aliases), '총신대입구');
  });

  test('별칭에 없으면 그대로, 앞뒤 공백만 턴다', () => {
    assert.equal(normalizeName('역삼', aliases), '역삼');
    assert.equal(normalizeName('  역삼  ', aliases), '역삼');
  });

  // 실시간 API 는 부역명을 괄호로 붙여 준다 (우리 표에는 괄호가 붙은 이름이 하나도 없다 — 벗겨도 안전).
  test('끝에 붙은 괄호 부역명을 벗긴다 — 총신대입구(이수) → 총신대입구', () => {
    assert.equal(normalizeName('총신대입구(이수)', aliases), '총신대입구');
    assert.equal(normalizeName('천호(풍납토성)', aliases), '천호');
    assert.equal(normalizeName('남한산성입구(성남법원,검찰청)', aliases), '남한산성입구');
  });

  test('괄호 안이 노선명이어도 벗긴다 — 신촌(경의중앙선) → 신촌', () => {
    assert.equal(normalizeName('신촌(경의중앙선)', aliases), '신촌');
  });

  test('괄호를 먼저 벗기고 그 다음에 별칭을 본다 — 응암순환(상선) → 응암', () => {
    assert.equal(normalizeName('응암순환(상선)', aliases), '응암');
  });

  test('괄호가 이름 가운데 있으면 건드리지 않는다 — 끝에 붙은 것만 부역명이다', () => {
    assert.equal(normalizeName('가(나)다', aliases), '가(나)다');
  });
});

describe('buildStatnIdMap', () => {
  test('(노선, 이름) 으로 station_id 를 붙인다', () => {
    const { rows, unmapped } = buildStatnIdMap([event('1002', '역삼', '1002000222')], ID_ROWS, ALIAS_ROWS);

    assert.deepEqual(rows, [{ statn_id: '1002000222', station_id: '222', line_id: '1002', name: '역삼' }]);
    assert.deepEqual(unmapped, []);
  });

  test('1호선은 statnId 체계가 달라도 이름·노선으로 붙는다 — 서울역 1001000133 → 150', () => {
    const { rows, unmapped } = buildStatnIdMap([event('1001', '서울역', '1001000133')], ID_ROWS, ALIAS_ROWS);

    assert.deepEqual(rows, [{ statn_id: '1001000133', station_id: '150', line_id: '1001', name: '서울' }]);
    assert.deepEqual(unmapped, []);
  });

  test('동명이역은 노선으로 가른다 — 신촌 2호선 240 · 경의중앙 1252', () => {
    const { rows } = buildStatnIdMap(
      [event('1002', '신촌', '1002000240'), event('1063', '신촌', '1063080000')],
      ID_ROWS,
      ALIAS_ROWS
    );

    assert.deepEqual(
      rows.map((r) => [r.statn_id, r.station_id]),
      [
        ['1002000240', '240'],
        ['1063080000', '1252'],
      ]
    );
  });

  test('같은 역이 여러 회차에 와도 한 행만 남는다', () => {
    const { rows } = buildStatnIdMap(
      [event('1002', '역삼', '1002000222'), event('1002', '역삼', '1002000222')],
      ID_ROWS,
      ALIAS_ROWS
    );

    assert.equal(rows.length, 1);
  });

  test('표에 없는 역은 unmapped 로, 몇 번 나왔는지까지', () => {
    const { rows, unmapped } = buildStatnIdMap(
      [event('1002', '없는역', '1002009999'), event('1002', '없는역', '1002009999'), event('1002', '역삼', '1002000222')],
      ID_ROWS,
      ALIAS_ROWS
    );

    assert.equal(rows.length, 1, '붙은 것만 rows');
    assert.deepEqual(unmapped, [{ statn_id: '1002009999', line_id: '1002', name: '없는역', count: 2 }]);
  });

  test('이름은 표에 있어도 그 노선이 아니면 안 붙는다', () => {
    const { rows, unmapped } = buildStatnIdMap([event('1003', '역삼', '1003000222')], ID_ROWS, ALIAS_ROWS);

    assert.deepEqual(rows, []);
    assert.deepEqual(unmapped, [{ statn_id: '1003000222', line_id: '1003', name: '역삼', count: 1 }]);
  });

  test('괄호 부역명이 붙어 와도 station_id 를 찾는다 — 총신대입구(이수) 1004 → 432', () => {
    const { rows, unmapped } = buildStatnIdMap([event('1004', '총신대입구(이수)', '1004000432')], ID_ROWS, ALIAS_ROWS);

    assert.deepEqual(rows, [{ statn_id: '1004000432', station_id: '432', line_id: '1004', name: '총신대입구' }]);
    assert.deepEqual(unmapped, []);
  });

  test('unmapped 에도 정규화한 이름이 들어간다 — 원본 표기가 아니라', () => {
    const { unmapped } = buildStatnIdMap([event('1032', '서울', '1032000351')], ID_ROWS, ALIAS_ROWS);

    assert.deepEqual(unmapped, [{ statn_id: '1032000351', line_id: '1032', name: '서울', count: 1 }]);
  });

  test('결과는 statn_id 순으로 정렬된다 — 표가 커밋되면 diff 가 안정적이어야 한다', () => {
    const { rows } = buildStatnIdMap(
      [event('1002', '신촌', '1002000240'), event('1001', '서울역', '1001000133'), event('1002', '역삼', '1002000222')],
      ID_ROWS,
      ALIAS_ROWS
    );

    assert.deepEqual(
      rows.map((r) => r.statn_id),
      ['1001000133', '1002000222', '1002000240']
    );
  });
});
