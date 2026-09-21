package com.ssafy.s15p21a104.load.crowdpred;

import com.ssafy.s15p21a104.load.crowd.CrowdStationCodes;
import com.ssafy.s15p21a104.load.subway.LineCodes;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * AI CROWD 배치 산출물({@code AI/data/CROWD/serving/predictions_<날짜>_<시각>.csv}) →
 * {@link CongestionPredRow} (S15P21A104-305).
 *
 * <p>열 10개는 {@code pred_date · line · from_station_no · to_station_no · direction · time_slot ·
 * level · data_status · pred_source · predictor_version} 이고 순서·이름은 회신 04 6.1절에서 확정했다.
 * 하루치가 2만 행대라 {@link #accept(Map)} 로 한 행씩 받는다(재고 예측 파서와 같은 방식).
 *
 * <p><b>값을 만들어 넣지 않는다.</b> {@code level} 이 빈 칸이면 그대로 null 이다 — 0 으로 채우면
 * "혼잡도 0%" 와 "모른다" 가 구분되지 않는다. 그래서 {@code data_status} 가 이유를 따로 말한다.
 *
 * <p><b>{@code direction} 은 원천 값을 그대로 둔다.</b> 2호선이라도 지선 구간은 내선/외선이 아니라
 * 상선/하선으로 온다(AI 통지 07). 역번호 순서로 재추론하면 그런 구간이 어긋나고, 애초에
 * {@code from→to} 가 이미 방향 있는 링크라 재추론할 이유가 없다.
 *
 * <p>역번호는 {@link CrowdStationCodes} 로 우리 {@code station_id} 에 잇는다 — 혼잡도 통계 적재와
 * <b>같은 표를 재사용</b>한다. 원천이 같은 서울교통공사 외부역코드 체계이기 때문이다(AI 통지 07 4절).
 * 모르는 역번호·노선은 <b>행을 만들지 않고</b> 건수를 집계 경고한다 — 추측으로 채우지 않는다.
 */
public final class CongestionPredParser {

    /** 하나라도 없으면 원천 스키마가 바뀐 것이라 첫 행에서 멈춘다. */
    private static final List<String> REQUIRED_COLUMNS = List.of(
            "pred_date", "line", "from_station_no", "to_station_no", "direction",
            "time_slot", "level", "data_status", "pred_source", "predictor_version");

    /** {@code level} 은 NUMERIC(5,1). */
    private static final int LEVEL_SCALE = 1;
    private static final int EXAMPLE_LIMIT = 10;

    /**
     * @param sourceRows      읽은 원천 행 수
     * @param links           행이 만들어진 고유 링크 수 (from|to|line|direction)
     * @param timeSlots       나온 슬롯 종류 수. <b>48 이 아니다</b> — 운행 없는 새벽은 행이 없다
     * @param skipped         매핑·형식 문제로 행을 만들지 않은 원천 행 수
     * @param unknownStations 우리 역 표에 없던 역번호 종류 수
     * @param unknownLines    우리 노선 표에 없던 노선 이름 종류 수
     * @param predDates       나온 대상 날짜들. 배치가 오늘·내일 2일치를 만들 수 있어 하나로 가정하지 않는다
     * @param predSources     {@code pred_source} 별 행 수. {@code lookup_*} 비율이 곧 모델을 안 쓴 비율이다
     */
    public record Stats(int sourceRows, int links, int timeSlots, int skipped,
                        int unknownStations, int unknownLines,
                        Set<LocalDate> predDates, Map<String, Integer> predSources) {
    }

    public record Result(List<CongestionPredRow> rows, Stats stats) {
    }

    private final CrowdStationCodes codes;

    private final List<CongestionPredRow> rows = new ArrayList<>();
    private final Set<String> links = new LinkedHashSet<>();
    private final Set<Integer> slots = new LinkedHashSet<>();
    private final Set<LocalDate> predDates = new LinkedHashSet<>();
    private final Map<String, Integer> predSources = new LinkedHashMap<>();
    private final Set<String> unknownStations = new LinkedHashSet<>();
    private final Set<String> unknownLines = new LinkedHashSet<>();
    private final List<String> badRows = new ArrayList<>();
    private final List<String> warnings = new ArrayList<>();
    private int sourceRows;
    private int skipped;
    private boolean columnsChecked;

    public CongestionPredParser(CrowdStationCodes codes) {
        this.codes = codes;
    }

    public void accept(Map<String, String> row) {
        if (!columnsChecked) {
            requireColumns(row);
            columnsChecked = true;
        }
        sourceRows++;

        LocalDate predDate = dateOrNull(row.get("pred_date"));
        Integer timeSlot = intOrNull(row.get("time_slot"));
        String fromRaw = value(row, "from_station_no");
        String toRaw = value(row, "to_station_no");
        Optional<String> from = codes.stationIdOf(fromRaw);
        Optional<String> to = codes.stationIdOf(toRaw);
        String lineName = value(row, "line");
        Optional<String> lineId = LineCodes.fromName(lineName);

        if (from.isEmpty()) {
            unknownStations.add(fromRaw);
        }
        if (to.isEmpty()) {
            unknownStations.add(toRaw);
        }
        if (lineId.isEmpty()) {
            unknownLines.add(lineName);
        }
        if (predDate == null || timeSlot == null || from.isEmpty() || to.isEmpty() || lineId.isEmpty()) {
            skipped++;
            if (badRows.size() < EXAMPLE_LIMIT) {
                badRows.add(lineName + " " + fromRaw + "→" + toRaw + " slot=" + value(row, "time_slot"));
            }
            return;
        }

        rows.add(new CongestionPredRow(predDate, from.get(), to.get(), lineId.get(),
                value(row, "direction"), timeSlot, decimalOrNull(row.get("level")),
                value(row, "data_status"), value(row, "pred_source"), value(row, "predictor_version")));
        links.add(from.get() + "|" + to.get() + "|" + lineId.get() + "|" + value(row, "direction"));
        slots.add(timeSlot);
        predDates.add(predDate);
        predSources.merge(value(row, "pred_source"), 1, Integer::sum);
    }

    public Result finish() {
        if (!unknownStations.isEmpty()) {
            warnings.add("역 표에 없는 역번호 " + unknownStations.size()
                    + "종 (혼잡도 별칭표 conf/crowd-station-aliases.csv 에 추가하거나 역 마스터를 확인한다): "
                    + head(List.copyOf(unknownStations)));
        }
        if (!unknownLines.isEmpty()) {
            warnings.add("노선 표에 없는 노선 " + unknownLines.size() + "종: " + head(List.copyOf(unknownLines)));
        }
        if (skipped > 0) {
            warnings.add("매핑·형식 문제로 " + skipped + "행 건너뜀 (값을 지어내지 않는다): " + head(badRows));
        }
        return new Result(List.copyOf(rows), new Stats(sourceRows, links.size(), slots.size(), skipped,
                unknownStations.size(), unknownLines.size(),
                Set.copyOf(predDates), Map.copyOf(predSources)));
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    private static void requireColumns(Map<String, String> row) {
        List<String> missing = REQUIRED_COLUMNS.stream().filter(c -> !row.containsKey(c)).toList();
        if (!missing.isEmpty()) {
            throw new IllegalStateException("원천 CSV 에 필수 열이 없습니다: " + String.join(", ", missing)
                    + " (있는 열: " + String.join(", ", row.keySet()) + ")");
        }
    }

    /** 빈 칸은 결측이라 null 이다 — 0 으로 채우지 않는다. 숫자가 아니어도 null(그 행은 status 가 설명한다). */
    private static BigDecimal decimalOrNull(String raw) {
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return new BigDecimal(text).setScale(LEVEL_SCALE, RoundingMode.HALF_UP);
        } catch (NumberFormatException e) {
            return null;
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

    private static String head(List<String> items) {
        List<String> shown = items.size() > EXAMPLE_LIMIT ? items.subList(0, EXAMPLE_LIMIT) : items;
        String joined = String.join(", ", shown);
        return items.size() > EXAMPLE_LIMIT ? joined + ", …" : joined;
    }
}
