// 외부 데이터 소스 3종(지하철 실시간 도착·따릉이 bikeList·버스 도착정보)의
// URL 조립, 인증키 선택, 응답 판정 규칙을 고정하는 테스트.
// 실행: node --test "BE/scripts/external/test/*.test.mjs"
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { SOURCES, buildUrl, parseResponse, redactKey, resolveKey } from '../lib/sources.mjs';

describe('buildUrl', () => {
  test('subway 기본은 전체 역 일괄(ALL) 첫 페이지(0~1000)다', () => {
    // 인덱스 없는 /ALL 은 별도 승인 서비스(ERROR-340). 인덱스를 붙인 형식이 일반 전용키로 동작한다.
    assert.equal(
      buildUrl('subway', 'K1'),
      'http://swopenapi.seoul.go.kr/api/subway/K1/json/realtimeStationArrival/0/1000/ALL',
    );
  });

  test('subway 일괄은 start/end 인덱스로 분할 조회한다', () => {
    assert.equal(
      buildUrl('subway', 'K1', { start: 1000, end: 2000 }),
      'http://swopenapi.seoul.go.kr/api/subway/K1/json/realtimeStationArrival/1000/2000/ALL',
    );
  });

  test('subway 일괄은 end-start 가 1000을 넘으면 서버가 ERROR-336 을 내므로 미리 막는다', () => {
    assert.throws(() => buildUrl('subway', 'K1', { start: 0, end: 1001 }), /1000/);
  });

  test('bike 는 한 번에 1000건(end-start+1)을 넘으면 미리 막는다', () => {
    assert.throws(() => buildUrl('bike', 'K2', { start: 1, end: 1001 }), /1000/);
  });

  test('subway에 station을 주면 역명 조회 경로로 바뀌고 한글은 인코딩된다', () => {
    assert.equal(
      buildUrl('subway', 'K1', { station: '서울', count: 5 }),
      `http://swopenapi.seoul.go.kr/api/subway/K1/json/realtimeStationArrival/0/5/${encodeURIComponent('서울')}`,
    );
  });

  test('bike 기본 범위는 1~1000이다', () => {
    assert.equal(buildUrl('bike', 'K2'), 'http://openapi.seoul.go.kr:8088/K2/json/bikeList/1/1000/');
  });

  test('bike 범위를 지정할 수 있다', () => {
    assert.equal(
      buildUrl('bike', 'K2', { start: 1001, end: 2000 }),
      'http://openapi.seoul.go.kr:8088/K2/json/bikeList/1001/2000/',
    );
  });

  test('bus는 stId가 없으면 실패한다', () => {
    assert.throws(() => buildUrl('bus', 'K3'), /stId/);
  });

  test('bus는 serviceKey와 resultType=json을 쿼리로 보낸다', () => {
    const url = new URL(buildUrl('bus', 'K3', { stId: '123000001' }));
    assert.equal(url.origin + url.pathname, 'http://ws.bus.go.kr/api/rest/arrive/getLowArrInfoByStId');
    assert.equal(url.searchParams.get('serviceKey'), 'K3');
    assert.equal(url.searchParams.get('stId'), '123000001');
    assert.equal(url.searchParams.get('resultType'), 'json');
  });

  test('모르는 소스는 이름을 알려주며 실패한다', () => {
    assert.throws(() => buildUrl('taxi', 'K'), /taxi/);
  });
});

describe('resolveKey', () => {
  test('명시한 키가 환경변수보다 우선한다', () => {
    assert.equal(resolveKey('subway', { SEOUL_SUBWAY_KEY: 'env' }, 'cli'), 'cli');
  });

  test('전용 키가 있으면 일반 키보다 먼저 쓴다', () => {
    assert.equal(resolveKey('bike', { SEOUL_BIKE_KEY: 'bike', SEOUL_API_KEY: 'general' }), 'bike');
  });

  test('전용 키가 없으면 일반 키로 대체한다', () => {
    assert.equal(resolveKey('subway', { SEOUL_API_KEY: 'general' }), 'general');
  });

  test('빈 문자열은 없는 것으로 본다', () => {
    assert.equal(resolveKey('bike', { SEOUL_BIKE_KEY: '', SEOUL_API_KEY: 'general' }), 'general');
  });

  test('키가 하나도 없으면 필요한 환경변수 이름을 알려주며 실패한다', () => {
    assert.throws(() => resolveKey('bus', {}), /DATA_GO_KR_KEY/);
  });
});

