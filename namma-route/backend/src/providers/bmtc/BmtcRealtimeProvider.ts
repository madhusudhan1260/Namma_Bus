import { NormalizedVehicle, ProviderHealth, RealtimeProvider, RealtimeProviderStatus } from './RealtimeProvider';
import { bmtcApiClient } from './BmtcApiClient';
import { BmtcNormalizer } from './BmtcNormalizer';
import Logger from '../../utils/logger';
import prisma from '../../db/prisma';

export class BmtcRealtimeProvider implements RealtimeProvider {
  public readonly name = 'BMTC_REALTIME';
  private reachable: boolean = false;
  private lastSuccessfulUpdate: string | null = null;
  private lastAttempt: string = new Date().toISOString();
  private lastError: string | null = null;
  private lastLatencyMs: number = 0;
  private cachedVehicles: Map<string, NormalizedVehicle> = new Map();
  private routeParentIdCache: Map<string, number> = new Map();

  constructor() {
    // Pre-populate parent IDs for high-frequency Bengaluru corridors to save initial lookup roundtrips
    this.routeParentIdCache.set('500-D', 1066);
    this.routeParentIdCache.set('500D', 1066);
    this.routeParentIdCache.set('335-E', 1242);
    this.routeParentIdCache.set('335E', 1242);
    this.routeParentIdCache.set('365', 843);
    this.routeParentIdCache.set('KIA-8', 1980);
    this.routeParentIdCache.set('KIA8', 1980);
    this.routeParentIdCache.set('201', 512);
  }

  // ---------------------------------------------------------------------------------------------
  // Network-wide polling (all routes in the imported GTFS network, not a fixed subset).
  // BMTC exposes live positions per route (SearchByRouteDetails_v4). Each poll cycle spends a fixed
  // request budget: routes that currently have buses are refreshed first (oldest poll first), the rest
  // of the budget sweeps the remaining network in rotation, busiest routes (most GTFS trips) first.
  // Vehicles persist across cycles only while their own BMTC timestamp is within the retention window.
  // ---------------------------------------------------------------------------------------------
  private readonly routesPerCycle = Math.max(1, parseInt(process.env.BMTC_ROUTES_PER_CYCLE || '24', 10) || 24);
  private readonly concurrency = Math.max(1, Math.min(8, parseInt(process.env.BMTC_CONCURRENCY || '4', 10) || 4));
  private readonly retentionSeconds = 300;
  private networkRoutes: { id: string; routeShortName: string; destination: string | null }[] = [];
  private networkRoutesLoadedAt = 0;
  private coldCursor = 0;
  // Set when the set of routes with live buses collapses (BMTC answering but returning no buses), so discovery
  // restarts from the busiest routes when buses come back instead of continuing deep in the quiet routes.
  private hadFleet = false;
  private fleetCollapsed = false;
  private routeLastPolledAt: Map<string, number> = new Map();
  private routeLastVehiclesAt: Map<string, number> = new Map();
  private backoffUntil = 0;
  private backoffMs = 0;
  private authorizationBlockedAt = 0;
  private lastCycle = { routesRequested: 0, routesSucceeded: 0, routesFailed: 0, vehiclesSeen: 0, errorCodes: {} as Record<string, number> };

  private async loadNetworkRoutes(): Promise<void> {
    if (this.networkRoutes.length && Date.now() - this.networkRoutesLoadedAt < 6 * 3600_000) return;
    const [routes, tripCounts] = await Promise.all([
      prisma.route.findMany({ select: { id: true, routeShortName: true, destination: true } }),
      prisma.trip.groupBy({ by: ['routeId'], _count: { _all: true } }),
    ]);
    const trips = new Map<string, number>(tripCounts.map((t: any) => [t.routeId, t._count._all]));
    // BMTC's routeparentid is the GTFS route_id in this dataset, so it can be queried directly
    this.networkRoutes = routes
      .filter((r) => /^\d+$/.test(r.id))
      .sort((a, b) => (trips.get(b.id) || 0) - (trips.get(a.id) || 0));
    this.networkRoutesLoadedAt = Date.now();
    Logger.info(`[BmtcRealtimeProvider] Network poller covering ${this.networkRoutes.length} routes (${this.routesPerCycle} requests/cycle, concurrency ${this.concurrency})`);
  }

