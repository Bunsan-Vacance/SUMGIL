package com.ssafy.s15p21a104.load.bikepreddaily;

import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;
import java.util.stream.Stream;

/**
 * AI 따릉이 날짜축 예측 산출물 CSV 를 읽는 원천 (S15P21A104-309). 경로는 <b>파일 또는 폴더</b>다.
 *
 * <p>폴더를 주면 {@code bike_stock_pred_*.csv} 중 사이드카에 {@code target_date} 가 있는 것만 골라
 * <b>대상 날짜마다 {@code generated_at} 이 가장 늦은 회차 하나씩</b> 읽는다. 혼잡도 원천
 * ({@code CsvCongestionPredSource})과 같은 규칙인데 두 군데가 다르다:
 * <ul>
 *   <li><b>대상 날짜를 파일명이 아니라 사이드카에서 읽는다.</b> AI {@code batch_predict.py} 가 예측기와 무관하게
 *       {@code bike_stock_pred_<생성시각>.csv} 로 짓기 때문이다 — 이름에 대상 날짜가 없다</li>
 *   <li><b>avg 산출물이 섞여도 고르지 않는다.</b> 같은 파일명 규칙이고 사이드카 {@code target_date} 만 {@code null} 이다.
 *       폴더는 분리하지만({@code serving-daily}) 누가 잘못 놓아도 조용히 섞이지 않게 한다</li>
 * </ul>
 *
 * <p><b>사이드카는 필수다</b> — {@code generated_at} 이 NOT NULL 열이고, {@code rows} 합이 어긋나면 잘린 파일이라
 * 그날 예측이 반쪽으로 들어간다. 둘 다 경고로 넘기지 않고 멈춘다.
 *
 * <p>반대로 <b>산출물이 아직 없는 것은 멈추지 않는다</b> — 폴더가 없거나 비었으면 경고와 빈 결과를 돌려준다.
 * 날짜축 표는 비어도 되는 표이고(조회가 평균표로 떨어진다), 매일 도는 CronJob 이 AI 산출물 시작 전까지
 * 실패로 찍히면 진짜 실패가 묻힌다.
 */
public final class CsvBikeStockPredDailySource implements BikeStockPredDailySource {

    static final String FILE_PREFIX = "bike_stock_pred_";
    static final String FILE_SUFFIX = ".csv";
    static final String META_SUFFIX = ".meta.json";

    private final Path path;

    public CsvBikeStockPredDailySource(Path path) {
        this.path = path;
    }

    @Override
    public Loaded read() throws IOException {
        List<Path> csvs = resolveCsvs();
        if (csvs.isEmpty()) {
            // 날짜축 표는 비어 있어도 된다(조회가 평균표로 떨어진다). AI 가 산출물을 내기 전에 매일 실패로 멈추면
            // CronJob 실패 기록이 가짜로 쌓여 앞 적재의 진짜 실패가 묻힌다 — 경고만 남기고 0행으로 넘긴다.
            var empty = new BikeStockPredDailyParser().finish();
            return new Loaded(List.of(), empty.stats(), List.of(), List.of(
                    "따릉이 날짜축 예측 산출물이 아직 없어 건너뜁니다 (조회는 평균표로 나간다): " + path
                            + " 에 사이드카 target_date 가 있는 " + FILE_PREFIX + "*" + FILE_SUFFIX));
        }

        var parser = new BikeStockPredDailyParser();
        int expectedRows = 0;
        for (Path csv : csvs) {
            BikeStockPredDailyMeta meta = readMeta(csv);
            expectedRows += meta.rows();
            parser.beginFile(meta.generatedAt());
            try (Reader reader = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
                CsvTable.forEachRow(reader, parser::accept);
            }
        }
        BikeStockPredDailyParser.Result parsed = parser.finish();

        if (expectedRows != parsed.stats().sourceRows()) {
            throw new IOException("사이드카 meta 의 rows 합과 실제 행 수가 다릅니다 — 파일이 잘렸을 수 있습니다: "
                    + "meta " + expectedRows + " · 실제 " + parsed.stats().sourceRows() + " (" + csvs + ")");
        }
        return new Loaded(parsed.rows(), parsed.stats(), csvs, parser.warnings());
    }

    /**
     * 폴더면 대상 날짜마다 최신 회차 하나씩(날짜 순), 파일이면 그것 하나. 폴더가 없거나 날짜축 산출물이 없으면 빈 목록이다.
     * 경로가 {@code .csv} 로 끝나면 사람이 파일을 고른 것이라, 없으면 빈 목록이 아니라 멈춘다.
     */
    private List<Path> resolveCsvs() throws IOException {
        if (Files.isRegularFile(path)) {
            return List.of(path);
        }
        if (!Files.isDirectory(path)) {
            if (path.getFileName() != null && path.getFileName().toString().endsWith(FILE_SUFFIX)) {
                throw new IOException("따릉이 날짜축 예측 산출물이 없습니다: " + path);
            }
            return List.of();
        }
        Map<LocalDate, Path> latestByDate = new TreeMap<>();
        Map<LocalDate, BikeStockPredDailyMeta> latestMeta = new TreeMap<>();
        List<Path> candidates;
        try (Stream<Path> files = Files.list(path)) {
            candidates = files.filter(CsvBikeStockPredDailySource::isCsv).sorted().toList();
        }
        for (Path csv : candidates) {
            Optional<String> text = metaText(csv);
            if (text.isEmpty() || BikeStockPredDailyMeta.targetDateOf(text.get()).isEmpty()) {
                continue; // 사이드카 없는 파일·avg 산출물 — 날짜축 후보가 아니다
            }
            BikeStockPredDailyMeta meta = BikeStockPredDailyMeta.parse(text.get(), metaOf(csv).toString());
            BikeStockPredDailyMeta best = latestMeta.get(meta.targetDate());
            // 같으면 파일명이 뒤인 것 — candidates 가 이름 순이라 나중 것이 이긴다.
            if (best == null || !meta.generatedAt().isBefore(best.generatedAt())) {
                latestMeta.put(meta.targetDate(), meta);
                latestByDate.put(meta.targetDate(), csv);
            }
        }
        return new ArrayList<>(latestByDate.values());
    }

    private static boolean isCsv(Path p) {
        String name = p.getFileName().toString();
        return name.startsWith(FILE_PREFIX) && name.endsWith(FILE_SUFFIX);
    }

    private static Path metaOf(Path csv) {
        String name = csv.getFileName().toString();
        return csv.resolveSibling(name.substring(0, name.length() - FILE_SUFFIX.length()) + META_SUFFIX);
    }

    private static Optional<String> metaText(Path csv) throws IOException {
        Path meta = metaOf(csv);
        return Files.isRegularFile(meta) ? Optional.of(Files.readString(meta, StandardCharsets.UTF_8)) : Optional.empty();
    }

    private static BikeStockPredDailyMeta readMeta(Path csv) throws IOException {
        Path meta = metaOf(csv);
        if (!Files.isRegularFile(meta)) {
            throw new IOException("사이드카 meta 가 없습니다 — generated_at 과 행 수 대조에 필요합니다: " + meta);
        }
        return BikeStockPredDailyMeta.parse(Files.readString(meta, StandardCharsets.UTF_8), meta.toString());
    }
}
