package com.ssafy.s15p21a104.domain.route.bike;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 따릉이 재고 폴백 게이트. 순수 로직이며 DB에 접근하지 않는다.
 *
 * <p>예측 맵(대여소 ID → 예상 재고)이 비어 있으면 원천 없음으로 보고 기본 허용한다.
 * AI 산출물 연동 시 이 맵만 채우면 된다. 응답 스키마는 바꾸지 않는다.
 */
public final class BikeStockGate {

    private BikeStockGate() {
    }

    /**
     * 후보 legs가 재고 게이트를 통과하는지 판정한다.
     *
     * @param legs 후보 legs
     * @param predictedBikes 대여소별 예상 재고. 비어 있으면 원천 없음(허용)
     * @return BIKE leg 출발 대여소가 소진(0대 이하)이면 false, 그 외 true
     */
    public static boolean passes(List<RouteLegResponse> legs, Map<String, Integer> predictedBikes) {
        Objects.requireNonNull(legs, "legs");
        if (predictedBikes == null || predictedBikes.isEmpty()) {
            return true;
        }
        for (RouteLegResponse leg : legs) {
            if (leg.mode() != TravelMode.BIKE) {
                continue;
            }
            Integer bikes = predictedBikes.get(leg.fromNodeId());
            if (bikes != null && bikes <= 0) {
                return false;
            }
        }
        return true;
    }

    /**
     * 탐색 결과 엣지들이 재고 게이트를 통과하는지 판정한다.
     *
     * <p>BIKE 구간이 여러 엣지로 묶여 하나의 leg가 되면 경유 대여소가 leg 경계에
     * 나타나지 않는다. 엣지 단위 검사가 정확한 판정이다.
     *
     * @param fromNodes 엣지별 출발 정점 ID (순서대로)
     * @param modes 엣지별 수단 (순서대로, fromNodes와 같은 크기)
     * @param predictedBikes 대여소별 예상 재고. 비어 있으면 원천 없음(허용)
     * @return BIKE 엣지 출발 대여소가 소진(0대 이하)이면 false, 그 외 true
     */
    public static boolean passesEdges(
            List<String> fromNodes, List<TravelMode> modes, Map<String, Integer> predictedBikes) {
        Objects.requireNonNull(fromNodes, "fromNodes");
        Objects.requireNonNull(modes, "modes");
        if (predictedBikes == null || predictedBikes.isEmpty()) {
            return true;
        }
        for (int i = 0; i < fromNodes.size() && i < modes.size(); i++) {
            if (modes.get(i) != TravelMode.BIKE) {
                continue;
            }
            Integer bikes = predictedBikes.get(fromNodes.get(i));
            if (bikes != null && bikes <= 0) {
                return false;
            }
        }
        return true;
    }
}
