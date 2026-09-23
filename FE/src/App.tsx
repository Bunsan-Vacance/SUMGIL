import { useCallback, useEffect, useRef, useState } from 'react'
import { useRoutePlanner } from './app/useRoutePlanner'
import { screenTitles } from './app/useNavigation'
import PreviewToolbar from './app/PreviewToolbar'
import KakaoMap from './features/map/KakaoMap'
import FilterDialog from './features/route/FilterDialog'
import GuidanceDialogs from './features/guidance/GuidanceDialogs'
import HomePage from './pages/HomePage'
import BrowsePage from './pages/BrowsePage'
import SearchPage from './pages/SearchPage'
import ResultsPage from './pages/ResultsPage'
import DetailPage from './pages/DetailPage'
import GuidePage from './pages/GuidePage'
import ArrivalPage from './pages/ArrivalPage'
import ActiveGuidanceBar from './features/guidance/ActiveGuidanceBar'
import Modal from './components/Modal'
import SplashScreen from './components/SplashScreen'
import { isBackendConfigured, isRouteSearchMockEnabled } from './api/repositories'
import { isGuidanceMockEnabled } from './api/guidance'
import { remaining } from './features/route/selectors'

export default function App() {
  const [showSplash, setShowSplash] = useState(true)
  const completeSplash = useCallback(() => setShowSplash(false), [])
  const planner = useRoutePlanner()
  const { screen, go, trip, guidance, destinationName, modal, setModal } = planner
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (!showSplash && screen !== 'search' && screen !== 'browse') title.current?.focus()
  }, [screen, showSplash])
  if (showSplash) return <SplashScreen onComplete={completeSplash} />

  return (
    <div className={`workspace workspace-${screen}`}>
      {screen !== 'results' && (
        <PreviewToolbar guiding={screen === 'guide'} isLiveApi={!isGuidanceMockEnabled} />
      )}
      <main className={`app-shell screen-${screen}`}>
        <div className="page-viewport">
          <h1 ref={title} tabIndex={-1} className="sr-only">
            {screenTitles[screen]}
          </h1>
          {screen !== 'search' &&
            screen !== 'arrival' &&
            screen !== 'browse' &&
            screen !== 'results' && (
              <KakaoMap
                key={screen}
                origin={
                  screen === 'home'
                    ? null
                    : screen === 'guide'
                      ? guidance.origin || trip.origin
                      : trip.origin
                }
                destination={
                  screen === 'guide'
                    ? guidance.destination
                    : screen === 'home'
                      ? null
                      : trip.destination
                }
                route={
                  screen === 'guide' ? guidance.route : screen === 'detail' ? trip.selected : null
                }
                autoLocate={screen === 'home'}
                onCurrentLocation={
                  screen === 'home' ? planner.setOriginFromCurrentLocation : undefined
                }
                onMessage={planner.setMessage}
              />
            )}
          {screen === 'home' && (
            <HomePage
              origin={trip.origin}
              destination={trip.destination}
              openSearch={planner.openSearch}
              routePanelOpen={planner.routePanelOpen}
              toggleRoutePanel={planner.toggleRoutePanel}
              closeRoutePanel={planner.closeRoutePanel}
              findRoutes={planner.findRoutes}
              swapPlaces={planner.swapPlaces}
            />
          )}
          {screen === 'browse' && (
            <BrowsePage
              onBack={() => planner.go('home')}
              onMessage={planner.setMessage}
              setOrigin={planner.setOriginFromBrowse}
              findRoutes={planner.findRoutes}
            />
          )}
          {screen === 'search' && (
            <SearchPage
              key={planner.searchTarget}
              searchTarget={planner.searchTarget}
              cancelSearch={planner.cancelSearch}
              choosePlace={planner.choosePlace}
            />
          )}
          {screen === 'results' && (
            <ResultsPage
              origin={trip.origin}
              destinationName={destinationName}
              visible={trip.visible}
              selectedId={trip.selected?.id ?? null}
              setSelectedId={planner.selectRoute}
              status={trip.status}
              retry={() => planner.findRoutes()}
              error={trip.error}
              errorCode={trip.errorCode}
              enabled={trip.enabled}
              priority={trip.priority}
              setPriority={trip.setPriority}
              openFilter={() => setModal('filter')}
              openSearch={planner.openSearch}
              onBackToInput={planner.returnToRouteInput}
              go={go}
              canSwap={!!trip.destination}
              swapPlaces={planner.swapPlaces}
              isLiveApi={isBackendConfigured && !isRouteSearchMockEnabled}
              departureTime={trip.departureTime ?? undefined}
              onDepartureTimeChange={trip.setDepartureTime}
              onResetModes={trip.resetModes}
              onSearchWalk={trip.searchWalkOnly}
            />
          )}
          {screen === 'detail' && trip.selected && (
            <DetailPage
              origin={trip.origin}
              destinationName={destinationName}
              selected={trip.selected}
              alternatives={trip.visible}
              setSelectedId={planner.selectRoute}
              go={go}
              startGuide={planner.startGuide}
            />
          )}
          {screen === 'guide' && guidance.route && (
            <GuidePage
              selected={guidance.route}
              step={guidance.step}
              train={guidance.train}
              selectedArrival={guidance.selectedArrival || null}
              destinationName={destinationName}
              go={go}
              onExit={() => setModal('exit')}
              onPrevious={planner.previous}
              onNext={planner.advance}
              onTrain={planner.openTrain}
              onReplan={planner.openReplan}
              replanDisabled={Boolean(guidance.train)}
              locationStatus={guidance.locationStatus}
              onRetryLocation={guidance.retryLocation}
              onStepChange={guidance.setStep}
            />
          )}
          {screen === 'arrival' && (
            <ArrivalPage destinationName={destinationName} onHome={() => go('home')} />
          )}
          {planner.message && (
            <div className="toast" role="status">
              {planner.message}
            </div>
          )}
        </div>
        {guidance.route &&
          !guidance.completed &&
          screen !== 'guide' &&
          screen !== 'arrival' &&
          guidance.destination && (
            <ActiveGuidanceBar
              route={guidance.route}
              step={guidance.step}
              destinationName={guidance.destination.name}
              onResume={planner.resumeGuide}
            />
          )}
      </main>
      {modal === 'replace-guide' && (
        <Modal title="안내 경로를 바꿀까요?" onClose={() => setModal(null)}>
          <p className="section-label">진행 중인 안내를 종료하고 선택한 경로로 안내해요.</p>
          <div className="modal-actions">
            <button className="secondary" onClick={() => setModal(null)}>
              기존 안내 유지
            </button>
            <button className="primary" onClick={planner.confirmReplacement}>
              새 경로로 안내
            </button>
          </div>
        </Modal>
      )}
      {modal === 'filter' && (
        <FilterDialog
          enabled={trip.enabled}
          onApply={planner.applyFilter}
          onClose={() => setModal(null)}
        />
      )}
      {modal &&
        modal !== 'filter' &&
        modal !== 'replace-guide' &&
        screen === 'guide' &&
        guidance.route?.legs[guidance.step] && (
          <GuidanceDialogs
            dialog={modal}
            leg={guidance.route.legs[guidance.step]}
            arrivals={planner.arrivals}
            arrivalStatus={planner.arrivalStatus}
            proposals={planner.replan.proposals}
            currentRemaining={guidance.route ? remaining(guidance.route, guidance.step) : 0}
            replanStatus={planner.replan.status}
            replanError={planner.replan.error}
            onClose={planner.closeGuidanceDialog}
            onExit={planner.exitGuide}
            onTrain={(arrival) => {
              guidance.setTrain(arrival ? arrival.arrivalTime : 'unknown', arrival)
              planner.closeGuidanceDialog()
            }}
            onLoadArrivals={planner.openTrain}
            onLoadReplan={planner.requestReplan}
            onAcceptReplan={planner.acceptReplan}
          />
        )}
    </div>
  )
}
