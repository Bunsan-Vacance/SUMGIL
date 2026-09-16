// prod Kafka 덤프를 N배로 불려 부하 시험 입력을 만드는 규칙 (S15P21A104-171).
//
// 그냥 복제하면 아무것도 못 잰다. 함정이 둘이다.
//   1) event_id 가 같으면 컨슈머 중복 제거가 전부 걸러낸다 → 처리량이 아니라 중복 제거 속도를 재게 된다
//   2) 시각이 그대로면 멱등 규칙("기존 값보다 최신일 때만")에 걸려 쓰기가 전부 스킵된다
// 둘 다 시각을 회차마다 앞으로 밀면 풀린다 — payload 가 바뀌니 event_id 도 자동으로 달라진다.
//
// event_id 규칙은 Java EventIdFactory 와 같다: SHA-256(source|entity_id|source_generated_at|payload_hash),
// payload_hash = SHA-256(키 정렬 정규형 JSON). 값이 달라지면 컨슈머가 중복으로 안 보므로 규칙이 어긋나도
// 부하 시험 자체는 성립하지만, 같은 값을 만들어 두면 덤프와 재생분을 섞어도 계산이 맞는다.
import { createHash } from 'node:crypto';

const sha256 = (text) => createHash('sha256').update(text, 'utf8').digest('hex');

/** 키를 정렬한 정규형 JSON. Java 의 ORDER_MAP_ENTRIES_BY_KEYS 와 같은 결과를 낸다. */
export function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value ?? null);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`;
}

export function payloadHash(payload) {
  return sha256(canonicalJson(payload ?? {}));
}

export function eventId(source, entityId, sourceGeneratedAt, payload) {
  return sha256(`${source}|${entityId}|${sourceGeneratedAt ?? ''}|${payloadHash(payload)}`);
}

/** "2026-09-16T10:46:22+09:00" 에 초를 더한다. 오프셋 표기는 그대로 유지한다. */
export function shiftIso(text, seconds) {
  if (!text) return text;
  const offset = text.slice(-6);
  const shifted = new Date(new Date(text).getTime() + seconds * 1000);
  const local = new Date(shifted.getTime() + offsetMinutes(offset) * 60000);
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  const ms = local.getUTCMilliseconds();
  const base = `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())}`
    + `T${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}:${pad(local.getUTCSeconds())}`;
  return `${base}${ms ? `.${pad(ms, 3)}` : ''}${offset}`;
}

function offsetMinutes(offset) {
  const sign = offset[0] === '-' ? -1 : 1;
  return sign * (Number(offset.slice(1, 3)) * 60 + Number(offset.slice(4, 6)));
}

/** "2026-09-16 10:46:22" (지하철 recptnDt 형식) 에 초를 더한다. */
export function shiftRecptnDt(text, seconds) {
  if (!text) return text;
  const iso = shiftIso(`${text.replace(' ', 'T')}+09:00`, seconds);
  return iso.slice(0, 19).replace('T', ' ');
}

/**
 * 이벤트 하나를 `seconds` 초 뒤로 민 복제본으로. 시각 셋과 payload 의 recptnDt 를 함께 밀고 event_id 를 다시 만든다.
 *
 * @param event 원본 이벤트 (계약 JSON 을 파싱한 객체)
 * @param seconds 밀 초. 회차 번호 × 주기
 */
export function shiftEvent(event, seconds) {
  const payload = { ...event.payload };
  if (payload.recptnDt) payload.recptnDt = shiftRecptnDt(payload.recptnDt, seconds);

  const source_generated_at = shiftIso(event.source_generated_at, seconds);
  return {
    event_id: eventId(event.source, event.entity_id, source_generated_at, payload),
    source: event.source,
    entity_id: event.entity_id,
    source_generated_at,
    ingested_at: shiftIso(event.ingested_at, seconds),
    poll_run_at: shiftIso(event.poll_run_at, seconds),
    payload,
  };
}

/**
 * 회차 하나를 `times` 배로 불린다. 회차 n 은 n × intervalSeconds 만큼 밀린다 (n=0 은 원본 그대로).
 *
 * @returns {{key: string, value: string}[]} kafka-console-producer 에 넣을 키·값
 */
export function replay(events, times, intervalSeconds) {
  const out = [];
  for (let cycle = 0; cycle < times; cycle += 1) {
    for (const event of events) {
      const shifted = cycle === 0 ? event : shiftEvent(event, cycle * intervalSeconds);
      out.push({ key: shifted.entity_id, value: JSON.stringify(shifted) });
    }
  }
  return out;
}
