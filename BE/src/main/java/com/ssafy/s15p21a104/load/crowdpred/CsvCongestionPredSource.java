package com.ssafy.s15p21a104.load.crowdpred;

import com.ssafy.s15p21a104.load.crowd.CrowdStationCodes;
import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * AI CROWD 배치 산출물 CSV 를 읽는 원천. 경로는 <b>파일 또는 폴더</b>다.
 *
 * <p>폴더를 주면 {@code predictions_<날짜>_<시각>.csv} 중 <b>파일명이 가장 늦은 것</b>을 고른다.
 * 배치가 매일 09:30 KST 에 시각이 붙은 새 파일을 만들기 때문에 적재 명령이 날짜마다 달라지면 안 된다.
 * 이름에 생성시각이 들어 있어 사전순 = 시간순이다.
 *
 * <p>{@code predictions_train_…} 같은 다른 산출물과 parquet·meta 는 이름 규칙으로 걸러진다.
 *
 * <p><b>사이드카 {@code .meta.json} 은 필수다.</b> 재고 예측(172)은 없어도 경고만 내고 적재했지만
 * 여기서는 두 가지가 다르다 — ① {@code generated_at} 이 {@code congestion_pred} 의 NOT NULL 열이라
 * 없으면 넣을 값이 자체가 없고, ② {@code row_count} 가 어긋나면 전송이 끊긴 파일이라 그날 예측이
 * 반쪽으로 들어간다. 둘 다 경고로 넘기면 조용히 잘못된 표가 남는다.
 */
public final class CsvCongestionPredSource implements CongestionPredSource {

    /** {@code predictions_2026-09-20_234300.csv} 형태만 고른다. */
    static final Pattern ARTIFACT = Pattern.compile("^predictions_\\d{4}-\\d{2}-\\d{2}_\\d{6}\\.csv$");
    static final String FILE_SUFFIX = ".csv";
    static final String META_SUFFIX = ".meta.json";

    private final Path path;
    private final CrowdStationCodes codes;

    public CsvCongestionPredSource(Path path, CrowdStationCodes codes) {
        this.path = path;
        this.codes = codes;
    }

    @Override
    public Loaded read() throws IOException {
        Path csv = resolveCsv();
        CongestionPredMeta meta = readMeta(csv);

        var parser = new CongestionPredParser(codes);
        try (Reader reader = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
            CsvTable.forEachRow(reader, parser::accept);
        }
        CongestionPredParser.Result parsed = parser.finish();

        if (meta.rowCount() != parsed.stats().sourceRows()) {
            throw new IOException("사이드카 meta 의 row_count 와 실제 행 수가 다릅니다 — 파일이 잘렸을 수 있습니다: "
                    + "meta " + meta.rowCount() + " · 실제 " + parsed.stats().sourceRows() + " (" + csv + ")");
        }
        return new Loaded(parsed.rows(), parsed.stats(), csv, meta, parser.warnings());
    }

    /** 폴더면 최신 산출물을 고르고, 파일이면 그대로 쓴다. 어느 쪽이든 없으면 찾은 경로를 밝힌다. */
    private Path resolveCsv() throws IOException {
        if (Files.isDirectory(path)) {
            try (Stream<Path> files = Files.list(path)) {
                return files.filter(CsvCongestionPredSource::isArtifact)
                        .max(Comparator.comparing(p -> p.getFileName().toString()))
                        .orElseThrow(() -> new IOException(
                                "혼잡도 예측 산출물이 없습니다: " + path + " 에 predictions_<날짜>_<시각>.csv"));
            }
        }
        if (!Files.isRegularFile(path)) {
            throw new IOException("혼잡도 예측 산출물이 없습니다: " + path);
        }
        return path;
    }

    private static boolean isArtifact(Path p) {
        return ARTIFACT.matcher(p.getFileName().toString()).matches();
    }

    private static CongestionPredMeta readMeta(Path csv) throws IOException {
        String name = csv.getFileName().toString();
        Path meta = csv.resolveSibling(name.substring(0, name.length() - FILE_SUFFIX.length()) + META_SUFFIX);
        if (!Files.isRegularFile(meta)) {
            throw new IOException("사이드카 meta 가 없습니다 — generated_at 과 행 수 대조에 필요합니다: " + meta);
        }
        return CongestionPredMeta.parse(Files.readString(meta, StandardCharsets.UTF_8), meta.toString());
    }
}
