package com.ssafy.s15p21a104.controller;

import com.ssafy.s15p21a104.dto.StationResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * TODO: 지금은 mock 데이터를 내려준다.
 * 데이터 수집 파트가 DB에 대여소 마스터 테이블을 채우면, 그 테이블을 조회하도록 교체할 것.
 */
@RestController
public class StationController {

    @GetMapping("/api/stations/nearby")
    public List<StationResponse> nearby(
            @RequestParam Double lat,
            @RequestParam Double lng
    ) {
        return List.of(
                StationResponse.builder()
                        .name("논현역 10번출구")
                        .lat(lat + 0.001)
                        .lng(lng + 0.001)
                        .rackTotal(12)
                        .distanceMeters(150.0)
                        .build()
        );
    }
}
