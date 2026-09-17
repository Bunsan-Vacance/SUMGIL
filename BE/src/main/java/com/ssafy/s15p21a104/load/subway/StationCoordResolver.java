package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 좌표 원천 4종을 합쳐 적재용 좌표 목록을 만든다 — 규칙은 data/subway/README.md "좌표 결정 규칙" 과 같다.
 * <p>
 * 우선순위는 서울교통공사 역사 좌표 → 국가철도공단 노선별 역위치 → 전국도시철도역사정보표준데이터 → KTDB 노드이고,
 * 빌더가 목록 앞쪽 값을 먼저 쓰므로 이 순서대로 이어 붙인다. 앞 원천이 덮는 역의 뒤 원천 좌표는 쓰이지 않으므로
 * 검증 대상에서 빼고 목록 뒤에 남긴다 — 쓰이지 않는 값으로 경고를 내지 않기 위해서다.
 * <p>
 * 검증은 두 단계다. ① <b>세 원천 다수결</b>({@link StationCoordCrossCheck#majority}): 쓰일 좌표가 표준데이터와
 * 어긋나는데 표준데이터·KTDB 는 일치하면 그 원천의 오기로 보고 표준데이터 값으로 바꾼다. 서울교통공사 파일에도
 * 다른 역 좌표가 섞인 행이 있어(용답에 시청 좌표 6.4 km, S15P21A104-114) 1순위도 대상이다.
 * ② <b>교차검증</b>({@link StationCoordCrossCheck#resolve}): 표준데이터가 없어 다수결이 판정하지 못한 역 중
 * KTDB 와 5 km 넘게 어긋나는 값은 빼서 KTDB 가 채우게 하고, 500 m~5 km 는 유지하되 검토 목록으로 남긴다.
 * <p>
 * 값을 만들어 넣지 않는다 — 어느 원천에도 없으면 좌표 없이 남고, 원천 CSV 는 고치지 않는다.
 */
public final class StationCoordResolver {

    /**
     * @param coords             우선순위 순으로 이어 붙인 조회 목록 (빌더가 앞쪽 값을 쓴다)
     * @param sourcesInPriority  원본 4종 (대체 전 값). 적재 로그의 "역 좌표 출처" 집계가 값으로 출처를 되짚는 데 쓴다
     * @param seoulVote          서울교통공사 좌표의 다수결 결과
     * @param kricVote           국가철도공단 좌표(쓰이는 역만)의 다수결 결과
     * @param crossCheck         다수결을 통과한 좌표의 KTDB 교차검증 결과
     * @param stdUsed            앞 두 원천에 없어 실제로 쓰인 표준데이터 좌표 수
     */
    public record Result(List<StationCoord> coords, List<List<StationCoord>> sourcesInPriority,
                         StationCoordCrossCheck.Result seoulVote, StationCoordCrossCheck.Result kricVote,
                         StationCoordCrossCheck.Result crossCheck, int stdUsed) {
    }

    private StationCoordResolver() {
    }

    /**
     * @param warnMeters    이보다 어긋나면 경고하고, 다수결에서는 대체 판정의 기준이 된다
     * @param replaceMeters 교차검증에서 이보다 어긋나면 원천 결함으로 보고 빼낸다
     */
    public static Result resolve(List<StationCoord> seoulMetro, List<StationCoord> kric,
                                 List<StationCoord> std, List<StationCoord> ktdb,
                                 double warnMeters, double replaceMeters) {
        var seoulVote = StationCoordCrossCheck.majority(seoulMetro, std, ktdb, warnMeters);

        Set<String> seoulNames = names(seoulMetro);
        List<StationCoord> kricUsed = kric.stream().filter(c -> !seoulNames.contains(c.stationName())).toList();
        List<StationCoord> kricCovered = kric.stream().filter(c -> seoulNames.contains(c.stationName())).toList();
        var kricVote = StationCoordCrossCheck.majority(kricUsed, std, ktdb, warnMeters);

        Set<String> kricNames = names(kricUsed);
        List<StationCoord> stdUsed = std.stream()
                .filter(c -> !seoulNames.contains(c.stationName()) && !kricNames.contains(c.stationName())).toList();

        List<StationCoord> official = new ArrayList<>(kricVote.kept());
        official.addAll(stdUsed);
        var crossCheck = StationCoordCrossCheck.resolve(official, ktdb, warnMeters, replaceMeters);

        List<StationCoord> coords = new ArrayList<>(seoulVote.kept());
        coords.addAll(kricCovered);
        coords.addAll(crossCheck.kept());
        coords.addAll(ktdb);
        return new Result(List.copyOf(coords), List.of(seoulMetro, kric, std, ktdb),
                seoulVote, kricVote, crossCheck, stdUsed.size());
    }

    private static Set<String> names(List<StationCoord> coords) {
        return coords.stream().map(StationCoord::stationName).collect(Collectors.toSet());
    }
}
