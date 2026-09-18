import React from 'react'
import { ALargeSmall, Minus, Plus, RotateCcw, Type } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import {
  DEFAULT_FONT_FAMILY,
  DEFAULT_FONT_SIZE,
  FONT_FAMILIES,
  MAX_FONT_SIZE,
  MIN_FONT_SIZE,
} from '@/features/typography/typographyCatalog'
import type { FontFamilyId } from '@/features/typography/typographyCatalog'
import { useTypography } from '@/features/typography/typographyContext'

export const TypographySettings: React.FC = () => {
  const {
    fontFamily,
    fontSize,
    setFontFamily,
    setFontSize,
    resetTypography,
  } = useTypography()
  const selectedFont =
    FONT_FAMILIES.find((font) => font.id === fontFamily) || FONT_FAMILIES[0]
  const isDefault =
    fontFamily === DEFAULT_FONT_FAMILY && fontSize === DEFAULT_FONT_SIZE

  return (
    <section className="mx-auto max-w-5xl rounded-xl border bg-white/95 p-5 shadow-sm backdrop-blur-sm">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Type className="h-5 w-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-800">字体与字号</h2>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            字体会应用到整个应用，字号仅缩放文字，不改变侧栏、按钮和图标尺寸。
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={isDefault}
          onClick={resetTypography}
        >
          <RotateCcw className="mr-1 h-4 w-4" /> 恢复默认
        </Button>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <div>
          <label
            htmlFor="appearance-font-family"
            className="mb-2 block text-sm font-medium text-gray-700"
          >
            字体类型
          </label>
          <select
            id="appearance-font-family"
            value={fontFamily}
            onChange={(event) => setFontFamily(event.target.value as FontFamilyId)}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {FONT_FAMILIES.map((font) => (
              <option key={font.id} value={font.id}>
                {font.name} · {font.description}
              </option>
            ))}
          </select>
          <p className="mt-2 text-xs text-gray-500">{selectedFont.description}</p>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <label
              htmlFor="appearance-font-size"
              className="text-sm font-medium text-gray-700"
            >
              字体大小
            </label>
            <output
              htmlFor="appearance-font-size"
              className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700"
            >
              {fontSize}px
            </output>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="icon"
              aria-label="减小字体"
              disabled={fontSize <= MIN_FONT_SIZE}
              onClick={() => setFontSize(fontSize - 1)}
              className="h-9 w-9 flex-shrink-0 p-0"
            >
              <Minus className="h-4 w-4" />
            </Button>
            <input
              id="appearance-font-size"
              type="range"
              min={MIN_FONT_SIZE}
              max={MAX_FONT_SIZE}
              step={1}
              value={fontSize}
              aria-valuetext={`${fontSize} 像素`}
              onChange={(event) => setFontSize(Number(event.target.value))}
              className="h-2 min-w-0 flex-1 cursor-pointer accent-blue-600"
            />
            <Button
              variant="outline"
              size="icon"
              aria-label="增大字体"
              disabled={fontSize >= MAX_FONT_SIZE}
              onClick={() => setFontSize(fontSize + 1)}
              className="h-9 w-9 flex-shrink-0 p-0"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <div className="mt-2 flex justify-between text-xs text-gray-400">
            <span>{MIN_FONT_SIZE}px</span>
            <span>{MAX_FONT_SIZE}px</span>
          </div>
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-blue-100 bg-blue-50/70 p-4">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-blue-700">
          <ALargeSmall className="h-4 w-4" /> 实时预览
        </div>
        <p
          className="leading-relaxed text-gray-800"
          style={{ fontFamily: selectedFont.cssStack, fontSize: `${fontSize}px` }}
        >
          故事始于一个安静的清晨，风从书页间轻轻穿过。
        </p>
      </div>
    </section>
  )
}
