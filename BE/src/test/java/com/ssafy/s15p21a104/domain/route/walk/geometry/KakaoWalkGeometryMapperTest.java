package com.ssafy.s15p21a104.domain.route.walk.geometry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoLeg;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoPath;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoRoute;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoStep;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 실제 카카오 API 호출(2026-09-14)로 확인한 응답 스키마 기준.
 * {@code status: "OK"}, {@code route.legs[].steps[].path.points}가 [lng,lat] 쌍 배열.
 */
class KakaoWalkGeometryMapperTest {

    @Test
    @DisplayName("정상 응답의 step.path.points를 그대로 LineString으로 담는다")
    void 정상_응답_변환() {
        KakaoWalkDirectionsResponse response = new KakaoWalkDirectionsResponse("OK",
                new KakaoRoute(List.of(
                        new KakaoLeg(List.of(
                                new KakaoStep(new KakaoPath(
                                        List.of(List.of(126.99, 37.56), List.of(126.992, 37.562)))))))));

        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(response);

        assertTrue(result.isPresent());
        assertEquals("MultiLineString", result.get().type());
        assertEquals(List.of(List.of(126.99, 37.56), List.of(126.992, 37.562)),
                result.get().coordinates().get(0));
    }

    @Test
    @DisplayName("여러 leg·step은 각각 별도 LineString으로 담긴다")
    void 여러_구간은_별도_LineString() {
        KakaoWalkDirectionsResponse response = new KakaoWalkDirectionsResponse("OK",
                new KakaoRoute(List.of(
                        new KakaoLeg(List.of(
                                new KakaoStep(new KakaoPath(
                                        List.of(List.of(126.99, 37.56), List.of(126.992, 37.562)))),
                                new KakaoStep(new KakaoPath(
                                        List.of(List.of(126.993, 37.563), List.of(126.994, 37.564)))))))));

        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(response);

        assertTrue(result.isPresent());
        assertEquals(2, result.get().coordinates().size());
    }

    @Test
    @DisplayName("status가 OK가 아니면(경로 없음 등) 빈 값")
    void 실패상태는_빈값() {
        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(
                new KakaoWalkDirectionsResponse("NOT_FOUND", null));

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("route·legs가 없으면 빈 값")
    void route_없으면_빈값() {
        assertTrue(KakaoWalkGeometryMapper.toMultiLineString(
                new KakaoWalkDirectionsResponse("OK", null)).isEmpty());
        assertTrue(KakaoWalkGeometryMapper.toMultiLineString(null).isEmpty());
    }

    @Test
    @DisplayName("좌표 한 점뿐인 step은(선이 안 되므로) 제외한다")
    void 점_하나뿐인_step은_제외() {
        KakaoWalkDirectionsResponse response = new KakaoWalkDirectionsResponse("OK",
                new KakaoRoute(List.of(
                        new KakaoLeg(List.of(
                                new KakaoStep(new KakaoPath(List.of(List.of(126.99, 37.56)))))))));

        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(response);

        assertTrue(result.isEmpty());
    }
}
