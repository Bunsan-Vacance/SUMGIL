package com.ssafy.s15p21a104.domain.congestion.scoring;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 경로 후보(leg 목록)의 혼잡도 폴백 점수를 계산한다(S15P21A104-157, 원래 S15P21A104-153 범위).
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다. 이미 조회된 노선별 혼잡도(정원 대비 %, 100을
 * 넘을 수 있다)를 인자로 받는다. 링크 단위 예측({@link LinkCongestionScorer})이 하나도 없을 때만
 * 쓰는 노선(LINE) 통계 폴백이다.
 *
 * <p>SUBWAY leg만 대상으로 한다. 점수는 "가장 혼잡한 leg"의 값(최대)이다(2026-09-22 표시·정렬
 * 기준 변경 — 종전 시간 가중 평균은 순위와 표시를 어긋나게 했다). 어떤 leg에서 나온 값인지는
 * {@link Worst#leg()}로 표시 계층에 넘긴다.
 */
public final class CongestionScorer {

    private CongestionScorer() {
    }

    /**
     * @param level 가장 혼잡한 SUBWAY leg의 혼잡도(정원 대비 %)
     * @param leg 그 값을 가진 leg(표시용)
     */
    public record Worst(double level, RouteLegResponse leg) {
    }

    /**
     * @param legs leg 목록(경로 후보 하나)
     * @param lineCongestionByRouteId 노선 ID(routeId) → 해당 시간대 혼잡도(정원 대비 %). 모르는
     *         노선은 맵에 없어야 한다(0으로 채우지 않는다 — 값을 지어내지 않는다는 원칙)
     * @return 가장 혼잡한 leg의 값과 leg. 혼잡도를 아는 SUBWAY leg가 하나도 없으면(전부 다른
     *         수단이거나 노선 정보가 없으면) 빈 값 — 이 경로는 혼잡도 기준으로 비교할 수 없다는 뜻이다
     */
    public static Optional<Worst> worst(List<RouteLegResponse> legs, Map<String, Double> lineCongestionByRouteId) {
        Worst worst = null;
        for (RouteLegResponse leg : legs) {
            if (leg.mode() != TravelMode.SUBWAY || leg.routeId() == null) {
                continue;
            }
            Double level = lineCongestionByRouteId.get(leg.routeId());
            if (level == null) {
                continue;
            }
            if (worst == null || level > worst.level()) {
                worst = new Worst(level, leg);
            }
        }
        return Optional.ofNullable(worst);
    }
}
