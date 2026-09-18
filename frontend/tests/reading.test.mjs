import test from 'node:test'
import assert from 'node:assert/strict'
import { anchorHighlight, paintHighlight, rebaseHighlights, resolveHighlights } from '../src/features/reading/highlights.ts'

test('highlights remain separate from manuscript content and can span paragraphs', () => {
  const text = '雨夜来信。\n\n她推开了门。'
  const marks = paintHighlight(text, [], 2, 12, 'yellow')
  assert.equal(marks[0].text, '来信。\n\n她推开了门')
  assert.equal(text, '雨夜来信。\n\n她推开了门。')
  assert.deepEqual(resolveHighlights(text, JSON.parse(JSON.stringify(marks))), marks)
})
test('painting over a mark changes only the selected color and keeps both sides', () => {
  const text = 'abcdefghij'
  const marks = paintHighlight(text, [anchorHighlight(text, 0, 10, 'yellow')], 3, 7, 'pink')
  assert.deepEqual(marks.map((mark) => [mark.start, mark.end, mark.color]), [[0, 3, 'yellow'], [3, 7, 'pink'], [7, 10, 'yellow']])
  assert.equal(new Set(marks.map((mark) => mark.id)).size, 3)
})
test('clearing a selection splits a highlight; collapsed selection is a no-op', () => {
  const text = 'abcdefghij'
  const marks = [anchorHighlight(text, 0, 10, 'green')]
  assert.deepEqual(paintHighlight(text, marks, 2, 8, null).map((mark) => mark.text), ['ab', 'ij'])
  assert.deepEqual(paintHighlight(text, marks, 5, 5, null), marks)
})
test('insertion before a mark shifts offsets and insertion inside inherits color', () => {
  const original = '她推开门。'
  const marks = [anchorHighlight(original, 1, 4, 'yellow')]
  const shifted = rebaseHighlights(original, `忽然，${original}`, marks)
  assert.deepEqual([shifted[0].start, shifted[0].end, shifted[0].text], [4, 7, '推开门'])
  const expanded = rebaseHighlights(original, '她推开木门。', marks)
  assert.equal(expanded[0].text, '推开木门')
})
test('deleting a marked passage removes its mark without coloring neighboring text', () => {
  const text = 'before MARK after'
  const marks = [anchorHighlight(text, 7, 11, 'blue')]
  assert.deepEqual(rebaseHighlights(text, 'before  after', marks), [])
  assert.deepEqual(rebaseHighlights(text, '', marks), [])
})
test('edits at a boundary do not expand a mark into adjacent unselected text', () => {
  const text = 'abcDEFghi'
  const marks = [anchorHighlight(text, 3, 6, 'blue')]
  assert.equal(rebaseHighlights(text, 'abcXDEFghi', marks)[0].text, 'DEF')
  assert.equal(rebaseHighlights(text, 'abcDEFXghi', marks)[0].text, 'DEF')
})
test('context distinguishes repeated quotes after external insertions', () => {
  const text = '第一段：相同的句子。\n第二段：相同的句子。'
  const start = text.lastIndexOf('相同')
  const mark = anchorHighlight(text, start, start + 5, 'green')
  const next = '新增前言。\n' + text
  assert.equal(resolveHighlights(next, [mark])[0].start, next.lastIndexOf('相同'))
})
test('quotes resolve between HTML storage and visible reading text without rendering HTML', () => {
  const html = '<p>雨落城门。</p><p>她推开了门。</p>'
  const start = html.indexOf('她推开')
  const mark = anchorHighlight(html, start, start + 5, 'pink')
  const text = '雨落城门。\n\n她推开了门。'
  assert.equal(resolveHighlights(text, [mark])[0].start, text.indexOf('她推开'))
  assert.deepEqual(resolveHighlights('完全改写的新章节', [mark]), [])
})
test('emoji offsets match textarea UTF-16 positions and context never cuts surrogate pairs', () => {
  const text = '🌙' + '前'.repeat(23) + '正文' + '后'.repeat(23) + '🌙'
  const start = text.indexOf('正文')
  const mark = anchorHighlight(text, start, start + 2, 'yellow')
  assert.equal(Array.from(mark.prefix).length, 24)
  assert.ok(mark.prefix.startsWith('🌙'))
  assert.ok(mark.suffix.endsWith('🌙'))
  const next = '🚀' + text
  assert.equal(rebaseHighlights(text, next, [mark])[0].start, start + 2)
})
