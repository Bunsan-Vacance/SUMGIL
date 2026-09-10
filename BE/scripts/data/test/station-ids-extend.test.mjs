// 역 ID 표에 시각표 밖 노선의 역을 더하는 규칙(lib/station-ids-extend.mjs)을 고정하는 테스트.
// 기존 ID 는 바뀌지 않는다(임시 부여 → 표준 역번호 이관만 예외), 새 역은 표준데이터 역번호, 동명이역은 환승노선명·좌표로 갈라낸다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { compareIds, extendStationIdTable, lineIdsFromTransferNames, normalizeStation, pickStationNumber } from '../lib/station-ids-extend.mjs';

const std = (no, name, code, transfers, lat, lng) => ({ 역번호: no, 역사명: name, 노선번호: code, 환승노선명: transfers, 역위도: String(lat), 역경도: String(lng) });
const urban = (line, seq, name) => ({ 권역명: '수도권', 노선명: line, 순번: String(seq), 역명: name });

describe('normalizeStation', () => {
  test('괄호 부기와 끝의 "역"을 떼고 별칭을 적용한다 — 청량리역 → 청량리, 서울역(경의선) → 서울', () => {
    const aliases = new Map([['서울역', '서울']]);
    assert.equal(normalizeStation('청량리역', aliases), '청량리');
    assert.equal(normalizeStation('서울역(경의선)', aliases), '서울');
    assert.equal(normalizeStation('아신(아세아연합신학대)', aliases), '아신');
    assert.equal(normalizeStation('역삼', aliases), '역삼');
  });
});

describe('lineIdsFromTransferNames', () => {
  test('접두어가 붙거나 "선"이 빠진 표기를 line_id 로 — 모르는 토큰(GTX-A·김포도시철도)은 무시', () => {
    assert.deepEqual([...lineIdsFromTransferNames('수도권  광역철도 4호선+서울 도시철도 2호선')], ['1004', '1002']);
    assert.deepEqual([...lineIdsFromTransferNames('1호선, 경의중앙선, 분당선')], ['1001', '1063', '1075']);
    assert.deepEqual([...lineIdsFromTransferNames('일산선, 서해선, GTX-A')], ['1003', '1093']);
    assert.deepEqual([...lineIdsFromTransferNames('')], []);
  });
});

describe('pickStationNumber', () => {
  test('숫자 번호(코레일)를 우선하고 그중 가장 작은 값 — 판교 D011/1501 → 1501, 이매 1860/1502 → 1502', () => {
    assert.equal(pickStationNumber(['D011', '1501']), '1501');
    assert.equal(pickStationNumber(['1860', '1502']), '1502');
    assert.equal(pickStationNumber(['D004']), 'D004');
    assert.equal(pickStationNumber([null, '']), null);
  });
});

describe('compareIds', () => {
  test('숫자 ID 오름차순 뒤에 문자 ID 사전순', () => {
    assert.deepEqual(['D004', '1501', '150', 'A01'].sort(compareIds), ['150', '1501', 'A01', 'D004']);
  });
});

