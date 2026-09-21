package com.ssafy.s15p21a104.load.crowdpred;

import com.ssafy.s15p21a104.load.crowd.CrowdStationCodes;
import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * AI CROWD 배치 산출물 CSV 를 읽는 원천. 경로는 <b>파일 또는 폴더</b>다.
 *
 * <p>폴더를 주면 {@code predictions_<날짜>_<시각>.csv} 를 <b>대상 날짜마다 한 개씩, 그 날짜의 최신
 * 회차로</b> 골라 모두 읽는다. 파일 하나만 고르면 안 되는 이유가 두 겹이다:
 * <ul>
 *   <li>배치 기본이 {@code --today --tomorrow} 라 <b>한 번 돌 때 날짜가 다른 파일이 둘 생긴다.</b>
 *       이름만 정렬하면 내일 것만 잡히고 오늘 것이 영영 안 들어간다 — 조회는
 *       {@code pred_date = 오늘} 로 하므로 화면이 빈 채로 남는다</li>
 *   <li>같은 날짜를 다시 만들면 {@code _HHMMSS} 가 달라 <b>쌓인다</b>(AI 가 오래된 것을 지우지 않는다).
 *       그래서 날짜 안에서는 가장 늦은 회차 하나만 쓴다 — 판정은 파일명이 아니라 <b>사이드카
 *       {@code generated_at}</b> 이다. 파일명 시각엔 생성 날짜가 없어 이틀에 걸친 두 회차를 못 가른다(304)</li>
 * </ul>
 *
 * <p>대상 날짜는 파일명에서 읽는다 — 사이드카의 {@code target_date} 와 같은 값이고, 파일을 열지 않고
 * 고를 수 있어야 한다.
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
        List<Path> csvs = resolveCsvs();

        // 파서를 하나만 두고 파일을 이어 먹인다 — 통계(날짜·링크·슬롯·출처)가 전체 기준으로 집계된다.
        var parser = new CongestionPredParser(codes);
        CongestionPredMeta latestMeta = null;
        int expectedRows = 0;
        for (Path csv : csvs) {
            CongestionPredMeta meta = readMeta(csv);
            expectedRows += meta.rowCount();
            if (latestMeta == null || meta.generatedAt().isAfter(latestMeta.generatedAt())) {
                latestMeta = meta;
            }
            try (Reader reader = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
                CsvTable.forEachRow(reader, parser::accept);
            }
        }
        CongestionPredParser.Result parsed = parser.finish();

        if (expectedRows != parsed.stats().sourceRows()) {
            throw new IOException("사이드카 meta 의 row_count 합과 실제 행 수가 다릅니다 — 파일이 잘렸을 수 있습니다: "
                    + "meta " + expectedRows + " · 실제 " + parsed.stats().sourceRows() + " (" + csvs + ")");
        }
        // origin 은 대표 파일(가장 늦은 회차) — 로그·문서에 남길 한 줄이다. 전체 목록은 이 뒤 로그가 센다.
        Path origin = csvs.get(csvs.size() - 1);
        return new Loaded(parsed.rows(), parsed.stats(), origin, latestMeta, parser.warnings());
    }

    /**
     * 읽을 파일들. 폴더면 <b>대상 날짜마다 최신 회차 하나씩</b>을 날짜 순으로 돌려주고, 파일이면 그것 하나다.
     * 어느 쪽이든 없으면 찾은 경로를 밝힌다.
     *
     * <p>같은 날짜 안에서 "최신" 은 <b>사이드카 {@code generated_at}</b> 으로 정한다(같으면 파일명).
     * 파일명의 {@code _HHMMSS} 는 생성 <i>시각</i>만 있고 생성 <i>날짜</i>가 없다 — 같은 대상 날짜가
     * 전날 "내일치" 와 당일 "오늘치" 로 이틀에 걸쳐 두 번 만들어지고, 둘 다 00:30 UTC + 랜덤 지연이라
     * 파일명 정렬은 지터 크기로 갈린다. 당일 생성분(전날 실적이 lag 로 들어간 것)이 이겨야 한다(304).
     */
    private List<Path> resolveCsvs() throws IOException {
        if (!Files.isDirectory(path)) {
            if (!Files.isRegularFile(path)) {
                throw new IOException("혼잡도 예측 산출물이 없습니다: " + path);
            }
            return List.of(path);
        }
        Map<String, List<Path>> byDate = new TreeMap<>();
        try (Stream<Path> files = Files.list(path)) {
            files.filter(CsvCongestionPredSource::isArtifact)
                    .forEach(p -> byDate.computeIfAbsent(targetDateOf(p), k -> new ArrayList<>()).add(p));
        }
        if (byDate.isEmpty()) {
            throw new IOException("혼잡도 예측 산출물이 없습니다: " + path + " 에 predictions_<날짜>_<시각>.csv");
        }
        List<Path> chosen = new ArrayList<>(byDate.size());
        for (List<Path> candidates : byDate.values()) {
            chosen.add(latestByGeneratedAt(candidates));
        }
        return List.copyOf(chosen);
    }

    /** 같은 대상 날짜의 후보 중 사이드카 {@code generated_at} 이 가장 늦은 것. 같으면 파일명이 뒤인 것. */
    private static Path latestByGeneratedAt(List<Path> candidates) throws IOException {
        Path best = null;
        OffsetDateTime bestAt = null;
        for (Path candidate : candidates) {
            OffsetDateTime at = readMeta(candidate).generatedAt();
            boolean later = best == null || at.isAfter(bestAt)
                    || (at.isEqual(bestAt) && candidate.getFileName().toString()
                            .compareTo(best.getFileName().toString()) > 0);
            if (later) {
                best = candidate;
                bestAt = at;
            }
        }
        return best;
    }

    private static boolean isArtifact(Path p) {
        return ARTIFACT.matcher(p.getFileName().toString()).matches();
    }

    /** {@code predictions_2026-09-20_234300.csv} → {@code 2026-09-20}. 이름 규칙은 위 {@link #ARTIFACT} 가 강제한다. */
    private static String targetDateOf(Path p) {
        String name = p.getFileName().toString();
        return name.substring("predictions_".length(), "predictions_".length() + "0000-00-00".length());
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
