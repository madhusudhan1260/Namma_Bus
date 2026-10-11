/**
 * BMTC network API (ನಮ್ಮ Bus backend → NammaRoute PostgreSQL network).
 * No offline fallbacks: routes, stops and buses are never invented on the device.
 */
import { API_BASE_URL } from './api';
import {
  NetworkJourneyPlan,
  NetworkRouteDetail,
  NetworkRouteSummary,
  NetworkStatus,
  NetworkStop,
  NetworkVehiclesResponse,
} from '../types/network';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const b = await res.json();
      if (typeof b?.detail === 'string') detail = b.detail;
    } catch {
      // keep status
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export interface AssistantReply {
  answer: string;
  kind: 'answer' | 'help' | 'not_found' | 'unavailable';
  actions: { label: string; href: string }[];
  source: string;
}
export type FacilityCategory = 'TOILETS' | 'MEDICAL' | 'ATM' | 'WATER' | 'PARKING' | 'POLICE' | 'HOSPITAL' | 'FOOD';
export interface Facility {
  id: string;
  category: FacilityCategory;
  name: string | null;
  latitude: number;
  longitude: number;
  phone?: string | null;
  opening_hours?: string | null;
  distance_m: number;
}
export interface FacilitiesResponse {
  available: boolean;
  source: string;
  message?: string;
  radius_m?: number;
  stations: { name: string; latitude: number; longitude: number; facilities: Facility[]; counts: Partial<Record<FacilityCategory, number>> }[];
}
let vehiclesInFlight: Promise<NetworkVehiclesResponse> | null = null;

export const NetworkApi = {
  status: () => get<NetworkStatus>('/network/status'),
  searchRoutes: (q: string, limit = 30) =>
    get<{ total: number; routes: NetworkRouteSummary[] }>(`/network/routes?q=${enc(q)}&limit=${limit}`),
  search: (q: string) =>
    get<{ routes: NetworkRouteSummary[]; routes_total: number; stops: NetworkStop[] }>(`/network/search?q=${enc(q)}`),
  route: (route: string) => get<{ route: NetworkRouteDetail }>(`/network/routes/${enc(route)}`).then(r => r.route),
  routeStops: (route: string, direction: number) =>
    get<{ stops: NetworkStop[] }>(`/network/routes/${enc(route)}/stops?direction=${direction}`).then(r => r.stops),
  journey: (from: string, to: string) =>
    get<{ count: number; plans: NetworkJourneyPlan[] }>(`/network/journey?from=${enc(from)}&to=${enc(to)}`),
  facilities: () => get<FacilitiesResponse>('/network/facilities'),
  facilitiesNear: (lat: number, lng: number, radius = 2000, types = '') =>
    get<{ available: boolean; source: string; message?: string; places: Facility[] }>(
      `/network/facilities/near?lat=${lat}&lng=${lng}&radius=${radius}&types=${enc(types)}`
    ),
  timetable: (route: string) =>
    get<{ source: string; route: string; directions: { direction: number; headsign: string | null; from: string | null; departures: string[] }[] }>(
      `/network/routes/${enc(route)}/timetable`
    ),
  fareEstimate: (from: string, to: string) =>
    get<{
      source: string;
      options: {
        legs: { route: string; from: string; to: string; distance_km: number | null; stage: number | null; fares: Record<string, number>; source: string }[];
        totals: Record<'ADULT' | 'CHILD' | 'SENIOR', number>;
        minutes: number | null;
        estimate: boolean;
      }[];
    }>(`/network/fare-estimate?from=${enc(from)}&to=${enc(to)}`),
  stopsNearby: (lat: number, lng: number, radius = 800, limit = 8) =>
    get<{ count: number; stops: (NetworkStop & { distance?: number; distanceMeters?: number })[] }>(
      `/network/stops/nearby?lat=${lat}&lng=${lng}&radius=${radius}&limit=${limit}`
    ),
  /** Assistant that answers only from the real BMTC network and live feed. */
  async assistant(message: string, lang: 'EN' | 'KN'): Promise<AssistantReply> {
    const res = await fetch(`${API_BASE_URL}/network/assistant`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, lang }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
  /** All buses: concurrent callers share one request. */
  vehicles(route?: string): Promise<NetworkVehiclesResponse> {
    if (route) return get<NetworkVehiclesResponse>(`/network/vehicles?route=${enc(route)}`);
    if (vehiclesInFlight) return vehiclesInFlight;
    vehiclesInFlight = get<NetworkVehiclesResponse>('/network/vehicles').finally(() => {
      vehiclesInFlight = null;
    });
    return vehiclesInFlight;
  },
};
