package com.ssafy.s15p21a104.domain.congestion.scoring;

import java.util.Optional;
import java.util.Set;

/**
 * 링크(구간)의 진행 방향을 판정한다(S15P21A104-158, 통지 05 S-1).
 *
 * <p>기본 규칙은 역번호 오름차순이 한쪽 방향(상선/내선)이라는 것이다. 2호선 지선
 * (성수지선: 성수·용답·신답·용두·신설동 / 신정지선: 까치산·신정네거리·양천구청·신정·
 * 문래·신도림)은 이 규칙이 깨진다고 통지 05에서 확인됐고, 정확한 예외 규칙은 아직
 * 미수신(`TO_BE-crowd-contract-answers.md` 1.4절, 블로커)이다 — 그래서 지선 구간은
 * 값을 지어내지 않고 판정 자체를 보류한다(빈 값 → 결측과 동일하게 스킵).
 *
 * <p><b>2호선 지선이 아닌 구간의 방향 라벨(상선/하선/내선/외선)은 예외표 수신 전까지의
 * 잠정값이다.</b> 틀렸더라도 {@code congestion_pred} 조회가 그 문자열로 못 찾을 뿐이라
 * 결측과 똑같이 스킵되지, 잘못된 값이 나오지는 않는다(테이블 조회 실패 = Optional.empty).
 */
public final class SubwayDirectionResolver {

    private static final String LINE2_ID = "1002";

    /** 2호선 지선 역 — 역번호 오름차순 규칙이 깨지는 구간(성수지선·신정지선). */
    private static final Set<String> LINE2_BRANCH_STATION_IDS = Set.of(
            "211", "244", "245", "250", "156", // 성수지선: 성수·용답·신답·용두·신설동
            "200", "249", "248", "2520", "235", "234"); // 신정지선: 까치산·신정네거리·양천구청·신정·문래·신도림

    private SubwayDirectionResolver() {
    }

    /**
     * @param fromStationId 링크 시작 역
     * @param toStationId 링크 끝 역
     * @param lineId 링크가 속한 노선(예: 2호선은 "1002")
     * @return 방향 문자열(상선/하선/내선/외선). 지선 구간이거나 역번호가 숫자가 아니면 빈 값
     */
    public static Optional<String> resolve(String fromStationId, String toStationId, String lineId) {
        if (LINE2_BRANCH_STATION_IDS.contains(fromStationId) || LINE2_BRANCH_STATION_IDS.contains(toStationId)) {
            return Optional.empty();
        }
        Integer from = parseNumeric(fromStationId);
        Integer to = parseNumeric(toStationId);
        if (from == null || to == null) {
            return Optional.empty();
        }
        boolean ascending = from < to;
        if (LINE2_ID.equals(lineId)) {
            return Optional.of(ascending ? "내선" : "외선");
        }
        return Optional.of(ascending ? "상선" : "하선");
    }

    private static Integer parseNumeric(String stationId) {
        try {
            return Integer.valueOf(stationId);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
