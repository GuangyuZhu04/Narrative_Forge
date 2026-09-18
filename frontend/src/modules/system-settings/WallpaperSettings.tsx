import React, { useState } from 'react'
import { Check, ImagePlus, LoaderCircle, Trash2, Wallpaper, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { BUILT_IN_WALLPAPERS } from '@/features/wallpaper/wallpaperCatalog'
import type { WallpaperId } from '@/features/wallpaper/wallpaperCatalog'
import { useWallpaper } from '@/features/wallpaper/wallpaperContext'

interface WallpaperOptionProps {
  id: WallpaperId
  name: string
  imageUrl: string | null
  selected: boolean
  disabled?: boolean
  onSelect: (id: WallpaperId) => void
}

const WallpaperOption: React.FC<WallpaperOptionProps> = ({
  id,
  name,
  imageUrl,
  selected,
  disabled = false,
  onSelect,
}) => (
  <button
    type="button"
    aria-pressed={selected}
    aria-label={`选择壁纸：${name}`}
    disabled={disabled}
    onClick={() => onSelect(id)}
    className={`group overflow-hidden rounded-xl border bg-white text-left shadow-sm transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
      selected
        ? 'border-blue-500 ring-2 ring-blue-200'
        : 'border-gray-200 hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md'
    }`}
  >
    <div className="relative aspect-video overflow-hidden bg-gray-100">
      {imageUrl ? (
        <img
          src={imageUrl}
          alt=""
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        />
      ) : (
        <div className="flex h-full items-center justify-center bg-gradient-to-br from-gray-50 to-gray-200">
          <X className="h-7 w-7 text-gray-400" />
        </div>
      )}
      {selected && (
        <span className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 text-white shadow">
          <Check className="h-4 w-4" />
        </span>
      )}
    </div>
    <div className="px-3 py-2.5 text-sm font-medium text-gray-700">{name}</div>
  </button>
)

export const WallpaperSettings: React.FC = () => {
  const {
    selectedWallpaper,
    customWallpaperUrl,
    loadingCustomWallpaper,
    selectWallpaper,
    uploadWallpaper,
    removeCustomWallpaper,
  } = useWallpaper()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleUpload = async (file: File | null) => {
    if (!file) return
    setSaving(true)
    setError('')
    try {
      await uploadWallpaper(file)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '壁纸保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const handleRemoveCustom = async () => {
    setSaving(true)
    setError('')
    try {
      await removeCustomWallpaper()
    } catch {
      setError('自定义壁纸删除失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="mx-auto max-w-5xl rounded-xl border bg-white/95 p-5 shadow-sm backdrop-blur-sm">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Wallpaper className="h-5 w-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-800">应用壁纸</h2>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            壁纸会应用到项目列表、写作工作区与系统设置，并保存在当前浏览器中。
          </p>
        </div>
        <label
          className={`inline-flex cursor-pointer items-center justify-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 ${
            saving ? 'pointer-events-none opacity-50' : ''
          }`}
        >
          {saving ? (
            <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <ImagePlus className="mr-2 h-4 w-4" />
          )}
          {customWallpaperUrl ? '更换本地壁纸' : '上传本地壁纸'}
          <input
            className="hidden"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            disabled={saving}
            onChange={(event) => {
              void handleUpload(event.currentTarget.files?.[0] || null)
              event.currentTarget.value = ''
            }}
          />
        </label>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <WallpaperOption
          id="none"
          name="无壁纸"
          imageUrl={null}
          selected={selectedWallpaper === 'none'}
          onSelect={selectWallpaper}
        />
        {BUILT_IN_WALLPAPERS.map((wallpaper) => (
          <WallpaperOption
            key={wallpaper.id}
            id={wallpaper.id}
            name={wallpaper.name}
            imageUrl={wallpaper.url}
            selected={selectedWallpaper === wallpaper.id}
            onSelect={selectWallpaper}
          />
        ))}
        {(customWallpaperUrl || loadingCustomWallpaper) && (
          <WallpaperOption
            id="custom"
            name={loadingCustomWallpaper ? '正在读取本地壁纸…' : '我的壁纸'}
            imageUrl={customWallpaperUrl}
            selected={selectedWallpaper === 'custom'}
            disabled={loadingCustomWallpaper}
            onSelect={selectWallpaper}
          />
        )}
      </div>

      {customWallpaperUrl && (
        <div className="mt-5 flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50/80 px-4 py-3">
          <p className="text-sm text-gray-600">自定义壁纸仅保存在这台设备的当前浏览器中。</p>
          <Button
            variant="ghost"
            size="sm"
            disabled={saving}
            onClick={() => void handleRemoveCustom()}
            className="text-red-600 hover:bg-red-50"
          >
            <Trash2 className="mr-1 h-4 w-4" /> 删除自定义壁纸
          </Button>
        </div>
      )}
    </section>
  )
}
