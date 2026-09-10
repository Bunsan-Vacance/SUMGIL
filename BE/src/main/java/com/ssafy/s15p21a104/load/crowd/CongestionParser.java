package com.ssafy.s15p21a104.load.crowd;

import com.ssafy.s15p21a104.load.subway.LineCodes;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 서울교통공사 "지하철혼잡도정보"(공공데이터포털 15071311) → {@link CongestionRow}.
 * 열은 {@code 구분 · 호선 · 역번호 · 역명 · 상하구분} + 30분 단위 시각 39개(5시30분~00시30분)이고, 1~8호선만 담는다.
 * <p>
 * <b>STATION 은 그 물리 역의 모든 노선·방향 중 최대값이다.</b> 스키마에 방향이 없고 환승역은 노선별 행이 따로 있는데
 * ({@code station_id} 는 노선 코드 최솟값이라 합쳐진다 — 서울역 1호선 150 · 4호선 426 → 둘 다 150) 값은 하나여야 한다.
 * 최대를 쓰는 이유는 경로 추천에서 혼잡을 보수적으로 봐야 하고 평균이 한 방향·한 노선의 극심(원천 최대 144.6)을 희석하기 때문이다.
 * <p>
 * <b>LINE 은 그 노선 안에서만 계산한다</b> — 노선별 (역, 방향 최대) 값들의 평균(소수 1자리). STATION 값을 재사용하면
 * 환승역이 다른 노선의 값을 끌고 들어와 노선 평균이 오염된다(1~8호선에 그런 역이 35개 있다).
 * <p>
 * 값을 만들어 넣지 않는다: 원천이 덮지 않는 슬롯(01:00~05:29)·빈 칸·모르는 역번호는 행을 만들지 않고,
 * 모르는 역번호·구분·상하구분은 건수와 예시를 한 줄로 집계 경고한다.
 */
public final class CongestionParser {

    /** 혼잡도 % 는 정원 대비라 100 을 넘을 수 있다 — 넘는 건수만 집계해 원천 성격을 로그에 남긴다. */
    static final BigDecimal OVER_THRESHOLD = new BigDecimal("100");
    private static final String SOURCE = "stat";
    static final String STATION = "STATION";
    static final String LINE = "LINE";
    private static final Pattern TIME_COLUMN = Pattern.compile("^(\\d{1,2})시(\\d{2})분$");
    private static final Map<String, Integer> DOW_TYPES = Map.of("평일", 0, "토요일", 1, "일요일", 2);
    private static final Set<String> DIRECTIONS = Set.of("상선", "하선", "내선", "외선");
    private static final int EXAMPLE_LIMIT = 10;
    private static final List<String> FIXED_COLUMNS = List.of("구분", "호선", "역번호", "역명", "상하구분");

    /**
     * @param sourceRows   읽은 원천 행 수
     * @param stations     STATION 행이 만들어진 고유 역 수
     * @param slots        값이 있는 고유 슬롯 수
     * @param unknownCodes 역 ID 표에 없어 건너뛴 원천 행 수
     * @param over100      100 을 넘는 값의 수
     */
    public record Stats(int sourceRows, int stations, int slots, int unknownCodes, int over100) {
    }

    public record Result(List<CongestionRow> rows, Stats stats) {
    }

    private final CrowdStationCodes codes;
    private final List<String> warnings = new ArrayList<>();

    public CongestionParser(CrowdStationCodes codes) {
        this.codes = codes;
    }

