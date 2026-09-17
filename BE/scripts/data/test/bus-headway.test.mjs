// 버스 배차간격 수집의 순수 로직: 정류소 집합 덮기 · 응답→행 · 노선 단위 병합.
// 실행: node --test "BE/scripts/data/test/bus-headway.test.mjs"
//
// 도착정보(15000314)는 정류소 단위 호출이라 노선당 1콜(718)이 아니라 정류소를 골라 덮는다.
// 응답 한 건에 그 정류소를 지나는 노선이 여럿 딸려 오므로, 노선을 모두 덮는 최소 정류소 집합을 그리디로 고른다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { HEADWAY_FIELDS, coverStops, mergeByRoute, toHeadwayRows } from '../lib/bus-headway.mjs';

/** 노선-정류소 표 한 행 (원천 CSV 의 ROUTE_ID · NODE_ID 만 쓴다) */
const pair = (routeId, stopId) => ({ routeId, stopId });

/** 도착정보 응답의 노선 한 건 (필요한 필드만) */
const item = (busRouteId, rtNm, term, extra = {}) => ({
  busRouteId,
  rtNm,
  term: String(term),
  firstTm: '20260908040100',
  lastTm: '20260908225100',
  routeType: '3',
  mkTm: '2026-09-08 11:10:10.0',
  ...extra,
});

describe('coverStops', () => {
  test('노선을 전부 덮는 정류소를 고른다', () => {
    const { stops, uncovered } = coverStops([
      pair('R1', 'S1'), pair('R2', 'S1'),
      pair('R3', 'S2'),
    ]);

    assert.deepEqual(uncovered, []);
    assert.deepEqual([...stops].sort(), ['S1', 'S2']);
  });

  test('한 정류소가 여러 노선을 덮으면 정류소 수가 노선 수보다 적다', () => {
    const pairs = [];
    for (const r of ['R1', 'R2', 'R3', 'R4', 'R5']) pairs.push(pair(r, 'S1'));

    const { stops } = coverStops(pairs);

    assert.equal(stops.length, 1);
    assert.deepEqual(stops, ['S1']);
  });

  test('가장 많이 덮는 정류소를 먼저 고른다', () => {
    const { stops } = coverStops([
      pair('R1', 'BIG'), pair('R2', 'BIG'), pair('R3', 'BIG'),
      pair('R1', 'SMALL'),
      pair('R4', 'OTHER'),
    ]);

    assert.equal(stops[0], 'BIG');
    assert.deepEqual([...stops].sort(), ['BIG', 'OTHER']);
  });

  test('같은 입력이면 같은 결과다 — 동점은 정류소 ID 순으로 가른다', () => {
    const pairs = [pair('R1', 'S2'), pair('R1', 'S1'), pair('R2', 'S2'), pair('R2', 'S1')];

    const a = coverStops(pairs);
    const b = coverStops([...pairs].reverse());

    assert.deepEqual(a.stops, b.stops);
    assert.deepEqual(a.stops, ['S1']);
  });

  test('정류소가 없는 노선은 덮지 못한 노선으로 돌려준다', () => {
    const { stops, uncovered } = coverStops([pair('R1', 'S1'), pair('R2', '')]);

    assert.deepEqual(stops, ['S1']);
    assert.deepEqual(uncovered, ['R2']);
  });

  test('빈 입력이면 둘 다 빈 배열이다', () => {
    assert.deepEqual(coverStops([]), { stops: [], uncovered: [] });
  });
});

describe('HEADWAY_FIELDS', () => {
  test('열 순서를 고정한다 — 첫 열이 busRouteId 다', () => {
    assert.deepEqual(HEADWAY_FIELDS, [
      'busRouteId', 'rtNm', 'term', 'firstTm', 'lastTm', 'routeType', 'observedStId', 'mkTm',
    ]);
  });
});