describe('extendStationIdTable', () => {
  const existing = [
    { station_id: '150', name: '서울', codes: '1001:0150;1004:0426', source: 'timetable' },
    { station_id: '240', name: '신촌', codes: '1002:0240', source: 'timetable' },
    { station_id: '430', name: '이촌', codes: '1004:0430', source: 'timetable' },
    { station_id: '1015', name: '회기', codes: '1001:1015', source: 'timetable' },
    { station_id: '1760', name: '신길온천', codes: '1004:1760', source: 'timetable' },
    { station_id: '9001', name: '가천대', codes: '1075:', source: 'assigned' },
    { station_id: '9002', name: '이매', codes: '1075:', source: 'assigned' },
    { station_id: '9003', name: '도라산', codes: '1063:', source: 'assigned' },
  ];
  const standard = [
    std('0150', '서울역', 'I4101', '수도권  광역철도 4호선+수도권 광역철도 경의중앙+수도권 광역철도 공항', 37.5546, 126.9707),
    std('A01', '서울', 'I28A1', '서울 도시철도 1호선+서울 도시철도 4호선+경의선', 37.5490, 126.9704),
    std('1251', '서울역(경의선)', 'I4108', '1호선, 4호선, 인천국제공항선, GTX-A', 37.5568, 126.9695),
    std('0240', '신촌(지하)', 'S1102', '', 37.5551, 126.9368),
    std('1252', '신촌역', 'I4108', '', 37.5599, 126.9426),
    std('0430', '이촌(국립중앙박물관)', 'I1104', '수도권  광역철도 경의중앙', 37.5292, 126.9680),
    std('1008', '이촌역', 'I4102', '수도권 광역철도 4호선', 37.5222, 126.9741),
    std('1015', '회기역', 'I4102', '경의중앙선, 경춘선', 37.5897, 127.0576),
    std('1851', '가천대역', 'I4105', '', 37.4487, 127.1265),
    std('1860', '이매역', 'I4105', '경강선', 37.3956, 127.1279),
    std('1502', '이매역', 'I41K5', '분당선', 37.3956, 127.1279),
    std('1501', '판교역', 'I41K5', '신분당선', 37.3948, 127.1111),
    std('D011', '판교', 'I11D1', '수도권 광역철도 신분당선', 37.3946, 127.1112),
    std('1014', '청량리역', 'I4108', '1호선, 경의중앙선, 분당선', 37.5801, 127.0464),
    std('999', '신촌역', 'S2601', '', 35.1, 129.0),
  ];
  const lines = [
    urban('경의중앙', 22, '서울역'), urban('경의중앙', 21, '신촌'), urban('경의중앙', 29, '이촌'), urban('경의중앙', 1, '도라산'),
    urban('경의중앙', 36, '회기'), urban('경춘', 2, '회기'),
    urban('수인분당', 48, '신길온천'),
    urban('공항', 1, '서울역'),
    urban('수인분당', 15, '가천대'), urban('수인분당', 19, '이매(성남아트센터)'),
    urban('경강', 1, '판교(판교테크노밸리)'), urban('경강', 2, '이매'),
    urban('신분당', 11, '판교'),
    { 권역명: '부산권', 노선명: '경의중앙', 순번: '1', 역명: '무시' },
  ];
  const aliases = new Map([['서울역', '서울']]);
  const extra = [{ name: '원종', lineId: '1093' }];
  const standardWithWonjong = [...standard, std('1981', '원종역', 'I41WS', '', 37.5241, 126.8048)];
  const { rows, report } = extendStationIdTable({ existing, standard: standardWithWonjong, urban: lines, extra, aliases });
  const byName = (name) => rows.filter((r) => r.name === name);

  test('표준데이터에 행이 없는 역이 기존 역과 이름이 같으면 같은 역으로 병합하고 보고한다 — 신길온천(수인분당) → 4호선 1760', () => {
    assert.deepEqual(byName('신길온천'), [{ station_id: '1760', name: '신길온천', codes: '1004:1760;1075:', source: 'timetable' }]);
    assert.deepEqual(report.mergedByNameOnly, [{ id: '1760', name: '신길온천', lineIds: ['1075'] }]);
  });

  test('전체노선 파일에 없는 역은 extra 로 넣는다 — 서해선 원종 1981', () => {
    assert.deepEqual(byName('원종'), [{ station_id: '1981', name: '원종', codes: '1093:1981', source: 'standard' }]);
  });

  test('기존 역에 새 노선이 붙는 환승역은 ID 유지, codes 에 노선:역번호 추가 — 서울 +1063:1251;1065:A01', () => {
    assert.deepEqual(byName('서울'), [{ station_id: '150', name: '서울', codes: '1001:0150;1004:0426;1063:1251;1065:A01', source: 'timetable' }]);
    assert.deepEqual(report.patched.find((p) => p.name === '서울'), { id: '150', name: '서울', added: ['1063:1251', '1065:A01'] });
  });

  test('1호선 코레일 구간 역은 시각표 코드가 곧 코레일 역번호 — 회기 1015 에 경의중앙·경춘 코드를 붙이고 새 행을 만들지 않는다', () => {
    assert.deepEqual(byName('회기'), [{ station_id: '1015', name: '회기', codes: '1001:1015;1063:1015;1067:1015', source: 'timetable' }]);
  });

  test('표준데이터 환승노선에 기존 노선이 있으면 좌표가 900 m 떨어져도 같은 역 — 이촌(4호선)·이촌(경의중앙)', () => {
    assert.deepEqual(byName('이촌'), [{ station_id: '430', name: '이촌', codes: '1004:0430;1063:1008', source: 'timetable' }]);
  });

  test('환승 표기도 없고 좌표도 500 m 넘게 떨어진 동명이역은 별개 행 — 신촌(경의중앙) 1252, 2호선 신촌 240 은 그대로', () => {
    assert.deepEqual(byName('신촌'), [
      { station_id: '240', name: '신촌', codes: '1002:0240', source: 'timetable' },
      { station_id: '1252', name: '신촌', codes: '1063:1252', source: 'standard' },
    ]);
    assert.deepEqual(report.separate, [{ id: '1252', name: '신촌', existing: ['240'] }]);
  });

  test('임시 부여 행은 표준데이터 역번호로 이관하고 source 는 standard — 가천대 9001 → 1851', () => {
    assert.deepEqual(byName('가천대'), [{ station_id: '1851', name: '가천대', codes: '1075:1851', source: 'standard' }]);
    assert.ok(report.migrated.some((m) => m.from === '9001' && m.to === '1851'));
  });

  test('두 새 노선이 같은 물리 역이면 한 행, 번호는 숫자 우선·최솟값 — 이매 9002 → 1502(1075:1860;1081:1502), 판교 → 1501(1077:D011;1081:1501)', () => {
    assert.deepEqual(byName('이매'), [{ station_id: '1502', name: '이매', codes: '1075:1860;1081:1502', source: 'standard' }]);
    assert.deepEqual(byName('판교'), [{ station_id: '1501', name: '판교', codes: '1077:D011;1081:1501', source: 'standard' }]);
  });

  test('표준데이터에 없는 역은 9001 대 다음 번호를 유지·부여하고 보고한다 — 도라산은 9003 그대로(이관할 번호 없음)', () => {
    assert.deepEqual(byName('도라산'), [{ station_id: '9003', name: '도라산', codes: '1063:', source: 'assigned' }]);
    assert.deepEqual([...report.missingStandard].sort(), ['도라산(1063)', '신길온천(1075)']);
  });

  test('수도권 밖 표준데이터 행(부산 신촌)과 수도권 밖 전체노선 행은 무시한다', () => {
    assert.equal(rows.filter((r) => r.name === '무시').length, 0);
    assert.ok(!rows.some((r) => r.station_id === '999'));
  });

  test('기존 행은 원래 순서를 지키고 새 행은 ID 순으로 뒤에 붙는다', () => {
    assert.deepEqual(rows.slice(0, 8).map((r) => r.name), ['서울', '신촌', '이촌', '회기', '신길온천', '가천대', '이매', '도라산']);
    assert.deepEqual(rows.slice(8).map((r) => r.station_id), ['1252', '1501', '1981']);
  });

  test('새 역번호가 기존 ID 와 겹치면 멈춘다', () => {
    assert.throws(() => extendStationIdTable({
      existing: [{ station_id: '1501', name: '엉뚱', codes: '1002:1501', source: 'timetable' }],
      standard: [std('1501', '판교역', 'I41K5', '', 37.39, 127.11)],
      urban: [urban('경강', 1, '판교')],
    }), /1501/);
  });
});
