import { RepositoryError } from './errors'
import type {
  CongestionDataStatus,
  CongestionGrade,
  CongestionPrediction,
  CongestionPredictionBasis,
  BusRouteOption,
  GeometryLineString,
  Route,
  RouteEndpoint,
  RouteGeometry,
  RouteSource,
  SegmentCongestionGrade,
  TransitionType,
  WorstSegmentCongestion,
} from '../features/route/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function finite(value: unknown, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

function parseGeometry(value: unknown, status: unknown): RouteGeometry | undefined {
  // 'estimated'는 AI 재안내 도보 구간(walkLeg) 전용 상태다 — 실경로 조회 없이 직선 추정한
  // 좌표라는 뜻이며, 'available'과 마찬가지로 좌표는 그대로 유지한다(TO_FE-bike-reroute-04.md 2.2절).
  if (
    status !== undefined &&
    status !== 'available' &&
    status !== 'unavailable' &&
    status !== 'estimated'
  ) {
    throw new RepositoryError('invalid-response', '지원하지 않는 경로 좌표 상태 응답이에요.')
  }
  if (status === 'unavailable' || value === null || value === undefined) return undefined
  if (!isRecord(value) || value.type !== 'MultiLineString' || !Array.isArray(value.coordinates)) {
    throw new RepositoryError('invalid-response', '경로 좌표 응답이 올바르지 않아요.')
  }
  const coordinates: GeometryLineString[] = value.coordinates.map((line) => {
    if (!Array.isArray(line) || line.length < 2) {
      throw new RepositoryError('invalid-response', '경로 좌표 응답이 올바르지 않아요.')
    }
    return line.map((point) => {
      if (
        !Array.isArray(point) ||
        point.length < 2 ||
        !finite(point[0], -180, 180) ||
        !finite(point[1], -90, 90)
      ) {
        throw new RepositoryError('invalid-response', '경로 좌표 응답이 올바르지 않아요.')
      }
      return [point[0], point[1]] as [number, number]
    })
  })
  return { type: 'MultiLineString', coordinates }
}

function mapMode(mode: unknown): { mode: 'walk' | 'subway' | 'bus' | 'bike'; transfer?: boolean } {
  if (mode === 'TRANSFER') return { mode: 'walk', transfer: true }
  if (mode === 'WALK' || mode === 'SUBWAY' || mode === 'BUS' || mode === 'BIKE') {
    return { mode: mode.toLowerCase() as 'walk' | 'subway' | 'bus' | 'bike' }
  }
  throw new RepositoryError('invalid-response', '지원하지 않는 이동수단 응답이에요.')
}

function routeLineName(routeId: string | undefined) {
  if (!routeId) return undefined
  const names: Record<string, string> = {
    BUS: '버스',
    BIKE: '자전거',
    WALK: '도보',
    '1001': '1호선',
    '1002': '2호선',
    '1003': '3호선',
    '1004': '4호선',
    '1005': '5호선',
    '1006': '6호선',
    '1007': '7호선',
    '1008': '8호선',
    '1009': '9호선',
    '1063': '경의중앙선',
    '1075': '수인분당선',
  }
  return names[routeId] || routeId
}

function mapBusRouteOptions(value: unknown, mode: unknown): BusRouteOption[] | undefined {
  if (value === undefined || value === null) return undefined
  if (mode !== 'BUS' || !Array.isArray(value)) {
    throw new RepositoryError('invalid-response', '버스 노선 선택지 응답이 올바르지 않아요.')
  }
  const options = value.map((option) => {
    if (!isRecord(option) || !text(option.routeId)) {
      throw new RepositoryError('invalid-response', '버스 노선 선택지 응답이 올바르지 않아요.')
    }
    if (option.routeName != null && !text(option.routeName)) {
      throw new RepositoryError('invalid-response', '버스 노선명 응답이 올바르지 않아요.')
    }
    if (
      option.headwayMin != null &&
      (!Number.isInteger(option.headwayMin) || (option.headwayMin as number) <= 0)
    ) {
      throw new RepositoryError('invalid-response', '버스 배차간격 응답이 올바르지 않아요.')
    }
    return {
      routeId: text(option.routeId) as string,
      ...(text(option.routeName) ? { routeName: text(option.routeName) } : {}),
      ...(option.headwayMin != null ? { headwayMin: option.headwayMin as number } : {}),
    }
  })
  if (new Set(options.map((option) => option.routeId)).size !== options.length) {
    throw new RepositoryError('invalid-response', '버스 노선 선택지가 중복되었어요.')
  }
  return options
}

