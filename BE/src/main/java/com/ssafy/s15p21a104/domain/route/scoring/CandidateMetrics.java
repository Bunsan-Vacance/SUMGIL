package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;

/**
 * 후보 파생 메트릭(5부 C6, 티켓 `route-heuristic-cost-layer`) — 도보/자전거 분, 대여 행위 수, 환승 수.
 *
 * <p><b>후처리 전용</b>이다. 탐색 라벨·핫루프에 넣지 않는다(스칼라 비용 함수가 탐색을 담당,
 * 이 값은 필터·랭킹·골든 검증용). 원본 데이터는 legs뿐이라 저장 없이 즉시 파생한다.
 *
 * <p>대여 행위(act) 수는 BIKE leg 수로 센다 — 응답 계약에서 연속 BIKE 연결이
 * "대여~반납 1 leg"로 합쳐지기 때문(로드맵 1단계).
 */
public record CandidateMetrics(double walkMinutes, double bikeMinutes, int rentalActs, int transfers) {

    /** 응답 후보에서 파생한다. */
    public static CandidateMetrics of(RouteSearchResponse response) {
        return of(response.legs());
    }

    /** legs에서 파생한다. minutes가 null인 leg는 0으로 본다(선택 필드 아님 — 방어). */
    public static CandidateMetrics of(List<RouteLegResponse> legs) {
        double walk = 0;
        double bike = 0;
        int rentals = 0;
        int transfers = 0;
        for (RouteLegResponse leg : legs) {
            double minutes = leg.minutes() == null ? 0 : leg.minutes();
            if (leg.mode() == TravelMode.WALK) {
                walk += minutes;
            } else if (leg.mode() == TravelMode.BIKE) {
                bike += minutes;
                rentals++;
            } else if (leg.mode() == TravelMode.TRANSFER) {
                transfers++;
            }
        }
        return new CandidateMetrics(walk, bike, rentals, transfers);
    }
}
