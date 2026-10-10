import { useEffect, useRef, useState } from 'react'
import { useNavigation } from './useNavigation'
import { resolveScreen } from './resolveScreen'
import { previewTripFor } from './preview'
import { useToast } from '../components/useToast'
import { useTrip } from '../features/route/useTrip'
import { useGuidance } from '../features/guidance/useGuidance'
import { useRerouteCheck } from '../features/guidance/useRerouteCheck'
import { useCurrentLocation } from '../features/map/useCurrentLocation'
import { useFavoritePlaces } from '../features/route/useFavoritePlaces'
import { hasRouteLocation, samePlace } from '../features/route/placeRules'
import {
  isCurrentLocation,
  isRecentRoutePinned,
  pinRecentRoute,
  saveRecentRoute,
} from '../features/route/recentRoutes'
import { isRegisterablePlace } from '../features/route/favoritePlaces'
import type { FavoriteLabel } from '../features/route/favoritePlaces'
import type { GuidanceDialog, GuidanceRequestStatus } from '../features/guidance/GuidanceDialogs'
import type { RouteRepository } from '../api/contracts'
import type { Mode, Place, SearchTarget } from '../features/route/types'
import { RepositoryError } from '../api/errors'
import {
  guidanceRepository as defaultGuidanceRepository,
  type GuidanceRepository,
  type ReplanProposal,
  type TrainArrival,
} from '../api/guidance'
import {
  rerouteRepository as defaultRerouteRepository,
  isRerouteDebugForceEnabled,
  proposalToRoute,
  type RerouteCheckResponse,
  type RerouteRepository,
} from '../api/reroute'

interface ReplanState {
  status: GuidanceRequestStatus
  proposals: ReplanProposal[]
  error: string
}

const initialReplan: ReplanState = { status: 'idle', proposals: [], error: '' }

