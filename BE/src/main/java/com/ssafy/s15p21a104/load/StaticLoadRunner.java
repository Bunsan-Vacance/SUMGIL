package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bike.BikeStationParser;
import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bus.BusRouteParser;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopParser;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import com.ssafy.s15p21a104.load.csv.CsvTable;
import com.ssafy.s15p21a104.load.subway.EdgeTimeExpander;
import com.ssafy.s15p21a104.load.subway.EdgeTimeRow;
import com.ssafy.s15p21a104.load.subway.KorailSegmentParser;
import com.ssafy.s15p21a104.load.subway.LineCodes;
import com.ssafy.s15p21a104.load.subway.LoadValidator;
import com.ssafy.s15p21a104.load.subway.Segment;
import com.ssafy.s15p21a104.load.subway.SeoulMetroTimetableParser;
import com.ssafy.s15p21a104.load.subway.StationCoord;
import com.ssafy.s15p21a104.load.subway.StationNameNormalizer;
import com.ssafy.s15p21a104.load.subway.SubwayGraph;
import com.ssafy.s15p21a104.load.subway.SubwayGraphBuilder;
import com.ssafy.s15p21a104.load.subway.TransferParser;
import com.ssafy.s15p21a104.load.subway.TransferRecord;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/**
 * 정적 데이터 적재 실행기. 실행: SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.dry-run=true'
 * 대상은 --load.sources (기본 application-load.yml: subway,bus,bike) 순서대로 처리한다.
 * 순서: 원천 CSV 읽기 → 파싱 → (그래프 구성) → 검증(오류 있으면 중단) → upsert. 각 단계 소요시간과 건수를 로그로 남긴다.
 */
@Slf4j
@Component
@Profile("load")
@RequiredArgsConstructor
public class StaticLoadRunner implements ApplicationRunner {

    private static final String SUBWAY_DIR = "data/subway/";
    private static final String BUS_DIR = "data/bus/";
    private static final String BIKE_DIR = "data/bike/";

    // 원천 파일명 (출처·갱신일은 각 폴더 README). 새 배포분을 받으면 여기와 README 를 함께 바꾼다.
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
                default -> log.warn("모르는 적재 대상 '{}' — 건너뜁니다 (가능: subway, bus, bike)", source);
            }
        }
        log.info("적재 실행 종료: {} ({} ms)", props.sources(), elapsedMs(started));
    }

    private void loadSubway() throws IOException {
        long started = System.nanoTime();

        Map<String, String> aliases = readPairs("conf/station-aliases.csv", "원천표기", "정본표기");
        StationNameNormalizer normalizer = new StationNameNormalizer(aliases);

        Map<String, Map<String, String>> anchors = new HashMap<>();
        for (Map<String, String> row : csv(SUBWAY_DIR, "conf/branch-anchors.csv").rows()) {
            anchors.computeIfAbsent(row.get("line_id"), k -> new HashMap<>())
                    .put(normalizer.normalize(row.get("지선첫역")), normalizer.normalize(row.get("분기역")));
        }
        Map<String, List<String>> korailOverrides = new HashMap<>();
        for (Map<String, String> row : csv(SUBWAY_DIR, "conf/korail-line-overrides.csv").rows()) {
            korailOverrides.put(normalizer.normalize(row.get("출발역")) + "|" + normalizer.normalize(row.get("도착역")),
                    List.of(row.get("line_ids").split(";")));
        }
        Map<String, String> disambiguation = new HashMap<>();
        for (Map<String, String> row : csv(SUBWAY_DIR, "conf/station-disambiguation.csv").rows()) {
            disambiguation.put(normalizer.normalize(row.get("역명")) + "|" + row.get("line_id"), row.get("station_id"));
        }

        var timetable = new SeoulMetroTimetableParser(normalizer, anchors);
        var korail = new KorailSegmentParser(normalizer, props.avgSpeedMps(), korailOverrides);
        var transferParser = new TransferParser(normalizer);

        List<Segment> segments = new ArrayList<>(timetable.parse(csv(SUBWAY_DIR, "seoulmetro-station-time_20240810.csv").rows()));
        segments.addAll(korail.parse(csv(SUBWAY_DIR, "korail-segments_20240826.csv").rows()));
        List<TransferRecord> transfers = transferParser.parse(csv(SUBWAY_DIR, "seoulmetro-transfer_20250331.csv").rows());
        List<StationCoord> coords = readCoords(normalizer);
        logWarnings("역간거리 파싱", timetable.warnings());
        logWarnings("코레일 구간 파싱", korail.warnings());
        logWarnings("환승 파싱", transferParser.warnings());

        if (!props.region().isEmpty()) {
            segments = segments.stream().filter(s -> props.region().contains(s.lineId())).toList();
            transfers = transfers.stream().filter(t -> props.region().contains(t.fromLineId())).toList();
            log.info("권역 필터 적용: {}", props.region());
        }

        SubwayGraph graph = new SubwayGraphBuilder(disambiguation).build(segments, transfers, coords);
        ValidationReport report = LoadValidator.validate(graph);
        logWarningsGrouped("검증", report.warnings());
        long noCoords = graph.stations().stream().filter(s -> s.lat() == null).count();
        log.info("그래프: 노선 {} · 역 {} (좌표 없음 {}) · 환승 {} · 엣지 {} · edge_time 예정 {}",
                graph.lines().size(), graph.stations().size(), noCoords, graph.transfers().size(),
                graph.edges().size(), graph.edges().size() * 144);
        if (!abortIfErrors("지하철", report) || dryRun("지하철", started)) {
            return;
        }

        timed("line", () -> writer.upsertLines(graph.lines()));
        timed("station", () -> writer.upsertStations(graph.stations()));
        timed("transfer_meta", () -> writer.upsertTransfers(graph.transfers()));
        List<EdgeTimeRow> edgeTimes = EdgeTimeExpander.expandAll(graph.edges());
        timed("edge_time[" + props.writeMode() + "]", () -> writer.upsertEdgeTimes(edgeTimes, props.writeMode()));
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

    private List<StationCoord> readCoords(StationNameNormalizer normalizer) throws IOException {
        List<StationCoord> coords = new ArrayList<>();
        for (Map<String, String> row : csv(SUBWAY_DIR, "seoulmetro-station-coords_20250814.csv").rows()) {
            LineCodes.fromSeoulMetroLine(row.get("호선")).ifPresent(lineId -> coords.add(new StationCoord(
                    lineId, normalizer.normalize(row.get("역명")),
                    Double.parseDouble(row.get("위도")), Double.parseDouble(row.get("경도")),
                    row.get("고유역번호(외부역코드)"))));
        }
        for (Map<String, String> row : csv(SUBWAY_DIR, "kric-line9-station-coords_20250630.csv").rows()) {
            coords.add(new StationCoord("1009", normalizer.normalize(row.get("역명")),
                    Double.parseDouble(row.get("위도")), Double.parseDouble(row.get("경도")), null));
        }
        return coords;
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
