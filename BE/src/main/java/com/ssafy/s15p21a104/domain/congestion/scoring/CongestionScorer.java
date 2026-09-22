package com.ssafy.s15p21a104.domain.congestion.scoring;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 경로 후보(leg 목록)의 혼잡도 점수를 계산한다(S15P21A104-157, 원래 S15P21A104-153 범위).
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다 — 이미 조회된 노선별 혼잡도(정원 대비 %,
 * 100을 넘을 수 있다)를 인자로 받는다. 새 탐색 알고리즘이 아니라, 이미 나온 최단경로
 * 후보군을 재정렬하는 데만 쓴다({@link com.ssafy.s15p21a104.domain.route.service.RouteSearchService}
 * 참고, 최단경로 알고리즘 자체는 건드리지 않는다).
 *
 * <p>SUBWAY leg만 대상으로 한다 — 혼잡도 데이터가 있는 게 지하철 노선(LINE)뿐이다
 * (버스는 아직 산출물 없음, S15P21A104-151). 소요시간(minutes) 가중 평균을 쓴다 — 오래
 * 머무는 구간의 혼잡도가 점수에 더 크게 반영돼야 한다.
 */
public final class CongestionScorer {

    private CongestionScorer() {
    }

    /**
     * @param legs leg 목록(경로 후보 하나)
     * @param lineCongestionByRouteId 노선 ID(routeId) → 해당 시간대 혼잡도(정원 대비 %). 모르는
     *         노선은 맵에 없어야 한다(0으로 채우지 않는다 — 값을 지어내지 않는다는 원칙)
     * @return 소요시간 가중 평균 혼잡도. 혼잡도를 아는 SUBWAY leg가 하나도 없으면(전부 다른
     *         수단이거나 노선 정보가 없으면) 빈 값 — 이 경로는 혼잡도 기준으로 비교할 수 없다는 뜻이다
     */
    public static Optional<Double> score(List<RouteLegResponse> legs, Map<String, Double> lineCongestionByRouteId) {
        double weightedSum = 0;
        double knownMinutes = 0;
        for (RouteLegResponse leg : legs) {
            if (leg.mode() != TravelMode.SUBWAY || leg.routeId() == null) {
                continue;
            }
            Double level = lineCongestionByRouteId.get(leg.routeId());
            if (level == null) {
                continue;
            }
            // 대기 분리(2026-09-22) 후에도 가중치 합은 종전과 같게 유지한다(분리 전 minutes와 동일).
            double legMinutes = leg.minutes() + (leg.waitMinutes() == null ? 0 : leg.waitMinutes());
            weightedSum += level * legMinutes;
            knownMinutes += legMinutes;
        }
        if (knownMinutes <= 0) {
            return Optional.empty();
        }
        return Optional.of(weightedSum / knownMinutes);
    }
}
