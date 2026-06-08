const P = 'nwa_'

export const storage = {
  get: <T>(key: string): T | null => {
    const r = localStorage.getItem(P + key)
    return r ? JSON.parse(r) : null
  },
  set: (key: string, value: unknown) =>
    localStorage.setItem(P + key, JSON.stringify(value)),
  remove: (key: string) => localStorage.removeItem(P + key),
}
