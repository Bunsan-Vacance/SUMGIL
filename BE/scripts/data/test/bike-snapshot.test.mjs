// bikeList 응답 여러 페이지 → 대여소 마스터 스냅샷 행 규칙을 고정하는 테스트.
// 원천 값은 그대로 두고(이름 접두어 파싱은 Java 로더가 한다) 페이지 합치기와 중복 검사만 한다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { SNAPSHOT_FIELDS, mergePages } from '../lib/bike-snapshot.mjs';

const row = (id, name) => ({
  rackTotCnt: '15',
  stationName: name,
  parkingBikeTotCnt: '5',
  shared: '33',
  stationLatitude: '37.55564880',
  stationLongitude: '126.91062927',
  stationId: id,
});

describe('SNAPSHOT_FIELDS', () => {
  test('API 필드명을 그대로 열 이름으로 쓴다 — stationId 가 첫 열', () => {
    assert.deepEqual(SNAPSHOT_FIELDS, [
      'stationId', 'stationName', 'stationLatitude', 'stationLongitude', 'rackTotCnt', 'parkingBikeTotCnt', 'shared',
    ]);
  });
});

describe('mergePages', () => {
  test('페이지 순서대로 이어 붙이고 필드 순서를 SNAPSHOT_FIELDS 로 맞춘다', () => {
    const got = mergePages([[row('ST-4', '102. 망원역 1번출구 앞')], [row('ST-5', '103. 망원역 2번출구 앞')]]);

    assert.equal(got.length, 2);
    assert.deepEqual(got[0], ['ST-4', '102. 망원역 1번출구 앞', '37.55564880', '126.91062927', '15', '5', '33']);
    assert.equal(got[1][0], 'ST-5');
  });

  test('같은 stationId 가 두 번 나오면 오류다 — 페이지 경계가 겹친 호출', () => {
    assert.throws(() => mergePages([[row('ST-4', 'a')], [row('ST-4', 'a')]]), /중복/);
  });

  test('stationId 가 없는 행은 오류다', () => {
    assert.throws(() => mergePages([[{ stationName: 'x' }]]), /stationId/);
  });

  test('없는 필드는 빈 칸으로 둔다 — 값을 만들어 넣지 않는다', () => {
    const got = mergePages([[{ stationId: 'ST-9', stationName: 'n' }]]);
    assert.deepEqual(got[0], ['ST-9', 'n', '', '', '', '', '']);
  });
});
