import { describe, it, expect } from 'vitest';

interface TestVehicle {
  id: string;
  vehicleNumber?: string | null;
  routeNumber?: string | null;
  latitude: any;
  longitude: any;
  bearing?: number | null;
  status: 'LIVE' | 'RECENT' | 'STALE';
}

/**
 * Mirror of MapView vehicle filtering logic to verify transformation and filtering
 */
function filterDisplayVehicles(
  vehicles: TestVehicle[] | null | undefined,
  selectedRouteNumber?: string | null
): TestVehicle[] {
  if (!vehicles || !Array.isArray(vehicles)) return [];

  // Filter out any vehicle missing valid coordinates
  const validVehicles = vehicles.filter((v) => {
    const lat = Number(v?.latitude);
    const lon = Number(v?.longitude);
    return !isNaN(lat) && !isNaN(lon) && lat !== 0 && lon !== 0;
  });

  if (!selectedRouteNumber) return validVehicles;

  const cleanRoute = selectedRouteNumber.toLowerCase().replace(/[^a-z0-9]/g, '');

  // Match route with normalization & flexible matching
  const matchingVehicles = validVehicles.filter((v) => {
    if (!v.routeNumber) return false;
    const vRoute = v.routeNumber.toLowerCase().replace(/[^a-z0-9]/g, '');
    return vRoute === cleanRoute || vRoute.includes(cleanRoute) || cleanRoute.includes(vRoute);
  });

  // If passed vehicles were already specific to this route, return all valid vehicles
  return matchingVehicles.length > 0 ? matchingVehicles : validVehicles;
}

/**
 * Mirror of BusMarker coordinate validation
 */
function isValidMarkerPosition(lat: any, lng: any): boolean {
  const numLat = Number(lat);
  const numLng = Number(lng);
  return !isNaN(numLat) && !isNaN(numLng) && numLat !== 0 && numLng !== 0;
}

/**
 * Mirror of BusMarker CSS class and anchor computation
 */
function computeMarkerConfig(vehicle: TestVehicle, isSelected: boolean = false) {
  const isLive = vehicle.status === 'LIVE';
  const isRecent = vehicle.status === 'RECENT';
  const bearing = vehicle.bearing !== null && vehicle.bearing !== undefined ? vehicle.bearing : 0;

  let stateClass = 'stale';
  if (isSelected) {
    stateClass = 'selected';
  } else if (isLive) {
    stateClass = 'live';
  } else if (isRecent) {
    stateClass = 'recent';
  }

  return {
    iconSize: [36, 56],
    iconAnchor: [18, 18],
    popupAnchor: [0, -20],
    stateClass,
    bearing,
    routeLabel: vehicle.routeNumber || 'BMTC',
  };
}

describe('Vehicle Map Marker & Route Filtering Suite', () => {
  const sampleRealVehicles: TestVehicle[] = [
    {
      id: '25638',
      vehicleNumber: 'KA57F3196',
      routeNumber: '356-M',
      latitude: 12.779761,
      longitude: 77.7024,
      bearing: 209,
      status: 'LIVE',
    },
    {
      id: '27098',
      vehicleNumber: 'KA51AK1281',
      routeNumber: '356-M UP',
      latitude: 12.8523,
      longitude: 77.6631,
      bearing: 45,
      status: 'RECENT',
    },
    {
      id: '26616',
      vehicleNumber: 'KA51AJ6901',
      routeNumber: 'KBS-3C',
      latitude: 12.871755,
      longitude: 77.651985,
      bearing: 142,
      status: 'LIVE',
    },
    {
      id: '99999',
      vehicleNumber: 'KA01AB1234',
      routeNumber: '356M',
      latitude: '12.8200',
      longitude: '77.6800',
      bearing: null,
      status: 'STALE',
    },
  ];

  it('preserves valid coordinates and transforms them safely to numbers', () => {
    sampleRealVehicles.forEach((v) => {
      expect(isValidMarkerPosition(v.latitude, v.longitude)).toBe(true);
      expect(typeof Number(v.latitude)).toBe('number');
      expect(typeof Number(v.longitude)).toBe('number');
    });
  });

  it('safely drops corrupt or null/zero coordinates without throwing errors', () => {
    expect(isValidMarkerPosition(null, 77.59)).toBe(false);
    expect(isValidMarkerPosition(undefined, 77.59)).toBe(false);
    expect(isValidMarkerPosition(NaN, 77.59)).toBe(false);
    expect(isValidMarkerPosition('INVALID', 77.59)).toBe(false);
    expect(isValidMarkerPosition(0, 77.59)).toBe(false);
    expect(isValidMarkerPosition(12.97, 0)).toBe(false);

    const corruptVehicles: TestVehicle[] = [
      { id: '1', latitude: NaN, longitude: 77.59, status: 'LIVE', routeNumber: '356-M' },
      { id: '2', latitude: 12.97, longitude: null, status: 'LIVE', routeNumber: '356-M' },
      { id: '3', latitude: 0, longitude: 0, status: 'LIVE', routeNumber: '356-M' },
      { id: '4', latitude: 12.9716, longitude: 77.5946, status: 'LIVE', routeNumber: '356-M' },
    ];

    const result = filterDisplayVehicles(corruptVehicles);
    expect(result.length).toBe(1);
    expect(result[0].id).toBe('4');
  });

  it('returns all valid vehicles on global map when selectedRouteNumber is null', () => {
    const result = filterDisplayVehicles(sampleRealVehicles, null);
    expect(result.length).toBe(4);
  });

  it('correctly matches route 356-M variants without filtering out valid buses', () => {
    const result = filterDisplayVehicles(sampleRealVehicles, '356-M');
    // Should match "356-M", "356-M UP", and "356M"
    expect(result.length).toBe(3);
    const ids = result.map((r) => r.id);
    expect(ids).toContain('25638');
    expect(ids).toContain('27098');
    expect(ids).toContain('99999');
    expect(ids).not.toContain('26616'); // KBS-3C
  });

  it('normalizes alphanumeric route searches case-insensitively', () => {
    const resultLower = filterDisplayVehicles(sampleRealVehicles, '356m');
    const resultUpper = filterDisplayVehicles(sampleRealVehicles, '356-M');
    expect(resultLower.length).toBe(resultUpper.length);
  });

  it('falls back to showing all route-specific vehicles if passed directly to MapView', () => {
    const routeSpecificVehicles: TestVehicle[] = [
      { id: 'v1', latitude: 12.8, longitude: 77.6, status: 'LIVE', routeNumber: null },
      { id: 'v2', latitude: 12.82, longitude: 77.62, status: 'LIVE', routeNumber: undefined },
    ];
    const result = filterDisplayVehicles(routeSpecificVehicles, '356-M');
    // None have explicit matching routeNumber, but because they are route-specific, fallback retains them
    expect(result.length).toBe(2);
  });

  it('computes correct anchor, dimensions, and color classes for markers', () => {
    const liveConfig = computeMarkerConfig(sampleRealVehicles[0], false);
    expect(liveConfig.stateClass).toBe('live');
    expect(liveConfig.iconAnchor).toEqual([18, 18]); // Centered on 36x36 circle
    expect(liveConfig.popupAnchor).toEqual([0, -20]);
    expect(liveConfig.bearing).toBe(209);
    expect(liveConfig.routeLabel).toBe('356-M');

    const recentConfig = computeMarkerConfig(sampleRealVehicles[1], false);
    expect(recentConfig.stateClass).toBe('recent');

    const selectedConfig = computeMarkerConfig(sampleRealVehicles[0], true);
    expect(selectedConfig.stateClass).toBe('selected');
  });
});
