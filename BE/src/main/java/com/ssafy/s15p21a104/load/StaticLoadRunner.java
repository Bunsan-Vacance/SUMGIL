package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bike.BikeStationParser;
import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bus.BusRouteParser;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopParser;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import com.ssafy.s15p21a104.load.csv.CsvTable;
import com.ssafy.s15p21a104.load.railgeometry.RailGeometryParser;
import com.ssafy.s15p21a104.load.subway.DirectedSegment;
import com.ssafy.s15p21a104.load.subway.EdgeTimeExpander;
import com.ssafy.s15p21a104.load.subway.EdgeTimeRow;
import com.ssafy.s15p21a104.load.subway.KricStationCoordParser;
import com.ssafy.s15p21a104.load.subway.KtdbLinkSegmentParser;
import com.ssafy.s15p21a104.load.subway.KtdbNodeCoordParser;
import com.ssafy.s15p21a104.load.subway.LineSpeeds;
import com.ssafy.s15p21a104.load.subway.StdStationParser;
import com.ssafy.s15p21a104.load.subway.UrbanLineParser;
import com.ssafy.s15p21a104.load.subway.StationCoordResolver;
import com.ssafy.s15p21a104.load.subway.StationIdTable;
import com.ssafy.s15p21a104.load.subway.LineCodes;
import com.ssafy.s15p21a104.load.subway.LineRow;
import com.ssafy.s15p21a104.load.subway.LoadValidator;
import com.ssafy.s15p21a104.load.subway.Segment;
import com.ssafy.s15p21a104.load.subway.SlotWaits;
import com.ssafy.s15p21a104.load.subway.StationCoord;
import com.ssafy.s15p21a104.load.subway.StationNameNormalizer;
import com.ssafy.s15p21a104.load.subway.StationRow;
import com.ssafy.s15p21a104.load.subway.SubwayGraph;
import com.ssafy.s15p21a104.load.subway.SubwayGraphBuilder;
import com.ssafy.s15p21a104.load.subway.TrainTimetableParser;
import com.ssafy.s15p21a104.load.subway.TransferParser;
import com.ssafy.s15p21a104.load.subway.TransferRecord;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Supplier;
import java.util.stream.Collectors;
import java.util.zip.GZIPInputStream;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/**
 * 정적 데이터 적재 실행기. 실행: SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.dry-run=true'
 * 대상은 --load.sources (기본 application-load.yml: subway,bus,bike,railgeometry) 순서대로 처리한다.
 * 순서: 원천 CSV 읽기 → 파싱 → (그래프 구성) → 검증(오류 있으면 중단) → upsert → (지하철) prune. 각 단계 소요시간과 건수를 로그로 남긴다.
 */
@Slf4j
@Component
@Profile("load")
@RequiredArgsConstructor
public class StaticLoadRunner implements ApplicationRunner {

    private static final String SUBWAY_DIR = "data/subway/";
    private static final String BUS_DIR = "data/bus/";
    private static final String BIKE_DIR = "data/bike/";
    private static final String RAILGEOMETRY_DIR = "data/railgeometry/";