describe('toHeadwayRows', () => {
  test('응답 노선을 열 순서대로 문자열 행으로 만든다', () => {
    const got = toHeadwayRows([item('100100587', '705', 16)], '111000012');

    assert.equal(got.length, 1);
    assert.deepEqual(got[0], [
      '100100587', '705', '16', '20260908040100', '20260908225100', '3', '111000012', '2026-09-08 11:10:10.0',
    ]);
  });

  test('term 0 을 비우지 않고 그대로 둔다 — 0 과 결측은 다르다', () => {
    const [row] = toHeadwayRows([item('100000028', '새벽A741', 0)], 'S1');

    assert.equal(row[HEADWAY_FIELDS.indexOf('term')], '0');
  });

  test('없는 필드는 빈 문자열이다 — 값을 만들어 넣지 않는다', () => {
    const [row] = toHeadwayRows([{ busRouteId: 'R1', rtNm: '1', term: '5' }], 'S1');

    assert.equal(row[HEADWAY_FIELDS.indexOf('firstTm')], '');
    assert.equal(row[HEADWAY_FIELDS.indexOf('mkTm')], '');
  });

  test('busRouteId 가 없는 행은 오류다 — 노선을 식별할 수 없다', () => {
    assert.throws(() => toHeadwayRows([{ rtNm: '705', term: '16' }], 'S1'), /busRouteId/);
  });

  test('관측한 정류소를 행에 남긴다 — 어디서 받은 값인지 추적한다', () => {
    const [row] = toHeadwayRows([item('R1', '1', 5)], '111000012');

    assert.equal(row[HEADWAY_FIELDS.indexOf('observedStId')], '111000012');
  });
});

describe('mergeByRoute', () => {
  const row = (routeId, term, stId = 'S1') => toHeadwayRows([item(routeId, 'N', term)], stId)[0];

  test('같은 노선이 여러 정류소에서 오면 한 행으로 합친다', () => {
    const { rows, conflicts } = mergeByRoute([row('R1', 10, 'S1'), row('R1', 10, 'S2')]);

    assert.equal(rows.length, 1);
    assert.deepEqual(conflicts, []);
  });

  test('한쪽이 0 이면 0 이 아닌 값을 쓴다 — 0 은 운행 중이 아니라는 뜻이다', () => {
    const { rows } = mergeByRoute([row('R1', 0, 'S1'), row('R1', 12, 'S2')]);

    assert.equal(rows.length, 1);
    assert.equal(rows[0][HEADWAY_FIELDS.indexOf('term')], '12');
    assert.equal(rows[0][HEADWAY_FIELDS.indexOf('observedStId')], 'S2');
  });

  test('둘 다 0 이 아닌데 값이 다르면 충돌로 남기고 먼저 본 값을 쓴다', () => {
    const { rows, conflicts } = mergeByRoute([row('R1', 10, 'S1'), row('R1', 15, 'S2')]);

    assert.equal(rows.length, 1);
    assert.equal(rows[0][HEADWAY_FIELDS.indexOf('term')], '10');
    assert.equal(conflicts.length, 1);
    assert.match(conflicts[0], /R1/);
    assert.match(conflicts[0], /10/);
    assert.match(conflicts[0], /15/);
  });

  test('둘 다 0 이면 0 을 유지한다', () => {
    const { rows, conflicts } = mergeByRoute([row('R1', 0, 'S1'), row('R1', 0, 'S2')]);

    assert.equal(rows[0][HEADWAY_FIELDS.indexOf('term')], '0');
    assert.deepEqual(conflicts, []);
  });

  test('노선 ID 순으로 정렬해 돌려준다 — 같은 입력이면 같은 CSV 다', () => {
    const { rows } = mergeByRoute([row('R2', 5), row('R1', 5)]);

    assert.deepEqual(rows.map((r) => r[0]), ['R1', 'R2']);
  });

  test('빈 입력이면 빈 결과다', () => {
    assert.deepEqual(mergeByRoute([]), { rows: [], conflicts: [] });
  });
});
