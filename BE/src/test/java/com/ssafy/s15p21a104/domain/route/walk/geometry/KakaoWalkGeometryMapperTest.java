package com.ssafy.s15p21a104.domain.route.walk.geometry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoRoad;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoRoute;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsResponse.KakaoSection;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class KakaoWalkGeometryMapperTest {

    @Test
    @DisplayName("정상 응답의 평탄 vertexes를 [lng,lat] 쌍으로 묶어 MultiLineString으로 만든다")
    void 정상_응답_변환() {
        KakaoWalkDirectionsResponse response = new KakaoWalkDirectionsResponse(List.of(
                new KakaoRoute(0, List.of(
                        new KakaoSection(List.of(
                                new KakaoRoad(List.of(126.99, 37.56, 126.992, 37.562))))))));

        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(response);

        assertTrue(result.isPresent());
        assertEquals("MultiLineString", result.get().type());
        assertEquals(List.of(List.of(126.99, 37.56), List.of(126.992, 37.562)),
                result.get().coordinates().get(0));
    }

    @Test
    @DisplayName("여러 section·road는 각각 별도 LineString으로 담긴다")
    void 여러_구간은_별도_LineString() {
        KakaoWalkDirectionsResponse response = new KakaoWalkDirectionsResponse(List.of(
                new KakaoRoute(0, List.of(
                        new KakaoSection(List.of(
                                new KakaoRoad(List.of(126.99, 37.56, 126.992, 37.562)))),
                        new KakaoSection(List.of(
                                new KakaoRoad(List.of(126.993, 37.563, 126.994, 37.564))))))));

        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(response);

        assertTrue(result.isPresent());
        assertEquals(2, result.get().coordinates().size());
    }

    @Test
    @DisplayName("result_code가 0이 아니면(경로 없음 등) 빈 값")
    void 실패코드는_빈값() {
        KakaoWalkDirectionsResponse response = new KakaoWalkDirectionsResponse(List.of(
                new KakaoRoute(1, List.of())));

        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(response);

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("routes가 비어있으면 빈 값")
    void routes_없으면_빈값() {
        assertTrue(KakaoWalkGeometryMapper.toMultiLineString(
                new KakaoWalkDirectionsResponse(List.of())).isEmpty());
        assertTrue(KakaoWalkGeometryMapper.toMultiLineString(null).isEmpty());
    }

    @Test
    @DisplayName("좌표 한 점뿐인 road는(선이 안 되므로) 제외한다")
    void 점_하나뿐인_road는_제외() {
        KakaoWalkDirectionsResponse response = new KakaoWalkDirectionsResponse(List.of(
                new KakaoRoute(0, List.of(
                        new KakaoSection(List.of(
                                new KakaoRoad(List.of(126.99, 37.56))))))));

        Optional<MultiLineStringResponse> result = KakaoWalkGeometryMapper.toMultiLineString(response);

        assertTrue(result.isEmpty());
    }
}
