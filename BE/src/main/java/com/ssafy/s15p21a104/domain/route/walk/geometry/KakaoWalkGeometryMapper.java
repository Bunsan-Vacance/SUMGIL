package com.ssafy.s15p21a104.domain.route.walk.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoLeg;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoRoute;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoStep;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * 카카오 도보 경로 응답을 우리 계약(MultiLineString)으로 변환한다.
 *
 * <p>순수 함수이며 HTTP·DB에 의존하지 않는다. {@code step} 하나를 LineString 하나로 담는다
 * (KTDB가 link 단위로 나누는 것과 같은 패턴, {@link MultiLineStringResponse} 참고).
 * 실패·빈 결과는 예외 없이 {@link Optional#empty()} — 호출 측이 "unavailable"로 처리한다.
 */
final class KakaoWalkGeometryMapper {

    private KakaoWalkGeometryMapper() {
    }

    static Optional<MultiLineStringResponse> toMultiLineString(KakaoWalkDirectionsResponse response) {
        if (response == null || !"OK".equals(response.status())) {
            return Optional.empty();
        }
        KakaoRoute route = response.route();
        if (route == null || route.legs() == null) {
            return Optional.empty();
        }
        List<List<List<Double>>> coordinates = new ArrayList<>();
        for (KakaoLeg leg : route.legs()) {
            if (leg.steps() == null) {
                continue;
            }
            for (KakaoStep step : leg.steps()) {
                List<List<Double>> points = step.path() == null ? null : step.path().points();
                if (points != null && points.size() >= 2) {
                    coordinates.add(points);
                }
            }
        }
        if (coordinates.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(MultiLineStringResponse.of(coordinates));
    }
}
