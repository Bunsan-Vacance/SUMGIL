package com.ssafy.s15p21a104.domain.route.walk.geometry;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoRoad;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoRoute;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoSection;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * 카카오 도보 경로 응답을 우리 계약(MultiLineString)으로 변환한다.
 *
 * <p>순수 함수이며 HTTP·DB에 의존하지 않는다. {@code road} 하나를 LineString 하나로 담는다
 * (KTDB가 link 단위로 나누는 것과 같은 패턴, {@link MultiLineStringResponse} 참고).
 * 실패·빈 결과는 예외 없이 {@link Optional#empty()} — 호출 측이 "unavailable"로 처리한다.
 */
final class KakaoWalkGeometryMapper {

    private KakaoWalkGeometryMapper() {
    }

    static Optional<MultiLineStringResponse> toMultiLineString(KakaoWalkDirectionsResponse response) {
        if (response == null || response.routes() == null || response.routes().isEmpty()) {
            return Optional.empty();
        }
        KakaoRoute route = response.routes().get(0);
        if (route.resultCode() != null && route.resultCode() != 0) {
            return Optional.empty();
        }
        if (route.sections() == null) {
            return Optional.empty();
        }
        List<List<List<Double>>> coordinates = new ArrayList<>();
        for (KakaoSection section : route.sections()) {
            if (section.roads() == null) {
                continue;
            }
            for (KakaoRoad road : section.roads()) {
                List<List<Double>> line = toLine(road.vertexes());
                if (line.size() >= 2) {
                    coordinates.add(line);
                }
            }
        }
        if (coordinates.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(MultiLineStringResponse.of(coordinates));
    }

    /** 평탄 배열 [lng,lat,lng,lat,...]을 [[lng,lat],...]으로 묶는다. 홀수 개면 마지막 낙오값은 버린다. */
    private static List<List<Double>> toLine(List<Double> vertexes) {
        List<List<Double>> line = new ArrayList<>();
        if (vertexes == null) {
            return line;
        }
        for (int i = 0; i + 1 < vertexes.size(); i += 2) {
            line.add(List.of(vertexes.get(i), vertexes.get(i + 1)));
        }
        return line;
    }
}
