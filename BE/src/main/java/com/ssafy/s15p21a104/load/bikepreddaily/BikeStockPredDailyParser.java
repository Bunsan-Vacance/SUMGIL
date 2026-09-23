package com.ssafy.s15p21a104.load.bikepreddaily;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * AI 날짜축 예측 산출물 CSV → {@link BikeStockPredDailyRow} (S15P21A104-309).
 * 열은 {@code rental_id · pred_date · time_slot · exp_bikes · p_empty · p_full · source} 이고
 * {@code prediction_source} 는 있으면 읽는다(lightgbm 산출물에는 없다).
 *
 * <p>규칙은 요일축 파서({@code BikeStockPredParser})와 같다 — <b>값을 만들어 넣지 않는다</b>(빈 칸·형식 오류는 행을
 * 건너뛰고 건수를 경고), 마스터 대조는 여기서 하지 않는다. 다른 점은 파일을 여러 개 이어 먹이고, 파일마다
 * {@link #beginFile(OffsetDateTime)} 로 그 사이드카의 {@code generated_at} 을 받아 행에 싣는다는 것이다.
 */
public final class BikeStockPredDailyParser {

    /** 없으면 원천 스키마가 다른 것이라 멈춘다. avg 산출물(dow_type)을 날짜축으로 잘못 읽는 것도 여기서 막힌다. */
    private static final List<String> REQUIRED_COLUMNS =
            List.of("rental_id", "pred_date", "time_slot", "exp_bikes", "p_empty", "p_full", "source");

    private static final int EXP_BIKES_SCALE = 1;
    private static final int PROBABILITY_SCALE = 3;
    private static final int EXAMPLE_LIMIT = 10;

    /**
     * @param sourceRows        읽은 원천 행 수 (모든 파일 합)
     * @param stations          행이 만들어진 고유 대여소 수
     * @param predDates         행이 만들어진 대상 날짜 (오름차순)
     * @param skipped           빈 칸·형식 오류로 행을 만들지 않은 원천 행 수
     * @param predictionSources 라벨별 행 수. 라벨 없는 행은 세지 않는다
     */
    public record Stats(int sourceRows, int stations, List<LocalDate> predDates, int skipped,
                        Map<String, Integer> predictionSources) {
    }

    public record Result(List<BikeStockPredDailyRow> rows, Stats stats) {
    }

    private final List<BikeStockPredDailyRow> rows = new ArrayList<>();
    private final Set<String> stations = new LinkedHashSet<>();
    private final Set<LocalDate> predDates = new TreeSet<>();
    private final Map<String, Integer> predictionSources = new LinkedHashMap<>();
    private final List<String> skippedExamples = new ArrayList<>();
    private final List<String> warnings = new ArrayList<>();
    private OffsetDateTime generatedAt;
    private int sourceRows;
    private int skipped;
    private boolean columnsChecked;

    /** 다음 파일을 먹이기 전에 부른다. 헤더 검사도 파일마다 다시 한다. */
    public void beginFile(OffsetDateTime fileGeneratedAt) {
        this.generatedAt = fileGeneratedAt;
        this.columnsChecked = false;
    }

    public void accept(Map<String, String> row) {
        if (generatedAt == null) {
            throw new IllegalStateException("beginFile(generatedAt) 을 먼저 불러야 합니다");
        }
        if (!columnsChecked) {
            requireColumns(row);
            columnsChecked = true;
        }
        sourceRows++;

        String rentalId = value(row, "rental_id");
        LocalDate predDate = dateOrNull(row.get("pred_date"));
        Integer timeSlot = intOrNull(row.get("time_slot"));
        BigDecimal expBikes = decimalOrNull(row.get("exp_bikes"), EXP_BIKES_SCALE);
        BigDecimal pEmpty = decimalOrNull(row.get("p_empty"), PROBABILITY_SCALE);
        BigDecimal pFull = decimalOrNull(row.get("p_full"), PROBABILITY_SCALE);

        if (rentalId.isEmpty() || predDate == null || timeSlot == null
                || expBikes == null || pEmpty == null || pFull == null) {
            skipped++;
            if (skippedExamples.size() < EXAMPLE_LIMIT) {
                skippedExamples.add(rentalId.isEmpty() ? "(대여소 없음)" : rentalId);
            }
            return;
        }

        String predictionSource = emptyToNull(value(row, "prediction_source"));
        rows.add(new BikeStockPredDailyRow(rentalId, predDate, timeSlot, expBikes, pEmpty, pFull,
                value(row, "source"), predictionSource, generatedAt));
        stations.add(rentalId);
        predDates.add(predDate);
        if (predictionSource != null) {
            predictionSources.merge(predictionSource, 1, Integer::sum);
        }
    }

    public Result finish() {
        if (skipped > 0) {
            warnings.add("숫자·날짜 칸이 비었거나 형식이 틀려 " + skipped + "행 건너뜀 (값을 채우지 않는다): "
                    + head(skippedExamples));
        }
        return new Result(List.copyOf(rows), new Stats(sourceRows, stations.size(), List.copyOf(predDates),
                skipped, Map.copyOf(predictionSources)));
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    private static void requireColumns(Map<String, String> row) {
        List<String> missing = REQUIRED_COLUMNS.stream().filter(c -> !row.containsKey(c)).toList();
        if (!missing.isEmpty()) {
            throw new IllegalStateException("날짜축 예측 CSV 에 필수 열이 없습니다: " + String.join(", ", missing)
                    + " (있는 열: " + String.join(", ", row.keySet()) + ")");
        }
    }

    private static LocalDate dateOrNull(String raw) {
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return LocalDate.parse(text);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    private static BigDecimal decimalOrNull(String raw, int scale) {
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return new BigDecimal(text).setScale(scale, RoundingMode.HALF_UP);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Integer intOrNull(String raw) {
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return Integer.valueOf(text);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }

    private static String emptyToNull(String text) {
        return text.isEmpty() ? null : text;
    }

    private static String head(List<String> items) {
        return String.join(", ", items) + (items.size() >= EXAMPLE_LIMIT ? " …" : "");
    }
}
