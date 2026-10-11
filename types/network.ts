// BMTC network (NammaRoute, PostgreSQL) types as served by ನಮ್ಮ Bus /api/network/*.

export type NetworkFreshness = 'LIVE' | 'RECENT' | 'STALE';

export interface NetworkRouteSummary {
  id: string;
  routeNumber: string;
  routeName?: string;
  routeLongName?: string;
  serviceType?: string;
  origin?: string | null;
  destination?: string | null;
  activeBusesCount?: number;
}

export interface NetworkStop {
  id: string;
  stopId: string;
  name: string;
  nameKannada?: string | null;
  latitude: number;
  longitude: number;
  sequence?: number;
}

export interface NetworkDirection {
  direction: number;
  directionName?: string;
  originName?: string;
  destinationName?: string;
  stopCount?: number;
  geometry?: [number, number][];
}

export interface NetworkRouteDetail extends NetworkRouteSummary {
  routeFamily?: string;
  stops: NetworkStop[];
  directions: NetworkDirection[];
  geometry?: [number, number][];
}

export interface NetworkStopRef {
  stop_id?: string | null;
  stop_name?: string | null;
  sequence?: number | null;
  distance_meters?: number | null;
}

export interface NetworkVehicle {
  vehicle_id: string;
  vehicle_number: string | null;
  route_id: string | null;
  route_number: string | null;
  latitude: number;
  longitude: number;
  bearing: number | null;
  speed_kmh: number | null;
  timestamp: string | null;
  freshness: NetworkFreshness;
  freshness_seconds: number | null;
  source: string;
  direction: number | null;
  origin: string | null;
  destination: string | null;
  stop_status: string | null;
  current_stop: NetworkStopRef | null;
  next_stop: NetworkStopRef | null;
  total_stops: number | null;
  completed_stops: number | null;
  remaining_stops: number | null;
  progress_percentage: number | null;
}

export interface NetworkVehiclesResponse {
  realtime_status: string;
  live_connected: boolean;
  operational_statement: string | null;
  error: string | null;
  count: number;
  counts_by_freshness: Record<NetworkFreshness, number>;
  excluded: number;
  generated_at: string;
  vehicles: NetworkVehicle[];
}

export interface NetworkStatus {
  network_connected: boolean;
  routes?: number;
  stops?: number;
  live_connected: boolean;
  realtime_error?: string | null;
  operational_statement?: string | null;
  message?: string;
}

export interface NetworkJourneyLeg {
  routeId: string;
  routeNumber: string;
  routeName?: string;
  fromStop: { id: string; name: string };
  toStop: { id: string; name: string };
  stopCount: number;
  durationMinutes: number;
  distanceKm: number;
  geometry?: [number, number][];
}

export interface NetworkJourneyPlan {
  id: string;
  type: 'DIRECT' | 'TRANSFER' | string;
  totalDurationMinutes: number;
  totalDistanceKm: number;
  transferCount: number;
  legs: NetworkJourneyLeg[];
}
