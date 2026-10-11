/**
 * Local storage abstraction for NammaBlr.
 * Resiliently supports Web localStorage and React Native in-memory cache without external package dependencies.
 */

class StorageService {
  private memoryCache: Map<string, string> = new Map();

  private isLocalStorageAvailable(): boolean {
    try {
      return typeof globalThis !== 'undefined' && 'localStorage' in globalThis && globalThis.localStorage !== null;
    } catch {
      return false;
    }
  }

  async getItem<T>(key: string, defaultValue: T): Promise<T> {
    try {
      if (this.isLocalStorageAvailable()) {
        const raw = globalThis.localStorage.getItem(key);
        if (raw !== null) {
          return JSON.parse(raw) as T;
        }
      }
      const mem = this.memoryCache.get(key);
      if (mem !== undefined) {
        return JSON.parse(mem) as T;
      }
    } catch (e) {
      console.warn(`[StorageService] Failed to read key: ${key}`, e);
    }
    return defaultValue;
  }

  async setItem<T>(key: string, value: T): Promise<void> {
    try {
      const serialized = JSON.stringify(value);
      this.memoryCache.set(key, serialized);
      if (this.isLocalStorageAvailable()) {
        globalThis.localStorage.setItem(key, serialized);
      }
    } catch (e) {
      console.warn(`[StorageService] Failed to write key: ${key}`, e);
    }
  }

  async removeItem(key: string): Promise<void> {
    try {
      this.memoryCache.delete(key);
      if (this.isLocalStorageAvailable()) {
        globalThis.localStorage.removeItem(key);
      }
    } catch (e) {
      console.warn(`[StorageService] Failed to delete key: ${key}`, e);
    }
  }

  async clear(): Promise<void> {
    this.memoryCache.clear();
    try {
      if (this.isLocalStorageAvailable()) {
        globalThis.localStorage.clear();
      }
    } catch {}
  }
}

export const Storage = new StorageService();

export const STORAGE_KEYS = {
  SAVED_JOURNEYS: 'nammablr_saved_journeys',
  FAVORITE_ROUTES: 'nammablr_favorite_routes',
  ARRIVAL_REMINDERS: 'nammablr_arrival_reminders',
  PREFERENCES: 'nammablr_preferences',
  NOTIFICATIONS: 'nammablr_notifications',
  ACTIVE_JOURNEY: 'nammablr_active_journey',
  JOURNEY_HISTORY: 'nammablr_journey_history',
};