  private selectRoutesForCycle(): typeof this.networkRoutes {
    const now = Date.now();
    const byId = new Map(this.networkRoutes.map((r) => [r.id, r]));
    const hot = [...this.routeLastVehiclesAt.entries()]
      .filter(([, at]) => now - at < this.retentionSeconds * 1000 * 2)
      .map(([id]) => byId.get(id))
      .filter((r): r is (typeof this.networkRoutes)[number] => !!r)
      .sort((a, b) => (this.routeLastPolledAt.get(a.id) || 0) - (this.routeLastPolledAt.get(b.id) || 0));

    // Keep at least a quarter of the budget for discovering buses on the rest of the network
    const hotBudget = Math.min(hot.length, Math.ceil(this.routesPerCycle * 0.75));
    const chosen = hot.slice(0, hotBudget);
    const chosenIds = new Set(chosen.map((r) => r.id));
    let scanned = 0;
    while (chosen.length < this.routesPerCycle && scanned < this.networkRoutes.length) {
      const r = this.networkRoutes[this.coldCursor % this.networkRoutes.length];
      this.coldCursor = (this.coldCursor + 1) % this.networkRoutes.length;
      scanned++;
      if (!chosenIds.has(r.id)) {
        chosen.push(r);
        chosenIds.add(r.id);
      }
    }
    return chosen;
  }

  /** Merge normalized vehicles, keeping the newest upstream position per vehicle id */
  private mergeVehicles(vehicles: NormalizedVehicle[]) {
    for (const v of vehicles) {
      const prev = this.cachedVehicles.get(v.id);
      if (!prev || new Date(v.timestamp).getTime() >= new Date(prev.timestamp).getTime()) {
        this.cachedVehicles.set(v.id, v);
      }
    }
  }

  /** Drop vehicles whose own BMTC timestamp left the retention window; refresh freshness labels */
  private pruneFleet() {
    for (const [id, v] of this.cachedVehicles) {
      const age = BmtcNormalizer.getFreshnessSeconds(new Date(v.timestamp));
      if (age > this.retentionSeconds) {
        this.cachedVehicles.delete(id);
      } else {
        v.freshnessSeconds = age;
        v.status = BmtcNormalizer.determineStatus(age);
      }
    }
  }

  /**
   * Normalize the vehicles of both BMTC directions. BMTC lists each direction ("up"/"down") with its
   * own ordered stops, so every bus gets the origin/destination of the direction it is actually on
   * (not the route's single catalogue destination). Current-stop detection uses this to pick the
   * correct GTFS direction per bus.
   */
  private extractRouteVehicles(details: any, routeId: string | undefined, routeNumber: string, fallbackDestination?: string) {
    const out: NormalizedVehicle[] = [];
    for (const side of ['up', 'down'] as const) {
      const section = details?.[side] ?? details?.data?.[side];
      const mapData = Array.isArray(section?.mapData) ? section.mapData : [];
      const stops = Array.isArray(section?.data) ? section.data : [];
      const origin = stops.length ? String(stops[0]?.stationname || '').trim() || null : null;
      const destination = stops.length ? String(stops[stops.length - 1]?.stationname || '').trim() || null : null;
      for (const raw of mapData) {
        const n = BmtcNormalizer.normalizeRouteVehicle(raw, routeId, routeNumber, destination || fallbackDestination);
        if (n) {
          if (origin) n.origin = origin;
          out.push(n);
        }
      }
    }
    return out;
  }

