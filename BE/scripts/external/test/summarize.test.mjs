// 응답 요약(필드 목록·시각 필드 후보·샘플 축약)과 응답 시간 통계 규칙을 고정하는 테스트.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { fieldNames, stats, timeFieldCandidates, trimSample } from '../lib/summarize.mjs';

describe('fieldNames', () => {
  test('모든 행의 키를 합쳐 정렬해 돌려준다', () => {
    assert.deepEqual(fieldNames([{ b: 1, a: 1 }, { c: 1, a: 2 }]), ['a', 'b', 'c']);
  });

  test('행이 없으면 빈 배열이다', () => {
    assert.deepEqual(fieldNames([]), []);
  });
});

describe('timeFieldCandidates', () => {
  test('생성·수신 시각으로 보이는 필드만 샘플 값과 함께 고른다', () => {
    const rows = [
      {
        recptnDt: '2026-09-08 09:00:00',
        barvlDt: '120',
        stId: '1',
        rackTotCnt: '10',
        mkTm: '2026-09-08 09:00:00.0',
        collected_at: 'x',
      },
    ];
    const got = timeFieldCandidates(rows);
    assert.deepEqual(
      got.map((c) => c.field),
      ['barvlDt', 'collected_at', 'mkTm', 'recptnDt'],
    );
    assert.equal(got.find((c) => c.field === 'recptnDt').sample, '2026-09-08 09:00:00');
  });

  test('후보가 없으면 빈 배열이다', () => {
    assert.deepEqual(timeFieldCandidates([{ stationId: 'ST-1', shared: '0' }]), []);
  });
});

describe('trimSample', () => {
  test('행을 앞에서 n개만 남기고 _probe 메타에 원본·보존 건수를 적는다', () => {
    const rows = Array.from({ length: 30 }, (_, i) => ({ i }));
    const body = { rentBikeStatus: { RESULT: { CODE: 'INFO-000' }, row: rows } };

    const out = trimSample('bike', body, 20);

    assert.equal(out.rentBikeStatus.row.length, 20);
    assert.equal(out._probe.source, 'bike');
    assert.equal(out._probe.originalRowCount, 30);
    assert.equal(out._probe.keptRowCount, 20);
    // 입력은 바뀌지 않는다
    assert.equal(body.rentBikeStatus.row.length, 30);
    assert.equal(body._probe, undefined);
  });

  test('행이 n개 이하이면 그대로 두되 메타는 기록한다', () => {
    const body = { errorMessage: { code: 'INFO-000' }, realtimeArrivalList: [{ a: 1 }] };
    const out = trimSample('subway', body, 20);
    assert.equal(out.realtimeArrivalList.length, 1);
    assert.equal(out._probe.originalRowCount, 1);
    assert.equal(out._probe.keptRowCount, 1);
  });

  test('bus는 msgBody.itemList를 자른다', () => {
    const body = { msgHeader: { headerCd: '0' }, msgBody: { itemList: [{ a: 1 }, { a: 2 }, { a: 3 }] } };
    assert.equal(trimSample('bus', body, 2).msgBody.itemList.length, 2);
  });
});

describe('stats', () => {
  test('중앙값과 p95(최근접 순위)를 계산한다', () => {
    const s = stats([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]);
    assert.equal(s.n, 10);
    assert.equal(s.min, 100);
    assert.equal(s.max, 1000);
    assert.equal(s.median, 550);
    assert.equal(s.p95, 1000);
  });

  test('순서가 섞여 있어도 결과는 같다', () => {
    const s = stats([300, 100, 200]);
    assert.equal(s.median, 200);
    assert.equal(s.p95, 300);
  });

  test('값이 하나면 모든 통계가 그 값이다', () => {
    const s = stats([42]);
    assert.equal(s.min, 42);
    assert.equal(s.median, 42);
    assert.equal(s.p95, 42);
  });

  test('값이 없으면 n이 0이고 나머지는 null이다', () => {
    const s = stats([]);
    assert.equal(s.n, 0);
    assert.equal(s.median, null);
    assert.equal(s.p95, null);
  });
});
