import { useEffect, useRef } from 'react'
import { useRoutePlanner } from './app/useRoutePlanner'
import { screenTitles } from './app/useNavigation'
import { previewProposal } from './app/preview'
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

export default function App() {
  const planner = useRoutePlanner()
  const { screen, go, trip, guidance, destinationName, modal, setModal } = planner
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (screen !== 'search' && screen !== 'browse') title.current?.focus()
  }, [screen])
  return (
    <div className={`workspace workspace-${screen}`}>
      {screen !== 'results' && (
        <PreviewToolbar
          guiding={screen === 'guide'}
          lastStep={guidance.step === (guidance.route?.legs.length ?? 0) - 1}
          onProposal={() => setModal('proposal')}
          onTrain={() => setModal('train')}
          onNext={planner.advance}
        />
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
                origin={screen === 'guide' ? guidance.origin || trip.origin : trip.origin}
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
                onMessage={planner.setMessage}
              />
            )}
          {screen === 'home' && (
            <HomePage
              origin={trip.origin}
              destination={trip.destination}
              openSearch={planner.openSearch}
              openBrowse={planner.openBrowse}
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
              enabled={trip.enabled}
              priority={trip.priority}
              setPriority={trip.setPriority}
              openFilter={() => setModal('filter')}
              openSearch={planner.openSearch}
              onBackToInput={planner.returnToRouteInput}
              go={go}
              canSwap={!!trip.destination}
              swapPlaces={planner.swapPlaces}
              departureTime={trip.departureTime ?? undefined}
              onDepartureTimeChange={trip.setDepartureTime}
            />
          )}
          {screen === 'detail' && trip.selected && (
            <DetailPage
              origin={trip.origin}
              destinationName={destinationName}
              selected={trip.selected}
              go={go}
              startGuide={planner.startGuide}
            />
          )}
          {screen === 'guide' && guidance.route && (
            <GuidePage
              selected={guidance.route}
              step={guidance.step}
              train={guidance.train}
              destinationName={destinationName}
              go={go}
              onExit={() => setModal('exit')}
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
            proposal={previewProposal}
            onClose={() => setModal(null)}
            onExit={planner.exitGuide}
            onTrain={(time) => {
              guidance.setTrain(time)
              setModal(null)
            }}
            onProposal={planner.acceptProposal}
          />
        )}
    </div>
  )
}
