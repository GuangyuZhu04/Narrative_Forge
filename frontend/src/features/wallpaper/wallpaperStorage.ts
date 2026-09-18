const DATABASE_NAME = 'nwa_appearance'
const DATABASE_VERSION = 1
const STORE_NAME = 'wallpapers'
const CUSTOM_WALLPAPER_KEY = 'custom'

const openDatabase = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION)

    request.onupgradeneeded = () => {
      const database = request.result
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME)
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })

export const loadCustomWallpaper = async (): Promise<Blob | null> => {
  const database = await openDatabase()
  try {
    return await new Promise<Blob | null>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, 'readonly')
      const request = transaction.objectStore(STORE_NAME).get(CUSTOM_WALLPAPER_KEY)
      request.onsuccess = () => {
        resolve(request.result instanceof Blob ? request.result : null)
      }
      request.onerror = () => reject(request.error)
    })
  } finally {
    database.close()
  }
}

export const saveCustomWallpaper = async (image: Blob): Promise<void> => {
  const database = await openDatabase()
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, 'readwrite')
      transaction.objectStore(STORE_NAME).put(image, CUSTOM_WALLPAPER_KEY)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.onabort = () => reject(transaction.error)
    })
  } finally {
    database.close()
  }
}

export const deleteCustomWallpaper = async (): Promise<void> => {
  const database = await openDatabase()
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, 'readwrite')
      transaction.objectStore(STORE_NAME).delete(CUSTOM_WALLPAPER_KEY)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.onabort = () => reject(transaction.error)
    })
  } finally {
    database.close()
  }
}
