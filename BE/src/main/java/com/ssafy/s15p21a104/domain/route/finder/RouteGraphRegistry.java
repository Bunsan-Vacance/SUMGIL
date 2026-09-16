package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
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
    private List<RouteGraph> candidateSubgraphs = List.of();
    private Map<String, RouteMapper.StationInfo> stationInfos = Map.of();
    private Map<TransferRule.TransferKey, Integer> transferTimes = Map.of();
    private java.util.Set<String> rentalIds = java.util.Set.of();

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
            for (Station station : stationRepository.findAll()) {
                stationNames.put(station.getStationId(), station.getName());
                infos.put(station.getStationId(), new RouteMapper.StationInfo(
                        station.getStationId(), station.getName(), station.getLat(), station.getLng()));
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
            List<Edge> busEdges = BusEdgeBuilder.build(busRoutes);
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
            // 수단 조합별 하위 그래프를 기동 시 1회만 미리 계산해둔다(S15P21A104-155) — 검색
            // 요청마다 22만 엣지짜리 그래프를 7번씩 필터링하는 게 그래프가 커지면서(역 564→16,189개,
            // 엣지 12,626→224,184개, k6 부하테스트로 확인) 무거운 반복 작업이 됐다. 조합 목록
            // 자체는 요청과 무관하게 고정이라 로드 시점에 한 번만 만들어도 안전하다.
            List<RouteGraph> subgraphs = new java.util.ArrayList<>();
            for (java.util.Set<TravelMode> coreModes : CandidateModeSets.CORE_MODE_SETS) {
                subgraphs.add(this.graph.filterByModes(CandidateModeSets.withWalk(coreModes)));
            }
            this.candidateSubgraphs = List.copyOf(subgraphs);
            this.stationInfos = Map.copyOf(infos);
            this.rentalIds = java.util.Set.copyOf(rentals.keySet());
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
     * @return {@link CandidateModeSets#CORE_MODE_SETS} 순서대로 미리 필터링해둔 하위 그래프
     * 목록(S15P21A104-155). 요청마다 다시 필터링하지 않도록 기동 시 1회 계산해 캐싱한다.
     * 미적재 시 빈 목록
     */
    public List<RouteGraph> candidateSubgraphs() {
        return candidateSubgraphs;
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
     * @return 대여소별 예상 재고. 원천 없음으로 항상 빈 맵(게이트 기본 허용).
     * AI 산출물 연동 시 bike_stock_pred 조회로 교체한다.
     */
    public Map<String, Integer> bikeStock() {
        return Map.of();
    }
}
