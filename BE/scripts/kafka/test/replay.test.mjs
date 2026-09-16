// 부하 시험 입력 생성 규칙 (S15P21A104-171).
// 핵심은 "복제본이 진짜 다른 이벤트가 되는가" 다 — 안 그러면 컨슈머 중복 제거·멱등에 전부 걸려 아무것도 못 잰다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { canonicalJson, eventId, replay, shiftEvent, shiftIso, shiftRecptnDt } from '../lib/replay.mjs';

const EVENT = {
  event_id: 'original',
  source: 'subway.arrival',
  entity_id: '1002000222',
  source_generated_at: '2026-09-16T10:46:22+09:00',
  ingested_at: '2026-09-16T10:46:57.123+09:00',
  poll_run_at: '2026-09-16T10:46:57+09:00',
  payload: { statnId: '1002000222', recptnDt: '2026-09-16 10:46:22', barvlDt: '120' },
};

describe('canonicalJson', () => {
  test('키를 정렬한다 — 필드 순서가 달라도 같은 문자열', () => {
    assert.equal(canonicalJson({ b: 1, a: 2 }), canonicalJson({ a: 2, b: 1 }));
    assert.equal(canonicalJson({ b: 1, a: 2 }), '{"a":2,"b":1}');
  });

  test('null 값도 남긴다 — 원천 행에 null 필드가 흔하다', () => {
    assert.equal(canonicalJson({ a: null }), '{"a":null}');
  });
});

describe('shiftIso', () => {
  test('오프셋 표기를 유지한 채 초를 더한다', () => {
    assert.equal(shiftIso('2026-09-16T10:46:22+09:00', 60), '2026-09-16T10:47:22+09:00');
    assert.equal(shiftIso('2026-09-16T23:59:00+09:00', 120), '2026-09-17T00:01:00+09:00');
  });

  test('밀리초가 있으면 유지한다', () => {
    assert.equal(shiftIso('2026-09-16T10:46:57.123+09:00', 60), '2026-09-16T10:47:57.123+09:00');
  });
});

describe('shiftRecptnDt', () => {
  test('지하철 recptnDt 형식("yyyy-MM-dd HH:mm:ss") 그대로 민다', () => {
    assert.equal(shiftRecptnDt('2026-09-16 10:46:22', 60), '2026-09-16 10:47:22');
  });
});

describe('eventId', () => {
  test('SHA-256 16진수 64자', () => {
    const id = eventId('bike.stock', 'ST-1', null, { a: 1 });
    assert.match(id, /^[0-9a-f]{64}$/);
  });

  test('payload 필드 순서가 달라도 같은 id — 정규형이라서', () => {
    assert.equal(eventId('s', 'e', null, { a: 1, b: 2 }), eventId('s', 'e', null, { b: 2, a: 1 }));
  });

  test('시각이 다르면 다른 id', () => {
    assert.notEqual(
      eventId('s', 'e', '2026-09-16T10:00:00+09:00', { a: 1 }),
      eventId('s', 'e', '2026-09-16T10:01:00+09:00', { a: 1 })
    );
  });
});

describe('shiftEvent', () => {
  test('시각 셋과 payload.recptnDt 를 함께 민다', () => {
    const shifted = shiftEvent(EVENT, 60);

    assert.equal(shifted.source_generated_at, '2026-09-16T10:47:22+09:00');
    assert.equal(shifted.ingested_at, '2026-09-16T10:47:57.123+09:00');
    assert.equal(shifted.poll_run_at, '2026-09-16T10:47:57+09:00');
    assert.equal(shifted.payload.recptnDt, '2026-09-16 10:47:22', 'payload 안의 시각도 같이 밀어야 한다');
  });

  test('event_id 가 새로 만들어진다 — 안 그러면 컨슈머가 전부 중복으로 버린다', () => {
    const shifted = shiftEvent(EVENT, 60);

    assert.notEqual(shifted.event_id, EVENT.event_id);
    assert.match(shifted.event_id, /^[0-9a-f]{64}$/);
  });

  test('원본을 건드리지 않는다', () => {
    shiftEvent(EVENT, 60);

    assert.equal(EVENT.payload.recptnDt, '2026-09-16 10:46:22');
    assert.equal(EVENT.poll_run_at, '2026-09-16T10:46:57+09:00');
  });

  test('entity_id 는 그대로 — 같은 역이 같은 파티션으로 가야 순서가 보장된다', () => {
    assert.equal(shiftEvent(EVENT, 60).entity_id, EVENT.entity_id);
  });
});

describe('replay', () => {
  test('times 배로 불리고 회차마다 시각이 밀린다', () => {
    const out = replay([EVENT], 3, 60);

    assert.equal(out.length, 3);
    const runs = out.map((r) => JSON.parse(r.value).poll_run_at);
    assert.deepEqual(runs, [
      '2026-09-16T10:46:57+09:00',
      '2026-09-16T10:47:57+09:00',
      '2026-09-16T10:48:57+09:00',
    ]);
  });

  test('event_id 가 전부 다르다 — 이게 깨지면 부하 시험이 아무것도 안 잰다', () => {
    // 덤프의 이벤트는 저마다 event_id 가 다르다. 첫 회차는 원본을 그대로 쓰므로 픽스처도 그렇게 둔다.
    const other = { ...EVENT, entity_id: '1002000221', event_id: 'original-2' };
    const out = replay([EVENT, other], 5, 60);

    const ids = out.map((r) => JSON.parse(r.value).event_id);
    assert.equal(new Set(ids).size, ids.length, `중복 event_id 가 있다 (${ids.length}건 중 ${new Set(ids).size}개만 고유)`);
  });

  test('key 는 entity_id — kafka-console-producer 의 parse.key 로 넣는다', () => {
    const out = replay([EVENT], 1, 60);

    assert.equal(out[0].key, '1002000222');
  });

  test('첫 회차는 원본 그대로 — 덤프와 섞어도 계산이 맞는다', () => {
    const out = replay([EVENT], 1, 60);

    assert.equal(JSON.parse(out[0].value).event_id, EVENT.event_id);
  });
});
