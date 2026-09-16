// 역 ID 매핑 표(conf/station-ids.csv) 생성 규칙을 고정하는 테스트.
// station_id = 물리 역에 붙은 서울교통공사 노선별 역사코드 중 최솟값(앞의 0 제거). 코드가 없는 역은 9001부터 이름순 부여.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { buildStationIdTable, stationNumber } from '../lib/station-ids.mjs';

describe('stationNumber', () => {
  test('노선별 코드 중 가장 작은 번호, 앞의 0 은 뗀다 — 서울 0150·0426 → 150', () => {
    assert.equal(stationNumber(['0150', '0426']), '150');
    assert.equal(stationNumber(['0222']), '222');
    assert.equal(stationNumber(['4102', '2513']), '2513');
  });

  test('코드가 없으면 null', () => {
    assert.equal(stationNumber([]), null);
  });
});

describe('buildStationIdTable', () => {
  const rows = [
    { line: '1001', code: '0150', name: '서울' },
    { line: '1004', code: '0426', name: '서울' },
    { line: '1002', code: '0222', name: '강남' },
    { line: '1002', code: '0240', name: '신촌' },
  ];

  test('물리 역(정규화 이름)마다 한 행, codes 는 노선:코드를 세미콜론으로, source 는 timetable', () => {
    const table = buildStationIdTable(rows, []);

    assert.deepEqual(table.find((r) => r.name === '서울'), { station_id: '150', name: '서울', codes: '1001:0150;1004:0426', source: 'timetable' });
    assert.equal(table.find((r) => r.name === '강남').station_id, '222');
  });

  test('코드가 없는 역은 이름순으로 9001부터 부여하고 source 는 assigned, codes 에는 노선만("1063:") — 경의중앙·분당선 전용 역', () => {
    const table = buildStationIdTable(rows, [{ name: '한남', line: '1063' }, { name: '가천대', line: '1075' }, { name: '서빙고', line: '1063' }]);

    const assigned = table.filter((r) => r.source === 'assigned');
    assert.deepEqual(assigned.map((r) => [r.station_id, r.name, r.codes]), [['9001', '가천대', '1075:'], ['9002', '서빙고', '1063:'], ['9003', '한남', '1063:']]);
  });

  test('시각표에 있는 역이 추가 목록에도 있으면 시각표 코드를 쓴다(중복 행 없음)', () => {
    const table = buildStationIdTable(rows, [{ name: '서울', line: '1063' }]);

    assert.equal(table.filter((r) => r.name === '서울').length, 1);
    assert.equal(table.find((r) => r.name === '서울').station_id, '150');
  });

  test('station_id 가 겹치면 오류 — 코드가 유일하지 않은 원천은 표를 만들 수 없다', () => {
    assert.throws(() => buildStationIdTable([
      { line: '1001', code: '0150', name: '가' },
      { line: '1002', code: '0150', name: '나' },
    ], []), /겹/);
  });

  test('표는 station_id 숫자순으로 정렬된다', () => {
    const table = buildStationIdTable(rows, [{ name: '한남', line: '1063' }]);

    assert.deepEqual(table.map((r) => r.station_id), ['150', '222', '240', '9001']);
  });
});
