package com.ssafy.s15p21a104.load.bikepred;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * AI 배치 산출물({@code data/BIKE/serving/bike_stock_pred_<시각>.csv}) → {@link BikeStockPredRow}.
 * 열은 {@code rental_id · dow_type · time_slot · exp_bikes · p_empty · p_full · source · prediction_source} 다.
 * 대여소 약 2,800 × 요일 3 × 슬롯 48 = 40만 행이라 {@link #accept(Map)} 로 한 행씩 받는다
 * (시각표 파서와 같은 방식 — 원천을 통째로 메모리에 올리지 않는다).
 * <p>
 * <b>값을 만들어 넣지 않는다.</b> 숫자 칸이 비었거나 숫자가 아니면 그 행을 만들지 않고 건수를 한 줄로 집계 경고한다.
 * 원천은 AI 가 대여소 내부 평균으로 이미 격자를 다 채워 보내므로(그래서 {@code prediction_source} 가 있다)
 * 빈 칸이 나온다는 것은 파이프라인이 바뀌었다는 뜻이고, 우리가 임의로 메우면 그 신호가 사라진다.
 * <p>
 * <b>마스터에 없는 대여소를 여기서 거르지 않는다.</b> 예측 표가 대여소 마스터보다 최근이라 신설 대여소가 섞이는데,
 * 어느 쪽이 낡았는지는 이 파서가 알 수 없다. 적재 대상 판단은 러너가 마스터와 대조해 경고로 남긴다.
 */
public final class BikeStockPredParser {

    /** 없으면 원천 스키마가 바뀐 것이라 멈춘다. {@code prediction_source} 는 AI 가 나중에 붙인 열이라 뺀다. */
    private static final List<String> REQUIRED_COLUMNS =
            List.of("rental_id", "dow_type", "time_slot", "exp_bikes", "p_empty", "p_full", "source");

    /** {@code exp_bikes} 는 NUMERIC(5,1). */
    private static final int EXP_BIKES_SCALE = 1;
    /** {@code p_empty}·{@code p_full} 은 NUMERIC(4,3). */
    private static final int PROBABILITY_SCALE = 3;
    private static final int EXAMPLE_LIMIT = 10;

    /**
     * @param sourceRows        읽은 원천 행 수
     * @param stations          행이 만들어진 고유 대여소 수
     * @param skipped           숫자 칸이 비었거나 숫자가 아니어서 행을 만들지 않은 원천 행 수
     * @param predictionSources 라벨별 행 수 ({@code observed_avg} 가 아닌 비율이 곧 대체값 비율이다). 라벨 없는 행은 세지 않는다
     */
    public record Stats(int sourceRows, int stations, int skipped, Map<String, Integer> predictionSources) {
    }

    public record Result(List<BikeStockPredRow> rows, Stats stats) {
    }

    private final List<BikeStockPredRow> rows = new ArrayList<>();
    private final Set<String> stations = new LinkedHashSet<>();
    private final Map<String, Integer> predictionSources = new LinkedHashMap<>();
    private final List<String> skippedExamples = new ArrayList<>();
    private final List<String> warnings = new ArrayList<>();
    private int sourceRows;
    private int skipped;
    private boolean columnsChecked;

    public void accept(Map<String, String> row) {
        if (!columnsChecked) {
            requireColumns(row);
            columnsChecked = true;
        }
        sourceRows++;

        String rentalId = value(row, "rental_id");
        Integer dowType = intOrNull(row.get("dow_type"));
        Integer timeSlot = intOrNull(row.get("time_slot"));
        BigDecimal expBikes = decimalOrNull(row.get("exp_bikes"), EXP_BIKES_SCALE);
        BigDecimal pEmpty = decimalOrNull(row.get("p_empty"), PROBABILITY_SCALE);
        BigDecimal pFull = decimalOrNull(row.get("p_full"), PROBABILITY_SCALE);

        if (rentalId.isEmpty() || dowType == null || timeSlot == null
                || expBikes == null || pEmpty == null || pFull == null) {
            skipped++;
            if (skippedExamples.size() < EXAMPLE_LIMIT) {
                skippedExamples.add(rentalId.isEmpty() ? "(대여소 없음)" : rentalId);
            }
            return;
        }

        String predictionSource = emptyToNull(value(row, "prediction_source"));
        rows.add(new BikeStockPredRow(rentalId, dowType, timeSlot, expBikes, pEmpty, pFull,
                value(row, "source"), predictionSource));
        stations.add(rentalId);
        if (predictionSource != null) {
            predictionSources.merge(predictionSource, 1, Integer::sum);
        }
    }

    public Result finish() {
        if (skipped > 0) {
            warnings.add("숫자 칸이 비었거나 숫자가 아니어서 " + skipped + "행 건너뜀 (값을 채우지 않는다): " + head(skippedExamples));
        }
        return new Result(List.copyOf(rows), new Stats(sourceRows, stations.size(), skipped, Map.copyOf(predictionSources)));
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** 원천 스키마가 바뀌면 조용히 빈 값으로 읽히지 않도록 첫 행에서 멈춘다. 헤더는 모든 행이 같다 (CsvTable 계약). */
    private static void requireColumns(Map<String, String> row) {
        List<String> missing = REQUIRED_COLUMNS.stream().filter(c -> !row.containsKey(c)).toList();
        if (!missing.isEmpty()) {
            throw new IllegalStateException("원천 CSV 에 필수 열이 없습니다: " + String.join(", ", missing)
                    + " (있는 열: " + String.join(", ", row.keySet()) + ")");
        }
    }

    /** 원천은 배정밀도 실수라 DB 스케일로 줄인다. 빈 칸·숫자 아님은 null — 그 행은 만들지 않는다. */
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
        String joined = String.join(", ", items);
        return items.size() >= EXAMPLE_LIMIT ? joined + ", …" : joined;
    }
}
