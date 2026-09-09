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
}
