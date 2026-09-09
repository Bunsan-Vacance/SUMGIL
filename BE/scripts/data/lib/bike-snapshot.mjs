// bikeList(실시간 대여정보) 여러 페이지를 대여소 마스터 스냅샷 행으로 합친다.
// 값은 API 가 준 그대로 두고 열 순서만 고정한다. 이름 접두어("102. ") 분리는 Java 로더(BikeStationParser)가 한다.

/** API 필드명을 그대로 열 이름으로 쓴다. 첫 열 stationId 가 bike_station.rental_id 가 된다. */
export const SNAPSHOT_FIELDS = [
  'stationId', 'stationName', 'stationLatitude', 'stationLongitude', 'rackTotCnt', 'parkingBikeTotCnt', 'shared',
];

/**
 * @param {object[][]} pages 페이지별 row 배열 (호출 순서대로)
 * @returns {string[][]} SNAPSHOT_FIELDS 순서의 문자열 행. 없는 필드는 '' (값을 만들어 넣지 않는다)
 */
export function mergePages(pages) {
  const seen = new Set();
  const out = [];
  pages.forEach((rows, p) => {
    rows.forEach((row, i) => {
      const id = row?.stationId;
      if (!id) throw new Error(`stationId 가 없는 행: 페이지 ${p + 1}, ${i + 1}번째`);
      if (seen.has(id)) throw new Error(`stationId 중복: ${id} (페이지 ${p + 1}) — 페이지 범위가 겹친 호출`);
      seen.add(id);
      out.push(SNAPSHOT_FIELDS.map((f) => (row[f] === undefined || row[f] === null ? '' : String(row[f]))));
    });
  });
  return out;
}
