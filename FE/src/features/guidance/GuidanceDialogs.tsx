import Modal from '../../components/Modal'
import type { Leg } from '../route/types'
import type { ReplanProposal, TrainArrival } from '../../api/guidance'
import { roundMinutes } from '../route/selectors'

export type GuidanceDialog = 'exit' | 'train' | 'replan'
export type GuidanceRequestStatus =
  | 'idle'
  | 'loading'
  | 'success'
  | 'empty'
  | 'no-info'
  | 'outside-window'
  | 'stale'
  | 'error'
  | 'unsupported'

interface Props {
  dialog: GuidanceDialog
  leg: Leg
  arrivals: TrainArrival[]
  arrivalStatus: GuidanceRequestStatus
  proposals: ReplanProposal[]
  currentRemaining: number
  replanStatus: GuidanceRequestStatus
  replanError?: string
  onClose: () => void
  onExit: () => void
  onTrain: (arrival: TrainArrival | null) => void
  onLoadArrivals: () => void
  onLoadReplan: () => void
  onAcceptReplan: (proposal: ReplanProposal) => void
}

function formatArrival(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(value))
}

export default function GuidanceDialogs({
  dialog,
  leg,
  arrivals,
  arrivalStatus,
  proposals,
  currentRemaining,
  replanStatus,
  replanError,
  onClose,
  onExit,
  onTrain,
  onLoadArrivals,
  onLoadReplan,
  onAcceptReplan,
}: Props) {
  if (dialog === 'exit')
    return (
      <Modal title="안내를 종료할까요?" onClose={onClose}>
        <div className="modal-actions">
          <button className="secondary" onClick={onClose}>
            계속 안내
          </button>
          <button className="primary" onClick={onExit}>
            안내 종료
          </button>
        </div>
      </Modal>
    )
  if (dialog === 'train') {
    const canChoose = arrivalStatus === 'success' && arrivals.length > 0
    return (
      <Modal title="탑승을 확인할까요?" onClose={onClose}>
        <p className="section-label">{leg.title}</p>
        {arrivalStatus === 'loading' && (
          <p className="dialog-state">도착 정보를 불러오는 중이에요.</p>
        )}
        {arrivalStatus === 'unsupported' && (
          <p className="dialog-state" role="alert">
            현재 구간은 탑승 확인을 지원하지 않아요.
          </p>
        )}
        {arrivalStatus === 'error' && (
          <div className="dialog-state" role="alert">
            <p>도착 정보를 불러오지 못했어요.</p>
            <button className="secondary" onClick={onLoadArrivals}>
              다시 시도
            </button>
          </div>
        )}
        {arrivalStatus === 'empty' && (
          <p className="dialog-state" role="alert">
            확인할 수 있는 도착 정보가 없어요.
          </p>
        )}
        {arrivalStatus === 'no-info' && (
          <p className="dialog-state">현재 확인되는 열차가 없어요.</p>
        )}
        {arrivalStatus === 'outside-window' && (
          <p className="dialog-state">현재는 지하철 운행 시간이 아니에요.</p>
        )}
        {arrivalStatus === 'stale' && (
          <p className="dialog-state" role="alert">
            실시간 도착 정보가 지연되고 있어요.
          </p>
        )}
        {canChoose && (
          <div className="train-options">
            {arrivals.map((arrival) => (
              <button className="secondary" key={arrival.trainId} onClick={() => onTrain(arrival)}>
                <strong>{formatArrival(arrival.arrivalTime)}</strong>
                <span>{arrival.direction}</span>
                <span>이 열차에 탔어요</span>
                {arrival.source === 'MOCK' && <small>샘플</small>}
              </button>
            ))}
          </div>
        )}
        {arrivalStatus !== 'unsupported' && arrivalStatus !== 'loading' && (
          <button className="text-button full" onClick={() => onTrain(null)}>
            열차 정보 없이 탑승 확인
          </button>
        )}
      </Modal>
    )
  }
  return (
    <Modal title="다른 경로를 찾아볼까요?" onClose={onClose}>
      {replanStatus === 'idle' && (
        <>
          <p className="section-label">현재 구간 시작 지점 이후의 잔여 구간만 다시 계산해요.</p>
          <button className="primary full" onClick={onLoadReplan}>
            다른 경로 찾기
          </button>
        </>
      )}
      {replanStatus === 'loading' && (
        <p className="dialog-state">남은 경로를 다시 찾는 중이에요.</p>
      )}
      {replanStatus === 'error' && (
        <div className="dialog-state" role="alert">
          <p>{replanError || '경로를 다시 찾지 못했어요.'}</p>
          <button className="secondary" onClick={onLoadReplan}>
            다시 시도
          </button>
        </div>
      )}
      {replanStatus === 'empty' && (
        <div className="dialog-state" role="alert">
          <p>현재 구간 시작 지점 이후에 가능한 경로가 없어요.</p>
          <button className="secondary" onClick={onLoadReplan}>
            다시 시도
          </button>
        </div>
      )}
      {replanStatus === 'success' && (
        <div className="proposal-list">
          <p className="section-label">현재 경로와 남은 시간을 비교해 선택해 주세요.</p>
          {proposals.map((proposal) => (
            <article className="proposal-card" key={proposal.route.id}>
              <div>
                <strong>{proposal.route.label}</strong>
                <span>
                  현재 {roundMinutes(currentRemaining)}분 → 후보{' '}
                  {roundMinutes(proposal.route.minutes)}분
                  {` (${proposal.route.minutes - currentRemaining > 0 ? '+' : ''}${roundMinutes(proposal.route.minutes - currentRemaining)}분)`}
                </span>
                <span>{proposal.reason}</span>
                {proposal.source === 'MOCK' && <small>샘플 데이터</small>}
              </div>
              <button className="primary" onClick={() => onAcceptReplan(proposal)}>
                이 경로로 변경
              </button>
            </article>
          ))}
          <button className="secondary full" onClick={onClose}>
            기존 경로 유지
          </button>
        </div>
      )}
    </Modal>
  )
}
