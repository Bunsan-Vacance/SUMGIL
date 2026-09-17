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
 * 도착정보 API 가 응답하는 일반 정류소인가. NODE_ID 4~6자리가 `000` 이면 일반, `900` 이면 마을버스 전용이다.
 *
 * 2026-09-17 실측 근거 — 수신에 성공한 노선은 지나는 정류소 중 `900` 패턴이 평균 1% 였고,
 * 실패한 노선은 65% 였다. `900` 정류소를 직접 부르면 대부분 `headerCd 4 · itemList null`(결과 없음)이 온다.
 * 마을버스가 이 API 에서 안 나오는 이유가 노선 종류가 아니라 **정류소 체계**라는 뜻이다.
 */
export const GENERAL_STOP = (stopId) => String(stopId).slice(3, 6) === '000';

/**
 * 노선을 모두 덮는 정류소를 그리디로 고른다.
 *
 * 최소 집합 덮기는 NP-hard 라 최적해를 구하지 않는다. 매번 "아직 안 덮은 노선을 가장 많이 덮는 정류소"를 고르는
 * 그리디로 충분하다 — 목적이 최적화가 아니라 **호출 수를 노선 수(718)보다 확실히 줄이는 것**이기 때문이다.
 * 동점은 정류소 ID 오름차순으로 가른다. 같은 입력이면 같은 결과가 나와야 수집을 재현할 수 있다.
 *
 * <b>한 번으로 다 받지 못한다.</b> 이 표는 "이 노선이 이 정류소를 지난다" 는 정적 사실인데 API 는
 * "지금 이 정류소에 오는 버스" 를 준다. 그 시각에 운행하지 않는 노선은 응답에 아예 없고, 아무 버스도 없는
 * 정류소는 {@code headerCd 4 · itemList null} 로 빈 응답을 준다 (2026-09-17 실측: 178콜 중 39곳이 빈 응답,
 * 노선 718 중 451 만 수신). 그래서 <b>못 받은 노선만 좁혀 다시 도는 2차 수집</b>을 전제로 만든다.
 *
 * @param {{routeId: string, stopId: string}[]} pairs 노선-정류소 표 (원천 CSV 의 ROUTE_ID · NODE_ID)
 * @param {{only?: string[], skipStops?: string[]}} [opts]
 *   only 를 주면 그 노선만 대상으로 한다(이미 받은 노선은 다시 부르지 않는다).
 *   skipStops 는 빈 응답이었던 정류소 — 다시 고르지 않는다.
 * @returns {{stops: string[], uncovered: string[]}} 고른 정류소(고른 순서)와 어느 정류소에도 없는 노선
 */
export function coverStops(pairs, opts = {}) {
  const only = opts.only ? new Set(opts.only) : null;
  const skip = new Set(opts.skipStops ?? []);
  const routesOfStop = new Map();
  const allRoutes = new Set();
  const routesWithStop = new Set();

  for (const { routeId, stopId } of pairs) {
    if (!routeId) continue;
    if (only && !only.has(routeId)) continue;
    allRoutes.add(routeId);
    if (!stopId || skip.has(stopId)) continue;
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
 * 노선마다 정류소를 하나씩 고른다. 이미 고른 정류소가 다른 노선도 덮으면 재사용한다.
 *
 * {@link coverStops} 의 그리디는 "가장 많은 노선을 덮는 정류소" 부터 고르는데, 그런 곳은 간선이 몰리는
 * **큰 환승 거점**이다. 그래서 정류소를 적게 지나는 노선(마을버스처럼 동네 안에서만 도는 것)이 계속 빠진다 —
 * 2026-09-17 실측으로 받은 노선은 평균 70정류소, 못 받은 노선은 평균 36정류소였다.
 * 못 받은 노선을 확실히 덮으려면 호출 수를 줄이는 대신 **노선당 한 곳**을 집는다.
 *
 * @param {{routeId: string, stopId: string}[]} pairs
 * @param {{only?: string[], skipStops?: string[], stopFilter?: (stopId: string) => boolean}} [opts]
 *   stopFilter 로 부를 수 있는 정류소만 남긴다 — 마을버스 전용 정류소(NODE_ID 4~6자리가 900)는
 *   도착정보 API 가 빈 응답을 준다 ({@link GENERAL_STOP} 참고).
 * @returns {{stops: string[], uncovered: string[]}}
 */
export function oneStopPerRoute(pairs, opts = {}) {
  const only = opts.only ? new Set(opts.only) : null;
  const skip = new Set(opts.skipStops ?? []);
  const keep = opts.stopFilter ?? (() => true);
  const stopsOfRoute = new Map();

  for (const { routeId, stopId } of pairs) {
    if (!routeId) continue;
    if (only && !only.has(routeId)) continue;
    if (!stopsOfRoute.has(routeId)) stopsOfRoute.set(routeId, new Set());
    if (stopId && !skip.has(stopId) && keep(stopId)) stopsOfRoute.get(routeId).add(stopId);
  }

  const chosen = new Set();
  const uncovered = [];
  // 노선 ID 순으로 돌아 결과를 결정적으로 만든다. 입력 순서가 달라도 같은 CSV 가 나와야 한다.
  for (const routeId of [...stopsOfRoute.keys()].sort()) {
    const candidates = [...stopsOfRoute.get(routeId)].sort();
    if (candidates.length === 0) {
      uncovered.push(routeId);
      continue;
    }
    // 이미 부르기로 한 정류소가 이 노선도 지나면 그것으로 충분하다 — 호출을 늘리지 않는다.
    if (candidates.some((s) => chosen.has(s))) continue;
    chosen.add(candidates[0]);
  }

  return { stops: [...chosen], uncovered };
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
