package com.ssafy.s15p21a104.domain.route;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.service.RouteSearchService;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkDirectionsClient;
import com.ssafy.s15p21a104.domain.route.walk.geometry.KakaoWalkProperties;
import com.ssafy.s15p21a104.domain.route.walk.geometry.WalkGeometryRegistry;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * route 테스트 중앙 픽스처. 테스트 전용이며 프로덕션 코드에 의존하지 않는다.
 *
 * <p>그래프 조립·역 mock·표시 정보·엣지 단축·MVP 선행(버스·혼잡도·재고·실측·시각·
 * geometry·경계) 조립 함수를 한곳에 둔다. 각 테스트는 여기서 꺼내 쓰고, 파일 안에
 * 자체 헬퍼를 복붙하지 않는다.
 */
public final class RouteTestFixtures {

    /** 테스트 표준 좌표 (서울 시청 부근). */
    public static final double LAT = 37.5;

    /** 테스트 표준 좌표 (서울 시청 부근). */
    public static final double LNG = 127.0;

    /** TRANSFER 실측 표준 (B역 L1→L2 60초). */
    public static final int MEASURED_TRANSFER_SEC = 60;

    private RouteTestFixtures() {
    }

    // 그래프 조립

    /**
     * 엣지들로 테스트 그래프를 조립한다.
     *
     * @param edges 엣지 목록
     * @return 인메모리 그래프
     */
    public static RouteGraph graphOf(Edge... edges) {
        Set<String> nodes = new HashSet<>();
        Map<String, List<Edge>> adjacency = new HashMap<>();
        Map<String, Set<String>> lines = new HashMap<>();
        for (Edge edge : edges) {
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());
            adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            lines.computeIfAbsent(edge.fromNode(), key -> new HashSet<>()).add(edge.routeId());
            lines.computeIfAbsent(edge.toNode(), key -> new HashSet<>()).add(edge.routeId());
        }
        return RouteGraph.of(nodes, adjacency, lines);
    }

    // 엣지 단축 생성자

    /** 지하철 엣지. */
    public static Edge subway(String from, String to, String routeId, int sec) {
        return new Edge(from, to, routeId, sec, 0, TravelMode.SUBWAY);
    }

    /** 따릉이 엣지. */
    public static Edge bike(String from, String to, int sec) {
        return new Edge(from, to, BikeEdgeBuilder.BIKE_ROUTE_ID, sec, 0, TravelMode.BIKE);
    }

    /** 도보 엣지. */
    public static Edge walk(String from, String to, int sec) {
        return new Edge(from, to, WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK);
    }

    /** 버스 엣지 (ROUTE_ID 그대로, 노선별 leg 분리). */
    public static Edge bus(String from, String to, String routeId, int sec) {
        return new Edge(from, to, routeId, sec, 0, TravelMode.BUS);
    }

    // 역 mock·표시 정보

    /**
     * 역 mock (좌표 LAT/LNG 고정).
     *
     * @param id 역 ID
     * @param name 역 이름
     * @return mock 역
     */
    public static Station mockStation(String id, String name) {
        Station station = mock(Station.class);
        lenient().when(station.getStationId()).thenReturn(id);
        lenient().when(station.getName()).thenReturn(name);
        lenient().when(station.getLat()).thenReturn(LAT);
        lenient().when(station.getLng()).thenReturn(LNG);
        return station;
    }

    /**
     * 표시 정보 맵 (좌표 LAT/LNG 고정, 이름은 ID + "역").
     *
     * @param ids 정점 ID 목록
     * @return 표시 정보 맵
     */
    public static Map<String, RouteMapper.StationInfo> stationInfos(String... ids) {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : ids) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", LAT, LNG));
        }
        return infos;
    }

    /**
     * 좌표 없는 정점을 포함한 표시 정보 맵 (geometry 폴백 케이스용).
     *
     * @param nullIds 좌표 null 정점 ID 목록
     * @param normalIds 정상 정점 ID 목록
     * @return 표시 정보 맵
     */
    public static Map<String, RouteMapper.StationInfo> stationInfosWithNullCoords(
            List<String> nullIds, List<String> normalIds) {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>(stationInfos(
                normalIds.toArray(String[]::new)));
        for (String id : nullIds) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", null, null));
        }
        return infos;
    }

    // TRANSFER 실측·재고·시각

    /** 실측 표준 규칙 (B역 L1→L2 60초, 기본 180초). */
    public static TransferRule measuredRule() {
        return new TransferRule(180).withTable(Map.of(
                new TransferRule.TransferKey("B", "L1", "L2"), MEASURED_TRANSFER_SEC));
    }

    /** 실측 표준 테이블 (B역 L1→L2 60초). */
    public static Map<TransferRule.TransferKey, Integer> measuredTransferTimes() {
        return Map.of(new TransferRule.TransferKey("B", "L1", "L2"), MEASURED_TRANSFER_SEC);
    }

    /**
     * 재고 맵 변형.
     *
     * @param variant 있음·소진·원천없음 중 하나
     * @return 대여소별 예상 재고
     */
    public static Map<String, Integer> bikeStock(StockVariant variant) {
        return switch (variant) {
            case PRESENT -> Map.of("R1", 5);
            case DEPLETED -> Map.of("R1", 0);
            case NO_SOURCE -> Map.of();
        };
    }

    /** 재고 맵 변형. */
    public enum StockVariant {
        /** 재고 있음. */
        PRESENT,
        /** 재고 소진. */
        DEPLETED,
        /** 원천 없음 (기본 허용). */
        NO_SOURCE
    }

    /**
     * 출발 시각 슬롯 (63번 DepartureSlot 기준).
     *
     * @param variant 평일 오전·주말·슬롯 경계 중 하나
     * @return 시각 슬롯
     */
    public static DepartureSlot slot(SlotVariant variant) {
        return switch (variant) {
            case WEEKDAY_MORNING -> DepartureSlot.of(
                    java.time.LocalDateTime.of(2026, 9, 8, 8, 10));
            case WEEKEND -> DepartureSlot.of(
                    java.time.LocalDateTime.of(2026, 9, 13, 14, 0));
            case SLOT_BOUNDARY -> DepartureSlot.of(
                    java.time.LocalDateTime.of(2026, 9, 8, 9, 30));
        };
    }

    /** 시각 슬롯 변형. */
    public enum SlotVariant {
        /** 평일 오전 (출근 시간대). */
        WEEKDAY_MORNING,
        /** 주말 오후. */
        WEEKEND,
        /** 슬롯 경계 (30분 정각). */
        SLOT_BOUNDARY
    }

    // leg 응답 단축

    /** BIKE leg 응답 (게이트 판정용). */
    public static RouteLegResponse bikeLeg(String from) {
        return new RouteLegResponse(TravelMode.BIKE,
                from, "출발", LAT, LNG, "C", "도착", LAT, LNG,
                BikeEdgeBuilder.BIKE_ROUTE_ID, 4.0, null, "unavailable");
    }

    /** SUBWAY leg 응답 (게이트 판정용). */
    public static RouteLegResponse subwayLeg() {
        return new RouteLegResponse(TravelMode.SUBWAY,
                "A", "출발", LAT, LNG, "C", "도착", LAT, LNG,
                "L1", 15.0, null, "unavailable");
    }

    // 경계·혼합 OD 세트

    /** 고립 정점 그래프 (X는 자기 루프로 정점만 등록, 도달 불가). */
    public static RouteGraph disconnectedGraph() {
        return graphOf(
                subway("A", "B", "L1", 100),
                subway("X", "X", "L9", 10));
    }

    /** 혼잡도 비교용 OD 세트 (fast/calm 분리 선행 — 가중 전/후 그래프). */
    public static RouteGraph congestedGraph() {
        return graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100),
                subway("A", "C", "L2", 250));
    }

    // 서비스 조립

    /**
     * 그래프와 대여소 집합을 주입한 {@link RouteSearchService}를 만든다.
     *
     * <p>역 조회는 임의 ID에 대해 mock 역을 돌려주고, 표시 정보는 그래프 정점에서 파생한다.
     * 통합 테스트의 setUp 중복을 없애려는 공용 헬퍼다.
     *
     * @param graph 인메모리 그래프
     * @param rentalIds leg 경계 분할용 대여소 ID 집합
     * @return DB·Redis 없이 동작하는 서비스
     */
    public static RouteSearchService serviceWith(RouteGraph graph, Set<String> rentalIds) {
        StationRepository stationRepository = mock(StationRepository.class);
        lenient().when(stationRepository.findById(anyString())).thenAnswer(invocation -> {
            String id = invocation.getArgument(0);
            return Optional.of(mockStation(id, id + "역"));
        });
        RouteGraphRegistry registry = mock(RouteGraphRegistry.class);
        lenient().when(registry.graph()).thenReturn(graph);
        lenient().when(registry.rentalIds()).thenReturn(rentalIds == null ? Set.of() : rentalIds);
        lenient().when(registry.bikeStock()).thenReturn(Map.of());
        lenient().when(registry.transferTimes()).thenReturn(Map.of());
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String node : graph.nodes()) {
            infos.put(node, new RouteMapper.StationInfo(node, node + "역", LAT, LNG));
        }
        lenient().when(registry.stationInfos()).thenReturn(infos);
        return new RouteSearchService(stationRepository, registry, new TransferRule(180),
                new RailGeometryRegistry(null, null), noopWalkGeometryRegistry());
    }

    /**
     * 카카오 키 미설정 상태의 {@link WalkGeometryRegistry}. 실제 호출 없이 항상 빈 값을 준다
     * (S15P21A104-186 — 키 발급 전 테스트 기본값).
     */
    public static WalkGeometryRegistry noopWalkGeometryRegistry() {
        return new WalkGeometryRegistry(new KakaoWalkDirectionsClient(new KakaoWalkProperties(null, null)));
    }
}
