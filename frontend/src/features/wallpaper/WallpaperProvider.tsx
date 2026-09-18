import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import {
  deleteCustomWallpaper,
  loadCustomWallpaper,
  saveCustomWallpaper,
} from './wallpaperStorage'
import { BUILT_IN_WALLPAPERS } from './wallpaperCatalog'
import type { WallpaperId } from './wallpaperCatalog'
import { WallpaperContext } from './wallpaperContext'
import type { WallpaperContextValue } from './wallpaperContext'

const PREFERENCE_KEY = 'nwa_wallpaper_selection'
const VALID_WALLPAPER_IDS = new Set<WallpaperId>([
  'none',
  'custom',
  ...BUILT_IN_WALLPAPERS.map((wallpaper) => wallpaper.id),
])

const readSelection = (): WallpaperId => {
  const stored = localStorage.getItem(PREFERENCE_KEY)
  return stored && VALID_WALLPAPER_IDS.has(stored as WallpaperId)
    ? (stored as WallpaperId)
    : 'none'
}

const persistSelection = (wallpaper: WallpaperId) => {
  localStorage.setItem(PREFERENCE_KEY, wallpaper)
}

export const WallpaperProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [selectedWallpaper, setSelectedWallpaper] = useState<WallpaperId>(readSelection)
  const [customWallpaper, setCustomWallpaper] = useState<Blob | null>(null)
  const [loadingCustomWallpaper, setLoadingCustomWallpaper] = useState(true)

  useEffect(() => {
    let cancelled = false

    void loadCustomWallpaper()
      .then((image) => {
        if (cancelled) return
        setCustomWallpaper(image)
        if (!image) {
          setSelectedWallpaper((current) => {
            if (current !== 'custom') return current
            persistSelection('none')
            return 'none'
          })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSelectedWallpaper((current) => {
            if (current !== 'custom') return current
            persistSelection('none')
            return 'none'
          })
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingCustomWallpaper(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  const customWallpaperUrl = useMemo(
    () => (customWallpaper ? URL.createObjectURL(customWallpaper) : null),
    [customWallpaper],
  )

  useEffect(() => {
    return () => {
      if (customWallpaperUrl) URL.revokeObjectURL(customWallpaperUrl)
    }
  }, [customWallpaperUrl])

  const activeWallpaperUrl = useMemo(() => {
    if (selectedWallpaper === 'none') return null
    if (selectedWallpaper === 'custom') return customWallpaperUrl
    return (
      BUILT_IN_WALLPAPERS.find((wallpaper) => wallpaper.id === selectedWallpaper)
        ?.url || null
    )
  }, [customWallpaperUrl, selectedWallpaper])

  useEffect(() => {
    const body = document.body
    if (activeWallpaperUrl) {
      body.style.setProperty('--app-wallpaper-image', `url("${activeWallpaperUrl}")`)
      body.classList.add('wallpaper-active')
    } else {
      body.style.removeProperty('--app-wallpaper-image')
      body.classList.remove('wallpaper-active')
    }

    return () => {
      body.style.removeProperty('--app-wallpaper-image')
      body.classList.remove('wallpaper-active')
    }
  }, [activeWallpaperUrl])

  const selectWallpaper = useCallback(
    (wallpaper: WallpaperId) => {
      if (wallpaper === 'custom' && !customWallpaper) return
      setSelectedWallpaper(wallpaper)
      persistSelection(wallpaper)
    },
    [customWallpaper],
  )

  const uploadWallpaper = useCallback(async (file: File) => {
    if (!file.type.startsWith('image/')) {
      throw new Error('请选择图片文件')
    }
    await saveCustomWallpaper(file)
    setCustomWallpaper(file)
    setSelectedWallpaper('custom')
    persistSelection('custom')
  }, [])

  const removeCustomWallpaper = useCallback(async () => {
    await deleteCustomWallpaper()
    setCustomWallpaper(null)
    setSelectedWallpaper((current) => {
      if (current !== 'custom') return current
      persistSelection('none')
      return 'none'
    })
  }, [])

  const value = useMemo<WallpaperContextValue>(
    () => ({
      selectedWallpaper,
      customWallpaperUrl,
      loadingCustomWallpaper,
      selectWallpaper,
      uploadWallpaper,
      removeCustomWallpaper,
    }),
    [
      customWallpaperUrl,
      loadingCustomWallpaper,
      removeCustomWallpaper,
      selectWallpaper,
      selectedWallpaper,
      uploadWallpaper,
    ],
  )

  return <WallpaperContext.Provider value={value}>{children}</WallpaperContext.Provider>
}
