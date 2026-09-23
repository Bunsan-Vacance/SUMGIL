package com.ssafy.s15p21a104.domain.route.bus.geometry;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

/** 카카오 대중교통 경로 API 응답 중 버스 geometry 매칭에 필요한 필드. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record KakaoPublicTrafficResponse(
        String status,
        List<Route> routes
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Route(List<Step> steps) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Step(Properties properties, Path path) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Properties(
            String type,
            List<Stop> stops,
            List<Vehicle> vehicles,
            Integer time
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Stop(String name) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Vehicle(String name) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Path(List<List<Double>> points) {
    }
}
