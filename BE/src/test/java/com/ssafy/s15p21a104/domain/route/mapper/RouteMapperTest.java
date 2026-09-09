package com.ssafy.s15p21a104.domain.route.mapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.EnginePath;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.EngineSegment;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.StationInfo;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-98 매퍼 검증. 가짜 엔진 결과를 주입하므로 DB가 필요 없다.
 */
class RouteMapperTest {

    /** 분 단위 부동소수 허용 오차. */
    private static final double TOLERANCE = 1e-9;

    private Map<String, StationInfo> stations;

    @BeforeEach
    void setUp() {
        stations = Map.of(
                "1001", new StationInfo("1001", "기점역", 37.5000, 127.0000),
                "1002", new StationInfo("1002", "환승역", 37.5100, 127.0100),
                "1004", new StationInfo("1004", "중간역", 37.5150, 127.0150),
                "1003", new StationInfo("1003", "종점역", 37.5200, 127.0200)
        );
    }

    @Test
    @DisplayName("98-T1: 환승 1회 경로는 노선 경계로 2개 구간으로 나뉜다")
    void 환승_1회_경로는_2개_구간으로_나뉜다() {
        EnginePath enginePath = new EnginePath(List.of(
                new EngineSegment("1001", "1002", "2", 300),
                new EngineSegment("1002", "1003", "7", 420)
        ), 720, 1);

        RouteSearchResponse response = RouteMapper
                .toResponse(enginePath, stations, RouteType.SHORTEST, RouteSource.MOCK)
                .orElseThrow();

        assertEquals(RouteType.SHORTEST, response.routeType());
        assertEquals(RouteSource.MOCK, response.source());
        assertEquals(2, response.legs().size());
        assertEquals("1001", response.legs().get(0).fromNodeId());
        assertEquals("1002", response.legs().get(0).toNodeId());
        assertEquals("2", response.legs().get(0).routeId());
        assertEquals("1002", response.legs().get(1).fromNodeId());
        assertEquals("1003", response.legs().get(1).toNodeId());
        assertEquals("7", response.legs().get(1).routeId());
        assertTrue(response.legs().stream().allMatch(leg -> leg.mode() == TravelMode.SUBWAY));
    }

    @Test
    @DisplayName("98-T2: 구간 분 합이 전체 분과 허용 오차 안에서 같다")
    void 구간_분_합이_전체_분과_같다() {
        EnginePath enginePath = new EnginePath(List.of(
                new EngineSegment("1001", "1002", "2", 200),
                new EngineSegment("1002", "1003", "7", 520)
        ), 720, 1);

        RouteSearchResponse response = RouteMapper
                .toResponse(enginePath, stations, RouteType.SHORTEST, RouteSource.MOCK)
                .orElseThrow();

        assertEquals(720 / 60.0, response.totalMinutes(), TOLERANCE);
        double sum = response.legs().stream().mapToDouble(leg -> leg.minutes()).sum();
        assertEquals(response.totalMinutes(), sum, TOLERANCE);
    }

    @Test
    @DisplayName("98-T3: 환승 2회 경로는 3개 구간으로 나뉜다")
    void 환승_2회_경로는_3개_구간으로_나뉜다() {
        EnginePath enginePath = new EnginePath(List.of(
                new EngineSegment("1001", "1002", "2", 180),
                new EngineSegment("1002", "1004", "7", 240),
                new EngineSegment("1004", "1003", "5", 300)
        ), 720, 2);

        // 출처가 고정값이 아니라 주입값 그대로 반영되는지 함께 확인한다.
        RouteSearchResponse response = RouteMapper
                .toResponse(enginePath, stations, RouteType.SHORTEST, RouteSource.ALGORITHM)
                .orElseThrow();

        assertEquals(RouteSource.ALGORITHM, response.source());
        assertEquals(3, response.legs().size());
        assertEquals("2", response.legs().get(0).routeId());
        assertEquals("7", response.legs().get(1).routeId());
        assertEquals("5", response.legs().get(2).routeId());
        assertEquals("1001", response.legs().get(0).fromNodeId());
        assertEquals("1002", response.legs().get(0).toNodeId());
        assertEquals("1002", response.legs().get(1).fromNodeId());
        assertEquals("1004", response.legs().get(1).toNodeId());
        assertEquals("1004", response.legs().get(2).fromNodeId());
        assertEquals("1003", response.legs().get(2).toNodeId());
    }

    @Test
    @DisplayName("98-T4: 역 이름·좌표와 노선 ID가 정확히 매핑된다")
    void 역_이름_좌표_노선_ID가_정확하다() {
        EnginePath enginePath = new EnginePath(List.of(
                new EngineSegment("1001", "1002", "2", 300),
                new EngineSegment("1002", "1003", "7", 420)
        ), 720, 1);

        RouteSearchResponse response = RouteMapper
                .toResponse(enginePath, stations, RouteType.SHORTEST, RouteSource.MOCK)
                .orElseThrow();

        assertEquals("기점역", response.legs().get(0).fromNodeName());
        assertEquals("환승역", response.legs().get(0).toNodeName());
        assertEquals(37.5000, response.legs().get(0).fromLat(), TOLERANCE);
        assertEquals(127.0000, response.legs().get(0).fromLng(), TOLERANCE);
        assertEquals(37.5100, response.legs().get(0).toLat(), TOLERANCE);
        assertEquals(127.0100, response.legs().get(0).toLng(), TOLERANCE);
        assertEquals("환승역", response.legs().get(1).fromNodeName());
        assertEquals("종점역", response.legs().get(1).toNodeName());
        assertEquals(37.5100, response.legs().get(1).fromLat(), TOLERANCE);
        assertEquals(127.0100, response.legs().get(1).fromLng(), TOLERANCE);
        assertEquals(37.5200, response.legs().get(1).toLat(), TOLERANCE);
        assertEquals(127.0200, response.legs().get(1).toLng(), TOLERANCE);
        assertEquals(300 / 60.0, response.legs().get(0).minutes(), TOLERANCE);
        assertEquals(420 / 60.0, response.legs().get(1).minutes(), TOLERANCE);
    }

    @Test
    @DisplayName("98-T5: 경로 없음은 빈 결과로 구분된다")
    void 경로_없음은_빈_결과이다() {
        // 상위 계층은 빈 값을 빈 배열 응답으로 바꾼다(잘못된 입력 오류와 다름).
        assertTrue(RouteMapper
                .toResponse(new EnginePath(List.of(), 0, 0), stations, RouteType.SHORTEST, RouteSource.MOCK)
                .isEmpty());
        Optional<RouteSearchResponse> nullPath =
                RouteMapper.toResponse(null, stations, RouteType.SHORTEST, RouteSource.MOCK);
        assertTrue(nullPath.isEmpty());
    }
}
