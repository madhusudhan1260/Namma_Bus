import axios, { AxiosInstance, AxiosError } from 'axios';
import Logger from '../../utils/logger';

export interface BmtcApiResult<T = any> {
  success: boolean;
  data: T | null;
  status?: number;
  errorCode?: string;
  errorMessage?: string;
  /** Seconds the server asked us to wait (HTTP 429 Retry-After), when provided */
  retryAfterSeconds?: number;
  durationMs: number;
}

/**
 * Honest client identification. The previous implementation impersonated a desktop Chrome browser
 * and the BMTC web portal (Origin/Referer). The public BMTC endpoints answer self-identified
 * clients, so no impersonation is used. Override with BMTC_CLIENT_USER_AGENT if needed.
 */
/**
 * Official BMTC credentials, once issued. Nothing is sent when BMTC_API_KEY is empty.
 * BMTC_API_KEY_HEADER: header name BMTC specifies (default "x-api-key"; use "Authorization" for bearer tokens)
 * BMTC_API_KEY_PREFIX: optional prefix such as "Bearer "
 */
function officialAuthHeaders(): Record<string, string> {
  const key = (process.env.BMTC_API_KEY || '').trim();
  if (!key) return {};
  const header = (process.env.BMTC_API_KEY_HEADER || 'x-api-key').trim();
  return { [header]: `${process.env.BMTC_API_KEY_PREFIX || ''}${key}` };
}

const CLIENT_USER_AGENT =
  process.env.BMTC_CLIENT_USER_AGENT || 'NammaRoute/1.0 (Namma Bus transit app; server-side client)';

export interface RequestOptions {
  timeoutMs?: number;
  maxRetries?: number;
}

export class BmtcApiClient {
  private client: AxiosInstance;
  public readonly baseUrl: string;
  private timeoutMs: number;
  private lastError: string | null = null;
  private lastAttemptTimestamp: number = 0;
  private isReachableState: boolean = false;

  constructor() {
    this.baseUrl = process.env.BMTC_API_BASE_URL || 'https://bmtcmobileapi.karnataka.gov.in/WebAPI';
    const parsedTimeout = parseInt(process.env.BMTC_API_TIMEOUT || '4000', 10);
    this.timeoutMs = isNaN(parsedTimeout) ? 4000 : parsedTimeout;

    this.client = axios.create({
      baseURL: this.baseUrl,
      timeout: this.timeoutMs,
      headers: {
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        // Protocol parameters required by the BMTC API (response language, client type)
        'lan': 'en',
        'deviceType': 'WEB',
        'User-Agent': CLIENT_USER_AGENT,
        ...officialAuthHeaders(),
      },
    });
  }

  /**
   * Helper delay for exponential backoff
   */
  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Classify error into a structured classification code and message
   */
  private classifyError(err: any): { code: string; message: string; status?: number } {
    if (axios.isAxiosError(err)) {
      const axiosErr = err as AxiosError;
      const status = axiosErr.response?.status;
      if (status === 403) {
        return {
          code: 'HTTP_403_FORBIDDEN',
          message: 'Official BMTC authorization is required (upstream returned HTTP 403 Forbidden)',
          status,
        };
      }
      if (status === 401) {
        return {
          code: 'HTTP_401_UNAUTHORIZED',
          message: 'Official BMTC authorization is required (upstream returned HTTP 401 Unauthorized)',
          status,
        };
      }
      if (status === 429) {
        return {
          code: 'HTTP_429_RATE_LIMITED',
          message: 'BMTC upstream rate limit reached (HTTP 429); backing off',
          status,
        };
      }
      if (status === 404) {
        return {
          code: 'HTTP_404_NOT_FOUND',
          message: 'Endpoint not found on BMTC server',
          status,
        };
      }
      if (status && status >= 500) {
        return {
          code: 'HTTP_SERVER_ERROR',
          message: `Upstream BMTC server returned error HTTP ${status}`,
          status,
        };
      }
      if (axiosErr.code === 'ECONNABORTED' || axiosErr.message.includes('timeout')) {
        return {
          code: 'NETWORK_TIMEOUT',
          message: `BMTC server timed out after ${this.timeoutMs}ms`,
        };
      }
      if (axiosErr.code === 'ECONNREFUSED' || axiosErr.code === 'ENOTFOUND') {
        return {
          code: 'NETWORK_UNREACHABLE',
          message: `Unable to connect to BMTC host: ${axiosErr.code}`,
        };
      }
    }

    return {
      code: 'UNKNOWN_ERROR',
      message: err?.message || 'Unknown network or parsing error',
    };
  }

