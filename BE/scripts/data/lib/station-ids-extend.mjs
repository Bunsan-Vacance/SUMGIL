// 역 ID 표(data/subway/conf/station-ids.csv)에 시각표 밖 노선(경의중앙·수인분당·경춘·경강·서해·공항철도·신분당·우이신설·신림)의 역을 더하는 규칙.
// 기존 행의 ID 는 바꾸지 않는다 — 예외는 임시 부여(source=assigned) 행을 표준데이터 역번호로 이관하는 것 하나뿐이다.
// 새 역의 station_id 는 전국도시철도역사정보표준데이터(15013205)의 역번호(코레일 1014, 신분당 D004 …), 없으면 9001 대의 다음 번호.
// 같은 이름의 기존 역과 "같은 물리 역인가" 는 표준데이터의 환승노선명(또는 좌표 500 m 이내)으로 판정한다 — 신촌(2호선)·신촌(경의중앙)은 별개다.

/** 전체노선 파일의 노선명 → line_id. 실시간 API 코드가 있는 9개 노선만. */
export const TARGET_LINES = {
  경의중앙: '1063', 수인분당: '1075', 경춘: '1067', 경강: '1081', 서해선: '1093',
  공항: '1065', 신분당: '1077', 우이신설: '1092', 신림선: '1094',
};

/** 새 노선의 역을 표준데이터에서 찾을 때 허용하는 노선번호. 코레일은 물리 선로 코드(경원선 I4102)로도 실려 있다. */
export const STD_CODES_BY_LINE = {
  1063: ['I4108', 'I4102'], 1075: ['I4105', 'I28K1'], 1067: ['I41K2', 'I4108', 'I4102'], 1081: ['I41K5'],
  1093: ['I41WS'], 1065: ['I28A1'], 1077: ['I11D1'], 1092: ['L11UI'], 1094: ['L11SL'],
};

/** 표준데이터 노선번호 → line_id (서비스 노선이 하나로 정해지는 코드만). 기존 역의 표준데이터 행을 찾을 때 쓴다. */
export const STD_CODE_TO_LINE = {
  S1101: '1001', S1102: '1002', S1103: '1003', S1104: '1004', S1105: '1005', S1106: '1006', S1107: '1007', S1108: '1008', S1109: '1009',
  S1121: '1002', S1122: '1002', I4101: '1001', I1101: '1001', I1103: '1003', I4106: '1003', I1104: '1004', I4103: '1004', I4104: '1004',
  S4108: '1008', I4108: '1063', I4105: '1075', I28K1: '1075', I41K2: '1067', I41K5: '1081', I41WS: '1093', I28A1: '1065',
  I11D1: '1077', L11UI: '1092', L11SL: '1094',
};

// 환승노선명 토큰 → line_id. "수도권 광역철도 4호선", "서울 도시철도 2호선", "경의선", "분당" 처럼 표기가 제멋대로라 접두어를 떼고 본다.
const TRANSFER_NAME_TO_LINE = {
  '1호선': '1001', '2호선': '1002', '3호선': '1003', '4호선': '1004', '5호선': '1005', '6호선': '1006', '7호선': '1007', '8호선': '1008', '9호선': '1009',
  경부선: '1001', 경인선: '1001', 경원선: '1001', 국철: '1001',
  경의선: '1063', 경의중앙선: '1063', 경의중앙: '1063', 중앙선: '1063',
  분당: '1075', 분당선: '1075', 수인선: '1075', 수인분당선: '1075', 수인분당: '1075',
  경춘: '1067', 경춘선: '1067', 경강선: '1081', 경강: '1081', 서해선: '1093',
  공항: '1065', 공항선: '1065', 공항철도: '1065', 인천국제공항선: '1065',
  신분당선: '1077', 신분당: '1077', 우이신설선: '1092', 우이신설: '1092', 신림선: '1094',
  안산과천선: '1004', 안산선: '1004', 과천선: '1004', 진접선: '1004', 일산선: '1003',
};
const TRANSFER_PREFIX = /^(수도권|서울|인천)?\s*(광역철도|도시철도|경량도시철도|전절|지하철)?\s*/;
const SAME_STATION_METERS = 500;
const ASSIGNED_MIN = 9001;
const ASSIGNED_MAX = 9999;

