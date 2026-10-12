import type { FeedbackGrade } from '../../api/congestionFeedback'
import { formatClock } from '../map/stationArrivals'
import { lineColor, lineTextColor } from '../route/lineColor'
import { segmentCongestionPresentation } from '../route/segmentCongestion'
import { FEEDBACK_OPTIONS, type FeedbackTarget } from './congestionFeedback'

export interface FeedbackCardView {
  title: string
  subtitle: string
  // 지하철 노선 배지. 노선 색·번호를 알 수 없으면 없다.
  line?: { label: string; background: string; color: string }
  options: Array<{ grade: FeedbackGrade; label: string; hint: string; color: string }>
}

export function feedbackOptionView(grade: FeedbackGrade) {
  const option = FEEDBACK_OPTIONS.find((item) => item.grade === grade)!
  return { ...option, color: segmentCongestionPresentation(grade)!.color }
}

export function feedbackCardView(target: FeedbackTarget): FeedbackCardView {
  const { leg } = target
  const place = [leg.from?.name, leg.to?.name].filter(Boolean).join(' → ')
  const time = target.boardedAt ? formatClock(target.boardedAt, false) : ''
  const subtitle = [place, time && `${time} 탑승`].filter(Boolean).join(' · ')
  const background = lineColor(leg)
  const label = /(\d+)호선/.exec(`${leg.note} ${leg.title}`)?.[1]
  return {
    title: leg.mode === 'bus' ? '버스, 실제로 붐볐나요?' : '지하철, 실제로 붐볐나요?',
    subtitle,
    line:
      background && label
        ? { label, background, color: lineTextColor(leg) ?? '#17212b' }
        : undefined,
    options: FEEDBACK_OPTIONS.map((option) => feedbackOptionView(option.grade)),
  }
}
