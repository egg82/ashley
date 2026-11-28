// Whether the screen is at phone width: the breakpoint `workshop.css` collapses the grid to one column at.
import { PHONE, useMedia } from '../../../components/useMedia';

export const useNarrow = (): boolean => useMedia(PHONE);
