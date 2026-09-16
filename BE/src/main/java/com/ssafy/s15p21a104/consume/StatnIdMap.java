package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import org.springframework.core.io.ClassPathResource;

/**
 * 실시간 도착 API(OA-15799)의 {@code statnId} → 우리 {@code station.station_id} 대응표 (S15P21A104-171).
 *
 * <p>두 체계가 다르다 — 서울역이 API 에서는 {@code 1001000133}, 우리 표에서는 {@code 150} 이다. 산술로 맞출 수 없어
 * (노선, 역명) 으로 붙인 표를 만들어 두고 읽는다. 표는 {@code BE/scripts/data/statn-id-map-build.mjs} 가
 * prod Kafka 덤프로 만들고(외부 API 호출 0회), 커밋되면 정본이다 — 생성 규칙은 그 스크립트와 lib 테스트에 있다.
 *
 * <p>표에 없는 역은 {@link Optional#empty()} 다. 조용히 아무 역에나 쓰지 않는다 — 안 붙는 역은 반영기가 세어서
 * 로그에 남긴다. 2026-09-16 표 기준으로 안 붙는 것은 GTX-A(노선 1032) 9역과 1호선 지제뿐이고,
 * 셋 다 우리 정적 표에 노선·구간이 아직 없는 역이다.
 */
public final class StatnIdMap {

    static final String RESOURCE_PATH = "data/subway/conf/statn-id-map.csv";

    /**
     * @param stationId 우리 역번호
     * @param name      정본 역명. API 표기(부역명 괄호 등)가 아니라 표에 있는 이름이다
     */
    public record Mapped(String stationId, String name) {
    }

    private final Map<String, Mapped> byStatnId;

    StatnIdMap(Map<String, Mapped> byStatnId) {
        this.byStatnId = Map.copyOf(byStatnId);
    }

    public static StatnIdMap fromClasspath() {
        try {
            return parse(new ClassPathResource(RESOURCE_PATH).getContentAsString(StandardCharsets.UTF_8));
        } catch (java.io.IOException e) {
            throw new java.io.UncheckedIOException("statnId 대응표를 못 읽었다: " + RESOURCE_PATH, e);
        }
    }

    public static StatnIdMap parse(String csv) {
        Map<String, Mapped> map = new LinkedHashMap<>();
        for (Map<String, String> row : CsvTable.parse(csv).rows()) {
            String statnId = row.get("statn_id");
            String stationId = row.get("station_id");
            if (statnId != null && !statnId.isBlank() && stationId != null && !stationId.isBlank()) {
                String name = row.get("name");
                map.put(statnId.trim(), new Mapped(stationId.trim(), name == null ? null : name.trim()));
            }
        }
        return new StatnIdMap(map);
    }

    /** @return 우리 역번호와 정본 역명. 표에 없으면 비어 있다 */
    public Optional<Mapped> find(String statnId) {
        return statnId == null || statnId.isBlank() ? Optional.empty() : Optional.ofNullable(byStatnId.get(statnId));
    }

    /** @return 우리 station_id. 표에 없으면 비어 있다 */
    public Optional<String> stationId(String statnId) {
        return find(statnId).map(Mapped::stationId);
    }

    public int size() {
        return byStatnId.size();
    }
}
