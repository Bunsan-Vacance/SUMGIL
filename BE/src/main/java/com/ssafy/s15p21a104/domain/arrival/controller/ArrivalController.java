package com.ssafy.s15p21a104.domain.arrival.controller;

import com.ssafy.s15p21a104.domain.arrival.ArrivalReader;
import com.ssafy.s15p21a104.domain.arrival.ArrivalResult;
import com.ssafy.s15p21a104.domain.arrival.dto.response.ArrivalResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class ArrivalController implements ArrivalApi {

    private final ArrivalReader arrivalReader;

    @Override
    public ApiResult<ArrivalResponse> arrivals(String stationId, String routeId) {
        ArrivalResult result = arrivalReader.find(stationId, routeId);
        return ApiResult.ok(new ArrivalResponse(
                result.status().name(),
                result.trains().stream()
                        .map(train -> new ArrivalResponse.ArrivalTrainResponse(
                                train.trainId(), train.direction(), train.arrivalTime(),
                                train.updatedAt(), train.source()))
                        .toList(),
                result.updatedAt()));
    }
}