/** 로더의 StationNameNormalizer.normalizeStation 과 같은 규칙: 괄호 부기 제거 → 별칭 → 끝의 '역' 제거 → 별칭. */
export function normalizeStation(raw, aliases = new Map()) {
  const norm = (s) => {
    const stripped = s.replace(/\s*\([^)]*\)/g, '').trim();
    return aliases.get(stripped) ?? stripped;
  };
  let name = norm(raw ?? '');
  if (name.length > 1 && name.endsWith('역')) name = norm(name.slice(0, -1));
  return name;
}

/** 표준데이터 환승노선명("서울 도시철도 5호선+경의중앙선", "S1102, S1105 …" 는 번호 열이라 안 씀) → line_id 집합. 모르는 토큰은 무시. */
export function lineIdsFromTransferNames(text) {
  const out = new Set();
  for (const token of String(text ?? '').split(/[+,\n]/)) {
    const name = token.trim().replace(TRANSFER_PREFIX, '').trim();
    const id = TRANSFER_NAME_TO_LINE[name];
    if (id) out.add(id);
  }
  return out;
}

/** 후보 역번호 중 하나를 고른다: 숫자만인 번호(코레일)를 우선, 그중 가장 작은 값. 없으면 문자열 순 첫 값. */
export function pickStationNumber(numbers) {
  const list = [...new Set(numbers.filter(Boolean))];
  if (list.length === 0) return null;
  const numeric = list.filter((n) => /^\d+$/.test(n)).sort((a, b) => Number(a) - Number(b));
  return numeric[0] ?? list.sort()[0];
}

function inMetroArea(lat, lng) {
  return lat >= 36.5 && lat <= 38.5 && lng >= 126.0 && lng <= 128.0;
}