  /**
   * Execute POST request with retry on transient network errors
   */
  async executePost<T = any>(
    endpoint: string,
    payload: any = {},
    options?: number | RequestOptions
  ): Promise<BmtcApiResult<T>> {
    const startTime = Date.now();
    this.lastAttemptTimestamp = startTime;
    let attempt = 0;

    const maxRetries = typeof options === 'number'
      ? options
      : (options?.maxRetries ?? 2);

    const timeoutMs = (typeof options === 'object' && options?.timeoutMs)
      ? options.timeoutMs
      : this.timeoutMs;

    while (attempt <= maxRetries) {
      try {
        const response = await this.client.post<T>(endpoint, payload, { timeout: timeoutMs });
        const durationMs = Date.now() - startTime;
        // Some BMTC endpoints (e.g. SearchRoute_v2) return a JSON document encoded as a JSON string
        let body: any = response.data;
        if (typeof body === 'string') {
          try {
            body = JSON.parse(body);
          } catch {
            /* leave as-is */
          }
        }
        this.isReachableState = true;
        this.lastError = null;

        Logger.info(`[BMTC API] POST ${endpoint} succeeded in ${durationMs}ms`);
        return {
          success: true,
          data: body as T,
          status: response.status,
          durationMs,
        };
      } catch (err: any) {
        const durationMs = Date.now() - startTime;
        const classified = this.classifyError(err);
        this.lastError = classified.message;

        // If it's a 4xx client error (e.g. 403 Forbidden or 401), retrying will not help.
        // Fail immediately without burning retry budget or delaying response.
        const isClientError = classified.status && classified.status >= 400 && classified.status < 500;
        if (isClientError || attempt === maxRetries) {
          if (classified.code === 'HTTP_403_FORBIDDEN' || classified.code === 'NETWORK_UNREACHABLE') {
            this.isReachableState = false;
          }
          Logger.warn(`[BMTC API] POST ${endpoint} failed after ${durationMs}ms: [${classified.code}] ${classified.message}`);
          const retryAfterRaw = axios.isAxiosError(err) ? err.response?.headers?.['retry-after'] : undefined;
          const retryAfterSeconds = retryAfterRaw !== undefined ? parseInt(String(retryAfterRaw), 10) : NaN;
          return {
            success: false,
            data: null,
            status: classified.status,
            errorCode: classified.code,
            errorMessage: classified.message,
            retryAfterSeconds: isNaN(retryAfterSeconds) ? undefined : retryAfterSeconds,
            durationMs,
          };
        }

        // Retry with exponential backoff for transient issues
        const backoffMs = Math.min(2000, Math.pow(2, attempt) * 500);
        attempt++;
        Logger.warn(`[BMTC API] POST ${endpoint} attempt ${attempt} failed (${classified.code}). Retrying in ${backoffMs}ms...`);
        await this.delay(backoffMs);
      }
    }

    return {
      success: false,
      data: null,
      errorCode: 'MAX_RETRIES_EXCEEDED',
      errorMessage: this.lastError || 'Max retries exceeded',
      durationMs: Date.now() - startTime,
    };
  }

  async post<T = any>(endpoint: string, data: any = {}, options?: number | RequestOptions): Promise<T | null> {
    const result = await this.executePost<T>(endpoint, data, options);
    return result.data;
  }

  async searchRoute(routeText: string, options?: RequestOptions): Promise<any> {
    return this.post('SearchRoute_v2', { routetext: routeText }, {
      timeoutMs: options?.timeoutMs ?? Math.min(10000, this.timeoutMs),
      maxRetries: options?.maxRetries ?? 1,
    });
  }

  async getRouteDetails(routeId: number | string, options?: RequestOptions): Promise<any> {
    return this.post(
      'SearchByRouteDetails_v4',
      {
        routeid: typeof routeId === 'string' ? parseInt(routeId, 10) : routeId,
        servicetypeid: 0,
      },
      {
        // Route details for busy routes are several hundred KB; allow up to 20s
        timeoutMs: options?.timeoutMs ?? Math.max(15000, Math.min(20000, this.timeoutMs)),
        maxRetries: options?.maxRetries ?? 0,
      }
    );
  }

  /**
   * Route live details with the full request outcome (HTTP status, error class), used by the
   * network poller to react to 401/403/429/5xx without guessing.
   */
  async fetchRouteDetails(routeId: number | string, options?: RequestOptions): Promise<BmtcApiResult<any>> {
    return this.executePost(
      'SearchByRouteDetails_v4',
      {
        routeid: typeof routeId === 'string' ? parseInt(routeId, 10) : routeId,
        servicetypeid: 0,
      },
      {
        timeoutMs: options?.timeoutMs ?? Math.max(15000, this.timeoutMs),
        maxRetries: options?.maxRetries ?? 0,
      }
    );
  }

  async getVehicleTripDetails(vehicleId: number | string, options?: RequestOptions): Promise<any> {
    return this.post(
      'VehicleTripDetails_v2',
      {
        vehicleId: typeof vehicleId === 'string' ? parseInt(vehicleId, 10) : vehicleId,
      },
      options
    );
  }

  async listVehicles(regNo: string = ''): Promise<any> {
    return this.post('ListVehicles', {
      vehicleRegNo: regNo,
      deviceType: 'WEB',
    });
  }

  async getAllRoutes(): Promise<any> {
    return this.post('GetAllRouteList', {});
  }

  /**
   * Diagnostic check to test reachability of the BMTC server
   */
  async checkReachability(): Promise<{ reachable: boolean; latencyMs: number; error: string | null; status?: number }> {
    const startTime = Date.now();
    try {
      const res = await this.executePost('SearchRoute_v2', { routetext: '500' }, 0);
      const latencyMs = Date.now() - startTime;
      if (res.success) {
        return { reachable: true, latencyMs, error: null, status: res.status };
      }
      return {
        reachable: false,
        latencyMs,
        error: res.errorMessage || 'BMTC endpoint unreachable',
        status: res.status,
      };
    } catch (err: any) {
      return {
        reachable: false,
        latencyMs: Date.now() - startTime,
        error: err.message,
      };
    }
  }

  getLastError(): string | null {
    return this.lastError;
  }

  isReachable(): boolean {
    return this.isReachableState;
  }
}

export const bmtcApiClient = new BmtcApiClient();
export default bmtcApiClient;

