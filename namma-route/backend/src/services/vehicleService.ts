import { NormalizedVehicle, RealtimeProvider, RealtimeProviderStatus } from '../providers/bmtc/RealtimeProvider';
import { BmtcRealtimeProvider } from '../providers/bmtc/BmtcRealtimeProvider';
import { MockRealtimeProvider } from '../providers/bmtc/MockRealtimeProvider';
import { cacheService } from '../cache/cacheService';
import { currentStopService } from './currentStopService';
import { normalizeRouteIdentifier } from '../utils/routeNormalizer';
import Logger from '../utils/logger';
import prisma from '../db/prisma';

export interface RealtimeVehiclesResponse {
  status: 'LIVE' | 'DATA DELAYED' | 'TEMPORARILY UNAVAILABLE' | 'UNAVAILABLE';
  provider: string;
  source: 'BMTC' | 'DEMO';
  timestamp?: string;
  dataAge?: number;
  vehicleCount: number;
  vehicles: NormalizedVehicle[];
  demoMode?: boolean;
  error?: string | null;
  /** How much of the network the BMTC poller has recently covered */
  coverage?: Record<string, any>;
}

export class VehicleService {
  private provider: RealtimeProvider;
  private pollIntervalSeconds: number;
  private pollTimer: NodeJS.Timeout | null = null;
  private lastPollTimestamp: number = 0;
  private lastKnownVehicles: Map<string, NormalizedVehicle> = new Map();
  private demoMode: boolean;
  private inFlightFetch: Promise<NormalizedVehicle[]> | null = null;
  private inFlightRouteFetches: Map<string, Promise<NormalizedVehicle[]>> = new Map();

  constructor() {
    this.demoMode = process.env.DEMO_MODE === 'true';
    const providerType = process.env.REALTIME_PROVIDER?.toLowerCase() || 'bmtc';

    if (this.demoMode || providerType === 'mock') {
      this.provider = new MockRealtimeProvider();
      Logger.info('[VehicleService] Initialized with MockRealtimeProvider (DEMO MODE active)');
    } else {
      this.provider = new BmtcRealtimeProvider();
      Logger.info('[VehicleService] Initialized with BmtcRealtimeProvider (REAL BMTC MODE active)');
    }

    const intervalEnv = parseInt(process.env.REALTIME_POLL_INTERVAL || '30', 10);
    // Enforce safety minimum of 10s to prevent spamming
    this.pollIntervalSeconds = Math.max(10, isNaN(intervalEnv) ? 30 : intervalEnv);

    // Start background polling loop
    this.startBackgroundPolling();
  }

  private startBackgroundPolling() {
    Logger.info(`[VehicleService] Starting background polling every ${this.pollIntervalSeconds}s`);

    // Immediate first fetch
    this.fetchAndUpdateVehicles().catch((err) => {
      Logger.error('[VehicleService] Initial vehicle fetch error', err);
    });

    this.pollTimer = setInterval(() => {
      this.fetchAndUpdateVehicles().catch((err) => {
        Logger.error('[VehicleService] Background vehicle poll error', err);
      });
    }, this.pollIntervalSeconds * 1000);

    this.pollTimer.unref();
  }

  /**
   * Fetch live vehicles from active provider and update cache
   */
  async fetchAndUpdateVehicles(): Promise<NormalizedVehicle[]> {
    if (this.inFlightFetch) {
      return this.inFlightFetch;
    }

    this.inFlightFetch = (async () => {
      try {
        const freshVehicles = await this.provider.getVehicles();
        this.lastPollTimestamp = Date.now();

        if (freshVehicles && freshVehicles.length > 0) {
          // Clear previous cache if fresh full batch obtained
          this.lastKnownVehicles.clear();
          for (const vehicle of freshVehicles) {
            this.lastKnownVehicles.set(vehicle.id, vehicle);
          }
        } else if (!this.demoMode) {
          // If not in demo mode and 0 vehicles arrived, don't hold onto stale artifacts
          this.lastKnownVehicles.clear();
        }

        // Remove stale vehicles (> 300 seconds)
        this.removeStaleVehicles();

        const activeVehicles = Array.from(this.lastKnownVehicles.values());

        // Enrich vehicles with route-aware current-stop detection
        try {
          await currentStopService.enrichVehicles(activeVehicles);
        } catch (enrichErr) {
          Logger.error('[VehicleService] Failed to enrich vehicles with current stops', enrichErr);
        }

        // Save into cache layer with TTL
        await cacheService.set('realtime:vehicles:all', activeVehicles, this.pollIntervalSeconds * 2);

        return activeVehicles;
      } catch (err: any) {
        Logger.error('[VehicleService] fetchAndUpdateVehicles failed', err);
        if (!this.demoMode) {
          this.lastKnownVehicles.clear();
        }
        await cacheService.set('realtime:vehicles:all', [], this.pollIntervalSeconds);
        return [];
      } finally {
        this.inFlightFetch = null;
      }
    })();

    return this.inFlightFetch;
  }

