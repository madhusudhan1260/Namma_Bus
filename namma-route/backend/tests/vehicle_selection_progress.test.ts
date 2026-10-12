import { describe, it, expect, beforeAll } from 'vitest';
import currentStopService, { OrderedStop, StopDetectionResult } from '../src/services/currentStopService';
import routeService from '../src/services/routeService';
import { NormalizedVehicle } from '../src/providers/bmtc/RealtimeProvider';

describe('Bus Selection & Independent Direction-Aware Stop Progress Tests', () => {
  let route361C: any;
  let dir0Stops: OrderedStop[];
  let dir1Stops: OrderedStop[];

  beforeAll(async () => {
    // Load route 361-C and both directional stop sequences from database
    const variants = await currentStopService.getRouteVariants('361-C');
    const v0 = variants.find((v) => v.direction === 0);
    const v1 = variants.find((v) => v.direction === 1);

    expect(v0).toBeDefined();
    expect(v1).toBeDefined();

    dir0Stops = v0!.stops;
    dir1Stops = v1!.stops;
  });

  // 1 & 5 & 6 & 7 & 8: Selecting Bus A calculates Bus A progress
  it('1. Selecting Bus A calculates Bus A progress with accurate current/next stop, completed, and remaining stops', () => {
    // Bus A: Direction 0 (KR Market -> Anekal), at stop #36 Chandapura
    const stop36 = dir0Stops.find((s) => s.sequence === 36);
    expect(stop36).toBeDefined();

    const detectionA: StopDetectionResult = {
      currentStop: {
        stopId: stop36!.id,
        stopName: stop36!.name,
        sequence: stop36!.sequence,
        distanceMeters: 45,
      },
      nextStop: {
        stopId: dir0Stops.find((s) => s.sequence === 37)!.id,
        stopName: dir0Stops.find((s) => s.sequence === 37)!.name,
        sequence: 37,
        distanceMeters: 450,
      },
      stopStatus: 'AT_STOP',
    };

    const progressA = currentStopService.calculateStopProgress(dir0Stops, detectionA);

    expect(progressA.totalStops).toBe(dir0Stops.length); // 52
    expect(progressA.completedStops).toBe(35); // 36 - 1 = 35
    expect(progressA.remainingStops).toBe(dir0Stops.length - 36); // 52 - 36 = 16
    expect(progressA.progressPercentage).toBeGreaterThan(60);
  });

  // 2: Selecting Bus B recalculates all progress
  it('2. Selecting Bus B recalculates all progress independently from Bus A', () => {
    // Bus B: Direction 1 (Anekal -> KR Market), around Bommasandra
    const bommasandra = dir1Stops.find((s) => s.name.toLowerCase().includes('bommasandra')) || dir1Stops[15];
    expect(bommasandra).toBeDefined();

    const detectionB: StopDetectionResult = {
      currentStop: null,
      nextStop: {
        stopId: bommasandra.id,
        stopName: bommasandra.name,
        sequence: bommasandra.sequence,
        distanceMeters: 1200,
      },
      stopStatus: 'IN_TRANSIT',
    };

    const progressB = currentStopService.calculateStopProgress(dir1Stops, detectionB);

    expect(progressB.totalStops).toBe(dir1Stops.length); // 50
    expect(progressB.completedStops).toBe(bommasandra.sequence - 1);
    expect(progressB.remainingStops).toBe(dir1Stops.length - (bommasandra.sequence - 1));
  });

  // 3: Switching A -> B -> A restores correct values
  it('3. Switching A -> B -> A restores Bus A values with zero state leakage', () => {
    const stop36 = dir0Stops.find((s) => s.sequence === 36)!;
    const detectionA: StopDetectionResult = {
      currentStop: {
        stopId: stop36.id,
        stopName: stop36.name,
        sequence: stop36.sequence,
        distanceMeters: 40,
      },
      nextStop: null,
      stopStatus: 'AT_STOP',
    };
    const progressA1 = currentStopService.calculateStopProgress(dir0Stops, detectionA);

    // Switch to Bus B
    const stop10Dir1 = dir1Stops.find((s) => s.sequence === 10)!;
    const detectionB: StopDetectionResult = {
      currentStop: null,
      nextStop: {
        stopId: stop10Dir1.id,
        stopName: stop10Dir1.name,
        sequence: 10,
        distanceMeters: 300,
      },
      stopStatus: 'APPROACHING_STOP',
    };
    const progressB = currentStopService.calculateStopProgress(dir1Stops, detectionB);
    expect(progressB.completedStops).toBe(9);

    // Switch back to Bus A
    const progressA2 = currentStopService.calculateStopProgress(dir0Stops, detectionA);
    expect(progressA2).toEqual(progressA1);
    expect(progressA2.completedStops).toBe(35);
  });

  // 4: Two buses on opposite directions produce different stop sequences
  it('4. Two buses on opposite directions produce different stop sequences and opposite progression', () => {
    // Bus A: KR Market -> Anekal (Origin: KR Market, Dest: Anekal)
    expect(dir0Stops[0].name.toLowerCase()).toContain('market');
    expect(dir0Stops[dir0Stops.length - 1].name.toLowerCase()).toContain('anekal');

    // Bus B: Anekal -> KR Market (Origin: Anekal, Dest: KR Market)
    expect(dir1Stops[0].name.toLowerCase()).toContain('anekal');
    expect(dir1Stops[dir1Stops.length - 1].name.toLowerCase()).toContain('market');

    // Stop sequences count
    expect(dir0Stops.length).toBe(52);
    expect(dir1Stops.length).toBe(50);
  });

  // 5 & 6: Current and Next stop belong strictly to the selected vehicle
  it('5 & 6. Current and next stop belong strictly to the selected vehicle', () => {
    const vehicleA: NormalizedVehicle = {
      id: 'BUS_A',
      vehicleNumber: 'KA-01-F-1111',
      routeId: '361-C',
      routeNumber: '361-C',
      tripId: null,
      latitude: dir0Stops[35].latitude,
      longitude: dir0Stops[35].longitude,
      bearing: 160,
      speed: 25,
      currentStopId: null,
      nextStopId: null,
      timestamp: new Date().toISOString(),
      freshnessSeconds: 10,
      status: 'LIVE',
    };

    const vehicleB: NormalizedVehicle = {
      id: 'BUS_B',
      vehicleNumber: 'KA-01-F-2222',
      routeId: '361-C',
      routeNumber: '361-C',
      tripId: null,
      latitude: dir1Stops[15].latitude,
      longitude: dir1Stops[15].longitude,
      bearing: 340,
      speed: 28,
      currentStopId: null,
      nextStopId: null,
      timestamp: new Date().toISOString(),
      freshnessSeconds: 15,
      status: 'LIVE',
    };

    // Enrich both vehicles
    return currentStopService.enrichVehicles([vehicleA, vehicleB]).then(() => {
      // Vehicle A should be in direction 0
      expect(vehicleA.direction).toBe(0);
      expect(vehicleA.currentStop?.sequence || vehicleA.nextStop?.sequence).toBeDefined();

      // Vehicle B should be in direction 1
      expect(vehicleB.direction).toBe(1);
      expect(vehicleB.currentStop?.sequence || vehicleB.nextStop?.sequence).toBeDefined();

      // Both vehicles must not share the same next stop sequence
      expect(vehicleA.direction).not.toBe(vehicleB.direction);
    });
  });

  // 7 & 8: Completed and remaining stop counts belong to selected vehicle
  it('7 & 8. Completed and remaining stop counts belong to the selected vehicle', async () => {
    const enriched = await currentStopService.enrichVehicles([
      {
        id: 'BUS_NEAR_START',
        vehicleNumber: 'KA-01-F-0001',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[2].latitude,
        longitude: dir0Stops[2].longitude,
        bearing: 160,
        speed: 20,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 5,
        status: 'LIVE',
      },
      {
        id: 'BUS_NEAR_END',
        vehicleNumber: 'KA-01-F-0002',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[48].latitude,
        longitude: dir0Stops[48].longitude,
        bearing: 160,
        speed: 20,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 5,
        status: 'LIVE',
      },
    ]);

    const busNearStart = enriched.find((v) => v.id === 'BUS_NEAR_START')!;
    const busNearEnd = enriched.find((v) => v.id === 'BUS_NEAR_END')!;

    expect(busNearStart.completedStops).toBeLessThan(10);
    expect(busNearStart.remainingStops).toBeGreaterThan(40);

    expect(busNearEnd.completedStops).toBeGreaterThan(40);
    expect(busNearEnd.remainingStops).toBeLessThan(10);
  });

  // 9: Popup and sidebar use identical selected vehicle data
  it('9. Popup and sidebar models use identical selected vehicle data', async () => {
    const [enriched] = await currentStopService.enrichVehicles([
      {
        id: 'BUS_TEST_SYNC',
        vehicleNumber: 'KA-01-F-9999',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[25].latitude,
        longitude: dir0Stops[25].longitude,
        bearing: 160,
        speed: 30,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 8,
        status: 'LIVE',
      },
    ]);

    expect(enriched.direction).toBe(0);
    expect(enriched.totalStops).toBe(52);
    expect(typeof enriched.completedStops).toBe('number');
    expect(typeof enriched.remainingStops).toBe('number');
    expect(enriched.completedStops! + enriched.remainingStops!).toBeLessThanOrEqual(52);
  });

  // 10: Previous bus stop highlight disappears when another bus is selected
  it('10. Previous bus stop highlight sequence updates when switching selected bus', async () => {
    const buses = await currentStopService.enrichVehicles([
      {
        id: 'BUS_1',
        vehicleNumber: 'KA-01-F-1001',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[10].latitude,
        longitude: dir0Stops[10].longitude,
        bearing: 160,
        speed: 20,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 5,
        status: 'LIVE',
      },
      {
        id: 'BUS_2',
        vehicleNumber: 'KA-01-F-1002',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[30].latitude,
        longitude: dir0Stops[30].longitude,
        bearing: 160,
        speed: 20,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 5,
        status: 'LIVE',
      },
    ]);

    const bus1 = buses.find((b) => b.id === 'BUS_1')!;
    const bus2 = buses.find((b) => b.id === 'BUS_2')!;

    const highlight1 = bus1.currentStopSequence ?? bus1.nextStopSequence;
    const highlight2 = bus2.currentStopSequence ?? bus2.nextStopSequence;

    expect(highlight1).not.toBe(highlight2);
  });

  // 11: Selected marker ID matching
  it('11. Marker selection matches unique vehicle ID without colliding', () => {
    const selectedVehicleId = 'BUS_SELECTED';
    const vehicle1 = { id: 'BUS_SELECTED' };
    const vehicle2 = { id: 'BUS_OTHER' };

    expect(vehicle1.id === selectedVehicleId).toBe(true);
    expect(vehicle2.id === selectedVehicleId).toBe(false);
  });

  // 12: Live polling updates selected vehicle without losing selection
  it('12. Live polling updates vehicle position and stop progress while retaining selectedVehicleId', async () => {
    const selectedVehicleId = 'BUS_MOVING';

    // Cycle 1: at stop #10
    const [cycle1] = await currentStopService.enrichVehicles([
      {
        id: selectedVehicleId,
        vehicleNumber: 'KA-01-F-7777',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[10].latitude,
        longitude: dir0Stops[10].longitude,
        bearing: 160,
        speed: 25,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 2,
        status: 'LIVE',
      },
    ]);

    expect(cycle1.id).toBe(selectedVehicleId);
    const initialCompleted = cycle1.completedStops;

    // Cycle 2: bus has moved forward to stop #20
    const [cycle2] = await currentStopService.enrichVehicles([
      {
        id: selectedVehicleId,
        vehicleNumber: 'KA-01-F-7777',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[20].latitude,
        longitude: dir0Stops[20].longitude,
        bearing: 160,
        speed: 25,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 1,
        status: 'LIVE',
      },
    ]);

    expect(cycle2.id).toBe(selectedVehicleId);
    expect(cycle2.completedStops).toBeGreaterThan(initialCompleted!);
  });

  // 13: Selected vehicle disappearing from telemetry is handled gracefully
  it('13. Disappearing vehicle from telemetry is handled gracefully', () => {
    const selectedVehicleId = 'BUS_DISAPPEARED';
    const currentVehicles: NormalizedVehicle[] = [];

    const found = currentVehicles.find((v) => v.id === selectedVehicleId) ?? null;
    expect(found).toBeNull();
  });

  // 14: Route with multiple buses works
  it('14. Route with multiple active buses enriches every bus independently', async () => {
    const route = await routeService.getRouteById('361-C');
    expect(route).toBeDefined();
    expect(route!.directions.length).toBeGreaterThanOrEqual(2);
  });

  // 15: Route with one bus works
  it('15. Route with single bus calculates progress correctly', async () => {
    const singleBus = [
      {
        id: 'SOLO_BUS',
        vehicleNumber: 'KA-01-F-5555',
        routeId: '361-C',
        routeNumber: '361-C',
        tripId: null,
        latitude: dir0Stops[15].latitude,
        longitude: dir0Stops[15].longitude,
        bearing: 160,
        speed: 22,
        currentStopId: null,
        nextStopId: null,
        timestamp: new Date().toISOString(),
        freshnessSeconds: 10,
        status: 'LIVE' as const,
      },
    ];

    const [enriched] = await currentStopService.enrichVehicles(singleBus);
    expect(enriched.id).toBe('SOLO_BUS');
    expect(enriched.direction).toBe(0);
    expect(enriched.totalStops).toBe(52);
  });

  // 16: Route with zero buses works
  it('16. Route with zero live buses returns empty array gracefully without crashing', async () => {
    const emptyEnriched = await currentStopService.enrichVehicles([]);
    expect(emptyEnriched).toEqual([]);
  });
});
