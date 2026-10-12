import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Bus, Compass, Navigation, Search, Radio, X } from 'lucide-react';
import MapView from '../components/MapView';
import SearchBar from '../components/SearchBar';
import RouteDetails from '../components/RouteDetails';
import StopDetails from '../components/StopDetails';
import VehicleDetails from '../components/VehicleDetails';
import BottomSheet from '../components/BottomSheet';
import { useLiveVehicles } from '../hooks/useLiveVehicles';
import { useGeolocation } from '../hooks/useGeolocation';
import { useRouteDetails } from '../hooks/useRoutes';
import { useStopDetails } from '../hooks/useStops';
import { vehiclesApi } from '../services/vehiclesApi';
import { Vehicle } from '../types/vehicle';
import { Stop } from '../types/stop';
import { formatFreshness } from '../utils/formatTime';

export const Home: React.FC = () => {
  const navigate = useNavigate();
  const { data: realtimeData, isLoading: isRealtimeLoading, isError: isRealtimeError } = useLiveVehicles();
  const { latitude, longitude } = useGeolocation();
  const [isSlowLoading, setIsSlowLoading] = useState(false);

  useEffect(() => {
    let timer: any;
    if (isRealtimeLoading) {
      timer = setTimeout(() => {
        setIsSlowLoading(true);
      }, 6000);
    } else {
      setIsSlowLoading(false);
    }
    return () => clearTimeout(timer);
  }, [isRealtimeLoading]);

  // Selected State (single source of truth: IDs)
  const [selectedRouteNumber, setSelectedRouteNumber] = useState<string | null>(null);
  const [selectedVehicleId, setSelectedVehicleId] = useState<string | null>(null);
  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);
  const [isMobileSheetOpen, setIsMobileSheetOpen] = useState(false);

  // Queries for selected entities
  const { data: routeDetails } = useRouteDetails(selectedRouteNumber);
  const { data: stopDetails } = useStopDetails(selectedStopId);

  // Active vehicle collection based on route selection
  const activeVehicles = React.useMemo(() => {
    if (selectedRouteNumber && routeDetails?.liveBuses && routeDetails.liveBuses.length > 0) {
      return routeDetails.liveBuses;
    }
    return realtimeData?.vehicles || [];
  }, [selectedRouteNumber, routeDetails?.liveBuses, realtimeData?.vehicles]);

  // Derive selected vehicle from live collection to prevent stale snapshots
  const selectedVehicle = React.useMemo(() => {
    if (!selectedVehicleId) return null;
    return activeVehicles.find((v) => v.id === selectedVehicleId) ?? null;
  }, [activeVehicles, selectedVehicleId]);

  // Dashboard Stats Query
  const { data: stats } = useQuery({
    queryKey: ['dashboardStats'],
    queryFn: () => vehiclesApi.getStats(),
    refetchInterval: 25000,
  });

  const handleSelectRoute = (routeNumber: string) => {
    setSelectedRouteNumber(routeNumber);
    setSelectedVehicleId(null);
    setSelectedStopId(null);
    setIsMobileSheetOpen(true);
  };

  const handleSelectVehicle = (vehicle: Vehicle) => {
    setSelectedVehicleId(vehicle.id);
    setSelectedStopId(null);
    setIsMobileSheetOpen(true);
  };

  const handleSelectStop = (stop: Stop) => {
    setSelectedStopId(stop.id);
    setSelectedVehicleId(null);
    setIsMobileSheetOpen(true);
  };

  const clearSelection = () => {
    setSelectedRouteNumber(null);
    setSelectedVehicleId(null);
    setSelectedStopId(null);
    setIsMobileSheetOpen(false);
  };

  return (
    <div className="relative w-full h-[calc(100vh-4rem)] flex flex-col md:flex-row overflow-hidden bg-slate-900">
      {/* MAP VIEW CONTAINER (Full screen canvas) */}
      <div className="relative flex-1 h-full w-full">
        {/* Top Overlay Header for Search & Quick Actions */}
        <div className="absolute top-4 left-4 right-16 md:right-auto md:w-96 z-20 space-y-2">
          <SearchBar
            onSelectRoute={handleSelectRoute}
            onSelectStop={handleSelectStop}
          />

          {/* Quick Action Pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
            <button
              onClick={() => navigate('/nearby')}
              className="px-3 py-1.5 rounded-full bg-white/95 backdrop-blur-sm hover:bg-white text-slate-800 text-xs font-bold border border-slate-200/80 shadow-sm flex items-center gap-1.5 shrink-0 transition-transform active:scale-95"
            >
              <Navigation className="w-3.5 h-3.5 text-emerald-600" />
              <span>Nearby Buses</span>
            </button>
            <button
              onClick={() => navigate('/routes')}
              className="px-3 py-1.5 rounded-full bg-white/95 backdrop-blur-sm hover:bg-white text-slate-800 text-xs font-bold border border-slate-200/80 shadow-sm flex items-center gap-1.5 shrink-0 transition-transform active:scale-95"
            >
              <Compass className="w-3.5 h-3.5 text-indigo-600" />
              <span>Find a Route</span>
            </button>
            <button
              onClick={() => navigate('/journey')}
              className="px-3 py-1.5 rounded-full bg-white/95 backdrop-blur-sm hover:bg-white text-slate-800 text-xs font-bold border border-slate-200/80 shadow-sm flex items-center gap-1.5 shrink-0 transition-transform active:scale-95"
            >
              <Search className="w-3.5 h-3.5 text-blue-600" />
              <span>Plan Journey</span>
            </button>
          </div>
        </div>

        {/* Real-time Status Overlay Notification */}
        {(isRealtimeLoading || isRealtimeError) && (
          <div className="absolute top-24 left-4 right-16 md:right-auto md:w-96 z-20 pointer-events-none">
            <div className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs backdrop-blur-md border shadow-lg pointer-events-auto ${
              isRealtimeError
                ? 'bg-rose-950/90 text-rose-200 border-rose-800'
                : isSlowLoading
                ? 'bg-amber-950/90 text-amber-200 border-amber-800'
                : 'bg-slate-900/90 text-slate-200 border-slate-700'
            }`}>
              <Radio className={`w-3.5 h-3.5 shrink-0 ${
                isRealtimeError
                  ? 'text-rose-400'
                  : isSlowLoading
                  ? 'text-amber-400 animate-pulse'
                  : 'text-emerald-400 animate-pulse'
              }`} />
              <span className="font-medium text-[11px] leading-tight">
                {isRealtimeError
                  ? 'Live service temporarily unavailable. Route and stop information remain available.'
                  : isSlowLoading
                  ? 'BMTC live data is taking longer than usual. Connecting...'
                  : 'Connecting to BMTC live network…'}
              </span>
            </div>
          </div>
        )}

        {/* Dashboard Statistics Floating Bar (Bottom Left) */}
        {stats && (
          <div className="absolute bottom-4 left-4 z-20 hidden lg:flex items-center gap-4 bg-slate-900/95 backdrop-blur-md px-4 py-3 rounded-2xl border border-slate-700/80 text-white shadow-2xl text-xs">
            {/* Scheduled Network */}
            <div className="border-r border-slate-700/80 pr-4">
              <span className="text-[10px] uppercase font-bold tracking-wider text-slate-400 block mb-0.5">
                BMTC Scheduled Network
              </span>
              <div className="flex items-center gap-3">
                <div>
                  <span className="font-extrabold text-sm text-white font-mono">{stats.activeRoutes.toLocaleString()}</span>
                  <span className="text-[11px] text-slate-300 ml-1">routes</span>
                </div>
                <span className="text-slate-600">•</span>
                <div>
                  <span className="font-extrabold text-sm text-white font-mono">{stats.stops.toLocaleString()}</span>
                  <span className="text-[11px] text-slate-300 ml-1">stops</span>
                </div>
              </div>
            </div>

            {/* Live Reporting */}
            <div className="flex items-center gap-3 pr-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
              <div>
                <span className="text-[10px] uppercase font-bold tracking-wider text-emerald-400 block mb-0.5">
                  Live BMTC Telemetry
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-extrabold text-sm text-emerald-400 font-mono">
                    {stats.liveBuses}
                  </span>
                  <span className="text-[11px] text-slate-300">vehicles reporting live</span>
                  <span className="text-[10px] text-slate-500 font-mono ml-1">
                    (Updated {formatFreshness(stats.dataAgeSeconds)})
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Interactive Map View */}
        <MapView
          vehicles={activeVehicles}
          selectedVehicle={selectedVehicle}
          onSelectVehicle={handleSelectVehicle}
          selectedRouteNumber={selectedRouteNumber}
          routeGeometry={routeDetails?.geometry || null}
          routeStops={routeDetails?.stops || null}
          selectedStop={stopDetails || null}
          onSelectStop={handleSelectStop}
          userLocation={{ latitude, longitude }}
          onTrackRoute={handleSelectRoute}
        />
      </div>

      {/* DESKTOP SIDE PANEL (Right Sidebar for Details) */}
      {(selectedRouteNumber || selectedVehicleId || selectedStopId) && (
        <aside className="hidden md:flex flex-col w-96 bg-white border-l border-slate-200 z-30 shadow-xl overflow-y-auto">
          {/* Close Panel Button */}
          <div className="p-3 border-b border-slate-100 flex items-center justify-between bg-slate-50">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              {selectedVehicleId
                ? 'Bus Telemetry & Progress'
                : selectedStopId
                ? 'Stop Schedule'
                : 'Route Details'}
            </span>
            <button
              onClick={clearSelection}
              className="p-1 hover:bg-slate-200 rounded-lg text-slate-500 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-3">
            {selectedVehicleId && selectedVehicle && (
              <VehicleDetails
                vehicle={selectedVehicle}
                onSelectRoute={handleSelectRoute}
              />
            )}

            {selectedVehicleId && !selectedVehicle && (
              <div className="p-5 bg-slate-50 border border-slate-200 rounded-2xl text-center space-y-3">
                <p className="text-xs text-slate-600 font-medium">
                  Vehicle telemetry temporarily unavailable for selected bus #{selectedVehicleId}.
                </p>
                <button
                  onClick={() => setSelectedVehicleId(null)}
                  className="px-3 py-1.5 rounded-xl bg-slate-200 hover:bg-slate-300 text-slate-800 text-xs font-bold"
                >
                  Return to Network
                </button>
              </div>
            )}

            {!selectedVehicleId && selectedStopId && stopDetails && (
              <StopDetails
                stop={stopDetails}
                onSelectRoute={handleSelectRoute}
              />
            )}

            {!selectedVehicleId && !selectedStopId && routeDetails && (
              <RouteDetails
                route={routeDetails}
                onSelectStop={handleSelectStop}
                selectedVehicleId={selectedVehicleId}
                onSelectVehicleId={(id) => setSelectedVehicleId(id)}
              />
            )}
          </div>
        </aside>
      )}

      {/* MOBILE BOTTOM SHEET (Responsive for Handhelds) */}
      <BottomSheet
        isOpen={isMobileSheetOpen}
        onClose={clearSelection}
        title={
          selectedVehicle
            ? `Bus ${selectedVehicle.routeNumber || selectedVehicle.id}`
            : selectedStopId
            ? stopDetails?.name || 'Bus Stop'
            : selectedRouteNumber
            ? `Route ${selectedRouteNumber}`
            : 'Transit Details'
        }
      >
        {selectedVehicleId && selectedVehicle && (
          <VehicleDetails
            vehicle={selectedVehicle}
            onSelectRoute={handleSelectRoute}
          />
        )}

        {selectedVehicleId && !selectedVehicle && (
          <div className="p-4 text-center text-xs text-slate-600">
            Vehicle telemetry temporarily unavailable.
          </div>
        )}

        {!selectedVehicleId && selectedStopId && stopDetails && (
          <StopDetails
            stop={stopDetails}
            onSelectRoute={handleSelectRoute}
          />
        )}

        {!selectedVehicleId && !selectedStopId && routeDetails && (
          <RouteDetails
            route={routeDetails}
            onSelectStop={handleSelectStop}
            selectedVehicleId={selectedVehicleId}
            onSelectVehicleId={(id) => setSelectedVehicleId(id)}
          />
        )}
      </BottomSheet>
    </div>
  );
};

export default Home;
