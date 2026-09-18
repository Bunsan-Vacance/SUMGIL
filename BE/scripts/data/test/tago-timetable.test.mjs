// TAGO 지하철정보 응답 → 우리 표 매핑 규칙을 고정하는 테스트 (S15P21A104-243). 호출 0회.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DAILY_TYPES, MAPPING_FIELDS, TIMETABLE_FIELDS, UP_DOWN,
  buildTagoUrl, comboKey, doneKeysFromRows, lineIdOfRoute, normalizeName, parseTagoResponse,
  pendingCombos, pickStationMatches, targetStations, toTimetableRows,
} from '../lib/tago-timetable.mjs';

describe('lineIdOfRoute', () => {
  test("TAGO 표기(끝 '선' 유무 무관)를 line_id 로 — 2026-09-18 실측 표기", () => {
    assert.equal(lineIdOfRoute('경의중앙'), '1063');
    assert.equal(lineIdOfRoute('서해선'), '1093');
    assert.equal(lineIdOfRoute('신림선'), '1094');
    assert.equal(lineIdOfRoute('공항'), '1065');
    assert.equal(lineIdOfRoute('우이신설'), '1092');
    assert.equal(lineIdOfRoute('경강'), '1081');
    assert.equal(lineIdOfRoute('신분당'), '1077');
  });

  test('대상 밖 노선·모르는 표기는 null — 추측하지 않는다', () => {
    assert.equal(lineIdOfRoute('김포골드라인'), null);
    assert.equal(lineIdOfRoute('1호선'), null);
    assert.equal(lineIdOfRoute('9호선'), null);
    assert.equal(lineIdOfRoute(''), null);
    assert.equal(lineIdOfRoute(undefined), null);
  });
});

describe('normalizeName', () => {
  test("괄호 제거 → 별칭 → 끝 '역' 제거 — Java normalizeStation 과 같은 순서", () => {
    const aliases = { 서울역: '서울', 세종왕릉: '세종대왕릉' };
    assert.equal(normalizeName('서울역', aliases), '서울');
    assert.equal(normalizeName('판교역', aliases), '판교');
    assert.equal(normalizeName('서울역(경의)', aliases), '서울');
    assert.equal(normalizeName('세종왕릉역', aliases), '세종대왕릉');
    assert.equal(normalizeName('역', aliases), '역');
    assert.equal(normalizeName(null), '');
  });
});

describe('targetStations', () => {
  test('codes 에 대상 노선이 하나라도 있는 역만 고르고 노선을 중복 없이 모은다', () => {
    const rows = [
      { station_id: '150', name: '서울', codes: '1001:0150;1004:0426;1065:A01;1063:1251' },
      { station_id: '222', name: '강남', codes: '1002:0222;1077:D007' },
      { station_id: '201', name: '시청', codes: '1001:0151;1002:0201' },
      { station_id: '158', name: '청량리', codes: '1001:0158;1075:;1067:1014;1063:1014' },
    ];
    const got = targetStations(rows);
    assert.deepEqual(got.map((s) => s.name), ['서울', '강남', '청량리']);
    assert.deepEqual(got[0].lineIds, ['1065', '1063']);
    assert.deepEqual(got[2].lineIds, ['1075', '1067', '1063']);
  });
});

describe('pickStationMatches', () => {
  const wanted = { stationId: '158', name: '청량리', lineIds: ['1075', '1067', '1063'] };

  test('이름이 같고 우리 노선인 항목만 골라 MAPPING_FIELDS 행으로, 못 찾은 노선은 missing 에', () => {
    const items = [
      { subwayStationId: 'MTRKRK4K117', subwayStationName: '청량리', subwayRouteName: '경의중앙' },
      { subwayStationId: 'MTRKRK2K117', subwayStationName: '청량리', subwayRouteName: '경춘' },
      { subwayStationId: 'MTRS11124', subwayStationName: '청량리', subwayRouteName: '1호선' },
      { subwayStationId: 'MTRKRK4K999', subwayStationName: '청량리시장', subwayRouteName: '경의중앙' },
    ];
    const got = pickStationMatches(wanted, items);
    assert.deepEqual(got.matched, [
      ['158', '청량리', '1063', 'MTRKRK4K117', '경의중앙'],
      ['158', '청량리', '1067', 'MTRKRK2K117', '경춘'],
    ]);
    assert.deepEqual(got.missingLineIds, ['1075']);
    assert.deepEqual(got.ignored, ['청량리(1호선)', '청량리시장(경의중앙)']);
    assert.equal(got.matched[0].length, MAPPING_FIELDS.length);
  });

  test("다른 도시의 같은 이름(부산 1호선 양정)은 버리고, '역' 접미 차이는 같은 이름으로 본다", () => {
    const w = { stationId: '9001', name: '양정', lineIds: ['1063'] };
    const items = [
      { subwayStationId: 'MTRBS10121', subwayStationName: '양정', subwayRouteName: '1호선' },
      { subwayStationId: 'MTRKRK4K125', subwayStationName: '양정역', subwayRouteName: '경의중앙' },
    ];
    const got = pickStationMatches(w, items);
    assert.equal(got.matched.length, 1);
    assert.equal(got.matched[0][3], 'MTRKRK4K125');
    assert.deepEqual(got.missingLineIds, []);
  });

  test('같은 노선이 두 번 오면 첫 항목만 쓴다', () => {
    const w = { stationId: '1', name: 'A', lineIds: ['1063'] };
    const items = [
      { subwayStationId: 'X1', subwayStationName: 'A', subwayRouteName: '경의중앙' },
      { subwayStationId: 'X2', subwayStationName: 'A', subwayRouteName: '경의중앙' },
    ];
    const got = pickStationMatches(w, items);
    assert.equal(got.matched.length, 1);
    assert.equal(got.ignored.length, 1);
  });
});

