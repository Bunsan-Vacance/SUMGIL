// 실시간 도착 API(OA-15799)의 statnId 를 우리 station_id 로 붙이는 규칙 (S15P21A104-171).
//
// statnId 자체로는 못 찾는다 — 1호선이 다른 체계다(서울역 API 1001000133 vs 우리 150).
// 이름만으로도 못 찾는다 — 동명이역이 있다(신촌: 2호선 240 / 경의중앙 1252, 양평: 5호선 2523 / 경의중앙 1217).
// 그래서 (subwayId, 정규화한 statnNm) 두 개로 찾는다. subwayId 는 station-ids.csv 의 codes 앞자리(line_id)와 같은 체계다.
//
// 결과 표는 커밋되면 정본이다. 이 도구는 prod Kafka 덤프에서 표를 "만들기만" 하고,
// 안 붙은 역은 unmapped 로 따로 돌려준다 — 조용히 버리면 그 역이 서비스에서 사라진 걸 아무도 모른다.

/** "1001:0150;1004:0426" → [{line_id, code}] */
export function parseCodes(codes) {
  if (!codes) return [];
  return String(codes)
    .split(';')
    .map((pair) => pair.trim())
    .filter(Boolean)
    .map((pair) => {
      const sep = pair.indexOf(':');
      return sep < 0
        ? { line_id: pair, code: '' }
        : { line_id: pair.slice(0, sep), code: pair.slice(sep + 1) };
    });
}

/** 끝에 붙은 괄호 부역명. 실시간 API 는 '총신대입구(이수)'처럼 부역명을 괄호로 붙여 준다. */
const PAREN_SUFFIX = /\s*\([^()]*\)\s*$/;

/**
 * 원천 표기를 정본 표기로.
 *
 * 1. 끝에 붙은 괄호를 벗긴다 — 우리 표(station-ids.csv)에는 괄호가 붙은 이름이 하나도 없다. 가운데 괄호는 건드리지 않는다.
 * 2. 그 다음 station-aliases.csv 를 본다 — '응암순환(상선)'은 괄호를 벗겨야 '응암순환'이 되고, 거기서 별칭으로 '응암'이 된다.
 */
export function normalizeName(name, aliases) {
  const trimmed = String(name ?? '').trim();
  const base = trimmed.replace(PAREN_SUFFIX, '').trim();
  // 이름 전체가 괄호뿐이면 벗기지 않는다 — 빈 이름으로 만들면 엉뚱한 역에 붙을 수 있다
  const stripped = base === '' ? trimmed : base;
  return aliases.get(stripped) ?? stripped;
}

/**
 * @param events   {subwayId, statnNm, statnId}[] — 덤프에서 뽑은 이벤트 payload. 중복 허용
 * @param idRows   {station_id, name, codes}[] — station-ids.csv
 * @param aliasRows {원천표기, 정본표기}[] — station-aliases.csv
 * @returns {{rows: {statn_id, station_id, line_id, name}[], unmapped: {statn_id, line_id, name, count}[]}}
 *          둘 다 statn_id 순 정렬 — 표가 커밋되므로 diff 가 흔들리면 안 된다
 */
export function buildStatnIdMap(events, idRows, aliasRows) {
  const aliases = new Map((aliasRows ?? []).map((r) => [r.원천표기, r.정본표기]));

  // (line_id, 정본 이름) → station_id. 한 역이 여러 노선에 걸리면 노선마다 한 항목이다.
  const index = new Map();
  for (const row of idRows ?? []) {
    for (const { line_id } of parseCodes(row.codes)) {
      index.set(`${line_id}\t${row.name}`, row.station_id);
    }
  }

  const rows = new Map();
  const unmapped = new Map();
  for (const event of events ?? []) {
    const lineId = String(event.subwayId ?? '').trim();
    const statnId = String(event.statnId ?? '').trim();
    const name = normalizeName(event.statnNm, aliases);

    const stationId = index.get(`${lineId}\t${name}`);
    if (stationId === undefined) {
      const seen = unmapped.get(statnId);
      if (seen) seen.count += 1;
      else unmapped.set(statnId, { statn_id: statnId, line_id: lineId, name, count: 1 });
      continue;
    }
    if (!rows.has(statnId)) {
      rows.set(statnId, { statn_id: statnId, station_id: stationId, line_id: lineId, name });
    }
  }

  const byStatnId = (a, b) => (a.statn_id < b.statn_id ? -1 : a.statn_id > b.statn_id ? 1 : 0);
  return { rows: [...rows.values()].sort(byStatnId), unmapped: [...unmapped.values()].sort(byStatnId) };
}
