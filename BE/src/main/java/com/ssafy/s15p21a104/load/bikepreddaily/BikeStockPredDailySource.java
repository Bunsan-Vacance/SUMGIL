package com.ssafy.s15p21a104.load.bikepreddaily;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;

/**
 * 따릉이 날짜축 예측 표의 원천 (S15P21A104-309). 구현을 바꿔 원천을 교체한다 ({@code load.bikepreddaily.source}).
 * 지금 구현은 AI 배치 산출물 파일뿐이다 — 요일축 원천({@code BikeStockPredSource})과 같은 판단이다.
 */
public interface BikeStockPredDailySource {

    /**
     * @param rows     적재 후보 행. 행마다 자기 산출물의 {@code generated_at} 을 갖는다
     * @param stats    파싱 통계 (모든 파일 합)
     * @param origins  실제로 읽은 파일들. 대상 날짜 순이고 날짜마다 하나다
     * @param warnings 원천 단계 경고
     */
    record Loaded(List<BikeStockPredDailyRow> rows, BikeStockPredDailyParser.Stats stats, List<Path> origins,
                  List<String> warnings) {
    }

    Loaded read() throws IOException;
}
