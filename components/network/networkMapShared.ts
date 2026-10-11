import { NetworkFreshness, NetworkStop, NetworkVehicle } from '../../types/network';

export interface NetworkMapProps {
  vehicles: NetworkVehicle[];
  selectedVehicleId: string | null;
  onSelectVehicle?: (id: string) => void;
  routeLines?: { coords: [number, number][]; color?: string }[];
  stops?: NetworkStop[];
  onSelectStop?: (stop: NetworkStop) => void;
  focus?: { latitude: number; longitude: number } | null;
  /** Draw stops as bus-stand pins (nearby-stands mode) instead of small route dots */
  stopVariant?: 'dot' | 'stand';
  selectedStopId?: string | null;
  /** The user's position ("You are here") */
  userLocation?: { latitude: number; longitude: number } | null;
  /** Street map or satellite imagery */
  mapType?: 'standard' | 'satellite';
  /** Extra points of interest (facilities, journey start/end) */
  pois?: MapPoi[];
  onSelectPoi?: (id: string) => void;
}

export interface MapPoi {
  id: string;
  latitude: number;
  longitude: number;
  label: string;
  emoji: string;
  color: string;
}

/** Marker colour by freshness (the text label always states the freshness too). */
export function freshnessColor(f: NetworkFreshness): string {
  return f === 'LIVE' ? '#168A45' : f === 'RECENT' ? '#C47A00' : '#8A959F';
}
