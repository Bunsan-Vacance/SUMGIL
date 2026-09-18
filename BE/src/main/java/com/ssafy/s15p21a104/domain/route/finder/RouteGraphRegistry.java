package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteStopsReader;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphLoader;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphRawData;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.entity.TransferMeta;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.domain.station.repository.TransferMetaRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import jakarta.annotation.PostConstruct;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 탐색용 인메모리 그래프 보관소. 기동 시 {@code edge_time}을 1회 로드한다.
 *
 * <p>적재 전(DB 비어 있음)에는 그래프 없이 뜨고 호출 측은 기존 동작을 유지한다.
 * 탐색 루프에서는 이 그래프만 읽고 DB를 다시 조회하지 않는다.
 */
@Slf4j
@Component
public class RouteGraphRegistry {

    private final RouteEdgeTimeRepository edgeTimeRepository;
    private final StationRepository stationRepository;
    private final RouteLineRepository lineRepository;
    private final TransferMetaRepository transferMetaRepository;
    private final BikeStationRepository bikeStationRepository;

    private RouteGraph graph;
    private Map<String, RouteMapper.StationInfo> stationInfos = Map.of();
    private Map<TransferRule.TransferKey, Integer> transferTimes = Map.of();
    private java.util.Set<String> rentalIds = java.util.Set.of();
    private java.util.Set<String> stationIds = java.util.Set.of();
    private BusRouteIndex busRouteIndex = BusRouteIndex.build(Map.of());
    private final java.util.concurrent.ConcurrentMap<String, RouteGraph> slotGraphs =
            new java.util.concurrent.ConcurrentHashMap<>();

    public RouteGraphRegistry(RouteEdgeTimeRepository edgeTimeRepository,
                              StationRepository stationRepository,
                              RouteLineRepository lineRepository,
                              TransferMetaRepository transferMetaRepository,
                              BikeStationRepository bikeStationRepository) {
        this.edgeTimeRepository = edgeTimeRepository;
        this.stationRepository = stationRepository;
        this.lineRepository = lineRepository;
        this.transferMetaRepository = transferMetaRepository;
        this.bikeStationRepository = bikeStationRepository;
    }

