package com.ssafy.s15p21a104.load.subway;

import com.ssafy.s15p21a104.load.Coords;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 두 좌표 원천이 같은 역에서 어긋나는 정도로 원천 결함을 잡는다.
 * <p>
 * 2026-09-09 실측(국가철도공단 역위치 ↔ KTDB 노드): 대부분 중앙값 33 m 로 일치하지만 청산 28.6 km · 별내별가람 7.8 km 처럼
 * 같은 역의 "다른 기준점"으로는 설명이 안 되는 차이가 있다(국가철도공단 파일의 좌표 오기). 그런 값은 버리고 참조 원천이 채우게 한다.
 * 500 m~5 km 사이(산본 1.1 km)는 어느 쪽이 맞는지 원천이 말해 주지 않으므로 값을 유지하고 경고만 남긴다 — 사람이 검토할 목록이다.
 */
public final class StationCoordCrossCheck {

    /**
     * @param kept     유지한 좌표 (대체 임계값을 넘은 역은 빠져 있다)
     * @param replaced 대체 임계값을 넘어 뺀 역 이름 — 이름이 같은 참조 원천 좌표가 대신 쓰인다
     * @param warnings 경고 임계값을 넘은 역마다 한 줄 (대체된 역 포함)
     */
    public record Result(List<StationCoord> kept, List<String> replaced, List<String> warnings) {
    }

    private StationCoordCrossCheck() {
    }

    /** 경고만 필요할 때. {@link #resolve} 의 warnMeters 만 적용한 것과 같다. */
    public static List<String> warnings(List<StationCoord> primary, List<StationCoord> reference, double thresholdMeters) {
        return resolve(primary, reference, thresholdMeters, Double.POSITIVE_INFINITY).warnings();
    }

    /**
     * @param primary       비교 대상 좌표 (국가철도공단 역위치)
     * @param reference     참조 좌표 (KTDB 노드, 이름별 첫 값). 없는 역은 비교하지 않는다
     * @param warnMeters    이보다 어긋나면 경고
     * @param replaceMeters 이보다 어긋나면 원천 결함으로 보고 primary 에서 뺀다 (경고도 남긴다)
     */
    public static Result resolve(List<StationCoord> primary, List<StationCoord> reference, double warnMeters, double replaceMeters) {
        Map<String, StationCoord> ref = new LinkedHashMap<>();
        for (StationCoord c : reference) {
            ref.putIfAbsent(c.stationName(), c);
        }
        List<StationCoord> kept = new ArrayList<>(primary.size());
        List<String> replaced = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        for (StationCoord p : primary) {
            StationCoord r = ref.get(p.stationName());
            if (r == null) {
                kept.add(p);
                continue;
            }
            double d = Coords.distanceMeters(p.lat(), p.lng(), r.lat(), r.lng());
            if (d > replaceMeters) {
                replaced.add(p.stationName());
                warnings.add(String.format("%s: 원천 간 좌표 차이 %,.0f m — 원천 결함으로 보고 참조 좌표로 대체 (%.5f,%.5f → %.5f,%.5f)",
                        p.stationName(), d, p.lat(), p.lng(), r.lat(), r.lng()));
                continue;
            }
            if (d > warnMeters) {
                warnings.add(String.format("%s: 원천 간 좌표 차이 %,.0f m (%.5f,%.5f vs %.5f,%.5f) — 유지, 검토 필요",
                        p.stationName(), d, p.lat(), p.lng(), r.lat(), r.lng()));
            }
            kept.add(p);
        }
        return new Result(List.copyOf(kept), List.copyOf(replaced), List.copyOf(warnings));
    }
}
