package com.ssafy.s15p21a104.domain.congestion.scoring;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 링크(구간)의 진행 방향을 판정한다(S15P21A104-158, 통지 05 S-1).
 *
 * <p>기본 규칙은 역번호 오름차순이 한쪽 방향이라는 것이다. 어느 쪽인지는 노선마다 다르고,
 * 실측 혼잡도 CSV(`seoulmetro-congestion_20260630.csv`, 평일 08:00)로 확인됐다
 * (이원빈 회신 `TO_ROUTE-subway-direction-01.md`, 2026-09-21):
 *
 * <ul>
 *   <li>1호선: 오름차순 = 상선</li>
 *   <li>2호선: 오름차순 = 내선</li>
 *   <li>3~8호선: 오름차순 = <b>하선</b>(1호선과 반대) — 5·6·7호선은 최소 번호 종점의 상선값이
 *       정확히 0이라 반박 여지가 없다</li>
 * </ul>
 *
 * <p>station_id는 "물리 역의 노선별 역사코드 중 최솟값"(S15P21A104-103)이라, 환승역은 다른 노선
 * 번호를 달고 있어 오름차순이 뒤집힌다(예: 3호선 고속터미널 329 ↔ 교대 223 — 교대 3호선 번호는
 * 0330). 그래서 {@code station-ids.csv}의 <b>노선별 역번호</b>로 비교하고, 그 노선 번호가 없는
 * 역만 station_id로 비교한다. 노선 번호로도 순서가 안 맞는 링크는 역 집합을 통째로 거르지 않고
 * 화이트리스트로 판정을 보류한다 — 안 그러면 같은 역번호를 공유하는 다른 노선 구간까지 결측으로
 * 같이 날아간다(이전 버전의 버그, 신정 5호선·신설동 1호선·문래 2호선 본선 구간을 억울하게 잃었다).
 *
 * <p>보류하는 링크(둘 다 방향으로 등록):
 * <ul>
 *   <li>2호선 성수지선: 용두(250) ↔ 신설동(156) — 신설동 station_id가 1호선 코드</li>
 *   <li>2호선 신정지선: 신정네거리(249) ↔ 까치산(200) — 까치산 station_id가 2호선 본선 코드</li>
 *   <li>1호선: 동묘앞(159) ↔ 신설동(156) — 동묘앞이 나중에 개통해 번호만 뒤에 붙음</li>
 * </ul>
 *
 * <p>8호선 남위례(2828) ↔ 산성(2822)도 나중 개통으로 번호가 뒤에 붙었지만, 보류하면 RAPTOR
 * 노선 조립에서 체인 중간이 끊기므로 판정을 뒤집는다({@code FLIPPED_LINKS}).
 *
 * <p>9호선 이상은 아직 실측 확인이 안 됐다 — 3~8호선과 같은 패턴(오름차순=하선)으로 잠정
 * 적용한다. 틀렸더라도 {@code congestion_pred} 조회가 그 문자열로 못 찾을 뿐이라 결측과
 * 똑같이 스킵되지, 잘못된 값이 나오지는 않는다.
 */
public final class SubwayDirectionResolver {

    private static final String LINE1_ID = "1001";
    private static final String LINE2_ID = "1002";

    /** 역번호 오름차순이 실제 방향과 안 맞아 판정을 보류하는 링크 3개(양방향 다 등록). */
    private static final Set<String> REVERSED_LINKS = Set.of(
            linkKey("250", "156"), linkKey("156", "250"), // 2호선 성수지선: 용두 ↔ 신설동
            linkKey("249", "200"), linkKey("200", "249"), // 2호선 신정지선: 신정네거리 ↔ 까치산
            linkKey("159", "156"), linkKey("156", "159")  // 1호선: 동묘앞 ↔ 신설동
    );

    /**
     * 노선 번호가 순서를 어기지만 방향은 분명해 뒤집어 판정하는 링크(양방향 다 등록).
     * 보류하면 RAPTOR 노선 조립에서 체인 중간이 끊긴다.
     */
    private static final Set<String> FLIPPED_LINKS = Set.of(
            linkKey("2828", "2822"), linkKey("2822", "2828") // 8호선: 남위례(복정 2821 · 산성 2822 사이, 나중 개통) ↔ 산성
    );

    private static final String STATION_IDS_CSV = "data/subway/conf/station-ids.csv";

    private SubwayDirectionResolver() {
    }

    /**
     * @param fromStationId 링크 시작 역
     * @param toStationId 링크 끝 역
     * @param lineId 링크가 속한 노선(예: 2호선은 "1002")
     * @return 방향 문자열(상선/하선/내선/외선). 역번호가 숫자가 아니거나 보류 링크 중
     *         하나면 빈 값
     */
    public static Optional<String> resolve(String fromStationId, String toStationId, String lineId) {
        if (REVERSED_LINKS.contains(linkKey(fromStationId, toStationId))) {
            return Optional.empty();
        }
        Integer from = lineCode(fromStationId, lineId);
        Integer to = lineCode(toStationId, lineId);
        if (from == null || to == null) {
            from = parseNumeric(fromStationId);
            to = parseNumeric(toStationId);
        }
        if (from == null || to == null) {
            return Optional.empty();
        }
        boolean ascending = from < to != FLIPPED_LINKS.contains(linkKey(fromStationId, toStationId));
        if (LINE1_ID.equals(lineId)) {
            return Optional.of(ascending ? "상선" : "하선");
        }
        if (LINE2_ID.equals(lineId)) {
            return Optional.of(ascending ? "내선" : "외선");
        }
        return Optional.of(ascending ? "하선" : "상선");
    }

    /** 그 노선의 역번호(숫자). 없거나 숫자가 아니면 null. */
    private static Integer lineCode(String stationId, String lineId) {
        Map<String, Integer> codes = LineCodes.BY_STATION.get(stationId);
        return codes == null ? null : codes.get(lineId);
    }

    /** station-ids.csv 지연 로드: station_id → (노선 → 역번호). */
    private static final class LineCodes {
        private static final Map<String, Map<String, Integer>> BY_STATION = load();

        private static Map<String, Map<String, Integer>> load() {
            InputStream in = SubwayDirectionResolver.class.getClassLoader().getResourceAsStream(STATION_IDS_CSV);
            if (in == null) {
                return Map.of();
            }
            Map<String, Map<String, Integer>> byStation = new HashMap<>();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
                reader.readLine(); // station_id,name,codes,source
                for (String line; (line = reader.readLine()) != null; ) {
                    String[] cells = line.split(",", -1);
                    if (cells.length < 3) {
                        continue;
                    }
                    for (String code : cells[2].split(";")) {
                        String[] lineAndCode = code.split(":");
                        Integer numeric = lineAndCode.length == 2 ? parseNumeric(lineAndCode[1]) : null;
                        if (numeric != null) {
                            byStation.computeIfAbsent(cells[0], key -> new HashMap<>()).put(lineAndCode[0], numeric);
                        }
                    }
                }
            } catch (IOException e) {
                throw new UncheckedIOException(e);
            }
            return byStation;
        }
    }

    private static String linkKey(String fromStationId, String toStationId) {
        return fromStationId + ":" + toStationId;
    }

    private static Integer parseNumeric(String stationId) {
        try {
            return Integer.valueOf(stationId);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
