package com.ssafy.s15p21a104.load.bike;

import com.ssafy.s15p21a104.load.Coords;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * bikeList 스냅샷(BE/scripts/data/bike-snapshot.mjs 산출 CSV) → bike_station 행.
 * <p>
 * rental_id 는 API 의 stationId(ST-xxx) 다. 파일형 "따릉이 대여소 정보"(OA-13252)에는 이 ID 가 없어 스냅샷이 주 원천이고,
 * 파일은 대여소번호(스냅샷 이름의 접두어 "102. " = 파일의 대여소번호 102)로 대조해 누락·거치대수 차이를 경고로만 남긴다.
 * 값은 스냅샷 것을 쓴다 — 실시간 재고(Redis bike:stock:{rentalId})와 같은 체계여야 하기 때문이다.
 */
public final class BikeStationParser {

    /** "102. 망원역 1번출구 앞" → 번호 102, 이름 "망원역 1번출구 앞". */
    static final Pattern NUMBER_PREFIX = Pattern.compile("^\\s*(\\d+)\\.\\s*(.*)$");
    private static final int LIST_LIMIT = 20;

    /**
     * 파일 대조 결과.
     *
     * @param matched        번호가 양쪽에 있는 대여소 수
     * @param onlyInSnapshot 스냅샷에만 있는 대여소번호 (파일 배포 뒤 신설 가능)
     * @param onlyInFile     파일에만 있는 대여소번호 (폐쇄·휴점 가능)
     * @param dockMismatch   스냅샷 rackTotCnt 와 파일 LCD+QR 거치대수가 다른 수
     */
    public record CrossCheck(int matched, List<String> onlyInSnapshot, List<String> onlyInFile, int dockMismatch) {
        static final CrossCheck NONE = new CrossCheck(0, List.of(), List.of(), 0);
    }

    private final List<String> warnings = new ArrayList<>();
    private CrossCheck crossCheck = CrossCheck.NONE;

    /**
     * @param snapshotRows bikeList 스냅샷 행 (stationId · stationName · stationLatitude · stationLongitude · rackTotCnt · …)
     * @param fileRows     대여소 정보 파일 행 (대여소번호 · 보관소명 · … · LCD거치대수 · QR거치대수). 비어 있으면 대조하지 않는다
     */
    public List<BikeStationRow> parse(List<Map<String, String>> snapshotRows, List<Map<String, String>> fileRows) {
        Map<String, BikeStationRow> out = new LinkedHashMap<>();
        Map<String, String> numberById = new LinkedHashMap<>();
        for (Map<String, String> row : snapshotRows) {
            String id = value(row, "stationId");
            String rawName = value(row, "stationName");
            if (id.isEmpty()) {
                warnings.add("stationId 없는 행: '" + rawName + "'");
                continue;
            }
            if (out.containsKey(id)) {
                warnings.add("stationId 중복: " + id + " — 두 번째 행을 건너뜀");
                continue;
            }
            String name = rawName;
            String number = null;
            Matcher m = NUMBER_PREFIX.matcher(rawName);
            if (m.matches()) {
                number = stripLeadingZeros(m.group(1));
                name = m.group(2).trim();
            } else {
                warnings.add("대여소번호 접두어 없는 이름: " + id + " '" + rawName + "' — 파일 대조 불가");
            }
            if (name.isEmpty()) {
                warnings.add("이름 없는 대여소: " + id);
                continue;
            }
            Double lat = Coords.parseOrNull(row.get("stationLatitude"));
            Double lng = Coords.parseOrNull(row.get("stationLongitude"));
            if (lat == null || lng == null) {
                warnings.add("좌표 없음: " + id + " " + name);
            }
            out.put(id, new BikeStationRow(id, name, lat, lng, Coords.parseIntOrNull(row.get("rackTotCnt"))));
            if (number != null) {
                numberById.put(id, number);
            }
        }
        crossCheck = crossCheck(out, numberById, fileRows);
        return List.copyOf(out.values());
    }

    private CrossCheck crossCheck(Map<String, BikeStationRow> stations, Map<String, String> numberById,
                                  List<Map<String, String>> fileRows) {
        if (fileRows.isEmpty()) {
            return CrossCheck.NONE;
        }
        Map<String, Map<String, String>> fileByNumber = new LinkedHashMap<>();
        for (Map<String, String> row : fileRows) {
            String number = stripLeadingZeros(value(row, "대여소번호"));
            if (!number.isEmpty()) {
                fileByNumber.putIfAbsent(number, row);
            }
        }
        int matched = 0;
        List<String> mismatches = new ArrayList<>();
        List<String> onlyInSnapshot = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Map.Entry<String, String> e : numberById.entrySet()) {
            String id = e.getKey();
            String number = e.getValue();
            seen.add(number);
            Map<String, String> file = fileByNumber.get(number);
            if (file == null) {
                onlyInSnapshot.add(number);
                continue;
            }
            matched++;
            Integer fileDock = lcdPlusQr(file);
            Integer dock = stations.get(id).dockCount();
            if (fileDock != null && dock != null && !fileDock.equals(dock)) {
                mismatches.add(number + " " + stations.get(id).name() + " " + dock + "≠" + fileDock);
            }
        }
        List<String> onlyInFile = fileByNumber.keySet().stream().filter(n -> !seen.contains(n)).toList();
        int mismatch = mismatches.size();
        // 파일은 반기 갱신이라 스냅샷과 수백 건이 어긋난다. 건마다 찍으면 다른 경고가 묻히므로 한 줄로 묶는다.
        if (mismatch > 0) {
            warnings.add("거치대수 불일치 " + mismatch + "건 (스냅샷 rackTotCnt ≠ 파일 LCD+QR, 스냅샷 값을 쓴다): " + head(mismatches));
        }
        if (!onlyInSnapshot.isEmpty()) {
            warnings.add("파일에 없는 대여소 " + onlyInSnapshot.size() + "개 (스냅샷에만 있음, 신설 가능): " + head(onlyInSnapshot));
        }
        if (!onlyInFile.isEmpty()) {
            warnings.add("스냅샷에 없는 대여소 " + onlyInFile.size() + "개 (파일에만 있음, 폐쇄·휴점 가능): " + head(onlyInFile));
        }
        return new CrossCheck(matched, List.copyOf(onlyInSnapshot), onlyInFile, mismatch);
    }

    /** 파일의 거치대수 = LCD + QR. 둘 다 비어 있으면 null (대조하지 않는다). */
    private static Integer lcdPlusQr(Map<String, String> file) {
        Integer lcd = Coords.parseIntOrNull(file.get("LCD거치대수"));
        Integer qr = Coords.parseIntOrNull(file.get("QR거치대수"));
        if (lcd == null && qr == null) {
            return null;
        }
        return (lcd == null ? 0 : lcd) + (qr == null ? 0 : qr);
    }

    private static String stripLeadingZeros(String digits) {
        return digits.replaceFirst("^0+(?=\\d)", "");
    }

    private static String head(List<String> items) {
        String joined = String.join(", ", items.subList(0, Math.min(LIST_LIMIT, items.size())));
        return items.size() > LIST_LIMIT ? joined + ", …" : joined;
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    public CrossCheck crossCheck() {
        return crossCheck;
    }
}
