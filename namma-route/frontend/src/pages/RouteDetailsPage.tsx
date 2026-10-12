import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Loader2, AlertCircle, RefreshCw } from 'lucide-react';
import { useRouteDetails } from '../hooks/useRoutes';
import RouteDetails from '../components/RouteDetails';
import MapView from '../components/MapView';
import { Vehicle } from '../types/vehicle';

export const RouteDetailsPage: React.FC = () => {
  const { routeId } = useParams<{ routeId: string }>();
  const navigate = useNavigate();
  const { data: route, isLoading, error, refetch } = useRouteDetails(routeId || null);
  const [selectedDirection, setSelectedDirection] = useState<number>(0);
  const [selectedVehicleId, setSelectedVehicleId] = useState<string | null>(null);
  const [isSlowLoading, setIsSlowLoading] = useState(false);

  // Derive selected vehicle from latest live buses
  const selectedVehicle = React.useMemo(() => {
    if (!selectedVehicleId || !route?.liveBuses) return null;
    return route.liveBuses.find((b) => b.id === selectedVehicleId) ?? null;
  }, [route?.liveBuses, selectedVehicleId]);

  // Synchronize direction when selected bus has an assigned direction
  useEffect(() => {
    if (
      selectedVehicle &&
      typeof selectedVehicle.direction === 'number' &&
      selectedVehicle.direction !== selectedDirection
    ) {
      setSelectedDirection(selectedVehicle.direction);
    }
  }, [selectedVehicle?.id, selectedVehicle?.direction]);

  const handleSelectVehicle = (vehicle: Vehicle) => {
    setSelectedVehicleId(vehicle.id);
    if (typeof vehicle.direction === 'number' && vehicle.direction !== selectedDirection) {
      setSelectedDirection(vehicle.direction);
    }
  };

  useEffect(() => {
    let timer: any;
    if (isLoading) {
      timer = setTimeout(() => {
        setIsSlowLoading(true);
      }, 6000);
    } else {
      setIsSlowLoading(false);
    }
    return () => clearTimeout(timer);
  }, [isLoading]);

  // Get geometry for active direction if route is loaded
  const activeDirObj = route?.directions?.find((d) => d.direction === selectedDirection);
  const activeGeometry = activeDirObj?.geometry || route?.geometry || null;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-2 text-xs font-bold text-slate-600 hover:text-slate-900 mb-4 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Back to Routes</span>
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Side: Route Details, Stops, Timetable or Skeleton / Error */}
        <div className="lg:col-span-5">
          {error && !route ? (
            <div className="bg-white rounded-3xl p-6 border border-slate-200 shadow-sm text-center space-y-4">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-rose-50 border border-rose-100 flex items-center justify-center text-rose-500">
                <AlertCircle className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-bold text-slate-900">Route Information Unavailable</h3>
                <p className="text-xs text-slate-500 max-w-sm mx-auto">
                  Unable to find route information for "{routeId}". The service or network may be temporarily slow.
                </p>
              </div>
              <div className="flex items-center justify-center gap-2 pt-2">
                <button
                  onClick={() => refetch()}
                  className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition-all flex items-center gap-1.5"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Retry</span>
                </button>
                <button
                  onClick={() => navigate('/routes')}
                  className="px-4 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition-all"
                >
                  <span>Browse All Routes</span>
                </button>
              </div>
            </div>
          ) : isLoading && !route ? (
            <div className="bg-white rounded-3xl p-6 border border-slate-200 shadow-sm space-y-5">
              <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-7 bg-slate-200 rounded-lg animate-pulse" />
                  <div className="space-y-1.5">
                    <div className="w-32 h-4 bg-slate-200 rounded animate-pulse" />
                    <div className="w-48 h-3 bg-slate-100 rounded animate-pulse" />
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2.5 p-3 rounded-2xl bg-slate-50 border border-slate-100 text-xs text-slate-600">
                <Loader2 className="w-4 h-4 text-emerald-600 animate-spin shrink-0" />
                <span className="font-medium text-[11px]">
                  {isSlowLoading
                    ? 'BMTC live data is taking longer than usual. Retrieving corridor telemetry...'
                    : `Loading live buses for ${routeId}...`}
                </span>
              </div>

              <div className="space-y-2 pt-2">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                  Scheduled Stops
                </span>
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="flex items-center gap-3 py-2 border-b border-slate-50">
                    <div className="w-5 h-5 rounded-full bg-slate-100 animate-pulse shrink-0" />
                    <div className="w-3/4 h-3.5 bg-slate-100 rounded animate-pulse" />
                  </div>
                ))}
              </div>
            </div>
          ) : route ? (
            <RouteDetails
              route={route}
              selectedDirection={selectedDirection}
              onDirectionChange={(dir) => setSelectedDirection(dir)}
              onSelectStop={(stop) => navigate(`/stops/${stop.id}`)}
              selectedVehicleId={selectedVehicleId}
              onSelectVehicleId={(id) => setSelectedVehicleId(id)}
            />
          ) : null}
        </div>

        {/* Right Side: Route Map */}
        <div className="relative lg:col-span-7 h-[500px] lg:h-[650px] rounded-3xl overflow-hidden shadow-lg border border-slate-200">
          {isLoading && !route && (
            <div className="absolute top-4 left-4 z-20 pointer-events-none">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900/90 backdrop-blur-md text-white border border-slate-700 text-xs font-medium shadow-lg">
                <Loader2 className="w-3.5 h-3.5 text-emerald-400 animate-spin" />
                <span>Loading corridor & live buses…</span>
              </div>
            </div>
          )}

          <MapView
            vehicles={route?.liveBuses || []}
            selectedVehicle={selectedVehicle}
            onSelectVehicle={handleSelectVehicle}
            selectedRouteNumber={route?.routeNumber || routeId}
            routeGeometry={activeGeometry}
            routeStops={(route?.stops as any) || null}
          />
        </div>
      </div>
    </div>
  );
};

export default RouteDetailsPage;
