import React, { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  DEFAULT_FONT_FAMILY,
  DEFAULT_FONT_SIZE,
  FONT_FAMILIES,
  MAX_FONT_SIZE,
  MIN_FONT_SIZE,
} from './typographyCatalog'
import type { FontFamilyId } from './typographyCatalog'
import { TypographyContext } from './typographyContext'
import type { TypographyContextValue } from './typographyContext'

const FONT_FAMILY_KEY = 'nwa_font_family'
const FONT_SIZE_KEY = 'nwa_font_size'
const FONT_SIZE_VARIABLES = {
  '--app-text-xs': 0.75,
  '--app-text-sm': 0.875,
  '--app-text-base': 1,
  '--app-text-lg': 1.125,
  '--app-text-xl': 1.25,
  '--app-text-2xl': 1.5,
} as const
const VALID_FONT_FAMILIES = new Set<FontFamilyId>(
  FONT_FAMILIES.map((font) => font.id),
)

const clampFontSize = (fontSize: number) =>
  Math.min(MAX_FONT_SIZE, Math.max(MIN_FONT_SIZE, Math.round(fontSize)))

const readFontFamily = (): FontFamilyId => {
  const stored = localStorage.getItem(FONT_FAMILY_KEY)
  return stored && VALID_FONT_FAMILIES.has(stored as FontFamilyId)
    ? (stored as FontFamilyId)
    : DEFAULT_FONT_FAMILY
}

const readFontSize = () => {
  const stored = Number(localStorage.getItem(FONT_SIZE_KEY))
  return Number.isFinite(stored) && stored >= MIN_FONT_SIZE && stored <= MAX_FONT_SIZE
    ? clampFontSize(stored)
    : DEFAULT_FONT_SIZE
}

export const TypographyProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [fontFamily, setFontFamilyState] = useState<FontFamilyId>(readFontFamily)
  const [fontSize, setFontSizeState] = useState(readFontSize)

  useEffect(() => {
    const selectedFont = FONT_FAMILIES.find((font) => font.id === fontFamily)
    document.body.style.setProperty(
      '--app-font-family',
      selectedFont?.cssStack || FONT_FAMILIES[0].cssStack,
    )
    document.body.style.setProperty('--app-font-size', `${fontSize}px`)
    Object.entries(FONT_SIZE_VARIABLES).forEach(([property, ratio]) => {
      document.body.style.setProperty(property, `${fontSize * ratio}px`)
    })

    return () => {
      document.body.style.removeProperty('--app-font-family')
      document.body.style.removeProperty('--app-font-size')
      Object.keys(FONT_SIZE_VARIABLES).forEach((property) => {
        document.body.style.removeProperty(property)
      })
    }
  }, [fontFamily, fontSize])

  const setFontFamily = useCallback((nextFontFamily: FontFamilyId) => {
    if (!VALID_FONT_FAMILIES.has(nextFontFamily)) return
    setFontFamilyState(nextFontFamily)
    localStorage.setItem(FONT_FAMILY_KEY, nextFontFamily)
  }, [])

  const setFontSize = useCallback((nextFontSize: number) => {
    const normalized = clampFontSize(nextFontSize)
    setFontSizeState(normalized)
    localStorage.setItem(FONT_SIZE_KEY, String(normalized))
  }, [])

  const resetTypography = useCallback(() => {
    setFontFamilyState(DEFAULT_FONT_FAMILY)
    setFontSizeState(DEFAULT_FONT_SIZE)
    localStorage.removeItem(FONT_FAMILY_KEY)
    localStorage.removeItem(FONT_SIZE_KEY)
  }, [])

  const value = useMemo<TypographyContextValue>(
    () => ({
      fontFamily,
      fontSize,
      setFontFamily,
      setFontSize,
      resetTypography,
    }),
    [fontFamily, fontSize, resetTypography, setFontFamily, setFontSize],
  )

  return <TypographyContext.Provider value={value}>{children}</TypographyContext.Provider>
}