    // 원천 파일명 (출처·갱신일은 각 폴더 README). 새 배포분을 받으면 여기와 README 를 함께 바꾼다.
    static final String TIMETABLE_FILE = "seoul-train-timetable_20260616.csv.gz";
    /** 국토교통부 도시철도 전체노선(15122916). 시각표 밖 노선의 후보 목록과 역 목록 대조용 — 인접 관계는 여기서 뽑지 않는다(지선 순번 중복). */
    static final String URBAN_LINES_FILE = "molit-urban-lines_20251211.csv";
    /** 전국도시철도역사정보표준데이터(15013205). 코레일·사철 역의 좌표(국가철도공단 역위치 파일이 없는 노선)와 역번호(station-ids 정본). */
    static final String STATION_STANDARD_FILE = "kric-station-standard_20260630.csv";
    /** KTDB 철도망 링크(63 에서 도입한 railgeometry 원천을 읽기만 한다). 시각표 밖 노선의 인접 구간·선로 거리 정본. */
    static final String KTDB_LINK_FILE = "data/railgeometry/ktdb-rail-link_2024.csv";
    static final String TRANSFER_FILE = "seoulmetro-transfer_20250331.csv";
    static final String SEOULMETRO_COORDS_FILE = "seoulmetro-station-coords_20250814.csv";
    /** 국가철도공단 노선별 역위치 (data/subway/kric/). 서울교통공사 좌표가 없는 코레일·연장 구간 역을 채운다. */
    static final List<String> KRIC_COORD_FILES = List.of(
            "kric/kric-line1-station-coords_20250630.csv", "kric/kric-line2-station-coords_20251230.csv",
            "kric/kric-line3-station-coords_20250630.csv", "kric/kric-line4-station-coords_20250630.csv",
            "kric/kric-line5-station-coords_20250630.csv", "kric/kric-line6-station-coords_20240930.csv",
            "kric/kric-line7-station-coords_20240930.csv", "kric/kric-line8-station-coords_20250630.csv",
            "kric/kric-line9-station-coords_20250630.csv", "kric/kric-suin-bundang-station-coords_20250630.csv",
            "kric/kric-gyeongui-jungang-station-coords_20250630.csv");
    /** KTDB 철도망 노드(63 에서 도입한 railgeometry 원천을 읽기만 한다). 역위치 파일이 무효인 역의 마지막 보완 원천. */
    static final String KTDB_NODE_FILE = "data/railgeometry/ktdb-rail-node_2024.csv";
    static final double COORD_CROSSCHECK_METERS = 500;
    static final double COORD_REPLACE_METERS = 5000;
    static final String BUS_STOPS_FILE = "seoul-bus-stops_20260902.csv";
    static final String BUS_ROUTE_STOPS_FILE = "seoul-bus-route-stops_20260902.csv";
    static final String BIKE_SNAPSHOT_FILE = "seoul-bike-stations-live_20260909.csv";
    static final String BIKE_FILE = "seoul-bike-stations_202606.csv";

    private final LoadProperties props;
    private final UpsertWriter writer;

    @Override
    public void run(ApplicationArguments args) throws IOException {
        long started = System.nanoTime();
        for (String source : props.sources()) {
            switch (source.trim()) {
                case "subway" -> loadSubway();
                case "bus" -> loadBus();
                case "bike" -> loadBike();
                case "railgeometry" -> loadRailGeometry();
                default -> log.warn("모르는 적재 대상 '{}' — 건너뜁니다 (가능: subway, bus, bike, railgeometry)", source);
            }
        }
        log.info("적재 실행 종료: {} ({} ms)", props.sources(), elapsedMs(started));
    }