export function useRoutePlanner(
  repository?: RouteRepository,
  guidanceApi: GuidanceRepository = defaultGuidanceRepository,
  rerouteApi: RerouteRepository | null = defaultRerouteRepository,
) {
  const navigation = useNavigation()
  const { go, replace } = navigation
  const trip = useTrip(previewTripFor(location.search), repository)
  const guidance = useGuidance(navigation.screen === 'guide')
  const screen = resolveScreen(navigation.screen, trip, guidance)
  const { message, setMessage } = useToast()
  const [usedRouteSaved, setUsedRouteSaved] = useState(false)
  const favorites = useFavoritePlaces()
  // 화면 전환 시 토스트를 비우는 effect가 등록 완료 안내까지 지우지 않도록 다음 화면에 넘길 메시지를 보관한다.
  const pendingMessage = useRef<string | null>(null)
  const [searchTarget, setSearchTarget] = useState<SearchTarget>('destination')
  const [searchReturnScreen, setSearchReturnScreen] = useState<'home' | 'results'>('home')
  const [routePanelOpen, setRoutePanelOpen] = useState(true)
  const [modal, setModal] = useState<GuidanceDialog | 'filter' | 'replace-guide' | null>(null)
  const [arrivals, setArrivals] = useState<TrainArrival[]>([])
  const [arrivalStatus, setArrivalStatus] = useState<GuidanceRequestStatus>('idle')
  const [replan, setReplan] = useState<ReplanState>(initialReplan)
  const [rerouteProposal, setRerouteProposal] = useState<{
    proposal: RerouteCheckResponse
    legIndex: number
  } | null>(null)
  const arrivalRequest = useRef<AbortController | null>(null)
  const replanRequest = useRef<AbortController | null>(null)
  const requestSequence = useRef(0)
  const replanContext = useRef<{
    route: typeof guidance.route
    step: number
    sequence: number
  } | null>(null)
  const guidanceCursor = useRef<{ route: typeof guidance.route; step: number }>({
    route: guidance.route,
    step: guidance.step,
  })
  const originRef = useRef(trip.origin)
  originRef.current = trip.origin
  const setOriginFromCurrentLocation = (position: GeolocationPosition) => {
    const { latitude, longitude } = position.coords
    if (
      !Number.isFinite(latitude) ||
      !Number.isFinite(longitude) ||
      latitude < -90 ||
      latitude > 90 ||
      longitude < -180 ||
      longitude > 180
    ) {
      setMessage('현재 위치를 확인하지 못했어요. 다시 시도해 주세요.')
      return
    }
    if (originRef.current.name.trim()) return
    trip.setOrigin({
      id: `current-location:${latitude}:${longitude}`,
      name: '현재 위치',
      address: `위도 ${latitude.toFixed(6)}, 경도 ${longitude.toFixed(6)}`,
      kind: '현재 위치',
      lat: latitude,
      lng: longitude,
    })
  }
  const { locate } = useCurrentLocation(setOriginFromCurrentLocation, setMessage, screen)
  useEffect(() => {
    if (screen !== navigation.screen) replace(screen)
  }, [screen, navigation.screen, replace])
  useEffect(() => {
    const { origin, destination } = guidance
    if (!origin || !destination) {
      setUsedRouteSaved(false)
      return
    }
    setUsedRouteSaved(isRecentRoutePinned(isCurrentLocation(origin) ? null : origin, destination))
  }, [screen, guidance.origin, guidance.destination])
  useEffect(() => {
    setModal(null)
    setMessage(pendingMessage.current ?? '')
    pendingMessage.current = null
    arrivalRequest.current?.abort()
    replanRequest.current?.abort()
    setArrivals([])
    setArrivalStatus('idle')
    setReplan(initialReplan)
    setRerouteProposal(null)
  }, [screen, setMessage])
  useEffect(() => {
    const previous = guidanceCursor.current
    if (previous.route !== guidance.route || previous.step !== guidance.step) {
      arrivalRequest.current?.abort()
      replanRequest.current?.abort()
      requestSequence.current += 1
      replanContext.current = null
      setArrivals([])
      setArrivalStatus('idle')
      setReplan(initialReplan)
      setRerouteProposal(null)
    }
    guidanceCursor.current = { route: guidance.route, step: guidance.step }
  }, [guidance.route, guidance.step])
  useEffect(
    () => () => {
      arrivalRequest.current?.abort()
      replanRequest.current?.abort()
      requestSequence.current += 1
    },
    [],
  )
  useRerouteCheck({
    state: guidance,
    enabled: screen === 'guide' && rerouteApi !== null,
    repository: rerouteApi,
    debugForce: isRerouteDebugForceEnabled,
    onProposal: (proposal, legIndex) => {
      setRerouteProposal({ proposal, legIndex })
      setModal((current) => (current === null ? 'reroute' : current))
    },
  })
  const openSearch = (target: 'origin' | 'destination') => {
    setSearchTarget(target)
    setSearchReturnScreen(screen === 'results' ? 'results' : 'home')
    // 홈 패널의 열림 상태는 그대로 둔다. 상단 검색창에서 열었다 취소하면 검색창 홈으로 돌아온다.
    go('search')
  }
  const openFavoriteRegistration = (label: FavoriteLabel) => {
    setSearchTarget(label)
    setSearchReturnScreen(screen === 'results' ? 'results' : 'home')
    go('search')
  }
  const openBrowse = () => go('browse')
  const toggleRoutePanel = () => {
    if (routePanelOpen) {
      setRoutePanelOpen(false)
      return
    }
    setRoutePanelOpen(true)
    if (!trip.origin.name.trim()) locate()
  }
  const returnToRouteInput = () => {
    setRoutePanelOpen(true)
    go('home')
  }
  const saveUsedRoute = () => {
    const { origin, destination } = guidance
    if (!origin || !destination) return false
    pinRecentRoute(origin, destination)
    setUsedRouteSaved(true)
    setMessage('경로를 저장했어요')
    return true
  }
  const cancelSearch = () => go(searchReturnScreen)
  const findRoutes = (place?: Place) => {
    const destination = place || trip.destination
    if (!destination) {
      openSearch('destination')
      return false
    }
    if (!hasRouteLocation(trip.origin)) {
      if (place) trip.setDestination(place)
      openSearch('origin')
      return Boolean(place)
    }
    if (samePlace(destination, trip.origin)) {
      setMessage('출발지와 다른 도착지를 선택해 주세요.')
      return false
    }
    saveRecentRoute(trip.origin, destination)
    void trip.search(destination)
    go('results')
    return true
  }
  const findRoutesFrom = (origin: Place, destination: Place) => {
    if (!hasRouteLocation(origin)) {
      trip.setDestination(destination)
      openSearch('origin')
      return false
    }
    if (samePlace(destination, origin)) {
      setMessage('출발지와 다른 도착지를 선택해 주세요.')
      return false
    }
    saveRecentRoute(origin, destination)
    void trip.search(destination, origin)
    go('results')
    return true
  }
  const choosePlace = (place: Place) => {
    if (searchTarget === 'home' || searchTarget === 'work') {
      if (!isRegisterablePlace(place)) {
        setMessage('현재 위치는 즐겨찾기로 등록할 수 없어요')
        return false
      }
      favorites.setLabel(place, searchTarget)
      pendingMessage.current = searchTarget === 'home' ? '집으로 등록했어요' : '회사로 등록했어요'
      go(searchReturnScreen)
      return true
    }
    if (searchTarget === 'origin') {
      if (trip.destination && samePlace(place, trip.destination)) {
        setMessage('출발지와 도착지는 다른 장소를 선택해 주세요.')
        return false
      }
      if (trip.destination) {
        saveRecentRoute(place, trip.destination)
        void trip.search(trip.destination, place)
        go('results')
        return true
      }
      trip.setOrigin(place)
      go('home')
      return true
    }
    return findRoutes(place)
  }
  const setOriginFromBrowse = (place: Place) => {
    if (trip.destination && samePlace(place, trip.destination)) {
      setMessage('출발지와 도착지는 다른 장소를 선택해 주세요.')
      return false
    }
    trip.setOrigin(place)
    setRoutePanelOpen(true)
    go('home')
    return true
  }
  const swapPlaces = () => {
    if (!trip.destination || !hasRouteLocation(trip.origin)) return false
    if (screen === 'results') {
      saveRecentRoute(trip.destination, trip.origin)
      void trip.search(trip.origin, trip.destination)
      go('results')
    } else {
      trip.swap()
    }
    return true
  }
  const selectRoute = (id: string) => {
    if (!trip.visible.some((route) => route.id === id)) return
    trip.select(id)
  }
  const startGuide = () => {
    if (trip.status !== 'success' || !trip.selected?.legs.length) return
    if (guidance.active) {
      const sameTrip =
        guidance.route === trip.selected &&
        guidance.origin?.id === trip.origin.id &&
        guidance.destination?.id === trip.destination?.id
      if (!sameTrip) {
        setModal('replace-guide')
        return
      }
    }
    guidance.start(trip.selected, trip.origin, trip.destination, {
      modes: trip.enabled,
      priority: trip.priority,
      departedAt: trip.selected.departedAt,
    })
    go('guide')
  }
  const confirmReplacement = () => {
    if (trip.status !== 'success' || !trip.selected?.legs.length) return
    guidance.start(trip.selected, trip.origin, trip.destination, {
      modes: trip.enabled,
      priority: trip.priority,
      departedAt: trip.selected.departedAt,
    })
    setModal(null)
    go('guide')
  }
  const resumeGuide = () => go('guide')
  const advance = () => {
    if (!guidance.route) return
    guidance.next()
    if (guidance.step >= guidance.route.legs.length - 1) go('arrival')
  }
  const previous = () => {
    if (!guidance.route || guidance.step <= 0) return
    guidance.previous()
  }
  const exitGuide = () => {
    guidance.stop()
    setModal(null)
    go('results')
  }
  const applyFilter = (modes: Mode[]) => {
    trip.setModes(modes)
    setModal(null)
  }
  const openTrain = () => {
    setModal('train')
    const route = guidance.route
    const leg = route?.legs[guidance.step]
    if (!route || !leg || leg.mode !== 'subway') {
      setArrivalStatus('unsupported')
      return
    }
    const stationId = leg.from?.id
    const routeId = leg.routeId
    if (!stationId || !routeId) {
      setArrivalStatus('error')
      return
    }
    arrivalRequest.current?.abort()
    const controller = new AbortController()
    arrivalRequest.current = controller
    setArrivalStatus('loading')
    setArrivals([])
    void guidanceApi
      .arrivals(
        {
          stationId,
          routeId,
          stationName: leg.from?.name,
          routeName: leg.title,
        },
        controller.signal,
      )
      .then((result) => {
        if (controller.signal.aborted) return
        setArrivals(result.trains)
        setArrivalStatus(
          result.status === 'LIVE'
            ? 'success'
            : result.status === 'NO_INFO'
              ? 'no-info'
              : result.status === 'OUTSIDE_WINDOW'
                ? 'outside-window'
                : 'stale',
        )
      })
      .catch((error: unknown) => {
        if (
          controller.signal.aborted ||
          (error instanceof DOMException && error.name === 'AbortError')
        )
          return
        setArrivalStatus('error')
      })
  }
  const closeGuidanceDialog = () => {
    arrivalRequest.current?.abort()
    replanRequest.current?.abort()
    requestSequence.current += 1
    replanContext.current = null
    setArrivals([])
    setArrivalStatus('idle')
    setReplan(initialReplan)
    setRerouteProposal(null)
    setModal(null)
  }
  const openReplan = () => {
    if (guidance.train) return
    setReplan(initialReplan)
    replanContext.current = null
    setModal('replan')
  }
  const requestReplan = () => {
    const route = guidance.route
    const destination = guidance.destination
    const step = guidance.step
    const leg = route?.legs[step]
    if (!route || !destination || !leg) return
    replanRequest.current?.abort()
    const controller = new AbortController()
    replanRequest.current = controller
    const sequence = ++requestSequence.current
    replanContext.current = { route, step, sequence }
    setReplan({ status: 'loading', proposals: [], error: '' })
    if (guidance.train) return
    const currentBoundary = leg.from
    void guidanceApi
      .replan(
        {
          currentRoute: route,
          step,
          currentBoundary: currentBoundary || { name: leg.title },
          currentLeg: { mode: leg.mode, routeId: leg.routeId, from: leg.from, to: leg.to },
          destination,
          conditions: {
            ...(guidance.conditions || { modes: [], priority: 'fast' as const }),
            requestedAt: new Date().toISOString(),
          },
        },
        controller.signal,
      )
      .then((proposals) => {
        if (controller.signal.aborted || sequence !== requestSequence.current) return
        setReplan({
          status: proposals.length ? 'success' : 'empty',
          proposals,
          error: '',
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequence.current) return
        setReplan({
          status: 'error',
          proposals: [],
          error: error instanceof RepositoryError ? error.message : '경로를 다시 찾지 못했어요.',
        })
      })
  }
  const acceptReplan = (proposal: ReplanProposal) => {
    const context = replanContext.current
    if (
      !context ||
      context.sequence !== requestSequence.current ||
      guidance.route !== context.route ||
      guidance.step !== context.step ||
      screen !== 'guide'
    ) {
      closeGuidanceDialog()
      return
    }
    guidance.replan(proposal.route)
    closeGuidanceDialog()
  }
  const acceptReroute = () => {
    const current = rerouteProposal
    if (!current) return
    try {
      const route = proposalToRoute(current.proposal, new Date().toISOString())
      guidance.replan(route, current.legIndex)
    } catch (error) {
      setMessage(
        error instanceof RepositoryError ? error.message : '재안내 경로를 적용하지 못했어요.',
      )
    }
    closeGuidanceDialog()
  }
  const dismissReroute = () => {
    closeGuidanceDialog()
  }
  return {
    screen,
    go,
    trip,
    guidance,
    message,
    setMessage,
    searchTarget,
    cancelSearch,
    favorites,
    modal,
    setModal,
    openSearch,
    openFavoriteRegistration,
    openBrowse,
    routePanelOpen,
    toggleRoutePanel,
    returnToRouteInput,
    findRoutes,
    findRoutesFrom,
    saveUsedRoute,
    usedRouteSaved,
    choosePlace,
    setOriginFromBrowse,
    setOriginFromCurrentLocation,
    swapPlaces,
    selectRoute,
    startGuide,
    confirmReplacement,
    resumeGuide,
    advance,
    exitGuide,
    applyFilter,
    previous,
    openTrain,
    openReplan,
    requestReplan,
    acceptReplan,
    closeGuidanceDialog,
    arrivals,
    arrivalStatus,
    replan,
    rerouteProposal,
    acceptReroute,
    dismissReroute,
    destinationName:
      screen === 'guide' || screen === 'arrival'
        ? guidance.destination?.name || '도곡역'
        : trip.destination?.name || '도곡역',
  }
}