    public Result parse(List<Map<String, String>> sourceRows) {
        warnings.clear();
        // (station|dow|slot) → 그 역의 모든 노선·방향 중 최대. 환승역은 노선 행이 여럿이라 여기서 한 값으로 합쳐진다.
        Map<String, BigDecimal> stationMax = new LinkedHashMap<>();
        // (line|station|dow|slot) → 그 노선 안에서의 방향 최대. LINE 평균은 이 값으로 낸다 —
        // STATION 을 재사용하면 환승역이 다른 노선의 값을 끌고 들어온다.
        Map<String, BigDecimal> lineStationMax = new LinkedHashMap<>();
        Set<String> stations = new LinkedHashSet<>();
        Set<Integer> slots = new LinkedHashSet<>();
        List<String> unknownStations = new ArrayList<>();
        Set<String> unknownDayOrDirection = new LinkedHashSet<>();
        int over100 = 0;

        for (Map<String, String> row : sourceRows) {
            String dowLabel = value(row, "구분");
            String direction = value(row, "상하구분");
            Integer dowType = DOW_TYPES.get(dowLabel);
            if (dowType == null || !DIRECTIONS.contains(direction)) {
                unknownDayOrDirection.add(dowLabel + "/" + direction);
                continue;
            }
            String crowdCode = value(row, "역번호");
            Optional<String> stationId = codes.stationIdOf(crowdCode);
            if (stationId.isEmpty()) {
                unknownStations.add(value(row, "역명") + "(" + crowdCode + ", " + value(row, "호선") + ")");
                continue;
            }
            String id = stationId.get();
            stations.add(id);
            String lineId = LineCodes.fromName(value(row, "호선")).orElse(null);

            for (Map.Entry<String, String> cell : row.entrySet()) {
                if (FIXED_COLUMNS.contains(cell.getKey())) {
                    continue;
                }
                Integer slot = slotOf(cell.getKey());
                if (slot == null) {
                    continue;
                }
                BigDecimal level = levelOf(cell.getValue());
                if (level == null) {
                    continue;
                }
                if (level.compareTo(OVER_THRESHOLD) > 0) {
                    over100++;
                }
                slots.add(slot);
                stationMax.merge(id + "|" + dowType + "|" + slot, level, CongestionParser::max);
                if (lineId != null) {
                    lineStationMax.merge(lineId + "|" + id + "|" + dowType + "|" + slot, level, CongestionParser::max);
                }
            }
        }

        List<CongestionRow> rows = new ArrayList<>(stationMax.size());
        for (Map.Entry<String, BigDecimal> e : stationMax.entrySet()) {
            String[] k = e.getKey().split("\\|", 3);
            rows.add(new CongestionRow(STATION, k[0], Integer.parseInt(k[1]), Integer.parseInt(k[2]), e.getValue(), SOURCE));
        }
        Map<String, List<BigDecimal>> lineValues = new LinkedHashMap<>();
        for (Map.Entry<String, BigDecimal> e : lineStationMax.entrySet()) {
            String[] k = e.getKey().split("\\|", 4);
            lineValues.computeIfAbsent(k[0] + "|" + k[2] + "|" + k[3], key -> new ArrayList<>()).add(e.getValue());
        }
        for (Map.Entry<String, List<BigDecimal>> e : lineValues.entrySet()) {
            String[] k = e.getKey().split("\\|", 3);
            rows.add(new CongestionRow(LINE, k[0], Integer.parseInt(k[1]), Integer.parseInt(k[2]), average(e.getValue()), SOURCE));
        }

        if (!unknownStations.isEmpty()) {
            warnings.add("역 ID 표에 없는 역번호 " + unknownStations.size() + "행 건너뜀 (지선·순환 분기용 가상 번호는 conf/crowd-station-aliases.csv 에 추가): "
                    + head(unknownStations));
        }
        if (!unknownDayOrDirection.isEmpty()) {
            warnings.add("모르는 구분/상하구분 " + unknownDayOrDirection.size() + "종 건너뜀 (원천 표기 변경 가능): "
                    + String.join(", ", unknownDayOrDirection));
        }
        return new Result(List.copyOf(rows),
                new Stats(sourceRows.size(), stations.size(), slots.size(), unknownStations.size(), over100));
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    /** "5시30분" → 11, "00시00분" → 0, "23시30분" → 47. 30분 슬롯이 아닌 열은 null. */
    static Integer slotOf(String column) {
        Matcher m = TIME_COLUMN.matcher(column == null ? "" : column.trim());
        if (!m.matches()) {
            return null;
        }
        int hour = Integer.parseInt(m.group(1));
        int minute = Integer.parseInt(m.group(2));
        if (hour > 23 || (minute != 0 && minute != 30)) {
            return null;
        }
        return hour * 2 + (minute == 30 ? 1 : 0);
    }

    /** 원천 값은 "8.8 " 처럼 공백이 붙어 있다. 빈 칸·숫자가 아닌 값은 null (그 슬롯은 행을 만들지 않는다). */
    private static BigDecimal levelOf(String raw) {
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return new BigDecimal(text).setScale(1, RoundingMode.HALF_UP);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static BigDecimal max(BigDecimal a, BigDecimal b) {
        return a.compareTo(b) >= 0 ? a : b;
    }

    private static BigDecimal average(List<BigDecimal> values) {
        BigDecimal sum = BigDecimal.ZERO;
        for (BigDecimal v : values) {
            sum = sum.add(v);
        }
        return sum.divide(BigDecimal.valueOf(values.size()), 1, RoundingMode.HALF_UP);
    }

    private static String head(List<String> items) {
        String joined = String.join(", ", items.subList(0, Math.min(EXAMPLE_LIMIT, items.size())));
        return items.size() > EXAMPLE_LIMIT ? joined + ", …" : joined;
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
