package com.ssafy.s15p21a104.controller;

import com.ssafy.s15p21a104.dto.RouteSearchResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * TODO: 지금은 mock 데이터를 내려준다.
 * 알고리즘 파트의 판정 로직이 준비되면 이 컨트롤러가 그 로직(또는 그 로직을 감싼 서비스)을
 * 호출해서 실제 결과를 채우도록 교체할 것.
 */
@RestController
public class RouteController {

    @GetMapping("/api/routes/search")
    public RouteSearchResponse search(
            @RequestParam String origin,
            @RequestParam String destination
    ) {
        return RouteSearchResponse.builder()
                .origin(origin)
                .destination(destination)
                .baselineTotalMin(13.6)
                .modeSummary(List.of(
                        RouteSearchResponse.ModeSummaryItem.builder()
                                .emoji("🚇").label("지하철").min(3.6).build(),
                        RouteSearchResponse.ModeSummaryItem.builder()
                                .emoji("🚶").label("도보").min(2.0).build(),
                        RouteSearchResponse.ModeSummaryItem.builder()
                                .emoji("🔄").label("환승대기 등(카카오 포함)").min(4.0).build()
                ))
                .adjustments(List.of(
                        RouteSearchResponse.AdjustmentItem.builder()
                                .label("출발역 실시간 대기").min(1.0).build()
                ))
                .reversals(List.of(
                        RouteSearchResponse.ReversalItem.builder()
                                .station("논현역")
                                .baselineMin(13.6)
                                .bikeMin(11.6)
                                .savedMin(2.0)
                                .option("논현역 10번출구 -> 신논현역 4번출구")
                                .build()
                ))
                .checkedOthers(List.of(
                        RouteSearchResponse.CheckedOtherItem.builder()
                                .station("언주역3번출구")
                                .note("따릉이로 갈아타도 17.2분 (지하철이 더 빠름)")
                                .bikeMin(17.2)
                                .build()
                ))
                .build();
    }
}
