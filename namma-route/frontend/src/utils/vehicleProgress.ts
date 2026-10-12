import { Vehicle, VehicleStopInfo, StopStatus, VehicleStatus } from '../types/vehicle';
import { RouteStop } from '../types/route';

export interface SelectedVehicleProgress {
  vehicleId: string;
  vehicleNumber: string | null;
  routeNumber: string | null;
  direction: number;
  origin: string | null;
  destination: string | null;
  currentStop: VehicleStopInfo | null;
  currentStopSequence: number | null;
  nextStop: VehicleStopInfo | null;
  nextStopSequence: number | null;
  completedStops: number;
  remainingStops: number;
  totalStops: number;
  progressPercentage: number;
  status: VehicleStatus;
  stopStatus: StopStatus;
  distanceToNextStop: number | null;
  speed: number | null;
  bearing: number | null;
  freshnessSeconds: number;
}

/**
 * Derive unified progress object from a Vehicle and optional direction-specific RouteStops list
 */
export function deriveVehicleProgress(
  vehicle: Vehicle | null | undefined,
  stops?: RouteStop[] | null
): SelectedVehicleProgress | null {
  if (!vehicle) return null;

  const direction = typeof vehicle.direction === 'number' ? vehicle.direction : 0;
  const currentStop = vehicle.currentStop || null;
  const nextStop = vehicle.nextStop || null;
  const currentStopSequence = currentStop?.sequence ?? vehicle.currentStopSequence ?? null;
  const nextStopSequence = nextStop?.sequence ?? vehicle.nextStopSequence ?? null;
  const stopStatus: StopStatus = vehicle.stopStatus || 'UNKNOWN';

  // Calculate stops using provided stops list if available, otherwise vehicle metrics
  const totalStops = stops && stops.length > 0 ? stops.length : vehicle.totalStops || 0;

  let completedStops = vehicle.completedStops ?? 0;
  let remainingStops = vehicle.remainingStops ?? Math.max(0, totalStops - completedStops);

  if (stops && stops.length > 0) {
    if (currentStop) {
      const idx = stops.findIndex(
        (s) => s.id === currentStop.stopId || s.sequence === currentStop.sequence
      );
      const effectiveIdx = idx >= 0 ? idx : Math.max(0, currentStop.sequence - 1);
      completedStops = effectiveIdx;
      remainingStops = Math.max(0, totalStops - (completedStops + 1));
    } else if (nextStop) {
      const idx = stops.findIndex(
        (s) => s.id === nextStop.stopId || s.sequence === nextStop.sequence
      );
      const effectiveIdx = idx >= 0 ? idx : Math.max(0, nextStop.sequence - 1);
      completedStops = effectiveIdx;
      remainingStops = Math.max(0, totalStops - completedStops);
    }
  }

  const progressPercentage =
    totalStops > 1
      ? Math.min(100, Math.max(0, Math.round((completedStops / (totalStops - 1)) * 100)))
      : completedStops > 0
      ? 100
      : 0;

  const distanceToNextStop = nextStop?.distanceMeters ?? null;

  return {
    vehicleId: vehicle.id,
    vehicleNumber: vehicle.vehicleNumber,
    routeNumber: vehicle.routeNumber,
    direction,
    origin: vehicle.origin || null,
    destination: vehicle.destination || null,
    currentStop,
    currentStopSequence,
    nextStop,
    nextStopSequence,
    completedStops,
    remainingStops,
    totalStops,
    progressPercentage,
    status: vehicle.status || 'LIVE',
    stopStatus,
    distanceToNextStop,
    speed: vehicle.speed ?? null,
    bearing: vehicle.bearing ?? null,
    freshnessSeconds: vehicle.freshnessSeconds ?? 0,
  };
}