  /**
   * Remove vehicles that haven't been heard from in 5 minutes (> 300s)
   */
  private removeStaleVehicles() {
    const now = Date.now();
    for (const [id, vehicle] of this.lastKnownVehicles.entries()) {
      const vehicleTime = new Date(vehicle.timestamp).getTime();
      const ageSeconds = (now - vehicleTime) / 1000;
      if (ageSeconds > 300) {
        this.lastKnownVehicles.delete(id);
      } else {
        vehicle.freshnessSeconds = Math.floor(ageSeconds);
        vehicle.status = ageSeconds <= 60 ? 'LIVE' : ageSeconds <= 120 ? 'RECENT' : 'STALE';
      }
    }
  }

  /**
   * Get all active vehicles with coalescing from cache
   */
  async getAllVehicles(): Promise<RealtimeVehiclesResponse> {
    const statusDiag = this.provider.getStatus();

    if (!this.demoMode) {
      // In Real BMTC mode, check cache first
      let vehicles = await cacheService.get<NormalizedVehicle[]>('realtime:vehicles:all');
      if (!vehicles) {
        if (this.lastKnownVehicles.size > 0) {
          vehicles = Array.from(this.lastKnownVehicles.values());
        } else {
          // If no vehicles available yet, kick off background fetch if not already in flight
          if (!this.inFlightFetch) {
            this.fetchAndUpdateVehicles().catch((err) => {
              Logger.warn(`[VehicleService] Background fetch error: ${err?.message || err}`);
            });
          }
          vehicles = [];
        }
      }

      const diag = this.provider.getStatus();
      const isLive = (diag.reachable || vehicles.length > 0) && vehicles.length > 0;

      // If upstream is unreachable or returns 0 vehicles, return UNAVAILABLE schema per contract
      if (!isLive) {
        return {
          status: 'UNAVAILABLE',
          provider: 'BMTC_REALTIME',
          source: 'BMTC',
          vehicleCount: 0,
          vehicles: [],
          error: diag.error || 'Realtime BMTC data unavailable',
          coverage: diag.coverage,
        };
      }

      const dataAge = this.lastPollTimestamp > 0
        ? Math.floor((Date.now() - this.lastPollTimestamp) / 1000)
        : 0;

      return {
        // Upstream failing while recent vehicles are retained is reported as delayed, not live
        status: dataAge > 120 || !diag.reachable ? 'DATA DELAYED' : 'LIVE',
        provider: 'BMTC_REALTIME',
        source: 'BMTC',
        timestamp: new Date().toISOString(),
        dataAge,
        vehicleCount: vehicles.length,
        vehicles,
        demoMode: false,
        error: diag.reachable ? null : diag.error,
        coverage: diag.coverage,
      };
    }

    // Demo Mode Active
    let vehicles = await cacheService.get<NormalizedVehicle[]>('realtime:vehicles:all');
    if (!vehicles || vehicles.length === 0) {
      vehicles = await this.fetchAndUpdateVehicles();
    }

    const dataAge = this.lastPollTimestamp > 0
      ? Math.floor((Date.now() - this.lastPollTimestamp) / 1000)
      : 0;

    return {
      status: 'LIVE',
      provider: 'MOCK_DEMO_PROVIDER',
      source: 'DEMO',
      timestamp: new Date().toISOString(),
      dataAge,
      vehicleCount: vehicles.length,
      vehicles,
      demoMode: true,
    };
  }

