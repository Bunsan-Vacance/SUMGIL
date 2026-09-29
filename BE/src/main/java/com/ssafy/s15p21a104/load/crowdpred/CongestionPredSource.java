package com.ssafy.s15p21a104.load.crowdpred;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;

/**
 * 혼잡도 예측 표의 원천. 구현을 바꿔 원천을 교체한다 ({@code load.crowdpred.source}).
 *
 * <p><b>지금 구현은 파일 하나뿐이다.</b> AI 는 PG 에 직접 쓰지 않고 BE load job 이 넣는다(회신 04 L-2).
 * AI CROWD 서빙 API 는 역·구간 단위 조회 창구라 하루치 2만 행을 옮기는 경로가 아니다 —
 * 재고 예측({@code load.bikepred})에서 내린 것과 같은 판단이다.
 */
public interface CongestionPredSource {

    /**
     * 읽은 결과.
     *
     * @param rows     적재 후보 행
     * @param stats    파싱 통계
     * @param origin   실제로 읽은 파일. 폴더를 줬을 때 어느 것이 뽑혔는지 로그·문서에 남긴다
     * @param meta     사이드카 meta. {@code generated_at} 이 적재 열로 들어가므로 <b>필수</b>다
     * @param warnings 원천 단계 경고(파싱 경고)
     */
    record Loaded(List<CongestionPredRow> rows, CongestionPredParser.Stats stats, Path origin,
                  CongestionPredMeta meta, List<String> warnings) {
    }

    Loaded read() throws IOException;
}
