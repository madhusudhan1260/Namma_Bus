import React from 'react';
import { Bus, Navigation, Gauge, Clock, MapPin, Eye } from 'lucide-react';
import { Vehicle } from '../types/vehicle';
import { formatBearingDirection, formatBusNumber } from '../utils/formatVehicle';
import { formatFreshness } from '../utils/formatTime';
import { deriveVehicleProgress } from '../utils/vehicleProgress';

interface VehicleDetailsProps {
  vehicle: Vehicle;
  onTrackOnMap?: () => void;
  onSelectRoute?: (routeNumber: string) => void;
}

export const VehicleDetails: React.FC<VehicleDetailsProps> = ({
  vehicle,
  onTrackOnMap,
  onSelectRoute,
}) => {
  const isLive = vehicle.status === 'LIVE';
  const isRecent = vehicle.status === 'RECENT';
  const progress = deriveVehicleProgress(vehicle);

  let statusBadge = (
    <span className="px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-slate-700/50 text-slate-300 border border-slate-600">
      ● STALE DATA
    </span>
  );
  if (isLive) {
    statusBadge = (
      <span className="px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
        ● LIVE BUS
      </span>
    );
  } else if (isRecent) {
    statusBadge = (
      <span className="px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-amber-500/20 text-amber-300 border border-amber-500/30">
        ● RECENT DATA
      </span>
    );
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden text-slate-800">
      {/* Header */}
      <div className="p-5 bg-gradient-to-br from-slate-900 via-slate-850 to-slate-900 text-white">
        <div className="flex items-center justify-between mb-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-xl bg-emerald-500 text-slate-950 font-black text-lg shadow-md">
            <span>ROUTE {vehicle.routeNumber || 'BMTC'}</span>
          </div>

          {statusBadge}
        </div>

        <h2 className="text-xl font-black text-white font-mono">
          {formatBusNumber(vehicle.vehicleNumber)}
        </h2>
        {progress?.destination && (
          <p className="text-xs text-slate-300 mt-1">
            Direction {progress.direction}: Towards <strong className="text-emerald-400">{progress.destination}</strong>
          </p>
        )}

        {onTrackOnMap && (
          <button
            onClick={onTrackOnMap}
            className="mt-4 w-full py-2 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs flex items-center justify-center gap-2 transition-colors shadow-md shadow-emerald-500/20"
          >
            <Eye className="w-4 h-4" />
            <span>Center Bus on Live Map</span>
          </button>
        )}
      </div>

      {/* Stop Progress Card */}
      {progress && progress.totalStops > 0 && (
        <div className="p-4 bg-emerald-50/60 border-b border-emerald-100/80 space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-800">
            <span className="text-emerald-900">Corridor Progression</span>
            <span className="text-emerald-700 font-extrabold">{progress.progressPercentage}%</span>
          </div>

          <div className="w-full bg-slate-200/80 h-2 rounded-full overflow-hidden">
            <div
              className="bg-emerald-600 h-full rounded-full transition-all duration-500"
              style={{ width: `${progress.progressPercentage}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-600 font-medium">
            <span className="font-bold text-emerald-800">{progress.completedStops} stops completed</span>
            <span className="text-slate-500 font-semibold">{progress.remainingStops} stops remaining</span>
          </div>
        </div>
      )}

      {/* Telemetry Metrics Grid */}
      <div className="p-4 grid grid-cols-3 gap-2 border-b border-slate-100 bg-slate-50">
        <div className="p-3 bg-white rounded-xl border border-slate-200 text-center">
          <div className="flex items-center justify-center text-slate-400 mb-1">
            <Gauge className="w-4 h-4" />
          </div>
          <span className="text-xs font-bold text-slate-900 block truncate">
            {vehicle.speed !== null && vehicle.speed !== undefined && !isNaN(vehicle.speed)
              ? `${Math.round(vehicle.speed)} km/h`
              : 'Unavailable'}
          </span>
          <span className="text-[10px] text-slate-400 font-semibold uppercase">Speed</span>
        </div>

        <div className="p-3 bg-white rounded-xl border border-slate-200 text-center">
          <div className="flex items-center justify-center text-slate-400 mb-1">
            <Navigation className="w-4 h-4" />
          </div>
          <span className="text-xs font-bold text-slate-900 block">
            {formatBearingDirection(vehicle.bearing)} ({vehicle.bearing || 0}°)
          </span>
          <span className="text-[10px] text-slate-400 font-semibold uppercase">Heading</span>
        </div>

        <div className="p-3 bg-white rounded-xl border border-slate-200 text-center">
          <div className="flex items-center justify-center text-slate-400 mb-1">
            <Clock className="w-4 h-4" />
          </div>
          <span className="text-xs font-bold text-slate-900 block">
            {formatFreshness(vehicle.freshnessSeconds)}
          </span>
          <span className="text-[10px] text-slate-400 font-semibold uppercase">Updated</span>
        </div>
      </div>

      {/* Route & Stop Information */}
      <div className="p-4 space-y-3">
        <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
            {progress?.stopStatus === 'AT_STOP'
              ? 'Current Stop'
              : progress?.stopStatus === 'APPROACHING_STOP'
              ? 'Approaching Stop'
              : 'Next En-Route Stop'}
          </span>
          <div className="flex items-center gap-2">
            <MapPin className="w-4 h-4 text-emerald-600 shrink-0" />
            <div className="truncate">
              <span className="text-sm font-bold text-slate-900 block truncate">
                {progress?.currentStop?.stopName ||
                  progress?.nextStop?.stopName ||
                  vehicle.nextStopId ||
                  'In Transit on Corridor'}
              </span>
              {progress?.nextStop?.distanceMeters && progress.stopStatus !== 'AT_STOP' && (
                <span className="text-[11px] text-slate-500 font-medium">
                  ~{progress.nextStop.distanceMeters}m away
                </span>
              )}
            </div>
          </div>
        </div>

        {vehicle.routeNumber && onSelectRoute && (
          <button
            onClick={() => onSelectRoute(vehicle.routeNumber!)}
            className="w-full py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-xl text-xs font-bold transition-colors"
          >
            View Route {vehicle.routeNumber} Full Timetable & Stops
          </button>
        )}
      </div>
    </div>
  );
};

export default VehicleDetails;
