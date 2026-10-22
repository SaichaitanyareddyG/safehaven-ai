import { useQuery } from '@tanstack/react-query'

import { getMissedDoses } from '@/api/patients'

export function useMissedDoses() {
  return useQuery({
    queryKey: ['missed-doses'],
    queryFn: getMissedDoses,
    refetchInterval: 5 * 60 * 1000,
    select: (data) => new Map(data.flags.map((f) => [f.patient_id, f])),
  })
}
