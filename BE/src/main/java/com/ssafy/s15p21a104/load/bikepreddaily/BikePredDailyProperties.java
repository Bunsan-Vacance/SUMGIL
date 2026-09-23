package com.ssafy.s15p21a104.load.bikepreddaily;

import java.nio.file.Path;

/**
 * 따릉이 날짜축 예측 원천 선택 (S15P21A104-309). 기본값은 application-load.yml 에 있고
 * 명령행 {@code --load.bikepreddaily.*} 로 덮어쓴다.
 *
 * @param source 원천 종류. 지금은 {@code csv} 뿐이다. 모르는 값은 조용히 넘기지 않고 멈춘다
 * @param path   {@code csv} 원천이 읽을 파일 또는 폴더. <b>avg 산출물 폴더와 달라야 한다</b> — 두 산출물의 파일명
 *               규칙이 같아서 한 폴더에 섞이면 avg 로더가 파일명 최신으로 lightgbm 파일을 집는다
 */
public record BikePredDailyProperties(String source, Path path) {

    public static final String CSV = "csv";
    /** 로컬에서 받아 두는 폴더. 로더는 {@code BE/} 에서 실행하므로 저장소 루트 기준 한 칸 위다. */
    public static final String DEFAULT_CSV_PATH = "../AI/data/BIKE/serving-daily";

    public BikePredDailyProperties {
        source = normalizeSource(source);
        if (path == null || path.toString().isBlank()) {
            path = Path.of(DEFAULT_CSV_PATH);
        }
    }

    public BikeStockPredDailySource toSource() {
        return new CsvBikeStockPredDailySource(path);
    }

    private static String normalizeSource(String raw) {
        if (raw == null || raw.isBlank()) {
            return CSV;
        }
        String value = raw.trim().toLowerCase();
        if (CSV.equals(value)) {
            return value;
        }
        throw new IllegalArgumentException("모르는 load.bikepreddaily.source '" + raw.trim() + "' — 가능: " + CSV);
    }
}
