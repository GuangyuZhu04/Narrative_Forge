import { createContext, useContext } from 'react'
import type { WallpaperId } from './wallpaperCatalog'

export interface WallpaperContextValue {
  selectedWallpaper: WallpaperId
  customWallpaperUrl: string | null
  loadingCustomWallpaper: boolean
  selectWallpaper: (wallpaper: WallpaperId) => void
  uploadWallpaper: (file: File) => Promise<void>
  removeCustomWallpaper: () => Promise<void>
}

export const WallpaperContext = createContext<WallpaperContextValue | null>(null)

export const useWallpaper = () => {
  const context = useContext(WallpaperContext)
  if (!context) {
    throw new Error('useWallpaper must be used inside WallpaperProvider')
  }
  return context
}
