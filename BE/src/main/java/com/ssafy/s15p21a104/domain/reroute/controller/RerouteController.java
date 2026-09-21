package com.ssafy.s15p21a104.domain.reroute.controller;

import com.ssafy.s15p21a104.domain.reroute.RerouteService;
import com.ssafy.s15p21a104.domain.reroute.dto.request.RerouteRequest;
import com.ssafy.s15p21a104.domain.reroute.dto.response.RerouteResponse;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import com.ssafy.s15p21a104.global.response.ApiResult;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class RerouteController implements RerouteApi {

    private final RouteGraphRegistry graphRegistry;
    private final TransferRule transferRule;

    @Override
    public ApiResult<List<RerouteResponse>> replan(RerouteRequest request) {
        if (request == null || request.boundaryId() == null || request.boundaryId().isBlank()) {
            throw new DomainException(ErrorType.INVALID_COORDINATE);
        }
        String destId = request.destStationId();
        if (destId == null || destId.isBlank()) {
            throw new DomainException(ErrorType.STATION_NOT_FOUND);
        }
        if (request.step() < 0) {
            throw new DomainException(ErrorType.INVALID_COORDINATE);
        }
        DepartureSlot slot = DepartureSlot.of(request.requestedAt() != null
                ? LocalDateTime.ofInstant(request.requestedAt().toInstant(), ZoneId.of("Asia/Seoul"))
                : LocalDateTime.now());
        RouteCandidateFinder finder = new RouteCandidateFinder(
                transferRule,
                graphRegistry.transferTimes(),
                graphRegistry.rentalIds(),
                graphRegistry.stationInfos(),
                graphRegistry::bikeStock);
        RerouteService service = new RerouteService(
                finder,
                () -> graphRegistry.graphFor(slot.dowType(), slot.timeSlot()));
        return ApiResult.ok(RerouteResponse.listOf(
                service.replan(request.boundaryId(), destId, slot.dowType(), slot.timeSlot())));
    }
}