  /**
   * Get vehicles plying on a specific route with dedicated route caching and coalescing
   */
  async getVehiclesByRoute(routeIdOrNumber: string, routeDbId?: string): Promise<NormalizedVehicle[]> {
    const routeKey = routeIdOrNumber.trim();
    if (!routeKey) {
      return [];
    }

    const normRouteKey = normalizeRouteIdentifier(routeKey) || routeKey.toLowerCase().replace(/[\s-]+/g, '');
    const cacheKey = `realtime:vehicles:route:${normRouteKey}`;

    // 1. Check dedicated route-specific cache (20-30s TTL)
    const cachedRouteVehicles = await cacheService.get<NormalizedVehicle[]>(cacheKey);
    if (cachedRouteVehicles && Array.isArray(cachedRouteVehicles)) {
      return cachedRouteVehicles;
    }

    // 2. Reuse in-flight request if one is already pending for this route
    if (this.inFlightRouteFetches.has(normRouteKey)) {
      return await this.inFlightRouteFetches.get(normRouteKey)!;
    }

    // 3. Check existing global in-memory vehicles without triggering a blocking global fetch
    const globalMatches = Array.from(this.lastKnownVehicles.values()).filter((v) => {
      const vNorm = normalizeRouteIdentifier(v.routeNumber);
      return (
        v.routeId === routeIdOrNumber ||
        (routeDbId && v.routeId === routeDbId) ||
        vNorm === normRouteKey ||
        v.routeNumber?.toLowerCase() === routeKey.toLowerCase()
      );
    });

    if (globalMatches.length > 0) {
      await cacheService.set(cacheKey, globalMatches, 25);
      return globalMatches;
    }

    // 4. Wrap lookup in coalesced Promise registered immediately
    const fetchPromise = (async () => {
      try {
        let canonicalRoute = routeKey;
        let resolvedDbId = routeDbId;

        if (!resolvedDbId) {
          try {
            const routeRecord = await prisma.route.findFirst({
              where: {
                OR: [
                  { id: routeKey },
                  { routeId: routeKey },
                  { routeShortName: routeKey },
                ],
              },
              select: { id: true, routeShortName: true },
            });
            if (routeRecord) {
              canonicalRoute = routeRecord.routeShortName;
              resolvedDbId = routeRecord.id;
            }
          } catch {
            // Fallback to routeKey
          }
        }

        // In Demo Mode, query the mock provider
        if (this.demoMode || !(this.provider instanceof BmtcRealtimeProvider)) {
          const demoVehicles = await this.provider.getVehiclesByRoute(canonicalRoute, resolvedDbId);
          if (demoVehicles && demoVehicles.length > 0) {
            try {
              await currentStopService.enrichVehicles(demoVehicles);
            } catch (enrichErr) {
              Logger.error(`[VehicleService] Failed to enrich demo vehicles for ${routeKey}`, enrichErr);
            }
          }
          await cacheService.set(cacheKey, demoVehicles, 25);
          return demoVehicles;
        }

        // Direct BMTC route-specific lookup
        const routeVehicles = await this.provider.getVehiclesByRoute(canonicalRoute, resolvedDbId);

        if (routeVehicles && routeVehicles.length > 0) {
          try {
            await currentStopService.enrichVehicles(routeVehicles);
          } catch (enrichErr) {
            Logger.error(
              `[VehicleService] Failed to enrich route ${routeKey} vehicles`,
              enrichErr
            );
          }

          // Merge discovered vehicles into lastKnownVehicles so global live map and proximity queries benefit
          for (const v of routeVehicles) {
            this.lastKnownVehicles.set(v.id, v);
          }

          await cacheService.set(cacheKey, routeVehicles, 25);
          return routeVehicles;
        }

        // Cache empty result briefly (10s) to prevent spamming
        await cacheService.set(cacheKey, [], 10);
        return [];
      } catch (err: any) {
        Logger.warn(
          `[VehicleService] Route-specific BMTC lookup failed for ${routeKey}: ${err?.message || err}`
        );
        await cacheService.set(cacheKey, [], 10);
        return [];
      } finally {
        this.inFlightRouteFetches.delete(normRouteKey);
      }
    })();

    this.inFlightRouteFetches.set(normRouteKey, fetchPromise);
    return await fetchPromise;
  }

  /**
   * Get single vehicle details
   */
  async getVehicleById(vehicleId: string): Promise<NormalizedVehicle | null> {
    const all = (await this.getAllVehicles()).vehicles;
    return all.find((v) => v.id === vehicleId) || null;
  }

  /**
   * Get health of provider
   */
  async getProviderHealth() {
    return this.provider.getHealth();
  }

  /**
   * Get diagnostics for /api/realtime/status
   */
  getStatusDiagnostics(): RealtimeProviderStatus {
    return this.provider.getStatus();
  }

  isDemoMode(): boolean {
    return this.demoMode;
  }

  stop() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}

export const vehicleService = new VehicleService();
export default vehicleService;

