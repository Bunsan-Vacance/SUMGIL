import { isBackendConfigured } from '../api/repositories'

interface Props {
  guiding: boolean
  lastStep: boolean
  onProposal: () => void
  onTrain: () => void
  onNext: () => void
  onHome: () => void
  isLiveApi?: boolean
}
export default function PreviewToolbar({
  guiding,
  lastStep,
  onProposal,
  onTrain,
  onNext,
  onHome,
  isLiveApi = isBackendConfigured,
}: Props) {
  return (
    <div className="demo-toolbar">
      {!isLiveApi && (
        <span>
          <b>숨길</b> 화면 미리보기 · 샘플 데이터
        </span>
      )}
      <div>
        {guiding && (
          <>
            <button disabled={isLiveApi} onClick={onProposal}>
              경로 제안
            </button>
            <button disabled={isLiveApi} onClick={onTrain}>
              탑승 확인
            </button>
            <button onClick={onNext}>{lastStep ? '도착' : '다음 단계'}</button>
          </>
        )}
        <button onClick={onHome}>처음으로</button>
      </div>
    </div>
  )
}
