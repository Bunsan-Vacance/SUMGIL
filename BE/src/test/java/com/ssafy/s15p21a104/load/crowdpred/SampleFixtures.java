package com.ssafy.s15p21a104.load.crowdpred;

import com.ssafy.s15p21a104.load.crowd.CrowdStationCodes;
import com.ssafy.s15p21a104.load.csv.CsvTable;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 테스트 입력. 실제 conf 파일과 AI 에게 받은 실물 샘플을 쓴다 — 역번호 체계나 열 구성이 바뀌면
 * 인라인 픽스처가 아니라 여기서 먼저 깨지는 것이 목적이다.
 *
 * <p>Gradle 테스트의 작업 디렉터리는 {@code BE/} 다.
 */
final class SampleFixtures {

    /** AI 가 2026-09-21 에 준 하루치 중 모든 분기를 담은 278행. 전체(21,684행)는 커밋하지 않는다. */
    static final String SAMPLE_CSV = "docs/external/samples/predictions_2026-09-20_278rows.csv";

    private SampleFixtures() {
    }

    static List<Map<String, String>> rows(String path) {
        try {
            return CsvTable.parse(Files.readString(Path.of(path), StandardCharsets.UTF_8)).rows();
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    static List<Map<String, String>> sampleRows() {
        return rows(SAMPLE_CSV);
    }

    /** 혼잡도 통계 적재와 같은 표. 원천이 같은 서울교통공사 외부역코드 체계다. */
    static CrowdStationCodes codes() {
        return CrowdStationCodes.from(
                rows("src/main/resources/data/subway/conf/station-ids.csv"),
                rows("src/main/resources/data/crowd/conf/crowd-station-aliases.csv"));
    }

    /** 역 마스터 대신 쓰는 station_id 집합 — conf 표의 station_id 열 그대로다. */
    static Set<String> stationIds() {
        Set<String> ids = new LinkedHashSet<>();
        for (Map<String, String> row : rows("src/main/resources/data/subway/conf/station-ids.csv")) {
            String id = row.get("station_id");
            if (id != null && !id.isBlank()) {
                ids.add(id.trim());
            }
        }
        return ids;
    }

    /** 1~9호선. 샘플이 이 범위만 담는다. */
    static Set<String> lineIds() {
        Set<String> ids = new LinkedHashSet<>();
        for (int i = 1; i <= 9; i++) {
            ids.add("100" + i);
        }
        return ids;
    }
}