  async getVehicles(): Promise<NormalizedVehicle[]> {
    const startTime = Date.now();
    this.lastAttempt = new Date().toISOString();

    // Authorization boundary: after a 401/403 do not keep hammering; re-check every 10 minutes
    if (this.authorizationBlockedAt && startTime - this.authorizationBlockedAt < 600_000) {
      this.pruneFleet();
      return Array.from(this.cachedVehicles.values());
    }
    if (startTime < this.backoffUntil) {
      this.pruneFleet();
      return Array.from(this.cachedVehicles.values());
    }

    try {
      await this.loadNetworkRoutes();
      const routes = this.selectRoutesForCycle();
      const cycle = { routesRequested: routes.length, routesSucceeded: 0, routesFailed: 0, vehiclesSeen: 0, errorCodes: {} as Record<string, number> };
      let stopCycle = false;

      for (let i = 0; i < routes.length && !stopCycle; i += this.concurrency) {
        const batch = routes.slice(i, i + this.concurrency);
        const results = await Promise.all(
          batch.map(async (route) => ({ route, res: await bmtcApiClient.fetchRouteDetails(route.id) }))
        );
        for (const { route, res } of results) {
          this.routeLastPolledAt.set(route.id, Date.now());
          if (res.success && res.data) {
            cycle.routesSucceeded++;
            const vehicles = this.extractRouteVehicles(res.data, route.id, route.routeShortName, route.destination || undefined);
            cycle.vehiclesSeen += vehicles.length;
            if (vehicles.length) this.routeLastVehiclesAt.set(route.id, Date.now());
            else this.routeLastVehiclesAt.delete(route.id);
            this.mergeVehicles(vehicles);
            continue;
          }
          cycle.routesFailed++;
          const code = res.errorCode || 'UNKNOWN_ERROR';
          cycle.errorCodes[code] = (cycle.errorCodes[code] || 0) + 1;
          this.lastError = res.errorMessage || 'Realtime BMTC data unavailable';
          if (res.status === 401 || res.status === 403) {
            this.authorizationBlockedAt = Date.now();
            stopCycle = true;
          } else if (res.status === 429) {
            this.backoffMs = Math.min(600_000, Math.max(60_000, this.backoffMs * 2));
            const wait = res.retryAfterSeconds ? res.retryAfterSeconds * 1000 : this.backoffMs;
            this.backoffUntil = Date.now() + wait;
            stopCycle = true;
          }
        }
        // Upstream completely down (nothing succeeded in the first batch): stop spending the budget
        if (cycle.routesSucceeded === 0 && cycle.routesFailed >= batch.length && i === 0) stopCycle = true;
      }

      this.lastCycle = cycle;
      this.lastLatencyMs = Date.now() - startTime;
      if (cycle.routesSucceeded > 0) {
        // Recovering from an outage: the "routes with buses" list emptied while BMTC was unreachable,
        // so restart discovery from the busiest routes instead of continuing deep in the rotation.
        if (!this.reachable && this.routeLastVehiclesAt.size < 10) {
          this.coldCursor = 0;
          Logger.info('[BmtcRealtimeProvider] BMTC reachable again; restarting route discovery from the busiest routes');
        }
        const routesWithBuses = this.routeLastVehiclesAt.size;
        if (routesWithBuses >= 30) this.hadFleet = true;
        if (this.hadFleet && routesWithBuses < 10 && cycle.vehiclesSeen === 0 && !this.fleetCollapsed) {
          this.fleetCollapsed = true;
          Logger.warn('[BmtcRealtimeProvider] BMTC is answering but returning no buses; will restart discovery from the busiest routes when buses return');
        }
        if (this.fleetCollapsed && cycle.vehiclesSeen > 0) {
          this.fleetCollapsed = false;
          this.hadFleet = false;
          this.coldCursor = 0;
          Logger.info('[BmtcRealtimeProvider] BMTC returning buses again; restarting route discovery from the busiest routes');
        }
        this.reachable = true;
        this.lastSuccessfulUpdate = new Date().toISOString();
        this.authorizationBlockedAt = 0;
        if (!Object.keys(cycle.errorCodes).length) {
          this.lastError = null;
          this.backoffMs = 0;
        }
      } else {
        this.reachable = false;
        // Nothing succeeded (timeouts, refusals, errors): back off instead of retrying every poll
        // (1 → 2 → 4 … up to 10 minutes); the first successful cycle resets it.
        if (cycle.routesFailed > 0 && Date.now() >= this.backoffUntil) {
          this.backoffMs = Math.min(600_000, Math.max(60_000, this.backoffMs * 2));
          this.backoffUntil = Date.now() + this.backoffMs;
          Logger.warn(`[BmtcRealtimeProvider] No BMTC route answered; pausing polling for ${Math.round(this.backoffMs / 1000)}s`);
        }
      }

      this.pruneFleet();
      Logger.providerRequest('BMTC_REALTIME', this.lastLatencyMs, this.cachedVehicles.size, false);
      if (!this.reachable) {
        Logger.warn(`[BmtcRealtimeProvider] Poll cycle reached no BMTC route (${this.lastError}). Retaining ${this.cachedVehicles.size} vehicles within their freshness window.`);
      }
      return Array.from(this.cachedVehicles.values());
    } catch (err: any) {
      this.lastLatencyMs = Date.now() - startTime;
      this.reachable = false;
      this.lastError = err.message || 'Realtime BMTC data unavailable';
      Logger.error('[BmtcRealtimeProvider] Live fetch failed', err);
      this.pruneFleet();
      return Array.from(this.cachedVehicles.values());
    }
  }

