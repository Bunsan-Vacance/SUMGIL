package com.ssafy.s15p21a104.domain.route.walk.geometry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-216 후속: 지오메트리 캐시 키에 좌표가 포함돼야 한다.
 * 노드 ID만 키로 쓰면 임시 장소 노드(PLACE-ORIGIN/PLACE-DEST)에서 요청 간 오염이 생긴다.
 */
class WalkGeometryRegistryTest {

    private static MultiLineStringResponse geo(double secondLng) {
        return MultiLineStringResponse.of(
                List.of(List.of(List.of(127.0, 37.5), List.of(secondLng, 37.5))));
    }

    @Test
    @DisplayName("같은 노드 ID라도 좌표가 다르면 따로 조회한다 (요청 간 캐시 오염 방지)")
    void 다른좌표_따로조회() {
        KakaoWalkDirectionsClient client = mock(KakaoWalkDirectionsClient.class);
        when(client.fetchGeometry(anyDouble(), anyDouble(), anyDouble(), anyDouble()))
                .thenReturn(Optional.of(geo(127.01)), Optional.of(geo(127.02)));
        WalkGeometryRegistry registry = new WalkGeometryRegistry(client);

        Optional<MultiLineStringResponse> first =
                registry.geometryFor("PLACE-ORIGIN", "PLACE-DEST", 37.5, 127.0, 37.5, 127.01);
        Optional<MultiLineStringResponse> second =
                registry.geometryFor("PLACE-ORIGIN", "PLACE-DEST", 37.5, 127.1, 37.5, 127.2);

        verify(client, times(2)).fetchGeometry(anyDouble(), anyDouble(), anyDouble(), anyDouble());
        assertEquals(127.01, first.orElseThrow().coordinates().get(0).get(1).get(0), 1e-9);
        assertEquals(127.02, second.orElseThrow().coordinates().get(0).get(1).get(0), 1e-9);
    }

    @Test
    @DisplayName("같은 노드 ID·같은 좌표는 캐시에서 돌려준다 (조회 1회)")
    void 같은좌표_캐시() {
        KakaoWalkDirectionsClient client = mock(KakaoWalkDirectionsClient.class);
        when(client.fetchGeometry(anyDouble(), anyDouble(), anyDouble(), anyDouble()))
                .thenReturn(Optional.of(geo(127.01)));
        WalkGeometryRegistry registry = new WalkGeometryRegistry(client);

        registry.geometryFor("A", "B", 37.5, 127.0, 37.5, 127.01);
        registry.geometryFor("A", "B", 37.5, 127.0, 37.5, 127.01);

        verify(client, times(1)).fetchGeometry(anyDouble(), anyDouble(), anyDouble(), anyDouble());
    }
}
