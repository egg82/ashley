// Whether the screen is wide enough for the map; a phone is not, and gets the summary alone.
import { useMedia } from '../../../components/useMedia';

export const useWide = (): boolean => useMedia('(min-width: 900px)');
