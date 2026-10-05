import { format, parseISO } from 'date-fns'

/**
 * One date style everywhere staff look (the product is US-only): "Oct 5, 2026,
 * 8:46 AM" and "Aug 8, 1966". Before this one patient page used five formats.
 */
export function formatDateTime(value: string | number | Date): string {
  return format(new Date(value), 'MMM d, yyyy, h:mm a')
}

/** A calendar date with no time ("1966-08-08" -> "Aug 8, 1966"), never shifted by time zone. */
export function formatDate(value: string): string {
  return format(parseISO(value), 'MMM d, yyyy')
}

export function formatTime(value: string | number | Date): string {
  return format(new Date(value), 'h:mm:ss a')
}