    @PostConstruct
    void load() {
        try {
            List<RouteEdgeRow> rows = edgeTimeRepository.findSubwayEdgesForDefaultSlot();
            Map<String, String> stationNames = new HashMap<>();
            Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
            java.util.Set<String> stationIdSet = new java.util.HashSet<>();
            for (Station station : stationRepository.findAll()) {
                stationNames.put(station.getStationId(), station.getName());
                infos.put(station.getStationId(), new RouteMapper.StationInfo(
                        station.getStationId(), station.getName(), station.getLat(), station.getLng()));
                stationIdSet.add(station.getStationId());
            }
            Map<String, String> lineNames = new HashMap<>();
            for (Line line : lineRepository.findAll()) {
                lineNames.put(line.getLineId(), line.getName());
            }
            Map<String, BikeEdgeBuilder.Stop> stops = new HashMap<>();
            Map<String, BikeEdgeBuilder.Stop> rentals = new HashMap<>();
            for (Station station : stationRepository.findAll()) {
                stops.put(station.getStationId(), new BikeEdgeBuilder.Stop(
                        station.getStationId(), station.getLat(), station.getLng()));
            }
            int rentalTotal = 0;
            for (BikeStation rental : bikeStationRepository.findAll()) {
                rentalTotal++;
                rentals.put(rental.getRentalId(), new BikeEdgeBuilder.Stop(
                        rental.getRentalId(), rental.getLat(), rental.getLng()));
                infos.put(rental.getRentalId(), new RouteMapper.StationInfo(
                        rental.getRentalId(), rental.getName(), rental.getLat(), rental.getLng()));
            }
            List<Edge> rentalEdges = BikeRentalEdgeBuilder.build(rentals);
            Map<String, List<BusEdgeBuilder.RouteStop>> busRoutes = BusRouteStopsReader.read();
            List<Edge> busEdges = BusEdgeBuilder.buildCorridors(busRoutes);
            Map<String, BikeEdgeBuilder.Stop> busStops = new HashMap<>();
            for (List<BusEdgeBuilder.RouteStop> routeStops : busRoutes.values()) {
                for (BusEdgeBuilder.RouteStop routeStop : routeStops) {
                    infos.putIfAbsent(routeStop.stopId(), new RouteMapper.StationInfo(
                            routeStop.stopId(),
                            routeStop.name() == null ? routeStop.stopId() : routeStop.name(),
                            routeStop.lat(), routeStop.lng()));
                    busStops.putIfAbsent(routeStop.stopId(), new BikeEdgeBuilder.Stop(
                            routeStop.stopId(), routeStop.lat(), routeStop.lng()));
                }
            }
            // 역↔정류장·대여소↔정류장 보행 연결(S15P21A104-188). 정류장↔정류장은 그대로 BUS 엣지 몫이다.
            List<Edge> walkEdges = WalkEdgeBuilder.build(stops, rentals, busStops);
            List<Edge> extraEdges = new java.util.ArrayList<>(walkEdges);
            extraEdges.addAll(rentalEdges);
            extraEdges.addAll(busEdges);
            RouteGraphLoader.LoadResult result = RouteGraphLoader.load(
                    new RouteGraphRawData(rows, stationNames, lineNames), extraEdges);
            this.graph = result.graph();
            this.stationInfos = Map.copyOf(infos);
            this.rentalIds = java.util.Set.copyOf(rentals.keySet());
            this.busRouteIndex = BusRouteIndex.build(busRoutes);
            this.stationIds = java.util.Set.copyOf(stationIdSet);
            Map<TransferRule.TransferKey, Integer> times = new HashMap<>();
            for (TransferMeta meta : transferMetaRepository.findAll()) {
                times.put(new TransferRule.TransferKey(
                        meta.getId().getStationId(),
                        meta.getId().getFromLine(),
                        meta.getId().getToLine()), meta.getWalkSec());
            }
            this.transferTimes = Map.copyOf(times);
            log.info("탐색 그래프 로드 완료: 역 {}개, 엣지 {}개, 환승 실측 {}건, 대여소 {}곳·자전거 엣지 {}개·도보 엣지 {}개·버스 엣지 {}개",
                    graph.nodeCount(), graph.edgeCount(), transferTimes.size(),
                    rentalTotal, rentalEdges.size(), walkEdges.size(), busEdges.size());
        } catch (DomainException e) {
            log.warn("탐색 그래프 없음(미적재). 그래프 로드 후 재기동하면 알고리즘 경로로 동작한다: {}",
                    e.getMessage());
        }
    }

    /**
     * @return 로드된 그래프. 미적재 시 null(호출 측은 기존 동작 유지)
     */
    public RouteGraph graph() {
        return graph;
    }

