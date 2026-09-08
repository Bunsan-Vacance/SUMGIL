package com.ssafy.s15p21a104.load;

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
import com.ssafy.s15p21a104.load.subway.ValidationReport;
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
 * 순서: 원천 CSV 읽기 → 파싱 → 그래프 구성 → 검증(오류 있으면 중단) → upsert. 각 단계 소요시간과 건수를 로그로 남긴다.
 */
@Slf4j
@Component
@Profile("load")
@RequiredArgsConstructor
public class StaticLoadRunner implements ApplicationRunner {

    private static final String DATA_DIR = "data/subway/";

    private final LoadProperties props;
    private final UpsertWriter writer;

    @Override
    public void run(ApplicationArguments args) throws IOException {
        if (!props.sources().contains("subway")) {
            log.info("적재 대상에 subway 가 없어 종료합니다: {}", props.sources());
            return;
        }
        loadSubway();
    }

    private void loadSubway() throws IOException {
        long started = System.nanoTime();

        Map<String, String> aliases = readPairs("conf/station-aliases.csv", "원천표기", "정본표기");
        StationNameNormalizer normalizer = new StationNameNormalizer(aliases);

        Map<String, Map<String, String>> anchors = new HashMap<>();
        for (Map<String, String> row : csv("conf/branch-anchors.csv").rows()) {
            anchors.computeIfAbsent(row.get("line_id"), k -> new HashMap<>())
                    .put(normalizer.normalize(row.get("지선첫역")), normalizer.normalize(row.get("분기역")));
        }
        Map<String, List<String>> korailOverrides = new HashMap<>();
        for (Map<String, String> row : csv("conf/korail-line-overrides.csv").rows()) {
            korailOverrides.put(normalizer.normalize(row.get("출발역")) + "|" + normalizer.normalize(row.get("도착역")),
                    List.of(row.get("line_ids").split(";")));
        }
        Map<String, String> disambiguation = new HashMap<>();
        for (Map<String, String> row : csv("conf/station-disambiguation.csv").rows()) {
            disambiguation.put(normalizer.normalize(row.get("역명")) + "|" + row.get("line_id"), row.get("station_id"));
        }

        var timetable = new SeoulMetroTimetableParser(normalizer, anchors);
        var korail = new KorailSegmentParser(normalizer, props.avgSpeedMps(), korailOverrides);
        var transferParser = new TransferParser(normalizer);

        List<Segment> segments = new ArrayList<>(timetable.parse(csv("seoulmetro-station-time_20240810.csv").rows()));
        segments.addAll(korail.parse(csv("korail-segments_20240826.csv").rows()));
        List<TransferRecord> transfers = transferParser.parse(csv("seoulmetro-transfer_20250331.csv").rows());
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
        // 좌표 없음은 코레일 역 전부에 해당해 수십 건이 나온다. 한 줄로 묶어 다른 경고가 묻히지 않게 한다.
        List<String> noCoordWarnings = report.warnings().stream().filter(w -> w.startsWith("좌표 없음")).toList();
        logWarnings("검증", report.warnings().stream().filter(w -> !w.startsWith("좌표 없음")).toList());
        if (!noCoordWarnings.isEmpty()) {
            log.warn("검증 경고: 좌표 없음 {}개 — {}", noCoordWarnings.size(),
                    String.join(", ", noCoordWarnings.stream().map(w -> w.substring("좌표 없음: ".length())).toList()));
        }
        long noCoords = graph.stations().stream().filter(s -> s.lat() == null).count();
        log.info("그래프: 노선 {} · 역 {} (좌표 없음 {}) · 환승 {} · 엣지 {} · edge_time 예정 {}",
                graph.lines().size(), graph.stations().size(), noCoords, graph.transfers().size(),
                graph.edges().size(), graph.edges().size() * 144);
        if (!report.ok()) {
            report.errors().forEach(e -> log.error("검증 오류: {}", e));
            throw new IllegalStateException("검증 오류 " + report.errors().size() + "건 — 적재하지 않습니다");
        }
        if (props.dryRun()) {
            log.info("dry-run: DB 에 쓰지 않고 종료합니다 ({} ms)", elapsedMs(started));
            return;
        }

        timed("line", () -> writer.upsertLines(graph.lines()));
        timed("station", () -> writer.upsertStations(graph.stations()));
        timed("transfer_meta", () -> writer.upsertTransfers(graph.transfers()));
        List<EdgeTimeRow> edgeTimes = EdgeTimeExpander.expandAll(graph.edges());
        timed("edge_time[" + props.writeMode() + "]", () -> writer.upsertEdgeTimes(edgeTimes, props.writeMode()));
        log.info("적재 완료 ({} ms)", elapsedMs(started));
    }

    private List<StationCoord> readCoords(StationNameNormalizer normalizer) throws IOException {
        List<StationCoord> coords = new ArrayList<>();
        for (Map<String, String> row : csv("seoulmetro-station-coords_20250814.csv").rows()) {
            LineCodes.fromSeoulMetroLine(row.get("호선")).ifPresent(lineId -> coords.add(new StationCoord(
                    lineId, normalizer.normalize(row.get("역명")),
                    Double.parseDouble(row.get("위도")), Double.parseDouble(row.get("경도")),
                    row.get("고유역번호(외부역코드)"))));
        }
        for (Map<String, String> row : csv("kric-line9-station-coords_20250630.csv").rows()) {
            coords.add(new StationCoord("1009", normalizer.normalize(row.get("역명")),
                    Double.parseDouble(row.get("위도")), Double.parseDouble(row.get("경도")), null));
        }
        return coords;
    }

    private Map<String, String> readPairs(String file, String keyCol, String valueCol) throws IOException {
        Map<String, String> out = new LinkedHashMap<>();
        for (Map<String, String> row : csv(file).rows()) {
            out.put(row.get(keyCol), row.get(valueCol));
        }
        return out;
    }

    private static CsvTable csv(String file) throws IOException {
        return CsvTable.parse(new ClassPathResource(DATA_DIR + file).getContentAsString(StandardCharsets.UTF_8));
    }

    private static void logWarnings(String stage, List<String> warnings) {
        warnings.forEach(w -> log.warn("{} 경고: {}", stage, w));
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
