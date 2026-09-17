package com.ssafy.s15p21a104.load.bikepred;

import java.nio.file.Path;

/**
 * 재고 예측 원천 선택. 티켓의 "원천 전환이 설정값 하나로 된다" 는 {@code load.bikepred.source} 를 뜻한다.
 * 기본값은 application-load.yml 에 있고 명령행 {@code --load.bikepred.*} 로 덮어쓴다.
 *
 * @param source 원천 종류. 지금은 {@code csv} 뿐이다 — AI 서빙 API 는 적재 원천이 아니라 <b>같은 산출물의 조회 창구</b>이기
 *               때문이다({@link BikeStockPredSource} javadoc). 모르는 값은 조용히 넘기지 않고 멈춘다
 * @param path   {@code csv} 원천이 읽을 파일 또는 폴더. <b>폴더면 그 안의 최신 산출물</b>을 고르므로
 *               배치가 매일 새 파일을 만들어도 적재 명령이 그대로다. yml 의 문자열은 스프링이 Path 로 바꿔 준다
 */
public record BikePredProperties(String source, Path path) {

    public static final String CSV = "csv";
    /**
     * AI 배치 산출물을 받아 두는 폴더. {@code BE/scripts/data/bikepred-fetch.mjs} 가 여기로 내려받는다.
     * 로더는 {@code BE/} 에서 실행하므로 저장소 루트 기준으로 한 칸 위다.
     */
    public static final String DEFAULT_CSV_PATH = "../AI/data/BIKE/serving";

    public BikePredProperties {
        source = normalizeSource(source);
        if (path == null || path.toString().isBlank()) {
            path = Path.of(DEFAULT_CSV_PATH);
        }
    }

    public BikeStockPredSource toSource() {
        return new CsvBikeStockPredSource(path);
    }

    private static String normalizeSource(String raw) {
        if (raw == null || raw.isBlank()) {
            return CSV;
        }
        String value = raw.trim().toLowerCase();
        if (CSV.equals(value)) {
            return value;
        }
        if ("api".equals(value)) {
            throw new IllegalArgumentException(
                    "load.bikepred.source=api 는 적재 원천이 아닙니다 — AI 서빙 API 는 대여소 하나씩 응답하는 조회 창구이고,"
                            + " 그 뒤에서 읽는 파일이 csv 원천이 읽는 것과 같은 배치 산출물입니다."
                            + " 표 전체를 주는 엔드포인트가 생기면 그때 구현을 추가합니다. 가능: " + CSV);
        }
        throw new IllegalArgumentException("모르는 load.bikepred.source '" + raw.trim() + "' — 가능: " + CSV);
    }
}