    /**
     * 요청 슬롯에 맞는 그래프를 돌려준다(S15P21A104-190).
     *
     * <p>슬롯별 SUBWAY 행으로 그래프를 조립해 캐시한다. 해당 슬롯 행이 DB에
     * 없으면(빈 목록) default 그래프로 폴백한다 — 값을 지어내지 않는다.
     * WALK·BIKE·BUS 연결은 default 로드 시 것과 같다(슬롯 의존 없음).
     *
     * @param dowType 요일 구분
     * @param timeSlot 시간 슬롯
     * @return 슬롯 그래프 또는 default 그래프. 미적재 시 null
     */
    public RouteGraph graphFor(int dowType, int timeSlot) {
        if (graph == null) {
            return null;
        }
        if (dowType == 0 && timeSlot == 0) {
            return graph;
        }
        String key = dowType + ":" + timeSlot;
        RouteGraph cached = slotGraphs.get(key);
        if (cached != null) {
            return cached;
        }
        List<RouteEdgeRow> rows;
        try {
            rows = edgeTimeRepository.findSubwayEdgesBySlot(dowType, timeSlot);
        } catch (RuntimeException e) {
            log.warn("슬롯 그래프 조회 실패, default 폴백 ({}:{}): {}", dowType, timeSlot, e.getMessage());
            return graph;
        }
        if (rows == null || rows.isEmpty()) {
            return graph;
        }
        List<Edge> subwayEdges = new java.util.ArrayList<>();
        for (RouteEdgeRow row : rows) {
            subwayEdges.add(new Edge(row.fromNode(), row.toNode(), row.routeId(),
                    row.travelSec(), row.waitSec(),
                    com.ssafy.s15p21a104.domain.route.entity.TravelMode.SUBWAY));
        }
        // default 그래프에서 SUBWAY 엣지만 갈아끼운다 — 비-SUBWAY 연결은 그대로.
        java.util.Set<String> nodes = new java.util.LinkedHashSet<>();
        java.util.Map<String, List<Edge>> adjacency = new java.util.LinkedHashMap<>();
        java.util.Map<String, java.util.Set<String>> stationLines = new java.util.LinkedHashMap<>();
        for (Edge edge : subwayEdges) {
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());
            adjacency.computeIfAbsent(edge.fromNode(), k -> new java.util.ArrayList<>()).add(edge);
            stationLines.computeIfAbsent(edge.fromNode(), k -> new java.util.LinkedHashSet<>()).add(edge.routeId());
            stationLines.computeIfAbsent(edge.toNode(), k -> new java.util.LinkedHashSet<>()).add(edge.routeId());
        }
        for (Edge edge : graph.edges()) {
            if (edge.mode() == com.ssafy.s15p21a104.domain.route.entity.TravelMode.SUBWAY) {
                continue;
            }
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());
            adjacency.computeIfAbsent(edge.fromNode(), k -> new java.util.ArrayList<>()).add(edge);
            stationLines.computeIfAbsent(edge.fromNode(), k -> new java.util.LinkedHashSet<>()).add(edge.routeId());
            stationLines.computeIfAbsent(edge.toNode(), k -> new java.util.LinkedHashSet<>()).add(edge.routeId());
        }
        RouteGraph slotGraph = RouteGraph.of(nodes, adjacency, stationLines);
        slotGraphs.putIfAbsent(key, slotGraph);
        return slotGraphs.getOrDefault(key, slotGraph);
    }

    /**
     * @return 역 표시 정보(역 ID 기준). 미적재 시 빈 맵
     */
    public Map<String, RouteMapper.StationInfo> stationInfos() {
        return stationInfos;
    }

    /**
     * @return 환승 실측표(역·이전 노선·다음 노선 기준). 미적재 시 빈 맵(호출 측은 상수 폴백)
     */
    public Map<TransferRule.TransferKey, Integer> transferTimes() {
        return transferTimes;
    }

    /**
     * @return 대여소 ID 집합(leg 경계 분할용). 미적재 시 빈 집합
     */
    public java.util.Set<String> rentalIds() {
        return rentalIds;
    }

    /**
     * @return 역 ID 집합(좌표 접근 후보 유형 구분용, S15P21A104-231). 미적재 시 빈 집합
     */
    public java.util.Set<String> stationIds() {
        return stationIds;
    }

    /**
     * @return 정류장 쌍별 운행 노선 인덱스(S15P21A104-234). 미적재 시 빈 인덱스
     */
    public BusRouteIndex busRouteIndex() {
        return busRouteIndex;
    }

    /**
     * @return 대여소별 예상 재고. 원천 없음으로 항상 빈 맵(게이트 기본 허용).
     * AI 산출물 연동 시 bike_stock_pred 조회로 교체한다.
     */
    public Map<String, Integer> bikeStock() {
        return Map.of();
    }
}