function endpointCoordinate(value: unknown, min: number, max: number) {
  if (value === undefined || value === null) return undefined
  if (!finite(value, min, max)) {
    throw new RepositoryError('invalid-response', '경로 지점 좌표 응답이 올바르지 않아요.')
  }
  return value as number
}

function mapEndpoint(
  rawLeg: Record<string, unknown>,
  prefix: 'from' | 'to',
): RouteEndpoint | undefined {
  const id = text(rawLeg[`${prefix}NodeId`])
  const name = text(rawLeg[`${prefix}NodeName`])
  const rentalId = text(rawLeg[`${prefix}RentalId`])
  const lat = endpointCoordinate(rawLeg[`${prefix}Lat`], -90, 90)
  const lng = endpointCoordinate(rawLeg[`${prefix}Lng`], -180, 180)
  if (!id && !name && lat === undefined && lng === undefined && !rentalId) return undefined
  return {
    ...(id ? { id } : {}),
    ...(name ? { name } : {}),
    ...(lat !== undefined ? { lat } : {}),
    ...(lng !== undefined ? { lng } : {}),
    ...(rentalId ? { rentalId } : {}),
  }
}

function optionalDistance(value: unknown) {
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new RepositoryError('invalid-response', '경로 거리 응답이 올바르지 않아요.')
  }
  return value as number
}

function optionalCongestionLevel(value: unknown) {
  if (value === undefined || value === null) return undefined
  if (!finite(value, 0, Number.MAX_VALUE)) {
    throw new RepositoryError('invalid-response', '구간 혼잡도 응답이 올바르지 않아요.')
  }
  return value as number
}

function optionalCongestionGrade(value: unknown): SegmentCongestionGrade | undefined {
  if (value === undefined || value === null) return undefined
  if (value !== 'RELAXED' && value !== 'NORMAL' && value !== 'CONGESTED' && value !== 'SATURATED') {
    throw new RepositoryError('invalid-response', '구간 혼잡도 등급 응답이 올바르지 않아요.')
  }
  return value
}

function mapTransitionType(value: unknown): TransitionType | undefined {
  if (value === undefined || value === null) return undefined
  if (
    value !== 'BOARDING' &&
    value !== 'ALIGHTING' &&
    value !== 'TRANSFER' &&
    value !== 'BIKE_RENTAL' &&
    value !== 'BIKE_RETURN'
  ) {
    throw new RepositoryError('invalid-response', '구간 전환 유형 응답이 올바르지 않아요.')
  }
  return value
}

function mapCongestionPrediction(value: unknown): CongestionPrediction | undefined {
  if (value === undefined || value === null) return undefined
  if (!isRecord(value)) {
    throw new RepositoryError('invalid-response', '혼잡도 예측 응답이 올바르지 않아요.')
  }
  const percent = value.congestionPercent
  if (percent !== null && !finite(percent, 0, Number.MAX_VALUE)) {
    throw new RepositoryError('invalid-response', '혼잡도 예측 수치 응답이 올바르지 않아요.')
  }
  const grade = value.congestionGrade
  if (grade !== null && grade !== 'LOW' && grade !== 'MEDIUM' && grade !== 'HIGH') {
    throw new RepositoryError('invalid-response', '혼잡도 예측 등급 응답이 올바르지 않아요.')
  }
  const dataStatus = value.dataStatus
  if (
    dataStatus !== 'AVAILABLE' &&
    dataStatus !== 'LINE1_TRUNCATED' &&
    dataStatus !== 'NO_CALIBRATION' &&
    dataStatus !== 'NO_LOOKUP'
  ) {
    throw new RepositoryError('invalid-response', '혼잡도 예측 상태 응답이 올바르지 않아요.')
  }
  const basis = value.predictionBasis
  if (
    basis !== null &&
    basis !== 'RECENT_7D' &&
    basis !== 'PARTIAL' &&
    basis !== 'WEEKDAY_AVERAGE' &&
    basis !== 'LIVE'
  ) {
    throw new RepositoryError('invalid-response', '혼잡도 예측 기준 응답이 올바르지 않아요.')
  }
  const worstSegment = value.worstSegment
  if (
    worstSegment !== undefined &&
    worstSegment !== null &&
    (!isRecord(worstSegment) ||
      (worstSegment.mode !== 'SUBWAY' && worstSegment.mode !== 'BUS') ||
      (worstSegment.fromNodeId != null && !text(worstSegment.fromNodeId)) ||
      (worstSegment.toNodeId != null && !text(worstSegment.toNodeId)) ||
      (worstSegment.congestionPercent !== null &&
        !finite(worstSegment.congestionPercent, 0, Number.MAX_VALUE)))
  ) {
    throw new RepositoryError('invalid-response', '최악 구간 혼잡도 응답이 올바르지 않아요.')
  }
  const hasPredictionValues = percent !== null && grade !== null && basis !== null
  const hasAnyPredictionValue = percent !== null || grade !== null || basis !== null
  if (
    (dataStatus === 'AVAILABLE' && !hasPredictionValues) ||
    (dataStatus !== 'AVAILABLE' && hasAnyPredictionValue)
  ) {
    throw new RepositoryError('invalid-response', '혼잡도 예측 값과 상태가 일치하지 않아요.')
  }
  return {
    congestionPercent: percent as number | null,
    congestionGrade: grade as CongestionGrade | null,
    dataStatus: dataStatus as CongestionDataStatus,
    predictionBasis: basis as CongestionPredictionBasis | null,
    ...(worstSegment !== undefined
      ? {
          worstSegment:
            worstSegment === null
              ? null
              : {
                  mode: worstSegment.mode as WorstSegmentCongestion['mode'],
                  fromNodeId: text(worstSegment.fromNodeId) ?? null,
                  toNodeId: text(worstSegment.toNodeId) ?? null,
                  congestionPercent: worstSegment.congestionPercent as number | null,
                },
        }
      : {}),
  }
}

