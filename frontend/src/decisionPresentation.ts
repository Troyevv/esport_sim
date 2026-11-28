import type { Decision } from "./careerData";

export const decisionPresentation: Record<Decision["action"], {icon: string; label: string}> = {
  calendar: {icon:"calendar", label:"Выбрать турнир"},
  entry: {icon:"users", label:"Открыть заявку"},
  play: {icon:"play", label:"В матч-центр"},
  match: {icon:"play", label:"В матч-центр"},
  repair: {icon:"settings", label:"Проверить и восстановить карты"},
  retry: {icon:"clock", label:"Повторить расчёт"},
  overview: {icon:"trophy", label:"Открыть турнир"},
  training: {icon:"report-analytics", label:"Открыть отчёт"},
  inbox: {icon:"inbox", label:"Во входящие"},
};
