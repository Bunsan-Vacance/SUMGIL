import { useEffect, useRef, useState } from 'react'
import { useNavigation } from './useNavigation'
import { resolveScreen } from './resolveScreen'
import { previewTrip } from './preview'
import { useToast } from '../components/useToast'
import { useTrip } from '../features/route/useTrip'
import { useGuidance } from '../features/guidance/useGuidance'
import type { GuidanceDialog, GuidanceRequestStatus } from '../features/guidance/GuidanceDialogs'
import type { RouteRepository } from '../api/contracts'
import type { Mode, Place } from '../features/route/types'
import { RepositoryError } from '../api/errors'
import {
  guidanceRepository as defaultGuidanceRepository,
  type GuidanceRepository,
  type ReplanProposal,
  type TrainArrival,
} from '../api/guidance'

interface ReplanState {
  status: GuidanceRequestStatus
  proposals: ReplanProposal[]
  error: string
}

const initialReplan: ReplanState = { status: 'idle', proposals: [], error: '' }

function samePlace(first: Place, second: Place) {
  return (
    first.id === second.id ||
    (first.lat !== undefined &&
      first.lng !== undefined &&
      second.lat !== undefined &&
      second.lng !== undefined &&
      first.lat === second.lat &&
      first.lng === second.lng)
  )
}

export function useRoutePlanner(
  repository?: RouteRepository,
  guidanceApi: GuidanceRepository = defaultGuidanceRepository,
) {
  const navigation = useNavigation()
  const { go, replace } = navigation
  const trip = useTrip(previewTrip, repository)
  const guidance = useGuidance()
  const screen = resolveScreen(navigation.screen, trip, guidance)
  const { message, setMessage } = useToast()
  const [searchTarget, setSearchTarget] = useState<'origin' | 'destination'>('destination')
  const [searchReturnScreen, setSearchReturnScreen] = useState<'home' | 'results'>('home')
  const [routePanelOpen, setRoutePanelOpen] = useState(false)
  const [modal, setModal] = useState<GuidanceDialog | 'filter' | 'replace-guide' | null>(null)
  const [arrivals, setArrivals] = useState<TrainArrival[]>([])
  const [arrivalStatus, setArrivalStatus] = useState<GuidanceRequestStatus>('idle')
  const [replan, setReplan] = useState<ReplanState>(initialReplan)
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
  useEffect(() => {
    if (screen !== navigation.screen) replace(screen)
  }, [screen, navigation.screen, replace])
  useEffect(() => {
    setModal(null)
    setMessage('')
    arrivalRequest.current?.abort()
    replanRequest.current?.abort()
    setArrivals([])
    setArrivalStatus('idle')
    setReplan(initialReplan)
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
  const openSearch = (target: 'origin' | 'destination') => {
    setSearchTarget(target)
    setSearchReturnScreen(screen === 'results' ? 'results' : 'home')
    if (screen === 'home') setRoutePanelOpen(true)
    go('search')
  }
  const openBrowse = () => go('browse')
  const toggleRoutePanel = () => setRoutePanelOpen((open) => !open)
  const closeRoutePanel = () => setRoutePanelOpen(false)
  const returnToRouteInput = () => {
    setRoutePanelOpen(true)
    go('home')
  }
  const cancelSearch = () => go(searchReturnScreen)
  const findRoutes = (place?: Place) => {
    const destination = place || trip.destination
    if (!destination) {
      openSearch('destination')
      return false
    }
    if (samePlace(destination, trip.origin)) {
      setMessage('출발지와 다른 도착지를 선택해 주세요.')
      return false
    }
    void trip.search(destination)
    go('results')
    return true
  }
  const choosePlace = (place: Place) => {
    if (searchTarget === 'origin') {
      if (trip.destination && samePlace(place, trip.destination)) {
        setMessage('출발지와 도착지는 다른 장소를 선택해 주세요.')
        return false
      }
      if (searchReturnScreen === 'results' && trip.destination) {
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
    if (!trip.destination) return false
    if (screen === 'results') {
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
  return {
    screen,
    go,
    trip,
    guidance,
    message,
    setMessage,
    searchTarget,
    cancelSearch,
    modal,
    setModal,
    openSearch,
    openBrowse,
    routePanelOpen,
    toggleRoutePanel,
    closeRoutePanel,
    returnToRouteInput,
    findRoutes,
    choosePlace,
    setOriginFromBrowse,
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
    destinationName:
      screen === 'guide' || screen === 'arrival'
        ? guidance.destination?.name || '도곡역'
        : trip.destination?.name || '도곡역',
  }
}