    /**
     * 지하철. 열차운행시각표가 1~9호선 엣지의 정본이고(방향 있는 구간 + 슬롯별 기대 대기, 코레일 운행 구간 포함), 시각표에 없는 노선
     * (경의중앙·수인분당·경춘·경강·서해·공항철도·신분당·우이신설·신림)은 KTDB 철도망 링크의 선로 거리 ÷ 노선별 표정속도로 보충한다(avg, wait_sec 0).
     * 전체노선 파일은 그 노선들의 역 목록을 대조하는 데만 쓴다. 적재 뒤 이번 그래프 노선의 옛 행을 prune 한다.
     */
    private void loadSubway() throws IOException {
        long started = System.nanoTime();

        Map<String, String> aliases = readPairs("conf/station-aliases.csv", "원천표기", "정본표기");
        StationNameNormalizer normalizer = new StationNameNormalizer(aliases);
        Map<String, KtdbLinkSegmentParser.LinkOverride> linkOverrides = new HashMap<>();
        for (Map<String, String> row : csv(SUBWAY_DIR, "conf/ktdb-link-overrides.csv").rows()) {
            Double km = Coords.parseOrNull(row.get("거리_km"));
            linkOverrides.put(normalizer.normalize(row.get("출발역")) + "|" + normalizer.normalize(row.get("도착역")),
                    new KtdbLinkSegmentParser.LinkOverride(List.of(row.get("line_ids").split(";")),
                            km == null ? null : (int) Math.round(km * 1000)));
        }
        LineSpeeds speeds = LineSpeeds.from(csv(SUBWAY_DIR, "conf/line-speeds.csv").rows(), props.avgSpeedMps());
        StationIdTable idTable = StationIdTable.from(csv(SUBWAY_DIR, "conf/station-ids.csv").rows());
        log.info("역 ID 표: {} 역 (conf/station-ids.csv — 서울교통공사 역번호, 코레일·사철 전용 역은 표준데이터 역번호)", idTable.size());

        // 1) 시각표 (42만 행, 스트리밍)
        long parseStarted = System.nanoTime();
        var timetable = new TrainTimetableParser(normalizer);
        try (Reader reader = gzipReader(SUBWAY_DIR + TIMETABLE_FILE)) {
            CsvTable.forEachRow(reader, timetable::accept);
        }
        TrainTimetableParser.Result tt = timetable.finish();
        var st = tt.stats();
        log.info("시각표: {} 행 · 완행 열차 {} (급행 {} 제외) · 방향 구간 {} · 이상치 {} · 표본 부족 제외 {} · 건너뜀 {} · 노선 {} ({} ms)",
                st.rows(), st.trains(), st.expressTrains(), tt.segments().size(), st.anomalies(), st.droppedEdges(),
                st.skippedRows(), tt.lineIds(), elapsedMs(parseStarted));
        logWarnings("시각표 파싱", timetable.warnings());

        // 2) KTDB 링크 거리 구간 — 전체노선 파일에 있으면서 시각표가 덮지 않는 노선만 (1~9호선은 코레일 운행 구간까지 시각표에 있다)
        var urban = new UrbanLineParser(normalizer);
        Map<String, List<String>> urbanLines = urban.parse(csv(SUBWAY_DIR, URBAN_LINES_FILE).rows());
        logWarnings("전체노선 파싱", urban.warnings());
        Set<String> distanceLines = urbanLines.keySet().stream().filter(l -> !tt.lineIds().contains(l))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        var ktdbLinks = new KtdbLinkSegmentParser(normalizer, speeds, linkOverrides);
        List<Segment> distanceSegments = ktdbLinks.parse(csv("", KTDB_NODE_FILE).rows(), csv("", KTDB_LINK_FILE).rows(), distanceLines);
        logWarnings("KTDB 링크 파싱", ktdbLinks.warnings());
        logWarnings("역 목록 대조", compareStationLists(ktdbLinks.stationsByLine(), urbanLines, distanceLines));
        log.info("KTDB 링크 거리 구간: 노선 {} {} · 구간 {} · 표정속도 표 {}개 노선, 기본 {} m/s 적용 {}", distanceLines.size(), distanceLines,
                distanceSegments.size(), speeds.table().size(), speeds.fallbackMps(),
                distanceLines.stream().filter(speeds::isDefault).toList());

        // 3) 환승·좌표
        var transferParser = new TransferParser(normalizer);
        List<TransferRecord> transfers = transferParser.parse(csv(SUBWAY_DIR, TRANSFER_FILE).rows());
        List<StationCoord> coords = readCoords(normalizer);
        logWarnings("환승 파싱", transferParser.warnings());

        List<DirectedSegment> directed = tt.segments();
        Map<String, SlotWaits> waits = tt.slotWaits();
        if (!props.region().isEmpty()) {
            directed = directed.stream().filter(s -> props.region().contains(s.lineId())).toList();
            waits = waits.entrySet().stream().filter(e -> props.region().contains(e.getKey().substring(0, e.getKey().indexOf('|'))))
                    .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue, (a, b) -> a, LinkedHashMap::new));
            distanceSegments = distanceSegments.stream().filter(s -> props.region().contains(s.lineId())).toList();
            transfers = transfers.stream().filter(t -> props.region().contains(t.fromLineId())).toList();
            log.info("권역 필터 적용: {}", props.region());
        }

        SubwayGraph graph = new SubwayGraphBuilder(idTable).build(directed, distanceSegments, transfers, coords, waits);
        ValidationReport report = LoadValidator.validate(graph);
        logWarningsGrouped("검증", report.warnings());
        long noCoords = graph.stations().stream().filter(s -> s.lat() == null).count();
        log.info("그래프: 노선 {} · 역 {} (좌표 없음 {}) · 환승 {} · 엣지 {} (슬롯 대기 있음 {}) · edge_time 예정 {}",
                graph.lines().size(), graph.stations().size(), noCoords, graph.transfers().size(),
                graph.edges().size(), graph.slotWaits().size(), graph.edges().size() * 144);
        logCoordSourceSummary(graph);
        if (!abortIfErrors("지하철", report)) {
            return;
        }

        Set<String> keptEdgeKeys = graph.edges().stream().map(EdgeTimeExpander::edgeKey).collect(Collectors.toSet());
        Set<String> keptStationIds = graph.stations().stream().map(StationRow::stationId).collect(Collectors.toSet());
        // prune 범위는 이번 그래프의 모든 노선 — 시각표 노선뿐 아니라 KTDB 거리 구간 노선의 옛 행(옛 코레일 구간 파일·임시 ID 9001~ 역)도 정리한다
        Set<String> coveredLines = graph.lines().stream().map(LineRow::lineId).collect(Collectors.toSet());
        if (props.dryRun()) {
            if (props.prune()) {
                var preview = writer.pruneSubway(coveredLines, keptEdgeKeys, keptStationIds, true);
                log.info("prune 예정: 시각표 노선에서 사라지는 엣지 {}개 — {}", preview.staleEdges(), head(preview.staleEdgeKeys()));
            }
            dryRun("지하철", started);
            return;
        }

        timed("line", () -> writer.upsertLines(graph.lines()));
        timed("station", () -> writer.upsertStations(graph.stations()));
        timed("transfer_meta", () -> writer.upsertTransfers(graph.transfers()));
        List<EdgeTimeRow> edgeTimes = EdgeTimeExpander.expandAll(graph.edges(), graph.slotWaits());
        timed("edge_time[" + props.writeMode() + "]", () -> writer.upsertEdgeTimes(edgeTimes, props.writeMode()));
        if (props.prune()) {
            var pruned = writer.pruneSubway(coveredLines, keptEdgeKeys, keptStationIds, false);
            log.info("prune: 엣지 {}개 ({} 행) · 환승 {} 행 · 고아 역 {}개 삭제 — 엣지 {} · 역 {}", pruned.staleEdges(), pruned.deletedEdgeRows(),
                    pruned.deletedTransferRows(), pruned.deletedStationIds().size(), head(pruned.staleEdgeKeys()), head(pruned.deletedStationIds()));
        }
        log.info("지하철 적재 완료 ({} ms)", elapsedMs(started));
    }

    /**
     * 버스 정류소·노선 마스터. 위치정보 파일이 정본이고 노선별 파일에만 있는 정류소(경기 구간)는 좌표를 보충한다.
     * --load.region 은 지하철 line_id 기준이라 여기에는 적용하지 않는다 (서비스 권역 확정 전 전체 적재).
     */
    private void loadBus() throws IOException {
        long started = System.nanoTime();
        List<Map<String, String>> stopRows = csv(BUS_DIR, BUS_STOPS_FILE).rows();
        List<Map<String, String>> routeStopRows = csv(BUS_DIR, BUS_ROUTE_STOPS_FILE).rows();

        var stopParser = new BusStopParser();
        var routeParser = new BusRouteParser();
        List<BusStopRow> stops = stopParser.parse(stopRows, routeStopRows);
        List<BusRouteRow> routes = routeParser.parse(routeStopRows);
        logWarningsGrouped("정류소 파싱", stopParser.warnings());
        logWarnings("노선 파싱", routeParser.warnings());

        ValidationReport report = MasterValidator.validateBus(stops, routes);
        logWarningsGrouped("검증", report.warnings());
        long noCoords = stops.stream().filter(s -> s.lat() == null).count();
        log.info("버스: 정류소 {} (위치정보 {} + 노선별 파일 보충 {}, 좌표 없음 {}) · 노선 {} (노선별 파일 {}행)",
                stops.size(), stops.size() - stopParser.addedFromRouteFile(), stopParser.addedFromRouteFile(), noCoords,
                routes.size(), routeStopRows.size());
        if (!abortIfErrors("버스", report) || dryRun("버스", started)) {
            return;
        }

        timed("bus_route", () -> writer.upsertBusRoutes(routes));
        timed("bus_stop", () -> writer.upsertBusStops(stops));
        log.info("버스 적재 완료 ({} ms)", elapsedMs(started));
    }

    /**
     * 따릉이 대여소 마스터. bikeList 스냅샷이 주 원천(rental_id = stationId)이고 파일형 대여소 정보는 대조용이다.
     */
    private void loadBike() throws IOException {
        long started = System.nanoTime();
        var parser = new BikeStationParser();
        List<BikeStationRow> stations = parser.parse(csv(BIKE_DIR, BIKE_SNAPSHOT_FILE).rows(), csv(BIKE_DIR, BIKE_FILE).rows());
        logWarningsGrouped("대여소 파싱", parser.warnings());

        ValidationReport report = MasterValidator.validateBike(stations);
        logWarningsGrouped("검증", report.warnings());
        var cc = parser.crossCheck();
        long noDock = stations.stream().filter(s -> s.dockCount() == null).count();
        log.info("따릉이: 대여소 {} (거치대수 없음 {}) · 파일 대조 일치 {} · 스냅샷에만 {} · 파일에만 {} · 거치대수 불일치 {}",
                stations.size(), noDock, cc.matched(), cc.onlyInSnapshot().size(), cc.onlyInFile().size(), cc.dockMismatch());
        if (!abortIfErrors("따릉이", report) || dryRun("따릉이", started)) {
            return;
        }

        timed("bike_station", () -> writer.upsertBikeStations(stations));
        log.info("따릉이 적재 완료 ({} ms)", elapsedMs(started));
    }

    /**
     * KTDB 철도망 geometry. 원천은 이미 정제된 CSV(BE/scripts/railgeometry/convert_ktdb.py 산출물)라
     * 좌표 변환·인코딩 처리가 필요 없다 — line_id 매칭만 한다. 매칭 안 되는 노선(수도권 밖 등)도
     * 그대로 적재한다 — 조회 시 자연히 unavailable로 빠지므로 위험 없다(--load.region 미적용).
     */
    private void loadRailGeometry() throws IOException {
        long started = System.nanoTime();
        var parser = new RailGeometryParser();
        var nodes = parser.parseNodes(csv(RAILGEOMETRY_DIR, "ktdb-rail-node_2024.csv").rows());
        var links = parser.parseLinks(csv(RAILGEOMETRY_DIR, "ktdb-rail-link_2024.csv").rows());
        logWarningsGrouped("KTDB geometry 파싱", parser.warnings());
        log.info("KTDB geometry: node {} · link {}", nodes.size(), links.size());
        if (dryRun("KTDB geometry", started)) {
            return;
        }

        timed("rail_node", () -> writer.upsertRailNodes(nodes));
        timed("rail_link_geometry", () -> writer.upsertRailLinkGeometry(links));
        log.info("KTDB geometry 적재 완료 ({} ms)", elapsedMs(started));
    }

    /**
     * 좌표 원천을 우선순위 순서로 잇는다 (빌더는 앞 원천을 먼저 쓴다):
     * ① 서울교통공사 역사 좌표(1~8호선) → ② 국가철도공단 노선별 역위치(코레일·연장 구간·9호선) → ③ KTDB 노드(②가 무효인 역, 이름 대조).
     * ②와 ③이 500 m 넘게 어긋나는 역은 경고로 남긴다 — 어느 쪽이 맞는지는 원천이 말해 주지 않는다.
     */
    private List<StationCoord> readCoords(StationNameNormalizer normalizer) throws IOException {
        List<StationCoord> seoulMetro = new ArrayList<>();
        for (Map<String, String> row : csv(SUBWAY_DIR, SEOULMETRO_COORDS_FILE).rows()) {
            LineCodes.fromSeoulMetroLine(row.get("호선")).ifPresent(lineId -> seoulMetro.add(new StationCoord(
                    lineId, normalizer.normalize(row.get("역명")),
                    Double.parseDouble(row.get("위도")), Double.parseDouble(row.get("경도")),
                    row.get("고유역번호(외부역코드)"))));
        }
        var kricParser = new KricStationCoordParser(normalizer);
        List<StationCoord> kric = new ArrayList<>();
        for (String file : KRIC_COORD_FILES) {
            kric.addAll(kricParser.parse(csv(SUBWAY_DIR, file).rows()));
        }
        logWarnings("역위치 파싱", kricParser.warnings());
        List<StationCoord> ktdb = new KtdbNodeCoordParser(normalizer).parse(
                CsvTable.parse(new ClassPathResource(KTDB_NODE_FILE).getContentAsString(StandardCharsets.UTF_8)).rows());

        var stdParser = new StdStationParser(normalizer);
        List<StationCoord> std = stdParser.parse(csv(SUBWAY_DIR, STATION_STANDARD_FILE).rows());

        // 우선순위·다수결·교차검증 규칙은 StationCoordResolver 에 있다 (data/subway/README.md "좌표 결정 규칙").
        var resolved = StationCoordResolver.resolve(seoulMetro, kric, std, ktdb, COORD_CROSSCHECK_METERS, COORD_REPLACE_METERS);
        logWarnings("좌표 다수결(서울교통공사)", resolved.seoulVote().warnings());
        logWarnings("좌표 다수결(국가철도공단)", resolved.kricVote().warnings());
        logWarnings("좌표 교차검증", resolved.crossCheck().warnings());
        log.info("좌표 원천: 서울교통공사 {} (표준데이터로 대체 {}: {}) · 국가철도공단 역위치 {} (무효 {} 건너뜀, 표준데이터로 대체 {}: {}) "
                        + "· 표준데이터 {} (수도권 밖 {} 건너뜀, 그중 실제 쓰임 {}) · KTDB 로 대체 {}: {} · KTDB 노드 {} (수도권, 이름별 평균)",
                seoulMetro.size(), resolved.seoulVote().replaced().size(), String.join(", ", resolved.seoulVote().replaced()),
                kric.size(), kricParser.skipped(), resolved.kricVote().replaced().size(), String.join(", ", resolved.kricVote().replaced()),
                std.size(), stdParser.skipped(), resolved.stdUsed(),
                resolved.crossCheck().replaced().size(), String.join(", ", resolved.crossCheck().replaced()), ktdb.size());

        this.coordSources = resolved.sourcesInPriority();
        return resolved.coords();
    }

    /**
     * KTDB 링크가 만든 역 집합과 전체노선 파일의 역 목록을 노선별로 대조한다.
     * 어느 한쪽에만 있는 역은 원천 누락·개통 시차(서해선 원종은 KTDB 에만, 경춘선 광운대는 예외 표로 붙임)라 경고로 남기고 값을 만들어 넣지 않는다.
     */
    private static List<String> compareStationLists(Map<String, Set<String>> fromLinks, Map<String, List<String>> fromUrbanFile,
                                                    Set<String> lines) {
        List<String> warnings = new ArrayList<>();
        for (String line : lines) {
            Set<String> links = fromLinks.getOrDefault(line, Set.of());
            Set<String> urban = new LinkedHashSet<>(fromUrbanFile.getOrDefault(line, List.of()));
            List<String> onlyLinks = links.stream().filter(s -> !urban.contains(s)).sorted().toList();
            List<String> onlyUrban = urban.stream().filter(s -> !links.contains(s)).toList();
            if (links.isEmpty()) {
                warnings.add(LineCodes.nameOf(line) + ": KTDB 링크가 없어 구간을 만들지 못함 (전체노선 역 " + urban.size() + "개)");
            } else if (!onlyLinks.isEmpty() || !onlyUrban.isEmpty()) {
                warnings.add(LineCodes.nameOf(line) + ": KTDB 링크에만 " + onlyLinks + " · 전체노선에만 " + onlyUrban);
            }
        }
        return warnings;
    }

    private List<List<StationCoord>> coordSources = List.of();

    /** 역마다 어느 원천의 좌표가 쓰였는지 값으로 되짚어 센다 (빌더는 출처를 남기지 않는다). */
    private void logCoordSourceSummary(SubwayGraph graph) {
        String[] labels = {"서울교통공사", "국가철도공단", "표준데이터", "KTDB"};
        int[] counts = new int[labels.length];
        List<String> ktdbStations = new ArrayList<>();
        for (StationRow s : graph.stations()) {
            if (s.lat() == null) {
                continue;
            }
            for (int i = 0; i < coordSources.size(); i++) {
                boolean hit = coordSources.get(i).stream().anyMatch(c -> c.lat() == s.lat() && c.lng() == s.lng());
                if (hit) {
                    counts[i]++;
                    if (i == labels.length - 1) {
                        ktdbStations.add(s.stationId());
                    }
                    break;
                }
            }
        }
        log.info("역 좌표 출처: 서울교통공사 {} · 국가철도공단 {} · 표준데이터 {} · KTDB {} ({})", counts[0], counts[1], counts[2], counts[3],
                String.join(", ", ktdbStations));
    }

    private Map<String, String> readPairs(String file, String keyCol, String valueCol) throws IOException {
        Map<String, String> out = new LinkedHashMap<>();
        for (Map<String, String> row : csv(SUBWAY_DIR, file).rows()) {
            out.put(row.get(keyCol), row.get(valueCol));
        }
        return out;
    }

    /** 검증 오류가 있으면 로그로 남기고 IllegalStateException — 부분 적재를 하지 않는다. 오류가 없으면 true. */
    private static boolean abortIfErrors(String label, ValidationReport report) {
        if (report.ok()) {
            return true;
        }
        report.errors().forEach(e -> log.error("{} 검증 오류: {}", label, e));
        throw new IllegalStateException(label + " 검증 오류 " + report.errors().size() + "건 — 적재하지 않습니다");
    }

    private boolean dryRun(String label, long started) {
        if (props.dryRun()) {
            log.info("{} dry-run: DB 에 쓰지 않고 넘어갑니다 ({} ms)", label, elapsedMs(started));
            return true;
        }
        return false;
    }

    private static CsvTable csv(String dir, String file) throws IOException {
        return CsvTable.parse(new ClassPathResource(dir + file).getContentAsString(StandardCharsets.UTF_8));
    }

    private static Reader gzipReader(String path) throws IOException {
        return new BufferedReader(new InputStreamReader(new GZIPInputStream(new ClassPathResource(path).getInputStream()),
                StandardCharsets.UTF_8));
    }

    private static void logWarnings(String stage, List<String> warnings) {
        warnings.forEach(w -> log.warn("{} 경고: {}", stage, w));
    }

    /** "좌표 없음" 경고는 수십~수백 건이 나올 수 있어 한 줄로 묶고, 나머지는 한 건씩 남긴다. */
    private static void logWarningsGrouped(String stage, List<String> warnings) {
        List<String> noCoord = warnings.stream().filter(w -> w.startsWith("좌표 없음")).toList();
        logWarnings(stage, warnings.stream().filter(w -> !w.startsWith("좌표 없음")).toList());
        if (!noCoord.isEmpty()) {
            log.warn("{} 경고: 좌표 없음 {}개 — {}", stage, noCoord.size(),
                    String.join(", ", noCoord.stream().map(w -> w.substring("좌표 없음: ".length())).toList()));
        }
    }

    private static String head(List<String> items) {
        int limit = 20;
        String joined = String.join(", ", items.subList(0, Math.min(limit, items.size())));
        return items.size() > limit ? joined + ", …(" + items.size() + ")" : joined;
    }

    private static void timed(String label, Supplier<Integer> work) {
        long started = System.nanoTime();
        int rows = work.get();
        long ms = elapsedMs(started);
        log.info("적재 {} · {} 행 · {} ms · {} 행/초", label, rows, ms, ms == 0 ? rows : Math.round(rows * 1000.0 / ms));
    }

    private static long elapsedMs(long startedNanos) {
        return (System.nanoTime() - startedNanos) / 1_000_000;
    }
}