  /** Coverage of the network poller, for honest status reporting */
  getCoverage() {
    const now = Date.now();
    const recent = [...this.routeLastPolledAt.values()].filter((t) => now - t < this.retentionSeconds * 1000).length;
    return {
      routesInNetwork: this.networkRoutes.length,
      routesPolledLast5Min: recent,
      routesWithLiveBuses: [...this.routeLastVehiclesAt.values()].filter((t) => now - t < this.retentionSeconds * 1000).length,
      requestsPerCycle: this.routesPerCycle,
      concurrency: this.concurrency,
      lastCycle: this.lastCycle,
      authorizationRequired: !!this.authorizationBlockedAt,
      backoffUntil: this.backoffUntil > now ? new Date(this.backoffUntil).toISOString() : null,
    };
  }

  private lastRouteError: string | null = null;

  async getVehiclesByRoute(routeIdOrNumber: string, routeDbId?: string): Promise<NormalizedVehicle[]> {
    const routeNumber = routeIdOrNumber.trim();

    if (!routeNumber) {
      return [];
    }

    const normKey = routeNumber.toLowerCase().replace(/[\s-]+/g, '');

    // While BMTC is refusing/timing out (paused) or requires authorization, don't make on-demand calls:
    // answer from vehicles already in the fleet (normally none in that state) instead of hanging.
    const now = Date.now();
    if (now < this.backoffUntil || (this.authorizationBlockedAt && now - this.authorizationBlockedAt < 600_000)) {
      this.pruneFleet();
      return Array.from(this.cachedVehicles.values()).filter(
        (v) => (routeDbId && v.routeId === routeDbId) || (v.routeNumber || '').toLowerCase().replace(/[\s-]+/g, '') === normKey
      );
    }

    try {
      // 1. Check parentId cache
      let parentId = this.routeParentIdCache.get(routeNumber) ||
                     this.routeParentIdCache.get(normKey);

      let matchedRouteName = routeNumber;

      // The GTFS route_id of this dataset is BMTC's routeparentid
      if (!parentId && routeDbId && /^\d+$/.test(routeDbId)) {
        parentId = parseInt(routeDbId, 10);
      }

      if (!parentId) {
        // Discover BMTC route parent ID dynamically
        const searchRes = await bmtcApiClient.searchRoute(routeNumber, {
          timeoutMs: 10000,
          maxRetries: 1,
        });

        const matches = Array.isArray(searchRes?.data) ? searchRes.data : [];

        if (matches.length === 0) {
          Logger.warn(`[BmtcRealtimeProvider] No BMTC route found for ${routeNumber}`);
          return [];
        }

        // Prefer an exact route-number match over variants (e.g. "356-M" over "356-M CPR-ANK-RMH")
        let exactMatch = matches.find(
          (r: any) => String(r?.routeno || '').trim().toLowerCase() === routeNumber.toLowerCase()
        );

        if (!exactMatch) {
          exactMatch = matches.find(
            (r: any) => String(r?.routeno || '').toLowerCase().replace(/[\s-]+/g, '') === normKey
          );
        }

        if (!exactMatch) {
          exactMatch = matches[0];
        }

        parentId = exactMatch?.routeparentid;
        matchedRouteName = exactMatch?.routeno || routeNumber;

        if (parentId) {
          this.routeParentIdCache.set(routeNumber, parentId);
          this.routeParentIdCache.set(normKey, parentId);
        }
      }

      if (!parentId) {
        Logger.warn(`[BmtcRealtimeProvider] No routeparentid found for ${routeNumber}`);
        return [];
      }

      // Fetch live vehicles for this route
      // On-demand lookups happen while a user waits (route page), so keep them short
      const details = await bmtcApiClient.getRouteDetails(parentId, {
        timeoutMs: 5000,
        maxRetries: 0,
      });

      if (!details) {
        Logger.warn(`[BmtcRealtimeProvider] No route details returned for ${routeNumber}`);
        // BMTC not answering: pause on-demand and background calls briefly instead of retrying per request
        if (Date.now() >= this.backoffUntil) {
          this.backoffMs = Math.max(60_000, this.backoffMs);
          this.backoffUntil = Date.now() + this.backoffMs;
        }
        return [];
      }

      const vehicles = new Map<string, NormalizedVehicle>();
      for (const normalized of this.extractRouteVehicles(details, routeDbId, routeNumber)) {
        if (!vehicles.has(normalized.id)) {
          vehicles.set(normalized.id, normalized);
        }
      }

      if (vehicles.size > 0) {
        this.reachable = true;
        this.lastSuccessfulUpdate = new Date().toISOString();
        // Share on-demand results with the network fleet (same retention rules)
        this.mergeVehicles(Array.from(vehicles.values()));
        if (routeDbId) this.routeLastVehiclesAt.set(routeDbId, Date.now());
      }

      Logger.info(
        `[BmtcRealtimeProvider] Route ${routeNumber}: ${vehicles.size} live vehicles resolved (parentId: ${parentId})`
      );

      return Array.from(vehicles.values());
    } catch (err: any) {
      this.lastRouteError = err?.message || 'Route-specific fetch failed';
      Logger.warn(
        `[BmtcRealtimeProvider] Route-specific fetch failed for ${routeNumber}: ${this.lastRouteError}`
      );
      return [];
    }
  }