describe('redactKey', () => {
  test('URL 안의 키를 {KEY}로 가린다', () => {
    assert.equal(redactKey('http://h/abc123/json', 'abc123'), 'http://h/{KEY}/json');
  });

  test('키가 비어 있으면 원문을 그대로 돌려준다', () => {
    assert.equal(redactKey('http://h/x', ''), 'http://h/x');
  });
});

describe('parseResponse', () => {
  test('subway 정상 응답은 errorMessage.code가 INFO-000이고 realtimeArrivalList가 행이다', () => {
    const body = {
      errorMessage: { status: 200, code: 'INFO-000', message: '정상 처리되었습니다.', total: 2 },
      realtimeArrivalList: [
        { statnNm: '서울', recptnDt: '2026-09-08 09:00:00' },
        { statnNm: '서울', recptnDt: '2026-09-08 09:00:00' },
      ],
    };
    const r = parseResponse('subway', body);
    assert.equal(r.ok, true);
    assert.equal(r.code, 'INFO-000');
    assert.equal(r.rows.length, 2);
    assert.equal(r.total, 2);
  });

  test('subway 오류 응답은 최상위 code/message로 오며 실패로 판정하고 행은 비어 있다', () => {
    const body = { status: 500, code: 'INFO-200', message: '해당하는 데이터가 없습니다.' };
    const r = parseResponse('subway', body);
    assert.equal(r.ok, false);
    assert.equal(r.code, 'INFO-200');
    assert.match(r.message, /데이터가 없습니다/);
    assert.deepEqual(r.rows, []);
  });

  test('bike 정상 응답은 rentBikeStatus.RESULT.CODE와 row를 쓴다', () => {
    const body = {
      rentBikeStatus: {
        list_total_count: 1,
        RESULT: { CODE: 'INFO-000', MESSAGE: '정상 처리되었습니다' },
        row: [{ stationId: 'ST-1' }],
      },
    };
    const r = parseResponse('bike', body);
    assert.equal(r.ok, true);
    assert.equal(r.code, 'INFO-000');
    assert.equal(r.rows.length, 1);
    assert.equal(r.total, 1);
  });

  test('bike 오류 응답은 최상위 RESULT.CODE로 오며 INFO-000이 아니면 실패다', () => {
    const body = { RESULT: { CODE: 'INFO-300', MESSAGE: '유효하지 않은 인증키입니다.' } };
    const r = parseResponse('bike', body);
    assert.equal(r.ok, false);
    assert.equal(r.code, 'INFO-300');
    assert.deepEqual(r.rows, []);
  });

  test('bus 정상 응답은 msgHeader.headerCd가 0이고 msgBody.itemList가 행이다', () => {
    const body = {
      msgHeader: { headerCd: '0', headerMsg: '정상적으로 처리되었습니다.', itemCount: 0 },
      msgBody: { itemList: [{ stId: '1', mkTm: '2026-09-08 09:00:00.0' }] },
    };
    const r = parseResponse('bus', body);
    assert.equal(r.ok, true);
    assert.equal(r.code, '0');
    assert.equal(r.rows.length, 1);
  });

  test('bus 오류 응답은 headerCd가 0이 아니면 실패다', () => {
    const body = { msgHeader: { headerCd: '7', headerMsg: '인증키가 유효하지 않습니다.' }, msgBody: {} };
    const r = parseResponse('bus', body);
    assert.equal(r.ok, false);
    assert.equal(r.code, '7');
    assert.deepEqual(r.rows, []);
  });

  test('bus itemList가 배열이 아니라 객체 하나로 오면 배열로 감싼다', () => {
    const body = { msgHeader: { headerCd: '0' }, msgBody: { itemList: { stId: '1' } } };
    assert.equal(parseResponse('bus', body).rows.length, 1);
  });

  test('본문이 객체가 아니면 실패로 판정한다', () => {
    const r = parseResponse('subway', null);
    assert.equal(r.ok, false);
    assert.deepEqual(r.rows, []);
  });
});

describe('SOURCES', () => {
  test('소스 3종이 정의돼 있고 각자 환경변수 후보를 가진다', () => {
    assert.deepEqual(Object.keys(SOURCES).sort(), ['bike', 'bus', 'subway']);
    for (const spec of Object.values(SOURCES)) {
      assert.ok(spec.envKeys.length >= 1);
    }
  });
});
