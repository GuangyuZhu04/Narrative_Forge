export const BUILT_IN_WALLPAPERS = [
  {
    id: 'misty-lake',
    name: '雾湖晨光',
    url: '/wallpapers/wallpaper_1.png',
  },
  {
    id: 'paper-mountains',
    name: '流光山峦',
    url: '/wallpapers/wallpaper_2.png',
  },
  {
    id: 'sunlit-desk',
    name: '窗边书桌',
    url: '/wallpapers/wallpaper_3.png',
  },
  {
    id: 'moonlit-sea',
    name: '月夜静海',
    url: '/wallpapers/wallpaper_4.png',
  },
] as const

type BuiltInWallpaperId = (typeof BUILT_IN_WALLPAPERS)[number]['id']
export type WallpaperId = 'none' | 'custom' | BuiltInWallpaperId