  async getVehicle(vehicleId: string): Promise<NormalizedVehicle | null> {
    try {
      const raw = await bmtcApiClient.getVehicleTripDetails(vehicleId);
      const liveLocations = raw?.LiveLocation || [];
      if (liveLocations.length > 0) {
        return BmtcNormalizer.normalizeTripLiveLocation(liveLocations[0]);
      }
    } catch (e: any) {
      Logger.warn(`[BmtcRealtimeProvider] getVehicle failed for ${vehicleId}: ${e.message}`);
    }

    const all = await this.getVehicles();
    return all.find((v) => v.id === vehicleId) || null;
  }

  async getHealth(): Promise<ProviderHealth> {
    const isRecentlySuccessful = Boolean(
      this.lastSuccessfulUpdate &&
      (Date.now() - new Date(this.lastSuccessfulUpdate).getTime()) < 180_000
    );
    const isHealthy = this.reachable || isRecentlySuccessful || this.cachedVehicles.size > 0;

    return {
      status: isHealthy ? 'HEALTHY' : 'DOWN',
      provider: 'BMTC_REALTIME',
      latencyMs: this.lastLatencyMs,
      message: isHealthy
        ? 'BMTC realtime API connected'
        : (this.lastError || 'Realtime BMTC data unavailable'),
      lastCheckTime: this.lastAttempt,
    };
  }

  getStatus(): RealtimeProviderStatus {
    const now = Date.now();
    const dataAge = this.lastSuccessfulUpdate
      ? Math.floor((now - new Date(this.lastSuccessfulUpdate).getTime()) / 1000)
      : 0;

    return {
      provider: 'BMTC_REALTIME',
      configured: true,
      reachable: this.reachable,
      lastSuccessfulUpdate: this.lastSuccessfulUpdate,
      lastAttempt: this.lastAttempt,
      vehicleCount: this.cachedVehicles.size,
      dataAge,
      error: this.lastError,
      coverage: this.getCoverage(),
    };
  }
}

