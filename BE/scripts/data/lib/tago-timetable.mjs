// TAGO 지하철정보(공공데이터포털 15098554) 역 검색·역별 시각표 응답을 우리 표(station_id·line_id)에 붙이는 순수 규칙.
// 네트워크·파일은 tago-timetable-fetch.mjs 가 하고, 여기는 판정·변환만 한다 (S15P21A104-243).
//
// 대상: 열차운행시각표(서울교통공사)가 덮지 않아 edge_time.wait_sec 이 0 인 수도권 9개 노선.
// TAGO 노선 표기는 "경의중앙"·"서해선"·"공항" 처럼 우리 LineCodes 표기와 다르다 — 끝의 '선' 을 떼고 대조한다.

export const TAGO_BASE = 'https://apis.data.go.kr/1613000/SubwayInfo';
export const OP_STATIONS = 'GetKwrdFndSubwaySttnList';
export const OP_TIMETABLE = 'GetSubwaySttnAcctoSchdulList';

/** TAGO subwayRouteName(끝 '선' 제거) → 우리 line_id. 여기 없는 노선(김포골드라인·부산 1호선 등)은 버린다. */
export const TARGET_LINES = {
  경의중앙: '1063',
  공항: '1065',
  공항철도: '1065',
  인천국제공항철도: '1065',
  경춘: '1067',
  수인분당: '1075',
  분당: '1075',
  수인: '1075',
  신분당: '1077',
  경강: '1081',
  우이신설: '1092',
  서해: '1093',
  신림: '1094',
};

export const TARGET_LINE_IDS = new Set(Object.values(TARGET_LINES));

/** 요일 유형 코드 → edge_time.dow_type. TAGO 01 평일 · 02 토 · 03 일(공휴일). */
export const DAILY_TYPES = ['01', '02', '03'];
export const UP_DOWN = ['U', 'D'];

export const MAPPING_FIELDS = ['station_id', 'name', 'line_id', 'tago_station_id', 'tago_route_name'];
export const TIMETABLE_FIELDS = [
  'line_id', 'station_id', 'station_name', 'tago_station_id', 'daily_type', 'up_down',
  'end_station_nm', 'dep_time', 'arr_time',
];

/** TAGO 노선 표기 → line_id. 모르면 null (추측하지 않는다). */
export function lineIdOfRoute(routeName) {
  if (!routeName) return null;
  const raw = String(routeName).trim();
  const candidates = [raw, raw.replace(/선$/, '')];
  for (const c of candidates) {
    if (TARGET_LINES[c]) return TARGET_LINES[c];
  }
  return null;
}

/**
 * 역명 정규화 — Java StationNameNormalizer.normalizeStation 과 같은 규칙: 괄호 제거 → 별칭 → 끝 '역' 제거 → 별칭.
 * @param {string} raw
 * @param {Record<string,string>} aliases 원천표기 → 정본표기 (conf/station-aliases.csv)
 */
export function normalizeName(raw, aliases = {}) {
  if (raw == null) return '';
  let name = String(raw).replace(/\s*[(（][^)）]*[)）]/g, '').trim();
  name = aliases[name] ?? name;
  if (name.length > 1 && name.endsWith('역')) {
    name = name.slice(0, -1);
    name = aliases[name] ?? name;
  }
  return name;
}

/**
 * conf/station-ids.csv 행에서 대상 노선에 속한 역을 뽑는다.
 * @param {Array<Record<string,string>>} rows station_id,name,codes(line:code;...) 행
 * @returns {Array<{stationId:string,name:string,lineIds:string[]}>}
 */
export function targetStations(rows) {
  const out = [];
  for (const row of rows) {
    const codes = String(row.codes ?? '').split(';').map((c) => c.split(':')[0].trim()).filter(Boolean);
    const lineIds = [...new Set(codes.filter((c) => TARGET_LINE_IDS.has(c)))];
    if (lineIds.length === 0) continue;
    out.push({ stationId: row.station_id, name: row.name, lineIds });
  }
  return out;
}

/**
 * 역 검색 응답에서 우리 역(이름·노선)에 해당하는 항목만 고른다. 같은 이름의 다른 도시 역, 대상 밖 노선은 버린다.
 * @param {{stationId:string,name:string,lineIds:string[]}} wanted
 * @param {Array<{subwayStationId:string,subwayStationName:string,subwayRouteName:string}>} items
 * @param {Record<string,string>} aliases
 * @returns {{matched: Array<string[]>, missingLineIds: string[], ignored: string[]}}
 *   matched 는 MAPPING_FIELDS 순서의 행, missingLineIds 는 응답에 없던 우리 노선, ignored 는 버린 항목의 "이름(노선)" 표기
 */
