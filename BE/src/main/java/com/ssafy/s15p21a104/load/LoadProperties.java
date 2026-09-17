package com.ssafy.s15p21a104.load;

import com.ssafy.s15p21a104.load.bikepred.BikePredProperties;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 로더 실행 옵션. 기본값은 application-load.yml 에 있고 명령행 --load.* 로 덮어쓴다.
 *
 * @param sources     적재할 원천 묶음. subway · bus · bike · railgeometry · congestion 중 골라 쓴다 (application-load.yml 기본값은 전부, 코드 기본값은 subway).
 *                    congestion 은 적재된 station·line 을 대상 검증에 쓰므로 subway 보다 뒤에 와야 한다
 * @param dryRun      true 면 파싱·검증·건수 출력까지만 하고 DB 에 쓰지 않는다 (prune 도 세기만 한다)
 * @param writeMode   edge_time 쓰기 방식. ROW 는 성능 비교용 baseline
 * @param region      포함할 line_id 목록. 비어 있으면 전부 (서비스 권역 확정 전 기본값). 지하철에만 적용된다
 * @param avgSpeedMps 소요시간이 없는 구간의 추정에 쓰는 기본 표정속도 (m/s). 노선별 값은 conf/line-speeds.csv 가 우선하고, 표에 없는 노선에만 이 값을 쓴다
 * @param prune       지하철 적재 뒤 시각표가 덮는 노선에서 이번 실행에 없는 edge_time 행과 고아 역을 지운다 (기본 true)
 * @param bikepred    재고 예측 적재의 원천 선택. bikepred 소스를 쓸 때만 본다
 */
@ConfigurationProperties("load")
public record LoadProperties(List<String> sources, boolean dryRun, UpsertWriter.WriteMode writeMode,
                             List<String> region, double avgSpeedMps, Boolean prune,
                             BikePredProperties bikepred) {

    public LoadProperties {
        if (sources == null || sources.isEmpty()) {
            sources = List.of("subway");
        }
        if (bikepred == null) {
            bikepred = new BikePredProperties(null, null);
        }
        if (writeMode == null) {
            writeMode = UpsertWriter.WriteMode.BATCH;
        }
        if (region == null) {
            region = List.of();
        }
        if (avgSpeedMps <= 0) {
            avgSpeedMps = 9.2;
        }
        if (prune == null) {
            prune = true;
        }
    }
}