function distanceMeters(a, b) {
  const rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

function linesOf(codes) {
  return codes.split(';').map((c) => c.split(':')[0].trim()).filter(Boolean);
}

function idSortKey(id) {
  return /^\d+$/.test(id) ? [0, Number(id), ''] : [1, 0, id];
}

export function compareIds(a, b) {
  const [ka, na, sa] = idSortKey(a);
  const [kb, nb, sb] = idSortKey(b);
  return ka - kb || na - nb || sa.localeCompare(sb);
}

/**
 * @param existing  기존 표 행 {station_id, name, codes, source}[]
 * @param standard  표준데이터 행 {역번호, 역사명, 노선번호, 환승노선명, 역위도, 역경도}[]
 * @param urban     전체노선 행 {권역명, 노선명, 순번, 역명}[]
 * @param extra     전체노선 파일에 없지만 KTDB 링크에는 있는 역 {name, lineId}[] (서해선 원종처럼 파일 갱신이 개통보다 늦은 경우)
 * @param aliases   Map<원천표기, 정본표기>
 * @returns {{rows: object[], report: object}} rows 는 기존 행(순서 유지, 코드 추가·이관 반영) + 새 행(ID 순)
 */
export function extendStationIdTable({ existing, standard, urban, extra = [], aliases = new Map() }) {
  const norm = (s) => normalizeStation(s, aliases);
  const std = standard
    .map((r) => ({
      no: (r['역번호'] ?? '').trim(), name: norm(r['역사명']), code: (r['노선번호'] ?? '').trim(),
      transfers: lineIdsFromTransferNames(r['환승노선명']), lat: Number(r['역위도']), lng: Number(r['역경도']),
    }))
    .filter((r) => r.no && r.name && Number.isFinite(r.lat) && Number.isFinite(r.lng) && inMetroArea(r.lat, r.lng));
  const stdByName = new Map();
  for (const r of std) {
    if (!stdByName.has(r.name)) stdByName.set(r.name, []);
    stdByName.get(r.name).push(r);
  }

  // 대상 노선의 (역명 → 노선 집합), 파일 순서 유지
  const groups = new Map();
  for (const r of urban) {
    if ((r['권역명'] ?? '').trim() !== '수도권') continue;
    const lineId = TARGET_LINES[(r['노선명'] ?? '').trim()];
    if (!lineId) continue;
    const name = norm(r['역명']);
    if (!groups.has(name)) groups.set(name, new Set());
    groups.get(name).add(lineId);
  }
  for (const e of extra) {
    const name = norm(e.name);
    if (!groups.has(name)) groups.set(name, new Set());
    groups.get(name).add(e.lineId);
  }

  const rows = existing.map((r) => ({ ...r }));
  const byName = new Map();
  for (const r of rows) {
    if (!byName.has(r.name)) byName.set(r.name, []);
    byName.get(r.name).push(r);
  }
  const usedIds = new Set(rows.map((r) => r.station_id));
  let nextAssigned = Math.max(ASSIGNED_MIN - 1, ...rows.map((r) => Number(r.station_id)).filter((n) => n >= ASSIGNED_MIN && n <= ASSIGNED_MAX)) + 1;

  const report = { migrated: [], patched: [], added: [], separate: [], assigned: [], missingStandard: [], mergedByNameOnly: [] };
  const added = [];

  for (const [name, lineIds] of groups) {
    const candidates = new Map(); // lineId → 표준데이터 행 | null
    for (const lineId of lineIds) {
      const row = (stdByName.get(name) ?? []).find((s) => STD_CODES_BY_LINE[lineId].includes(s.code)) ?? null;
      candidates.set(lineId, row);
      if (!row) report.missingStandard.push(`${name}(${lineId})`);
    }
    const found = [...candidates.values()].filter(Boolean);
    const sameRows = (byName.get(name) ?? []).filter((r) => isSamePhysicalStation(r, lineIds, found, stdByName.get(name) ?? []));
    // 표준데이터에 행이 아예 없는 역이 기존 역과 이름이 같으면 같은 역으로 본다 — 동명이역은 표준데이터에 두 행이 다 있어야 갈라낼 수 있고,
    // 이 경우(신길온천: 4호선·수인분당 공용 역)는 갈라낼 근거가 없다. 보고서에 남겨 검토하게 한다
    if (sameRows.length === 0 && found.length === 0 && (byName.get(name) ?? []).length === 1) {
      sameRows.push(byName.get(name)[0]);
      report.mergedByNameOnly.push({ id: sameRows[0].station_id, name, lineIds: [...lineIds] });
    }
    if (sameRows.length > 1) {
      throw new Error(`${name}: 같은 물리 역으로 판정된 기존 행이 둘 이상 — ${sameRows.map((r) => r.station_id).join(', ')}`);
    }

    if (sameRows.length === 1) {
      const row = sameRows[0];
      const before = row.station_id;
      // codes 는 "노선:코드;노선:코드". 없는 노선은 덧붙이고, 임시 부여 행처럼 "1075:" 로 코드가 비어 있던 노선은 표준 번호로 채운다
      const entries = row.codes.split(';').filter(Boolean).map((c) => {
        const [line, no = ''] = c.split(':');
        return [line.trim(), no.trim()];
      });
      const addedCodes = [];
      for (const [lineId, s] of candidates) {
        const entry = entries.find(([line]) => line === lineId);
        if (entry) {
          if (!entry[1] && s) {
            entry[1] = s.no;
            addedCodes.push(`${lineId}:${s.no}`);
          }
          continue;
        }
        entries.push([lineId, s ? s.no : '']);
        addedCodes.push(`${lineId}:${s ? s.no : ''}`);
      }
      row.codes = entries.map(([line, no]) => `${line}:${no}`).join(';');
      if (row.source === 'assigned') {
        const number = pickStationNumber(found.map((s) => s.no));
        if (number) {
          if (usedIds.has(number) && number !== row.station_id) throw new Error(`${name}: 이관할 역번호 ${number} 가 이미 쓰인다`);
          usedIds.delete(row.station_id);
          row.station_id = number;
          row.source = 'standard';
          usedIds.add(number);
          report.migrated.push({ from: before, to: number, name });
        }
      } else if (addedCodes.length > 0) {
        report.patched.push({ id: row.station_id, name, added: addedCodes });
      }
      continue;
    }

    // 새 물리 역 (기존에 같은 이름이 있으면 별개 역 = 동명이역)
    const number = pickStationNumber(found.map((s) => s.no));
    const id = number ?? String(nextAssigned++);
    if (usedIds.has(id)) throw new Error(`${name}: 새 역번호 ${id} 가 이미 쓰인다`);
    usedIds.add(id);
    const codes = [...candidates].sort(([a], [b]) => a.localeCompare(b)).map(([lineId, s]) => `${lineId}:${s ? s.no : ''}`).join(';');
    const row = { station_id: id, name, codes, source: number ? 'standard' : 'assigned' };
    added.push(row);
    byName.set(name, [...(byName.get(name) ?? []), row]);
    report.added.push({ id, name, codes });
    if ((byName.get(name) ?? []).length > 1) report.separate.push({ id, name, existing: byName.get(name).filter((r) => r !== row).map((r) => r.station_id) });
    if (!number) report.assigned.push({ id, name });
  }

  added.sort((a, b) => compareIds(a.station_id, b.station_id));
  return { rows: [...rows, ...added], report };
}

/**
 * 기존 행이 새 노선 역과 같은 물리 역인가. ① 임시 부여(assigned) 행은 그 이름의 코레일 전용 역이므로 같다.
 * ② 새 노선 쪽 표준데이터 역번호가 기존 행의 ID·코드와 같으면 같다 (1호선 코레일 구간 역).
 * ③ 새 노선 쪽 표준데이터 행의 환승노선에 기존 행의 노선이 있거나, 기존 역 쪽 표준데이터 행의 환승노선에 새 노선이 있으면 같다.
 * ④ 둘의 표준데이터 좌표가 500 m 이내면 같다. 모두 아니면 동명이역이다 (신촌 2호선 vs 경의중앙, 양평 5호선 vs 경의중앙).
 */
function isSamePhysicalStation(row, newLineIds, newStdRows, allStdRows) {
  if (row.source === 'assigned') return true;
  // 1호선 코레일 구간 역(회기 1015·광운대 1019·한대앞 1755)은 서울교통공사 시각표의 역사코드가 곧 코레일 역번호다 — 번호가 같으면 같은 역
  const existingNumbers = new Set([row.station_id, ...row.codes.split(';').map((c) => (c.split(':')[1] ?? '').trim()).filter(Boolean)]
    .flatMap((n) => (/^\d+$/.test(n) ? [n, String(Number(n))] : [n])));
  if (newStdRows.some((s) => existingNumbers.has(s.no) || (/^\d+$/.test(s.no) && existingNumbers.has(String(Number(s.no)))))) return true;
  const existingLines = new Set(linesOf(row.codes));
  for (const s of newStdRows) {
    if ([...s.transfers].some((l) => existingLines.has(l))) return true;
  }
  const existingStd = allStdRows.filter((s) => existingLines.has(STD_CODE_TO_LINE[s.code]));
  for (const s of existingStd) {
    if ([...s.transfers].some((l) => newLineIds.has(l))) return true;
  }
  for (const a of existingStd) {
    for (const b of newStdRows) {
      if (distanceMeters(a, b) <= SAME_STATION_METERS) return true;
    }
  }
  return false;
}
