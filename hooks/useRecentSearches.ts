import { useCallback, useEffect, useState } from 'react';
import { Storage } from '../services/storage';

/** Recent searches kept on this device only (per feature), newest first, de-duplicated, max `limit`. */
export function useRecentSearches<T extends { key: string }>(name: string, limit = 6) {
  const storageKey = `namma_recent_${name}_v1`;
  const [items, setItems] = useState<T[]>([]);
  useEffect(() => {
    Storage.getItem<T[]>(storageKey, []).then(setItems).catch(() => setItems([]));
  }, [storageKey]);
  const add = useCallback(
    (item: T) => {
      setItems(prev => {
        const next = [item, ...prev.filter(p => p.key !== item.key)].slice(0, limit);
        Storage.setItem(storageKey, next).catch(() => undefined);
        return next;
      });
    },
    [storageKey, limit]
  );
  const clear = useCallback(() => {
    setItems([]);
    Storage.setItem(storageKey, []).catch(() => undefined);
  }, [storageKey]);
  return { items, add, clear };
}
