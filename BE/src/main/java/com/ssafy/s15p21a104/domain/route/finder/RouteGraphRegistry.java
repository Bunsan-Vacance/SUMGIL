package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphLoader;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphRawData;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
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

    private RouteGraph graph;
    private Map<String, RouteMapper.StationInfo> stationInfos = Map.of();

    public RouteGraphRegistry(RouteEdgeTimeRepository edgeTimeRepository,
                              StationRepository stationRepository,
                              RouteLineRepository lineRepository) {
        this.edgeTimeRepository = edgeTimeRepository;
        this.stationRepository = stationRepository;
        this.lineRepository = lineRepository;
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
            RouteGraphLoader.LoadResult result =
                    RouteGraphLoader.load(new RouteGraphRawData(rows, stationNames, lineNames));
            this.graph = result.graph();
            this.stationInfos = Map.copyOf(infos);
            log.info("탐색 그래프 로드 완료: 역 {}개, 엣지 {}개", graph.nodeCount(), graph.edgeCount());
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
     * @return 역 표시 정보(역 ID 기준). 미적재 시 빈 맵
     */
    public Map<String, RouteMapper.StationInfo> stationInfos() {
        return stationInfos;
    }
}