export function mapBackendRoute(value: unknown, index: number, departedAt: string): Route {
  if (!isRecord(value) || !text(value.routeType) || !finite(value.totalMinutes, 0, 24 * 60)) {
    throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
  }
  const routeType = value.routeType
  if (
    routeType !== 'SHORTEST' &&
    routeType !== 'SHORTEST_WITH_BIKE' &&
    routeType !== 'ALTERNATIVE' &&
    routeType !== 'LOW_CONGESTION'
  ) {
    throw new RepositoryError('invalid-response', '지원하지 않는 경로 유형 응답이에요.')
  }
  const rawLegs = value.legs
  if (!Array.isArray(rawLegs) || !text(value.source)) {
    throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
  }
  if (value.source !== 'ALGORITHM' && value.source !== 'MOCK') {
    throw new RepositoryError('invalid-response', '지원하지 않는 경로 출처 응답이에요.')
  }
  const legs = rawLegs.map((rawLeg) => {
    if (!isRecord(rawLeg) || !finite(rawLeg.minutes, 0, 24 * 60)) {
      throw new RepositoryError('invalid-response', '경로 구간 응답이 올바르지 않아요.')
    }
    const mappedMode = mapMode(rawLeg.mode)
    const fromName = text(rawLeg.fromNodeName) || text(rawLeg.fromNodeId) || '출발 지점'
    const toName = text(rawLeg.toNodeName) || text(rawLeg.toNodeId) || '도착 지점'
    const routeId = text(rawLeg.routeId)
    const busRouteOptions = mapBusRouteOptions(rawLeg.routeOptions, rawLeg.mode)
    const rawCongestionLevel = optionalCongestionLevel(rawLeg.congestionLevel)
    const rawCongestionGrade = optionalCongestionGrade(rawLeg.congestionGrade)
    const segmentCongestionLevel =
      mappedMode.mode === 'subway' || mappedMode.mode === 'bus' ? rawCongestionLevel : undefined
    const segmentCongestionGrade =
      mappedMode.mode === 'subway' || mappedMode.mode === 'bus' ? rawCongestionGrade : undefined
    const transitionType = mapTransitionType(rawLeg.transitionType)
    if (transitionType && rawLeg.mode !== 'TRANSFER') {
      throw new RepositoryError(
        'invalid-response',
        '구간 전환 유형은 TRANSFER 구간에만 사용할 수 있어요.',
      )
    }
    if (rawLeg.routeName != null && !text(rawLeg.routeName)) {
      throw new RepositoryError('invalid-response', '노선명 응답이 올바르지 않아요.')
    }
    const geometry = parseGeometry(rawLeg.geometry, rawLeg.geometryStatus)
    const transfer =
      mappedMode.transfer === true &&
      (transitionType === undefined || transitionType === 'TRANSFER')
    const from = mapEndpoint(rawLeg, 'from')
    const to = mapEndpoint(rawLeg, 'to')
    const transition = transitionType
    const transitionName =
      transitionType === 'BOARDING'
        ? '승차'
        : transitionType === 'ALIGHTING'
          ? '하차'
          : transitionType === 'BIKE_RENTAL'
            ? '자전거 대여'
            : transitionType === 'BIKE_RETURN'
              ? '자전거 반납'
              : transfer
                ? '환승'
                : undefined
    const busRouteNames = busRouteOptions
      ?.map((option) => option.routeName || option.routeId)
      .filter(Boolean)
    return {
      mode: mappedMode.mode,
      transfer,
      title: transitionName ? `${fromName}에서 ${transitionName}` : `${fromName} → ${toName}`,
      note:
        text(rawLeg.routeName) ||
        (busRouteNames?.length ? busRouteNames.join(' · ') : undefined) ||
        routeLineName(routeId) ||
        transitionName ||
        '이동 구간',
      distanceMeters: optionalDistance(rawLeg.distanceMeters),
      minutes: rawLeg.minutes as number,
      ...(transition ? { transitionType: transition } : {}),
      ...(geometry ? { geometry } : {}),
      ...(routeId ? { routeId } : {}),
      ...(busRouteOptions !== undefined ? { busRouteOptions } : {}),
      ...(segmentCongestionLevel !== undefined ? { segmentCongestionLevel } : {}),
      ...(segmentCongestionGrade !== undefined ? { segmentCongestionGrade } : {}),
      ...(from ? { from } : {}),
      ...(to ? { to } : {}),
    }
  })
  const routeGeometry = legs.flatMap((leg) => leg.geometry?.coordinates || [])
  const lineNames = [
    ...new Set(
      rawLegs
        .map((leg) =>
          isRecord(leg) ? text(leg.routeName) || routeLineName(text(leg.routeId)) : undefined,
        )
        .filter((line): line is string => !!line),
    ),
  ]
  const explicitTransfers = rawLegs.filter(
    (leg) =>
      isRecord(leg) &&
      (leg.transitionType === 'TRANSFER' ||
        (leg.transitionType == null && leg.mode === 'TRANSFER')),
  ).length
  const transitRouteIds = rawLegs
    .filter((leg) => isRecord(leg) && (leg.mode === 'SUBWAY' || leg.mode === 'BUS') && leg.routeId)
    .map((leg) => (isRecord(leg) ? text(leg.routeId) : undefined))
    .filter((routeId): routeId is string => !!routeId)
  const routeTransitions = transitRouteIds
    .slice(1)
    .reduce((count, routeId, index) => count + (routeId !== transitRouteIds[index] ? 1 : 0), 0)
  if (
    value.transferCount != null &&
    (!Number.isInteger(value.transferCount) || (value.transferCount as number) < 0)
  ) {
    throw new RepositoryError('invalid-response', '환승 횟수 응답이 올바르지 않아요.')
  }
  const transfers =
    (value.transferCount as number | undefined) ?? (explicitTransfers || routeTransitions)
  const walkingLegs = legs.filter(
    (leg) => leg.mode === 'walk' && !leg.transfer && !leg.transitionType,
  )
  const walk =
    walkingLegs.length && walkingLegs.every((leg) => leg.distanceMeters !== undefined)
      ? walkingLegs.reduce((sum, leg) => sum + leg.distanceMeters!, 0)
      : undefined
  const label =
    routeType === 'SHORTEST'
      ? '빠른 경로'
      : routeType === 'ALTERNATIVE'
        ? '다른 경로'
        : routeType === 'LOW_CONGESTION'
          ? '다른 경로'
          : '따릉이 포함 경로'
  const congestionPrediction = mapCongestionPrediction(value.congestionPrediction)
  return {
    routeType,
    id: `${routeType.toLowerCase()}-${index}`,
    label,
    minutes: value.totalMinutes as number,
    transfers,
    source: value.source as RouteSource,
    ...(congestionPrediction ? { congestionPrediction } : {}),
    totalDistanceMeters: optionalDistance(value.totalDistanceMeters),
    ...(walk !== undefined ? { walk: Math.round(walk) } : {}),
    modes: [...new Set(legs.filter((leg) => !leg.transfer).map((leg) => leg.mode))],
    ...(lineNames.length ? { line: lineNames.join(' · ') } : {}),
    legs,
    ...(routeGeometry.length
      ? { geometry: { type: 'MultiLineString', coordinates: routeGeometry } }
      : {}),
    departedAt,
  }
}

export function mapRouteApiResponse(value: unknown, departedAt: string): Route[] {
  if (!isRecord(value) || value.success !== true || !Array.isArray(value.data)) {
    throw new RepositoryError('invalid-response', '경로 응답이 올바르지 않아요.')
  }
  return value.data.map((route, index) => mapBackendRoute(route, index, departedAt))
}
