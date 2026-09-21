package com.ssafy.s15p21a104.load.crowdpred;

import com.ssafy.s15p21a104.load.crowd.CrowdStationCodes;
import java.nio.file.Path;

/**
 * 혼잡도 예측 원천 선택 (S15P21A104-305). 기본값은 application-load.yml 에 있고
 * 명령행 {@code --load.crowdpred.*} 로 덮어쓴다.
 *
 * @param source 원천 종류. 지금은 {@code csv} 뿐이다 — AI 는 PG 에 직접 쓰지 않고 BE load job 이
 *               넣기로 했고(회신 04 L-2), CROWD 서빙 API 는 역·구간 단위 조회 창구라 하루치 2만 행을
 *               옮기는 경로가 아니다. 모르는 값은 조용히 넘기지 않고 멈춘다
 * @param path   {@code csv} 원천이 읽을 파일 또는 폴더. <b>폴더면 그 안의 최신 산출물</b>을 고르므로
 *               배치가 매일 새 파일을 만들어도 적재 명령이 그대로다
 */
public record CrowdPredProperties(String source, Path path) {

    public static final String CSV = "csv";
    /**
     * AI 배치 산출물을 받아 두는 폴더. {@code BE/scripts/data/crowdpred-fetch.mjs} 가 여기로 내려받는다.
     * 로더는 {@code BE/} 에서 실행하므로 저장소 루트 기준으로 한 칸 위다.
     */
    public static final String DEFAULT_CSV_PATH = "../AI/data/CROWD/serving";

    public CrowdPredProperties {
        source = normalizeSource(source);
        if (path == null || path.toString().isBlank()) {
            path = Path.of(DEFAULT_CSV_PATH);
        }
    }

    public CongestionPredSource toSource(CrowdStationCodes codes) {
        return new CsvCongestionPredSource(path, codes);
    }

    private static String normalizeSource(String raw) {
        if (raw == null || raw.isBlank()) {
            return CSV;
        }
        String value = raw.trim().toLowerCase();
        if (CSV.equals(value)) {
            return value;
        }
        throw new IllegalArgumentException("모르는 load.crowdpred.source '" + raw.trim() + "' — 가능: " + CSV);
    }
}
