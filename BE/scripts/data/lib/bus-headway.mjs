// 버스 배차간격 수집의 순수 로직. 호출·파일 쓰기는 진입점(bus-headway-fetch.mjs)이 한다.
//
// 원천은 도착정보(공공데이터포털 15000314) 다. 노선정보조회(15000193)는 우리 키로 안 열린다
// (401 등록되지 않은 서비스키 — 포털은 서비스마다 활용신청이 따로다. api-survey.md 4절 결정 7).
// 도착정보는 **정류소 단위** 호출인데 응답에 그 정류소를 지나는 노선이 모두 딸려 오므로,
// 노선을 다 덮는 최소 정류소 집합을 골라 호출 수를 줄인다.

/** CSV 열 순서. 원천 필드명을 그대로 쓰고 관측 정류소·제공시각을 덧붙인다. */
export const HEADWAY_FIELDS = [
  'busRouteId', 'rtNm', 'term', 'firstTm', 'lastTm', 'routeType', 'observedStId', 'mkTm',
];

const TERM = HEADWAY_FIELDS.indexOf('term');
const OBSERVED = HEADWAY_FIELDS.indexOf('observedStId');

/**
 * 노선을 모두 덮는 정류소를 그리디로 고른다.
 *
 * 최소 집합 덮기는 NP-hard 라 최적해를 구하지 않는다. 매번 "아직 안 덮은 노선을 가장 많이 덮는 정류소"를 고르는
 * 그리디로 충분하다 — 목적이 최적화가 아니라 **호출 수를 노선 수(718)보다 확실히 줄이는 것**이기 때문이다.
 * 동점은 정류소 ID 오름차순으로 가른다. 같은 입력이면 같은 결과가 나와야 수집을 재현할 수 있다.
 *
 * @param {{routeId: string, stopId: string}[]} pairs 노선-정류소 표 (원천 CSV 의 ROUTE_ID · NODE_ID)
 * @returns {{stops: string[], uncovered: string[]}} 고른 정류소(고른 순서)와 어느 정류소에도 없는 노선
 */
export function coverStops(pairs) {
  const routesOfStop = new Map();
  const allRoutes = new Set();
  const routesWithStop = new Set();

  for (const { routeId, stopId } of pairs) {
    if (!routeId) continue;
    allRoutes.add(routeId);
    if (!stopId) continue;
    routesWithStop.add(routeId);
    if (!routesOfStop.has(stopId)) routesOfStop.set(stopId, new Set());
    routesOfStop.get(stopId).add(routeId);
  }

  const uncovered = [...allRoutes].filter((r) => !routesWithStop.has(r)).sort();
  const remaining = new Set(routesWithStop);
  const stops = [];

  while (remaining.size > 0) {
    let best = null;
    let bestGain = 0;
    // 동점이면 정류소 ID 가 작은 쪽. Map 순회 순서(삽입 순)에 기대지 않는다.
    for (const stopId of [...routesOfStop.keys()].sort()) {
      let gain = 0;
      for (const r of routesOfStop.get(stopId)) if (remaining.has(r)) gain += 1;
      if (gain > bestGain) {
        bestGain = gain;
        best = stopId;
      }
    }
    if (best === null) break;
    stops.push(best);
    for (const r of routesOfStop.get(best)) remaining.delete(r);
  }

  return { stops, uncovered };
}

/**
 * 도착정보 응답의 노선 목록 → CSV 행. 값은 손대지 않는다.
 * <b>term 0 을 비우지 않는다</b> — 0("지금 운행 중이 아니라 모른다")과 결측(빈 칸)은 다르고,
 * 0 → NULL 변환은 자바 로더가 한다. CSV 만 보고도 둘을 가를 수 있어야 한다.
 *
 * @param {object[]} apiRows parseResponse('bus', body).rows (1건이어도 배열로 온다)
 * @param {string} stId 이 응답을 받은 정류소 — 어디서 받은 값인지 추적한다
 */
export function toHeadwayRows(apiRows, stId) {
  return apiRows.map((row, i) => {
    if (!row?.busRouteId) {
      throw new Error(`busRouteId 가 없는 행: 정류소 ${stId}, ${i + 1}번째`);
    }
    return HEADWAY_FIELDS.map((f) => {
      if (f === 'observedStId') return String(stId);
      const v = row[f];
      return v === undefined || v === null ? '' : String(v);
    });
  });
}

/**
 * 같은 노선이 여러 정류소에서 오므로 노선당 한 행으로 합친다.
 * - 한쪽이 0 이면 0 이 아닌 값을 쓴다 (운행 중인 정류소에서 받은 값이 낫다)
 * - 둘 다 0 이 아닌데 다르면 <b>충돌로 남기고 먼저 본 값</b>을 쓴다.
 *   09-08 과 09-17 관측에서 term 이 9일간 바뀌지 않았으므로 드물 것으로 보지만, 나면 알아야 한다.
 *
 * @returns {{rows: string[][], conflicts: string[]}} 노선 ID 순으로 정렬된 행과 충돌 설명
 */
export function mergeByRoute(allRows) {
  const byRoute = new Map();
  const conflicts = [];

  for (const row of allRows) {
    const routeId = row[0];
    const prev = byRoute.get(routeId);
    if (!prev) {
      byRoute.set(routeId, row);
      continue;
    }
    const prevTerm = Number(prev[TERM]) || 0;
    const nextTerm = Number(row[TERM]) || 0;
    if (prevTerm === nextTerm) continue;
    if (prevTerm === 0) {
      byRoute.set(routeId, row);
      continue;
    }
    if (nextTerm === 0) continue;
    conflicts.push(
      `노선 ${routeId}: 정류소 ${prev[OBSERVED]} 에서 ${prevTerm}분, ${row[OBSERVED]} 에서 ${nextTerm}분 — 먼저 본 ${prevTerm} 을 쓴다`,
    );
  }

  const rows = [...byRoute.keys()].sort().map((k) => byRoute.get(k));
  return { rows, conflicts };
}
