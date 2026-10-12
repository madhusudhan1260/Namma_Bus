import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { BmtcRealtimeProvider } from '../src/providers/bmtc/BmtcRealtimeProvider';
import { BmtcNormalizer } from '../src/providers/bmtc/BmtcNormalizer';
import { bmtcApiClient } from '../src/providers/bmtc/BmtcApiClient';
import { vehicleService } from '../src/services/vehicleService';
import { cacheService } from '../src/cache/cacheService';
import { currentStopService } from '../src/services/currentStopService';
import { routeService } from '../src/services/routeService';

describe('Route-Specific Live Vehicle Lookup & Resilient BMTC Integration Tests', () => {
  let provider: BmtcRealtimeProvider;

  beforeEach(() => {
    provider = new BmtcRealtimeProvider();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Test 1: SearchRoute_v2 exact route matching
  it('1. SearchRoute_v2 should perform exact route matching when variants exist', async () => {
    const mockSearchRes = {
      data: [
        { routeno: '356-M CPR-ANK-RMH', routeparentid: 5346 },
        { routeno: '356-M', routeparentid: 1020 },
        { routeno: '356-M KBS-D32', routeparentid: 6118 },
      ],
    };

    vi.spyOn(bmtcApiClient, 'searchRoute').mockResolvedValue(mockSearchRes);
    const getDetailsSpy = vi.spyOn(bmtcApiClient, 'getRouteDetails').mockResolvedValue({
      up: { mapData: [] },
      down: { mapData: [] },
    });

    await provider.getVehiclesByRoute('356-M');

    expect(getDetailsSpy).toHaveBeenCalledWith(1020, expect.any(Object));
  });

  // Test 2: 356-M dynamic route resolution
  it('2. 356-M dynamic route resolution should extract routeparentid without hardcoding', async () => {
    const mockSearchRes = {
      data: [{ routeno: '356-M', routeparentid: 1020 }],
    };

    const searchSpy = vi.spyOn(bmtcApiClient, 'searchRoute').mockResolvedValue(mockSearchRes);
    const detailsSpy = vi.spyOn(bmtcApiClient, 'getRouteDetails').mockResolvedValue({
      routeno: '356-M',
      up: {
        mapData: [
          {
            vehicleid: '26591',
            vehiclenumber: 'KA51AJ6637',
            centerlat: 12.868522,
            centerlong: 77.654106,
            heading: 327,
            speed: 25,
            lastrefreshon: new Date().toISOString(),
          },
        ],
      },
      down: { mapData: [] },
    });

    const vehicles = await provider.getVehiclesByRoute('356-M');

    expect(searchSpy).toHaveBeenCalledWith('356-M', expect.any(Object));
    expect(detailsSpy).toHaveBeenCalledWith(1020, expect.any(Object));
    expect(vehicles.length).toBe(1);
    expect(vehicles[0].vehicleNumber).toBe('KA51AJ6637');
    expect(vehicles[0].routeNumber).toBe('356-M');
  });

  // Test 3: Exact route selection when variants are also returned (case-insensitive and trimmed)
  it('3. Exact route selection should handle whitespace and case-insensitivity', async () => {
    const mockSearchRes = {
      data: [
        { routeno: '356-M KBS-SNBS-ANK', routeparentid: 8040 },
        { routeno: '356-M', routeparentid: 1020 },
      ],
    };

    vi.spyOn(bmtcApiClient, 'searchRoute').mockResolvedValue(mockSearchRes);
    const getDetailsSpy = vi.spyOn(bmtcApiClient, 'getRouteDetails').mockResolvedValue({
      up: { mapData: [] },
      down: { mapData: [] },
    });

    await provider.getVehiclesByRoute(' 356-m ');

    expect(getDetailsSpy).toHaveBeenCalledWith(1020, expect.any(Object));
  });

  // Test 4: Extraction of up.mapData
  it('4. Extraction of up.mapData should correctly normalize and include northbound vehicles', async () => {
    vi.spyOn(bmtcApiClient, 'searchRoute').mockResolvedValue({
      data: [{ routeno: '356-M', routeparentid: 1020 }],
    });

    vi.spyOn(bmtcApiClient, 'getRouteDetails').mockResolvedValue({
      up: {
        mapData: [
          {
            vehicleid: '27372',
            vehiclenumber: 'KA57F5972',
            centerlat: 12.769567,
            centerlong: 77.701484,
            heading: 174,
            speed: 30,
            lastrefreshon: new Date().toISOString(),
          },
        ],
      },
      down: { mapData: [] },
    });

    const vehicles = await provider.getVehiclesByRoute('356-M');
    expect(vehicles.length).toBe(1);
    expect(vehicles[0].id).toBe('27372');
    expect(vehicles[0].vehicleNumber).toBe('KA57F5972');
  });

  // Test 5: Extraction of down.mapData
  it('5. Extraction of down.mapData should correctly normalize and include southbound vehicles', async () => {
    vi.spyOn(bmtcApiClient, 'searchRoute').mockResolvedValue({
      data: [{ routeno: '356-M', routeparentid: 1020 }],
    });

    vi.spyOn(bmtcApiClient, 'getRouteDetails').mockResolvedValue({
      up: { mapData: [] },
      down: {
        mapData: [
          {
            vehicleid: '26570',
            vehiclenumber: 'KA51AJ6208',
            centerlat: 12.85523,
            centerlong: 77.6647,
            heading: 317,
            speed: 20,
            lastrefreshon: new Date().toISOString(),
          },
        ],
      },
    });

    const vehicles = await provider.getVehiclesByRoute('356-M');
    expect(vehicles.length).toBe(1);
    expect(vehicles[0].id).toBe('26570');
    expect(vehicles[0].vehicleNumber).toBe('KA51AJ6208');
  });

  // Test 6: Deduplication by vehicle ID
  it('6. Deduplication by vehicle ID should avoid duplicates present in both up and down payloads', async () => {
    vi.spyOn(bmtcApiClient, 'searchRoute').mockResolvedValue({
      data: [{ routeno: '356-M', routeparentid: 1020 }],
    });

    vi.spyOn(bmtcApiClient, 'getRouteDetails').mockResolvedValue({
      up: {
        mapData: [
          {
            vehicleid: '26591',
            vehiclenumber: 'KA51AJ6637',
            centerlat: 12.868522,
            centerlong: 77.654106,
            heading: 327,
            speed: 25,
            lastrefreshon: new Date().toISOString(),
          },
        ],
      },
      down: {
        mapData: [
          {
            vehicleid: '26591', // Duplicate ID in down
            vehiclenumber: 'KA51AJ6637',
            centerlat: 12.868522,
            centerlong: 77.654106,
            heading: 327,
            speed: 25,
            lastrefreshon: new Date().toISOString(),
          },
          {
            vehicleid: '26618',
            vehiclenumber: 'KA51AJ6903',
            centerlat: 12.709247,
            centerlong: 77.69835,
            heading: 342,
            speed: 15,
            lastrefreshon: new Date().toISOString(),
          },
        ],
      },
    });

    const vehicles = await provider.getVehiclesByRoute('356-M');
    expect(vehicles.length).toBe(2);
    const ids = vehicles.map((v) => v.id);
    expect(ids).toContain('26591');
    expect(ids).toContain('26618');
  });

  // Test 7: Normalization of real BMTC vehicle records
  it('7. Normalization of real BMTC vehicle records should correctly parse fields, check bounds, and assign LIVE status', () => {
    const raw = {
      vehicleid: 26570,
      vehiclenumber: 'KA51AJ6208',
      centerlat: 12.85523,
      centerlong: 77.6647,
      heading: 317,
      speed: 22,
      lastrefreshon: new Date().toISOString(),
    };

    const norm = BmtcNormalizer.normalizeRouteVehicle(raw, 'route-db-id', '356-M', 'Anekal');
    expect(norm).not.toBeNull();
    expect(norm?.id).toBe('26570');
    expect(norm?.vehicleNumber).toBe('KA51AJ6208');
    expect(norm?.latitude).toBe(12.85523);
    expect(norm?.longitude).toBe(77.6647);
    expect(norm?.bearing).toBe(317);
    expect(norm?.speed).toBe(22);
    expect(norm?.status).toBe('LIVE');
    expect(norm?.source).toBe('BMTC');
    expect(norm?.destination).toBe('Anekal');
  });

  // Test 8: Route-specific cache
  it('8. Route-specific cache should return cached vehicles without hitting upstream provider again', async () => {
    const testVehicles = [
      {
        id: 'KA51AJ6637',
        vehicleNumber: 'KA-51-AJ-6637',
        routeId: 'r356m',
        routeNumber: '356-M',
        tripId: null,
        latitude: 12.868,
        longitude: 77.654,
        bearing: 320,
        speed: 28,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 10,
        status: 'LIVE' as const,
        source: 'BMTC' as const,
      },
    ];

    await cacheService.set('realtime:vehicles:route:356m', testVehicles, 25);

    const providerSpy = vi.spyOn(vehicleService['provider'], 'getVehiclesByRoute');
    const result = await vehicleService.getVehiclesByRoute('356-M');

    expect(result.length).toBe(1);
    expect(result[0].id).toBe('KA51AJ6637');
    expect(providerSpy).not.toHaveBeenCalled();
  });

  // Test 9: Concurrent requests reuse one in-flight route lookup
  it('9. Concurrent requests should coalesce into a single in-flight route fetch', async () => {
    await cacheService.del('realtime:vehicles:route:356m');

    let resolvePromise: (val: any) => void;
    const delayedPromise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    const providerSpy = vi.spyOn(vehicleService['provider'], 'getVehiclesByRoute').mockImplementation(async () => {
      return (await delayedPromise) as any;
    });

    // Fire 3 simultaneous requests for 356-M
    const p1 = vehicleService.getVehiclesByRoute('356-M');
    const p2 = vehicleService.getVehiclesByRoute('356-M');
    const p3 = vehicleService.getVehiclesByRoute('356-M');

    // Release promise
    resolvePromise!([
      {
        id: 'v1',
        vehicleNumber: 'KA-01-A-1111',
        routeId: null,
        routeNumber: '356-M',
        tripId: null,
        latitude: 12.9,
        longitude: 77.6,
        bearing: 0,
        speed: 0,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 5,
        status: 'LIVE' as const,
        source: 'BMTC' as const,
      },
    ]);

    const [r1, r2, r3] = await Promise.all([p1, p2, p3]);

    expect(providerSpy).toHaveBeenCalledTimes(1);
    expect(r1.length).toBe(1);
    expect(r2.length).toBe(1);
    expect(r3.length).toBe(1);
  });

  // Test 10: BMTC timeout handling
  it('10. BMTC timeout handling should return an empty array without throwing or hanging', async () => {
    vi.spyOn(bmtcApiClient, 'searchRoute').mockRejectedValue(new Error('timeout of 10000ms exceeded'));

    const result = await provider.getVehiclesByRoute('TIMEOUT-ROUTE');
    expect(result).toEqual([]);
  });

  // Test 11: BMTC failure does not create mock data
  it('11. BMTC failure should not create mock or simulated vehicles', async () => {
    vi.spyOn(bmtcApiClient, 'searchRoute').mockResolvedValue({
      data: [{ routeno: 'FAIL-ROUTE', routeparentid: 99999 }],
    });
    vi.spyOn(bmtcApiClient, 'getRouteDetails').mockResolvedValue(null);

    const result = await provider.getVehiclesByRoute('FAIL-ROUTE');
    expect(result).toEqual([]);
    expect(result.some((v) => v.source === 'DEMO')).toBe(false);
  });

  // Test 12: Existing global vehicle polling still works
  it('12. Existing global vehicle polling should continue to function properly', async () => {
    const diag = provider.getStatus();
    expect(diag.provider).toBe('BMTC_REALTIME');
    expect(diag.configured).toBe(true);
    expect(typeof diag.reachable).toBe('boolean');
  });

  // Test 13: Existing current-stop enrichment still works
  it('13. Existing current-stop enrichment should enrich live route vehicles', async () => {
    const sampleVehicles = [
      {
        id: 'v-enrich',
        vehicleNumber: 'KA-01-A-2222',
        routeId: null,
        routeNumber: '356-M',
        tripId: null,
        latitude: 12.9775,
        longitude: 77.5735, // Near Majestic
        bearing: 90,
        speed: 5,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 5,
        status: 'LIVE' as const,
        source: 'BMTC' as const,
      },
    ];

    await currentStopService.enrichVehicles(sampleVehicles);
    expect(sampleVehicles[0]).toHaveProperty('stopStatus');
  });

  // Test 14: Existing route matching still works with variations
  it('14. Route matching should resolve variations like 356-M, 356M, 356-m to the canonical route', async () => {
    const r1 = await routeService.findRouteEntity('356-M');
    const r2 = await routeService.findRouteEntity('356M');
    const r3 = await routeService.findRouteEntity('356-m');

    expect(r1).not.toBeNull();
    expect(r2).not.toBeNull();
    expect(r3).not.toBeNull();
    expect(r1?.id).toBe(r2?.id);
    expect(r2?.id).toBe(r3?.id);
  });
});
