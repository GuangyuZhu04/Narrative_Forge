import { createContext, useContext } from 'react'
import type { FontFamilyId } from './typographyCatalog'

export interface TypographyContextValue {
  fontFamily: FontFamilyId
  fontSize: number
  setFontFamily: (fontFamily: FontFamilyId) => void
  setFontSize: (fontSize: number) => void
  resetTypography: () => void
}

export const TypographyContext = createContext<TypographyContextValue | null>(null)

export const useTypography = () => {
  const context = useContext(TypographyContext)
  if (!context) {
    throw new Error('useTypography must be used inside TypographyProvider')
  }
  return context
}
