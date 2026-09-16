// 역 ID 매핑 표(data/subway/conf/station-ids.csv) 생성 규칙.
// station_id = 물리 역(정규화 역명)에 붙은 서울교통공사 노선별 역사코드 중 최솟값, 앞의 0 제거 (지하철혼잡도정보의 역번호 표기: 서울역 150).
// 코드가 없는 코레일 전용 역은 9001부터 이름순으로 부여한다. 표는 한 번 커밋되면 정본이다 — 다시 생성해 덮어쓰지 않는다.

const ASSIGNED_START = 9001;

/** 노선별 코드 목록 → 역 번호. 앞의 0 을 뗀 가장 작은 번호. 비어 있으면 null. */
export function stationNumber(codes) {
  const nums = codes.map((c) => String(Number(c))).filter((c) => c !== 'NaN');
  if (nums.length === 0) return null;
  return nums.sort((a, b) => Number(a) - Number(b))[0];
}

/**
 * @param timetableRows {line, code, name}[] — 시각표의 (호선 → line_id, 역사코드, 정규화 역명), 중복 허용
 * @param extra {name, line}[] — 시각표에 없는 역 (코레일 전용). 시각표에 있는 이름은 무시한다
 * @returns {{station_id, name, codes, source}[]} station_id 숫자순
 */
export function buildStationIdTable(timetableRows, extra) {
  const byName = new Map();
  for (const r of timetableRows) {
    if (!byName.has(r.name)) byName.set(r.name, new Map());
    byName.get(r.name).set(r.line, r.code);
  }
  const rows = [];
  for (const [name, lines] of byName) {
    const entries = [...lines.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    rows.push({
      station_id: stationNumber(entries.map(([, c]) => c)),
      name,
      codes: entries.map(([l, c]) => `${l}:${c}`).join(';'),
      source: 'timetable',
    });
  }
  const extraNames = [...new Map(extra.filter((e) => !byName.has(e.name)).map((e) => [e.name, e])).values()]
    .sort((a, b) => a.name.localeCompare(b.name, 'ko'));
  extraNames.forEach((e, i) => rows.push({ station_id: String(ASSIGNED_START + i), name: e.name, codes: `${e.line}:`, source: 'assigned' }));

  const seen = new Map();
  for (const r of rows) {
    if (seen.has(r.station_id)) throw new Error(`station_id 가 겹침: ${r.station_id} (${seen.get(r.station_id)} / ${r.name})`);
    seen.set(r.station_id, r.name);
  }
  return rows.sort((a, b) => Number(a.station_id) - Number(b.station_id));
}
