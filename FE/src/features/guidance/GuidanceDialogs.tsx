import Modal from '../../components/Modal'
import type { Leg, Route } from '../route/types'
export type GuidanceDialog = 'exit' | 'train' | 'proposal'
interface Props {
  dialog: GuidanceDialog
  leg: Leg
  proposal: Route
  onClose: () => void
  onExit: () => void
  onTrain: (time: string) => void
  onProposal: () => void
}
export default function GuidanceDialogs({
  dialog,
  leg,
  proposal,
  onClose,
  onExit,
  onTrain,
  onProposal,
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
  if (dialog === 'train')
    return (
      <Modal title="어느 열차에 탑승했나요?" onClose={onClose}>
        <p className="section-label">
          {leg.mode === 'subway' ? leg.title : '역삼역 · 2호선 잠실·성수 방면'}
        </p>
        <div className="train-options">
          {['09:38', '09:42', '09:44'].map((time) => (
            <button className="secondary" key={time} onClick={() => onTrain(time)}>
              {time}
              <span>출발</span>
            </button>
          ))}
        </div>
        <button className="text-button full" onClick={() => onTrain('unknown')}>
          잘 모르겠어요
        </button>
      </Modal>
    )
  return (
    <Modal title="따릉이 경로로 바꿀까요?" onClose={onClose}>
      <p className="proposal-title">
        혼잡도 {proposal.congestionPercent}% · {proposal.minutes}분
      </p>
      <p className="section-label">가까운 대여소 → 한티역 → 수인분당선</p>
      <div className="modal-actions">
        <button className="secondary" onClick={onClose}>
          기존 경로 유지
        </button>
        <button className="primary" onClick={onProposal}>
          이 경로로 변경
        </button>
      </div>
    </Modal>
  )
}
