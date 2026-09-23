package com.ssafy.s15p21a104.load.bikepred;

import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * AI 배치 산출물 CSV 를 읽는 원천. 경로는 <b>파일 또는 폴더</b>다.
 * <p>
 * 폴더를 주면 {@code bike_stock_pred_*.csv} 중 <b>파일명이 가장 늦은 것</b>을 고른다. 배치가 매일 03:00 에
 * 시각이 붙은 새 파일을 만들기 때문에(`AI/DATA_ENGINE` 의 {@code bike-avg-batch.timer}) 적재 명령이 날짜마다
 * 달라지면 안 된다. 파일명 정렬로 고르는 것은 AI 서빙 API 와 <b>같은 규칙</b>이다
 * ({@code AI/app/BIKE/service.py} 의 {@code sorted(glob)}) — 양쪽이 "최신"을 다르게 고르면 우리가 적재한 표와
 * AI API 응답이 어긋난다. 생성시각은 이름에 들어 있어 사전순 = 시간순이다.
 * <p>
 * 같은 이름의 {@code .meta.json} 이 있으면 {@code rows} 를 실제 행 수와 대조해 어긋날 때 경고한다 —
 * 전송이 끊겨 파일이 잘린 것을 적재 전에 잡는다. 대조는 있을 때만 하고, 실패해도 적재를 막지 않는다.
 * <p>
 * <b>사이드카가 {@code "source": "model"} 인 파일은 고르지 않는다</b> (S15P21A104-309). AI {@code batch_predict.py} 는
 * lightgbm 으로 돌아도 같은 {@code bike_stock_pred_<시각>.csv} 이름을 쓰는데, 열은 {@code dow_type} 대신
 * {@code pred_date} 다. 같은 폴더에 더 늦게 생기면 파일명 최신으로 그걸 집어 적재 전체가 멈춘다. 날짜축 산출물은
 * {@code load.bikepreddaily} 가 따로 읽는다.
 */
public final class CsvBikeStockPredSource implements BikeStockPredSource {

    static final String FILE_PREFIX = "bike_stock_pred_";
    static final String FILE_SUFFIX = ".csv";
    /** meta.json 에서 행 수만 읽는다. JSON 파서를 들이지 않으려고 숫자 하나만 뽑는다. */
    private static final Pattern META_ROWS = Pattern.compile("\"rows\"\\s*:\\s*(\\d+)");
    /** 날짜축(lightgbm) 산출물 표시. 이 로더의 대상이 아니다. */
    private static final Pattern META_MODEL = Pattern.compile("\"source\"\\s*:\\s*\"model\"");

    private final Path path;

    public CsvBikeStockPredSource(Path path) {
        this.path = path;
    }

    @Override
    public Loaded read() throws IOException {
        Path csv = resolveCsv();
        var parser = new BikeStockPredParser();
        try (Reader reader = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
            CsvTable.forEachRow(reader, parser::accept);
        }
        BikeStockPredParser.Result parsed = parser.finish();

        List<String> warnings = new ArrayList<>(parser.warnings());
        metaMismatch(csv, parsed.stats().sourceRows()).ifPresent(warnings::add);
        return new Loaded(parsed.rows(), parsed.stats(), csv, List.copyOf(warnings));
    }

    /** 폴더면 최신 산출물을 고르고, 파일이면 그대로 쓴다. 어느 쪽이든 없으면 찾은 경로를 밝힌다. */
    private Path resolveCsv() throws IOException {
        if (Files.isDirectory(path)) {
            List<Path> newestFirst;
            try (Stream<Path> files = Files.list(path)) {
                newestFirst = files.filter(CsvBikeStockPredSource::isArtifact)
                        .sorted(Comparator.comparing((Path p) -> p.getFileName().toString()).reversed())
                        .toList();
            }
            for (Path candidate : newestFirst) {
                if (!isModelArtifact(candidate)) {
                    return candidate;
                }
            }
            throw new IOException("재고 예측 산출물이 없습니다: " + path + " 에 " + FILE_PREFIX + "*" + FILE_SUFFIX);
        }
        if (!Files.isRegularFile(path)) {
            throw new IOException("재고 예측 산출물이 없습니다: " + path);
        }
        return path;
    }

    /** parquet·meta.json 이 같은 폴더에 있으므로 이름 규칙으로 CSV 만 고른다. */
    private static boolean isArtifact(Path p) {
        String name = p.getFileName().toString();
        return name.startsWith(FILE_PREFIX) && name.endsWith(FILE_SUFFIX);
    }

    /** 사이드카가 날짜축(lightgbm) 산출물이라고 말하면 true. 사이드카가 없거나 못 읽으면 요일축으로 본다. */
    private static boolean isModelArtifact(Path csv) {
        Path meta = metaOf(csv);
        if (!Files.isRegularFile(meta)) {
            return false;
        }
        try {
            return META_MODEL.matcher(Files.readString(meta, StandardCharsets.UTF_8)).find();
        } catch (IOException e) {
            return false;
        }
    }

    private static Path metaOf(Path csv) {
        String name = csv.getFileName().toString();
        return csv.resolveSibling(name.substring(0, name.length() - FILE_SUFFIX.length()) + ".meta.json");
    }

    /**
     * 옆의 meta.json 과 행 수를 대조한다. 파일이 없거나 형식이 달라 읽지 못하면 그것도 경고로만 남긴다 —
     * 대조는 보조 확인이라 적재를 막을 이유가 없다.
     */
    private static Optional<String> metaMismatch(Path csv, int actualRows) {
        Path meta = metaOf(csv);
        if (!Files.isRegularFile(meta)) {
            return Optional.empty();
        }
        String text;
        try {
            text = Files.readString(meta, StandardCharsets.UTF_8);
        } catch (IOException e) {
            return Optional.of("meta.json 을 읽지 못해 행 수를 대조하지 못했습니다: " + meta + " (" + e.getMessage() + ")");
        }
        Matcher m = META_ROWS.matcher(text);
        if (!m.find()) {
            return Optional.of("meta.json 에 rows 가 없어 행 수를 대조하지 못했습니다: " + meta);
        }
        int expected = Integer.parseInt(m.group(1));
        if (expected == actualRows) {
            return Optional.empty();
        }
        return Optional.of("meta.json 의 rows 와 실제 행 수가 다릅니다 — 파일이 잘렸을 수 있습니다: "
                + "meta " + expected + " · 실제 " + actualRows + " (" + meta + ")");
    }
}
