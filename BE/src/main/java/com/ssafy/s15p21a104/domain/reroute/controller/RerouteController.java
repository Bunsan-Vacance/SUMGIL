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
    private final com.ssafy.s15p21a104.domain.route.service.RouteSearchService routeSearchService;

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
        LocalDateTime requested = request.requestedAt() != null
                ? LocalDateTime.ofInstant(request.requestedAt().toInstant(), ZoneId.of("Asia/Seoul"))
                : null;
        DepartureSlot slot = DepartureSlot.of(requested != null ? requested : LocalDateTime.now());
        RouteCandidateFinder finder = new RouteCandidateFinder(
                transferRule,
                graphRegistry.transferTimes(),
                graphRegistry.rentalIds(),
                graphRegistry.stationInfos(),
                graphRegistry::bikeStock,
                graphRegistry.busRouteIndex(),
                // replan도 슬롯 RAPTOR 입력으로(5부 D1) — null이면 레거시 폴백(제거는 D2).
                new RouteCandidateFinder.RaptorInput(
                        graphRegistry.raptorRouteSetFor(slot.dowType(), slot.timeSlot()), null));
        RerouteService service = new RerouteService(
                finder,
                () -> graphRegistry.graphFor(slot.dowType(), slot.timeSlot()))
                // 검색 응답과 같은 노선 이름·geometry 단계(TO_BE-bike-reroute-route-03 §1).
                .withDisplay(routes -> routeSearchService.withDisplayFields(routes, requested));
        return ApiResult.ok(RerouteResponse.listOf(
                service.replan(request.boundaryId(), destId, slot.dowType(), slot.timeSlot())));
    }
}
