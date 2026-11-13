// Dates as the household writes them, for the room's lines.
import { locale } from '../../../household/format';

export const dayOf = (iso: string): string => new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric' }).format(new Date(iso));