export function pickStationMatches(wanted, items, aliases = {}) {
  const wantName = normalizeName(wanted.name, aliases);
  const matched = [];
  const found = new Set();
  const ignored = [];
  for (const it of items ?? []) {
    const lineId = lineIdOfRoute(it.subwayRouteName);
    const sameName = normalizeName(it.subwayStationName, aliases) === wantName;
    if (!lineId || !sameName || !wanted.lineIds.includes(lineId) || found.has(lineId)) {
      ignored.push(`${it.subwayStationName}(${it.subwayRouteName})`);
      continue;
    }
    found.add(lineId);
    matched.push([wanted.stationId, wanted.name, lineId, it.subwayStationId, it.subwayRouteName]);
  }
  const missingLineIds = wanted.lineIds.filter((l) => !found.has(l));
  return { matched, missingLineIds, ignored };
}

/** 시각표 응답 항목 → TIMETABLE_FIELDS 순서의 행. 값은 원천 그대로(HHmmss 문자열), 없는 필드는 ''. */
export function toTimetableRows(mapping, dailyType, upDown, items) {
  return (items ?? []).map((it) => [
    mapping.line_id, mapping.station_id, mapping.name, mapping.tago_station_id, dailyType, upDown,
    it.endSubwayStationNm ?? '', it.depTime ?? '', it.arrTime ?? '',
  ]);
}

export function comboKey(tagoStationId, dailyType, upDown) {
  return `${tagoStationId}|${dailyType}|${upDown}`;
}

/**
 * 이미 받은 시각표 행(TIMETABLE_FIELDS 객체)에서 끝난 조합 키 집합을 만든다 — 이어받기용.
 * 응답이 0행인 조합은 파일에 흔적이 없어 다시 부르게 된다. 그 조합은 fetch 가 별도 목록(empty)으로 남긴다.
 */
export function doneKeysFromRows(rows) {
  const done = new Set();
  for (const r of rows ?? []) {
    if (r.tago_station_id && r.daily_type && r.up_down) done.add(comboKey(r.tago_station_id, r.daily_type, r.up_down));
  }
  return done;
}

/**
 * 매핑(역×노선) × 요일 3 × 방향 2 중 아직 안 받은 조합.
 * @param {Array<Record<string,string>>} mappings MAPPING_FIELDS 객체
 * @param {Set<string>} doneKeys
 */
export function pendingCombos(mappings, doneKeys = new Set()) {
  const out = [];
  for (const m of mappings) {
    for (const d of DAILY_TYPES) {
      for (const u of UP_DOWN) {
        if (!doneKeys.has(comboKey(m.tago_station_id, d, u))) out.push({ mapping: m, dailyType: d, upDown: u });
      }
    }
  }
  return out;
}

/** 게이트웨이 오류(OpenAPI_ServiceResponse)와 서비스 응답(response.header) 을 { ok, code, message, rows, total } 로 통일한다. */
export function parseTagoResponse(body) {
  if (body === null || typeof body !== 'object') {
    return { ok: false, code: null, message: '응답 본문이 JSON 객체가 아닙니다.', rows: [], total: null };
  }
  const gw = body.OpenAPI_ServiceResponse?.cmmMsgHeader;
  if (gw) {
    // 12 서비스 없음(경로 오류) · 30 등록되지 않은 서비스키(미신청) · 22 일일 한도 초과 — 코드로 원인을 가른다
    return { ok: false, code: gw.returnReasonCode ?? null, message: gw.returnAuthMsg ?? gw.errMsg ?? null, rows: [], total: null };
  }
  const head = body.response?.header ?? {};
  const code = head.resultCode ?? null;
  const ok = code === '00';
  const items = body.response?.body?.items?.item;
  const rows = ok ? (Array.isArray(items) ? items : items ? [items] : []) : [];
  const total = body.response?.body?.totalCount;
  return { ok, code, message: head.resultMsg ?? null, rows, total: total == null ? null : Number(total) };
}

/** 호출 URL. serviceKey 는 디코딩 키를 받아 인코딩한다 (공공데이터포털 규칙). */
export function buildTagoUrl(op, key, params) {
  const q = Object.entries({ serviceKey: key, _type: 'json', ...params })
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  return `${TAGO_BASE}/${op}?${q}`;
}
