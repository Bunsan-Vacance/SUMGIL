import { useEffect, useState } from 'react'
import { useNavigation } from './useNavigation'
import { resolveScreen } from './resolveScreen'
import { previewProposal, previewTrip } from './preview'
import { useToast } from '../components/useToast'
import { useTrip } from '../features/route/useTrip'
import { useGuidance } from '../features/guidance/useGuidance'
import type { GuidanceDialog } from '../features/guidance/GuidanceDialogs'
import type { RouteRepository } from '../api/contracts'
import type { Mode, Place } from '../features/route/types'
import { isBackendConfigured } from '../api/repositories'

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

export function useRoutePlanner(repository?: RouteRepository) {
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
  useEffect(() => {
    if (screen !== navigation.screen) replace(screen)
  }, [screen, navigation.screen, replace])
  useEffect(() => {
    setModal(null)
    setMessage('')
  }, [screen, setMessage])
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
    guidance.start(trip.selected, trip.origin, trip.destination)
    go('guide')
  }
  const confirmReplacement = () => {
    if (trip.status !== 'success' || !trip.selected?.legs.length) return
    guidance.start(trip.selected, trip.origin, trip.destination)
    setModal(null)
    go('guide')
  }
  const resumeGuide = () => go('guide')
  const advance = () => {
    if (!guidance.route) return
    guidance.next()
    if (guidance.step >= guidance.route.legs.length - 1) go('arrival')
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
  const acceptProposal = () => {
    if (isBackendConfigured || screen !== 'guide' || !guidance.route) return
    guidance.start(previewProposal, guidance.origin, guidance.destination)
    setModal(null)
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
    acceptProposal,
    destinationName:
      screen === 'guide' || screen === 'arrival'
        ? guidance.destination?.name || '도곡역'
        : trip.destination?.name || '도곡역',
  }
}
