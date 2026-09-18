export type JsonSseHandler = (
  payload: Record<string, unknown>
) => void | Promise<void>

const parseEventBlock = (block: string): Record<string, unknown> | null => {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
    .join('\n')

  if (!data || data === '{}' || data === '[DONE]') return null

  const parsed: unknown = JSON.parse(data)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('对话创作返回了无法识别的流式事件')
  }
  return parsed as Record<string, unknown>
}

export const readJsonSse = async (
  response: Response,
  onEvent: JsonSseHandler
): Promise<void> => {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('对话创作响应不可读取')

  const decoder = new TextDecoder()
  let buffer = ''

  const drain = async (flush = false) => {
    while (true) {
      const separator = buffer.match(/\r?\n\r?\n/)
      if (!separator || separator.index === undefined) break
      const block = buffer.slice(0, separator.index)
      buffer = buffer.slice(separator.index + separator[0].length)
      const payload = parseEventBlock(block)
      if (payload) await onEvent(payload)
    }

    if (flush && buffer.trim()) {
      const payload = parseEventBlock(buffer)
      buffer = ''
      if (payload) await onEvent(payload)
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      await drain()
    }
    buffer += decoder.decode()
    await drain(true)
  } catch (error) {
    await reader.cancel().catch(() => undefined)
    throw error
  } finally {
    reader.releaseLock()
  }
}