describe('toTimetableRows / pendingCombos / doneKeys', () => {
  const mapping = { station_id: '9001', name: '양정', line_id: '1063', tago_station_id: 'MTRKRK4K125', tago_route_name: '경의중앙' };

  test('시각표 항목을 원천 값 그대로 TIMETABLE_FIELDS 순서로 펼친다', () => {
    const rows = toTimetableRows(mapping, '01', 'U', [
      { endSubwayStationNm: '문산', depTime: '050330', arrTime: '050300' },
      { endSubwayStationNm: '수색', depTime: '073600', arrTime: '0' },
    ]);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].length, TIMETABLE_FIELDS.length);
    assert.deepEqual(rows[0], ['1063', '9001', '양정', 'MTRKRK4K125', '01', 'U', '문산', '050330', '050300']);
    assert.equal(rows[1][8], '0');
  });

  test('매핑 하나는 요일 3 × 방향 2 = 6 조합이고, 받은 조합은 빠진다', () => {
    assert.equal(pendingCombos([mapping]).length, DAILY_TYPES.length * UP_DOWN.length);
    const done = doneKeysFromRows([
      { tago_station_id: 'MTRKRK4K125', daily_type: '01', up_down: 'U' },
      { tago_station_id: 'MTRKRK4K125', daily_type: '01', up_down: 'U' },
      { tago_station_id: 'MTRKRK4K125', daily_type: '02', up_down: 'D' },
    ]);
    assert.equal(done.size, 2);
    const pending = pendingCombos([mapping], done);
    assert.equal(pending.length, 4);
    assert.ok(!pending.some((p) => comboKey(p.mapping.tago_station_id, p.dailyType, p.upDown) === 'MTRKRK4K125|01|U'));
  });
});

describe('parseTagoResponse', () => {
  test('정상 응답 — resultCode 00, item 이 하나여도 배열로', () => {
    const one = parseTagoResponse({ response: { header: { resultCode: '00', resultMsg: 'NORMAL SERVICE.' }, body: { items: { item: { depTime: '050330' } }, totalCount: 1 } } });
    assert.equal(one.ok, true);
    assert.equal(one.rows.length, 1);
    assert.equal(one.total, 1);
  });

  test('게이트웨이 오류는 cmmMsgHeader 코드로 — 12 경로 없음 · 30 미신청', () => {
    const gw = parseTagoResponse({ OpenAPI_ServiceResponse: { cmmMsgHeader: { errMsg: 'NO_OPENAPI_SERVICE_ERROR', returnAuthMsg: '해당 오픈API 서비스가 없거나 폐기됨', returnReasonCode: '12' } } });
    assert.equal(gw.ok, false);
    assert.equal(gw.code, '12');
    assert.deepEqual(gw.rows, []);
  });

  test('items 가 비어 있으면(운행 없음) ok 이고 rows 빈 배열', () => {
    const empty = parseTagoResponse({ response: { header: { resultCode: '00', resultMsg: 'NORMAL SERVICE.' }, body: { items: '', totalCount: 0 } } });
    assert.equal(empty.ok, true);
    assert.deepEqual(empty.rows, []);
    assert.equal(empty.total, 0);
  });

  test('JSON 객체가 아니면 실패', () => {
    assert.equal(parseTagoResponse(null).ok, false);
  });
});

describe('buildTagoUrl', () => {
  test('디코딩 키와 한글 파라미터를 인코딩하고 _type=json 을 붙인다', () => {
    const url = buildTagoUrl('GetKwrdFndSubwaySttnList', 'a+b/c==', { subwayStationName: '양정', numOfRows: 20 });
    assert.ok(url.startsWith('https://apis.data.go.kr/1613000/SubwayInfo/GetKwrdFndSubwaySttnList?'));
    assert.ok(url.includes('serviceKey=a%2Bb%2Fc%3D%3D'));
    assert.ok(url.includes('_type=json'));
    assert.ok(url.includes(`subwayStationName=${encodeURIComponent('양정')}`));
    assert.ok(url.includes('numOfRows=20'));
  });
});
