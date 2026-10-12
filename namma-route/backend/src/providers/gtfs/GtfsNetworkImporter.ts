import fs from 'fs';
import path from 'path';
import readline from 'readline';
import prisma from '../../db/prisma';

export interface NetworkImportStats {
  agenciesCount: number;
  calendarsCount: number;
  stopsCount: number;
  routesCount: number;
  variantsCount: number;
  routeStopsCount: number;
  tripsCount: number;
  stopTimesCount: number;
  shapesCount: number;
  shapePointsCount: number;
  aliasesCount: number;
  faresCount: number;
  durationSeconds: number;
  errors: string[];
}

function parseCsvLine(line: string): string[] {
  const result: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === ',' && !inQuotes) {
      result.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  result.push(current);
  return result;
}

function escapeSql(val: string | number | null | undefined): string {
  if (val === null || val === undefined) return 'NULL';
  if (typeof val === 'number') return isNaN(val) ? 'NULL' : String(val);
  return `'${String(val).replace(/'/g, "''")}'`;
}

/**
 * PostgreSQL upsert for a batch of pre-escaped value tuples.
 * - Rows are de-duplicated by key inside the batch (Postgres rejects ON CONFLICT DO UPDATE touching the
 *   same row twice in one statement); the last occurrence wins, matching the old INSERT OR REPLACE.
 * - conflictCols must be a unique constraint from schema.prisma.
 */
async function upsertBatch(
  table: string,
  columns: string[],
  conflictCols: string[],
  rows: Array<{ key: string; values: string }>,
  updateCols: string[] = columns.filter((c) => c !== 'id' && !conflictCols.includes(c) && c !== 'createdAt')
): Promise<number> {
  if (rows.length === 0) return 0;
  const byKey = new Map<string, string>();
  for (const r of rows) byKey.set(r.key, r.values);
  const cols = columns.map((c) => `"${c}"`).join(', ');
  const conflict = conflictCols.map((c) => `"${c}"`).join(', ');
  const action = updateCols.length
    ? `DO UPDATE SET ${updateCols.map((c) => `"${c}" = EXCLUDED."${c}"`).join(', ')}`
    : 'DO NOTHING';
  const sql = `INSERT INTO "${table}" (${cols}) VALUES ${Array.from(byKey.values()).join(',')} ON CONFLICT (${conflict}) ${action};`;
  await prisma.$executeRawUnsafe(sql);
  return byKey.size;
}

async function upsertChunked(
  table: string,
  columns: string[],
  conflictCols: string[],
  rows: Array<{ key: string; values: string }>,
  chunkSize: number,
  updateCols?: string[]
): Promise<number> {
  let total = 0;
  for (let i = 0; i < rows.length; i += chunkSize) {
    total += await upsertBatch(table, columns, conflictCols, rows.slice(i, i + chunkSize), updateCols);
  }
  return total;
}

function sqlBool(v: boolean): string {
  return v ? 'TRUE' : 'FALSE';
}

function normalizeStopName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, ' ').replace(/\s+/g, ' ').trim();
}

function extractRouteFamily(shortName: string): string {
  if (/^KIA/i.test(shortName)) {
    const m = shortName.match(/^(KIA-[0-9A-Z]+)/i);
    return m ? m[1].toUpperCase() : 'KIA';
  }
  if (/^MF/i.test(shortName)) {
    const m = shortName.match(/^(MF-[0-9A-Z]+)/i);
    return m ? m[1].toUpperCase() : 'MF';
  }
  if (/^G-/i.test(shortName)) {
    return shortName.split(/[\s-_]/)[0].toUpperCase();
  }
  const m = shortName.match(/\b(\d+)\b/) || shortName.match(/(\d+)/);
  if (m) {
    return m[1];
  }
  return shortName.split(/[\s-_]/)[0].toUpperCase();
}

function determineServiceType(shortName: string, longName: string): string {
  const upper = `${shortName} ${longName}`.toUpperCase();
  if (upper.includes('KIA-') || upper.includes('VAYU VAJRA') || upper.includes('AIRPORT')) {
    return 'VAYU_VAJRA';
  }
  if (shortName.startsWith('V-') || upper.includes('VAJRA')) {
    return 'VAJRA';
  }
  if (shortName.startsWith('MF-') || upper.includes('METRO FEEDER')) {
    return 'METRO_FEEDER';
  }
  if (shortName.startsWith('G-') || upper.includes('BIG 10') || upper.includes('BIG10')) {
    return 'BIG10';
  }
  return 'ORDINARY';
}

const LANDMARK_ALIASES: Array<{
  names: string[];
  canonicalSearch: string;
}> = [
  {
    names: ['Majestic', 'Majestic Bus Stand', 'KBS', 'Kempegowda Bus Station', 'ಮೆಜೆಸ್ಟಿಕ್', 'ಕೆಂಪೇಗೌಡ ಬಸ್ ನಿಲ್ದಾಣ'],
    canonicalSearch: 'Kempegowda Bus Station',
  },
  {
    names: ['Central Silk Board', 'Silk Board', 'CSB', 'ಸಿಲ್ಕ್ ಬೋರ್ಡ್', 'ಸೆಂಟ್ರಲ್ ಸಿಲ್ಕ್ ಬೋರ್ಡ್'],
    canonicalSearch: 'Central Silk Board',
  },
  {
    names: ['Electronic City', 'ECity', 'EC', 'Electronic City 1st Phase', 'ಎಲೆಕ್ಟ್ರಾನಿಕ್ ಸಿಟಿ'],
    canonicalSearch: 'Electronic City',
  },
  {
    names: ['Shivajinagar', 'Shivaji Nagar', 'Shivajinagar Bus Station', 'ಶಿವಾಜಿನಗರ'],
    canonicalSearch: 'Shivajinagar',
  },
  {
    names: ['KR Market', 'K.R. Market', 'Market', 'Kalasipalya', 'ಕೆ ಆರ್ ಮಾರ್ಕೆಟ್', 'ಕಲಾಸಿಪಾಳ್ಯ'],
    canonicalSearch: 'K.R.Market',
  },
  {
    names: ['Hebbal', 'Hebbal Bus Station', 'Hebbal Flyover', 'ಹೆಬ್ಬಾಳ'],
    canonicalSearch: 'Hebbal',
  },
  {
    names: ['Whitefield', 'ITPB', 'Hope Farm', 'Kadugodi', 'ವೈಟ್‌ಫೀಲ್ಡ್', 'ಐಟಿಪಿಬಿ'],
    canonicalSearch: 'White Field',
  },
  {
    names: ['Banashankari', 'BSK', 'Banashankari TTMC', 'ಬನಶಂಕರಿ'],
    canonicalSearch: 'Banashankari',
  },
  {
    names: ['Yeshwanthpur', 'Yeshwantpur', 'YPR', 'Yeshwanthpur TTMC', 'ಯಶವಂತಪುರ'],
    canonicalSearch: 'Yeshwanthpur',
  },
  {
    names: ['Kengeri', 'Kengeri TTMC', 'Kengeri Bus Stand', 'ಕೆಂಗೇರಿ'],
    canonicalSearch: 'Kengeri',
  },
  {
    names: ['Anekal', 'Anekal Bus Stand', 'ಆನೇಕಲ್'],
    canonicalSearch: 'Anekal',
  },
  {
    names: ['Chandapura', 'Chandapura Circle', 'ಚಂದಾಪುರ'],
    canonicalSearch: 'Chandapura',
  },
  {
    names: ['Jayanagar', 'Jayanagar 4th Block', 'Jayanagar TTMC', 'ಜಯನಗರ'],
    canonicalSearch: 'Jayanagar',
  },
  {
    names: ['Shantinagar', 'Shanthi Nagar', 'Shantinagar TTMC', 'ಶಾಂತಿನಗರ'],
    canonicalSearch: 'Shantinagar',
  },
  {
    names: ['Domlur', 'Domlur TTMC', 'Domlur Flyover', 'ದೋಮ್ಲೂರು'],
    canonicalSearch: 'Domlur',
  },
  {
    names: ['Koramangala', 'Koramangala Water Tank', 'ಕೋರಮಂಗಲ'],
    canonicalSearch: 'Koramangala',
  },
  {
    names: ['HSR Layout', 'HSR', 'ಹೆಚ್ ಎಸ್ ಆರ್ ಲೇಔಟ್'],
    canonicalSearch: 'HSR Layout',
  },
  {
    names: ['BTM Layout', 'BTM', 'ಬಿಟಿಎಂ ಲೇಔಟ್'],
    canonicalSearch: 'BTM Layout',
  },
  {
    names: ['Marathahalli', 'Marathahalli Bridge', 'ಮಾರತ್ ಹಳ್ಳಿ'],
    canonicalSearch: 'Marathahalli',
  },
  {
    names: ['Tin Factory', 'KR Puram', 'K.R. Puram', 'ಟಿನ್ ಫ್ಯಾಕ್ಟರಿ', 'ಕೆ ಆರ್ ಪುರಂ'],
    canonicalSearch: 'Tin Factory',
  },
  {
    names: ['KIA', 'Airport', 'Kempegowda International Airport', 'Bengaluru Airport', 'ವಿಮಾನ ನಿಲ್ದಾಣ'],
    canonicalSearch: 'Kempegowda International Airport',
  },
];

export class GtfsNetworkImporter {
  /**
   * Imports the GTFS feed in data/gtfs into PostgreSQL.
   *
   * PostgreSQL enforces foreign keys, so rows are written parent-first:
   * Agency → ServiceCalendar → Stop → Shape → ShapePoint → Route → RouteVariant → RouteStop → Trip →
   * StopTime → StopAlias. Every write is an idempotent upsert on the table's unique key, so the
   * import can be re-run without duplicates. Rows whose references do not exist in the feed are
   * skipped and reported in `errors` (nothing is invented to satisfy a foreign key).
   */
  static async importCompleteNetwork(gtfsDir?: string): Promise<NetworkImportStats> {
    const targetDir = gtfsDir || path.resolve(__dirname, '../../../../data/gtfs');
    const startTime = Date.now();
    console.log(`[GtfsNetworkImporter] Starting complete network import from: ${targetDir}`);

    const stats: NetworkImportStats = {
      agenciesCount: 0,
      calendarsCount: 0,
      stopsCount: 0,
      routesCount: 0,
      variantsCount: 0,
      routeStopsCount: 0,
      tripsCount: 0,
      stopTimesCount: 0,
      shapesCount: 0,
      shapePointsCount: 0,
      aliasesCount: 0,
      faresCount: 0,
      durationSeconds: 0,
      errors: [],
    };
    const skipped = { routeStopsUnknownStop: 0, tripsUnknownRoute: 0, tripsUnknownService: 0, stopTimesUnknownTrip: 0, stopTimesUnknownStop: 0, variantsUnknownRoute: 0, badShapePoints: 0 };

    const nowIso = new Date().toISOString();
    const readLines = (file: string) =>
      readline.createInterface({ input: fs.createReadStream(file), crlfDelay: Infinity });

    // ----------------------------------------------------
    // 1. Agency
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 1/11: Ingesting Agency...');
    const agencyIds = new Set<string>();
    const agencyFile = path.join(targetDir, 'agency.txt');
    if (fs.existsSync(agencyFile)) {
      const agencyLines = fs.readFileSync(agencyFile, 'utf-8').split(/\r?\n/).filter(l => l.trim().length > 0);
      if (agencyLines.length > 1) {
        const headers = parseCsvLine(agencyLines[0].replace(/^﻿/, ''));
        const idIdx = headers.indexOf('agency_id');
        const nameIdx = headers.indexOf('agency_name');
        const urlIdx = headers.indexOf('agency_url');
        const tzIdx = headers.indexOf('agency_timezone');
        const langIdx = headers.indexOf('agency_lang');
        const phoneIdx = headers.indexOf('agency_phone');

        const rows: Array<{ key: string; values: string }> = [];
        for (let i = 1; i < agencyLines.length; i++) {
          const vals = parseCsvLine(agencyLines[i]);
          if (vals.length < 2) continue;
          const aId = vals[idIdx] || '1';
          agencyIds.add(aId);
          rows.push({
            key: aId,
            values: `(${escapeSql(aId)}, ${escapeSql(vals[nameIdx] || 'BMTC')}, ${escapeSql(vals[urlIdx] || 'https://mybmtc.karnataka.gov.in')}, ${escapeSql(vals[tzIdx] || 'Asia/Kolkata')}, ${escapeSql(vals[langIdx] || 'en')}, ${escapeSql(phoneIdx >= 0 ? vals[phoneIdx] || null : null)})`,
          });
        }
        stats.agenciesCount = await upsertBatch('Agency', ['id', 'name', 'url', 'timezone', 'lang', 'phone'], ['id'], rows);
      }
    }

    // ----------------------------------------------------
    // 2. Service Calendar
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 2/11: Ingesting Service Calendar...');
    const serviceIds = new Set<string>();
    const calFile = path.join(targetDir, 'calendar.txt');
    if (fs.existsSync(calFile)) {
      const calLines = fs.readFileSync(calFile, 'utf-8').split(/\r?\n/).filter(l => l.trim().length > 0);
      if (calLines.length > 1) {
        const headers = parseCsvLine(calLines[0].replace(/^﻿/, ''));
        const idx = (h: string) => headers.indexOf(h);
        const rows: Array<{ key: string; values: string }> = [];
        for (let i = 1; i < calLines.length; i++) {
          const vals = parseCsvLine(calLines[i]);
          const sId = vals[idx('service_id')];
          if (!sId) continue;
          serviceIds.add(sId);
          const day = (h: string) => sqlBool(vals[idx(h)] === '1');
          rows.push({
            key: sId,
            values: `(${escapeSql(sId)}, ${escapeSql(sId)}, ${day('monday')}, ${day('tuesday')}, ${day('wednesday')}, ${day('thursday')}, ${day('friday')}, ${day('saturday')}, ${day('sunday')}, ${escapeSql(vals[idx('start_date')] || null)}, ${escapeSql(vals[idx('end_date')] || null)})`,
          });
        }
        stats.calendarsCount = await upsertBatch(
          'ServiceCalendar',
          ['id', 'serviceId', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'startDate', 'endDate'],
          ['serviceId'],
          rows
        );
      }
    }

    // Kannada stop names (translations.txt)
    const kannadaTranslations = new Map<string, string>();
    const transFile = path.join(targetDir, 'translations.txt');
    if (fs.existsSync(transFile)) {
      let isFirst = true;
      let tblIdx = 0, fieldIdx = 1, recIdx = 2, langIdx = 3, transIdx = 4;
      for await (const line of readLines(transFile)) {
        if (isFirst) {
          const headers = parseCsvLine(line.replace(/^﻿/, ''));
          tblIdx = headers.indexOf('table_name');
          fieldIdx = headers.indexOf('field_name');
          recIdx = headers.indexOf('record_id');
          langIdx = headers.indexOf('language');
          transIdx = headers.indexOf('translation');
          isFirst = false;
          continue;
        }
        const vals = parseCsvLine(line);
        if (vals[tblIdx] === 'stops' && vals[fieldIdx] === 'stop_name' && vals[langIdx] === 'kn' && vals[recIdx]) {
          kannadaTranslations.set(vals[recIdx], vals[transIdx]);
        }
      }
      console.log(`[GtfsNetworkImporter] Loaded ${kannadaTranslations.size} Kannada translations.`);
    }

    // ----------------------------------------------------
    // 3. Stops
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 3/11: Ingesting Stops...');
    const stopsFile = path.join(targetDir, 'stops.txt');
    const stopMap = new Map<string, { id: string; name: string; lat: number; lon: number }>();
    if (fs.existsSync(stopsFile)) {
      const rows: Array<{ key: string; values: string }> = [];
      let isFirst = true;
      let idIdx = 3, nameIdx = 0, latIdx = 5, lonIdx = 6, descIdx = 4, zoneIdx = 2, platIdx = 8, parentIdx = 1;
      for await (const line of readLines(stopsFile)) {
        if (isFirst) {
          const headers = parseCsvLine(line.replace(/^﻿/, ''));
          idIdx = headers.indexOf('stop_id');
          nameIdx = headers.indexOf('stop_name');
          latIdx = headers.indexOf('stop_lat');
          lonIdx = headers.indexOf('stop_lon');
          descIdx = headers.indexOf('stop_desc');
          zoneIdx = headers.indexOf('zone_id');
          platIdx = headers.indexOf('platform_code');
          parentIdx = headers.indexOf('parent_station');
          isFirst = false;
          continue;
        }
        const vals = parseCsvLine(line);
        const stopId = vals[idIdx];
        const lat = parseFloat(vals[latIdx]);
        const lon = parseFloat(vals[lonIdx]);
        if (!stopId || isNaN(lat) || isNaN(lon)) continue;
        const name = vals[nameIdx] || stopId;
        stopMap.set(stopId, { id: stopId, name, lat, lon });
        rows.push({
          key: stopId,
          values: `(${escapeSql(stopId)}, ${escapeSql(stopId)}, ${escapeSql(name)}, ${escapeSql(kannadaTranslations.get(stopId) || null)}, ${escapeSql(normalizeStopName(name))}, ${escapeSql(vals[descIdx] || null)}, ${lat}, ${lon}, ${escapeSql(vals[zoneIdx] || null)}, ${escapeSql(platIdx >= 0 ? vals[platIdx] || null : null)}, ${escapeSql(parentIdx >= 0 ? vals[parentIdx] || null : null)}, ${escapeSql(nowIso)}, ${escapeSql(nowIso)})`,
        });
      }
      stats.stopsCount = await upsertChunked(
        'Stop',
        ['id', 'stopId', 'name', 'nameKannada', 'normalizedName', 'description', 'latitude', 'longitude', 'zoneId', 'platformCode', 'parentStation', 'createdAt', 'updatedAt'],
        ['stopId'],
        rows,
        2000
      );
      console.log(`[GtfsNetworkImporter] Ingested ${stats.stopsCount} stops.`);
    }

    // ----------------------------------------------------
    // 4. Shapes (geometry JSON) and 5. Shape points
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 4/11: Parsing shapes and building route geometries...');
    const shapesFile = path.join(targetDir, 'shapes.txt');
    const shapeCoordinates = new Map<string, [number, number][]>();
    if (fs.existsSync(shapesFile)) {
      let isFirst = true;
      let count = 0;
      for await (const line of readLines(shapesFile)) {
        if (isFirst) {
          isFirst = false;
          continue;
        }
        count++;
        // shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence,shape_dist_traveled
        const c1 = line.indexOf(',');
        const c2 = line.indexOf(',', c1 + 1);
        const c3 = line.indexOf(',', c2 + 1);
        if (c1 === -1 || c2 === -1) continue;
        const sId = line.substring(0, c1);
        const lat = parseFloat(line.substring(c1 + 1, c2));
        const lon = parseFloat(line.substring(c2 + 1, c3 === -1 ? line.length : c3));
        if (!isNaN(lat) && !isNaN(lon)) {
          let coords = shapeCoordinates.get(sId);
          if (!coords) {
            coords = [];
            shapeCoordinates.set(sId, coords);
          }
          coords.push([lat, lon]);
        }
      }
      console.log(`[GtfsNetworkImporter] Processed ${count} shape points across ${shapeCoordinates.size} shapes.`);

      const shapeRows = Array.from(shapeCoordinates.entries()).map(([sId, coords]) => ({
        key: sId,
        values: `(${escapeSql(sId)}, ${escapeSql(sId)}, ${coords.length}, ${escapeSql(JSON.stringify(coords))})`,
      }));
      stats.shapesCount = await upsertChunked('Shape', ['id', 'shapeId', 'pointsCount', 'geometry'], ['shapeId'], shapeRows, 500);
      console.log(`[GtfsNetworkImporter] Ingested ${stats.shapesCount} shapes.`);

      console.log('[GtfsNetworkImporter] Step 5/11: Streaming shape points...');
      let batch: Array<{ key: string; values: string }> = [];
      isFirst = true;
      let seqIdx = 3, distIdx = 4;
      for await (const line of readLines(shapesFile)) {
        if (isFirst) {
          const headers = parseCsvLine(line.replace(/^﻿/, ''));
          seqIdx = headers.indexOf('shape_pt_sequence');
          distIdx = headers.indexOf('shape_dist_traveled');
          isFirst = false;
          continue;
        }
        const vals = line.split(',');
        const sId = vals[0];
        const lat = parseFloat(vals[1]);
        const lon = parseFloat(vals[2]);
        const seq = parseInt(vals[seqIdx], 10);
        if (!sId || isNaN(lat) || isNaN(lon) || isNaN(seq) || !shapeCoordinates.has(sId)) {
          skipped.badShapePoints++;
          continue;
        }
        const dist = distIdx >= 0 && vals[distIdx] !== undefined && vals[distIdx] !== '' ? parseFloat(vals[distIdx]) : null;
        const key = `${sId}_${seq}`;
        batch.push({ key, values: `(${escapeSql(key)}, ${escapeSql(sId)}, ${lat}, ${lon}, ${seq}, ${escapeSql(dist)})` });
        if (batch.length >= 5000) {
          stats.shapePointsCount += await upsertBatch('ShapePoint', ['id', 'shapeId', 'latitude', 'longitude', 'sequence', 'distTraveled'], ['id'], batch);
          batch = [];
        }
      }
      stats.shapePointsCount += await upsertBatch('ShapePoint', ['id', 'shapeId', 'latitude', 'longitude', 'sequence', 'distTraveled'], ['id'], batch);
      console.log(`[GtfsNetworkImporter] Ingested ${stats.shapePointsCount} shape points.`);
    }

    // ----------------------------------------------------
    // Parse trips → unique variants (inserted after routes)
    // ----------------------------------------------------
    const tripsFile = path.join(targetDir, 'trips.txt');
    interface VariantMeta {
      variantId: string;
      routeId: string;
      variantCode: string;
      direction: number;
      shapeId: string | null;
      headsign: string | null;
      sampleTripId: string;
      tripCount: number;
    }
    interface TripRow {
      tripId: string;
      routeId: string;
      variantId: string;
      serviceId: string;
      headsign: string | null;
      direction: number;
      shapeId: string | null;
    }
    const variantsMap = new Map<string, VariantMeta>();
    const sampleTripToVariant = new Map<string, string>();
    const tripList: TripRow[] = [];

    if (fs.existsSync(tripsFile)) {
      let isFirst = true;
      let rIdx = 0, sIdx = 1, hIdx = 2, dIdx = 3, shIdx = 4, tIdx = 5;
      for await (const line of readLines(tripsFile)) {
        if (isFirst) {
          const headers = parseCsvLine(line.replace(/^﻿/, ''));
          rIdx = headers.indexOf('route_id');
          sIdx = headers.indexOf('service_id');
          hIdx = headers.indexOf('trip_headsign');
          dIdx = headers.indexOf('direction_id');
          shIdx = headers.indexOf('shape_id');
          tIdx = headers.indexOf('trip_id');
          isFirst = false;
          continue;
        }
        const vals = parseCsvLine(line);
        const tripId = vals[tIdx];
        const routeId = vals[rIdx];
        if (!tripId || !routeId) continue;

        const serviceId = vals[sIdx] || '';
        const headsign = vals[hIdx] || null;
        const direction = parseInt(vals[dIdx] || '0', 10) || 0;
        const shapeId = vals[shIdx] || null;
        const variantCode = shapeId || `${direction}_${headsign || 'default'}`;
        const variantId = `${routeId}__${variantCode}`;

        if (!variantsMap.has(variantId)) {
          variantsMap.set(variantId, { variantId, routeId, variantCode, direction, shapeId, headsign, sampleTripId: tripId, tripCount: 0 });
          sampleTripToVariant.set(tripId, variantId);
        }
        variantsMap.get(variantId)!.tripCount++;
        tripList.push({ tripId, routeId, variantId, serviceId, headsign, direction, shapeId });
      }
      console.log(`[GtfsNetworkImporter] Found ${tripList.length} trips across ${variantsMap.size} unique route variants.`);
    }

    // Ordered stop sequence of each variant's sample trip (first pass over stop_times, no writes)
    const stopTimesFile = path.join(targetDir, 'stop_times.txt');
    const variantStopSequences = new Map<string, Array<{ stopId: string; seq: number }>>();
    let stHeaders = { tIdx: 0, aIdx: 1, dIdx: 2, sIdx: 3, seqIdx: 4 };
    if (fs.existsSync(stopTimesFile)) {
      let isFirst = true;
      for await (const line of readLines(stopTimesFile)) {
        if (isFirst) {
          const headers = parseCsvLine(line.replace(/^﻿/, ''));
          stHeaders = {
            tIdx: headers.indexOf('trip_id'),
            aIdx: headers.indexOf('arrival_time'),
            dIdx: headers.indexOf('departure_time'),
            sIdx: headers.indexOf('stop_id'),
            seqIdx: headers.indexOf('stop_sequence'),
          };
          isFirst = false;
          continue;
        }
        const vals = parseCsvLine(line);
        const variantId = sampleTripToVariant.get(vals[stHeaders.tIdx]);
        if (!variantId || !vals[stHeaders.sIdx]) continue;
        let list = variantStopSequences.get(variantId);
        if (!list) {
          list = [];
          variantStopSequences.set(variantId, list);
        }
        list.push({ stopId: vals[stHeaders.sIdx], seq: parseInt(vals[stHeaders.seqIdx] || '1', 10) });
      }
    }

    // Variant endpoints (origin/destination strictly from the ordered stop sequence)
    const routePrimaryVariants = new Map<string, Map<number, { originName: string; destName: string }>>();
    for (const [variantId, vMeta] of variantsMap.entries()) {
      const seqs = variantStopSequences.get(variantId) || [];
      seqs.sort((a, b) => a.seq - b.seq);
      if (seqs.length > 0) {
        const originName = stopMap.get(seqs[0].stopId)?.name;
        const destName = stopMap.get(seqs[seqs.length - 1].stopId)?.name;
        if (originName && destName) {
          if (!routePrimaryVariants.has(vMeta.routeId)) routePrimaryVariants.set(vMeta.routeId, new Map());
          const dm = routePrimaryVariants.get(vMeta.routeId)!;
          if (!dm.has(vMeta.direction)) dm.set(vMeta.direction, { originName, destName });
        }
      }
    }

    // ----------------------------------------------------
    // 6. Routes
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 6/11: Ingesting Routes with data-driven endpoints and families...');
    const routesFile = path.join(targetDir, 'routes.txt');
    const routeIds = new Set<string>();
    if (fs.existsSync(routesFile)) {
      const rows: Array<{ key: string; values: string }> = [];
      let isFirst = true;
      let idIdx = 4, shortIdx = 1, longIdx = 0, aIdx = 2, typeIdx = 3;
      for await (const line of readLines(routesFile)) {
        if (isFirst) {
          const headers = parseCsvLine(line.replace(/^﻿/, ''));
          idIdx = headers.indexOf('route_id');
          shortIdx = headers.indexOf('route_short_name');
          longIdx = headers.indexOf('route_long_name');
          aIdx = headers.indexOf('agency_id');
          typeIdx = headers.indexOf('route_type');
          isFirst = false;
          continue;
        }
        const vals = parseCsvLine(line);
        const routeId = vals[idIdx];
        if (!routeId) continue;

        const shortName = vals[shortIdx] || routeId;
        const rawLongName = vals[longIdx] || shortName;
        const rawAgency = vals[aIdx] || null;
        // Only reference an agency that exists in agency.txt; otherwise leave it NULL
        const agencyId = rawAgency && agencyIds.has(rawAgency) ? rawAgency : agencyIds.size === 1 && !rawAgency ? Array.from(agencyIds)[0] : null;
        const routeType = parseInt(vals[typeIdx] || '3', 10) || 3;

        const dirMap = routePrimaryVariants.get(routeId);
        let origin: string | null = null;
        let destination: string | null = null;
        if (dirMap?.has(0)) {
          origin = dirMap.get(0)!.originName;
          destination = dirMap.get(0)!.destName;
        } else if (dirMap?.has(1)) {
          origin = dirMap.get(1)!.destName;
          destination = dirMap.get(1)!.originName;
        }

        const longName = origin && destination ? `${origin} ⇄ ${destination}` : rawLongName;
        routeIds.add(routeId);
        rows.push({
          key: routeId,
          values: `(${escapeSql(routeId)}, ${escapeSql(routeId)}, ${escapeSql(shortName)}, ${escapeSql(longName)}, ${escapeSql(shortName)}, ${escapeSql(extractRouteFamily(shortName))}, ${escapeSql(determineServiceType(shortName, rawLongName))}, ${routeType}, ${escapeSql(agencyId)}, ${escapeSql(origin)}, ${escapeSql(destination)}, NULL, NULL, ${escapeSql(nowIso)}, ${escapeSql(nowIso)})`,
        });
      }
      stats.routesCount = await upsertChunked(
        'Route',
        ['id', 'routeId', 'routeShortName', 'routeLongName', 'routeDisplayName', 'routeFamily', 'serviceType', 'routeType', 'agencyId', 'origin', 'destination', 'color', 'textColor', 'createdAt', 'updatedAt'],
        ['routeId'],
        rows,
        1000
      );
      console.log(`[GtfsNetworkImporter] Ingested ${stats.routesCount} routes.`);
    }

    // ----------------------------------------------------
    // 7. Route variants  8. Route stops
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 7/11: Ingesting Route Variants...');
    const variantRows: Array<{ key: string; values: string }> = [];
    const routeStopRows: Array<{ key: string; values: string }> = [];
    const insertedVariants = new Set<string>();
    for (const [variantId, vMeta] of variantsMap.entries()) {
      if (!routeIds.has(vMeta.routeId)) {
        skipped.variantsUnknownRoute++;
        continue;
      }
      const seqs = (variantStopSequences.get(variantId) || []).filter((st) => {
        if (stopMap.has(st.stopId)) return true;
        skipped.routeStopsUnknownStop++;
        return false;
      });
      const originStopId = seqs.length ? seqs[0].stopId : null;
      const destStopId = seqs.length ? seqs[seqs.length - 1].stopId : null;
      const originName = originStopId ? stopMap.get(originStopId)!.name : null;
      const destName = destStopId ? stopMap.get(destStopId)!.name : null;
      const dirName = originName && destName ? `${originName} → ${destName}` : vMeta.headsign || null;
      const hasShape = !!vMeta.shapeId && shapeCoordinates.has(vMeta.shapeId);
      const geom = hasShape ? JSON.stringify(shapeCoordinates.get(vMeta.shapeId!)) : null;

      insertedVariants.add(variantId);
      variantRows.push({
        key: variantId,
        values: `(${escapeSql(variantId)}, ${escapeSql(vMeta.routeId)}, ${escapeSql(vMeta.variantCode)}, ${vMeta.direction}, ${escapeSql(dirName)}, ${escapeSql(originStopId)}, ${escapeSql(destStopId)}, ${escapeSql(originName)}, ${escapeSql(destName)}, ${escapeSql(hasShape ? vMeta.shapeId : null)}, ${escapeSql(geom)}, NULL, ${seqs.length})`,
      });
      for (const st of seqs) {
        routeStopRows.push({
          key: `${variantId}_${st.seq}`,
          values: `(${escapeSql(`${variantId}_${st.seq}`)}, ${escapeSql(variantId)}, ${escapeSql(st.stopId)}, ${st.seq}, NULL)`,
        });
      }
    }
    stats.variantsCount = await upsertChunked(
      'RouteVariant',
      ['id', 'routeId', 'variantCode', 'direction', 'directionName', 'originStopId', 'destinationStopId', 'originName', 'destinationName', 'shapeId', 'geometry', 'totalDistanceMeters', 'stopCount'],
      ['routeId', 'variantCode'],
      variantRows,
      200
    );
    console.log(`[GtfsNetworkImporter] Ingested ${stats.variantsCount} route variants.`);

    console.log('[GtfsNetworkImporter] Step 8/11: Ingesting Route Stops...');
    stats.routeStopsCount = await upsertChunked(
      'RouteStop',
      ['id', 'variantId', 'stopId', 'stopSequence', 'distanceTraveled'],
      ['variantId', 'stopSequence'],
      routeStopRows,
      2500
    );
    console.log(`[GtfsNetworkImporter] Ingested ${stats.routeStopsCount} route stops.`);

    // ----------------------------------------------------
    // 9. Trips
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 9/11: Ingesting Trips...');
    const insertedTrips = new Set<string>();
    const tripRows: Array<{ key: string; values: string }> = [];
    for (const t of tripList) {
      if (!routeIds.has(t.routeId) || !insertedVariants.has(t.variantId)) {
        skipped.tripsUnknownRoute++;
        continue;
      }
      if (!serviceIds.has(t.serviceId)) {
        skipped.tripsUnknownService++;
        continue;
      }
      insertedTrips.add(t.tripId);
      tripRows.push({
        key: t.tripId,
        values: `(${escapeSql(t.tripId)}, ${escapeSql(t.tripId)}, ${escapeSql(t.routeId)}, ${escapeSql(t.variantId)}, ${escapeSql(t.serviceId)}, ${escapeSql(t.headsign)}, ${t.direction}, ${escapeSql(t.shapeId)})`,
      });
    }
    stats.tripsCount = await upsertChunked(
      'Trip',
      ['id', 'tripId', 'routeId', 'variantId', 'serviceId', 'tripHeadsign', 'direction', 'shapeId'],
      ['tripId'],
      tripRows,
      2500
    );
    console.log(`[GtfsNetworkImporter] Ingested ${stats.tripsCount} trips.`);

    // ----------------------------------------------------
    // 10. Stop times (second streaming pass, after trips exist)
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 10/11: Streaming stop times...');
    if (fs.existsSync(stopTimesFile)) {
      let isFirst = true;
      let batch: Array<{ key: string; values: string }> = [];
      const cols = ['id', 'tripId', 'stopId', 'stopSequence', 'arrivalTime', 'departureTime', 'pickupType', 'dropOffType'];
      for await (const line of readLines(stopTimesFile)) {
        if (isFirst) {
          isFirst = false;
          continue;
        }
        const vals = parseCsvLine(line);
        const tripId = vals[stHeaders.tIdx];
        const stopId = vals[stHeaders.sIdx];
        if (!tripId || !stopId) continue;
        if (!insertedTrips.has(tripId)) {
          skipped.stopTimesUnknownTrip++;
          continue;
        }
        if (!stopMap.has(stopId)) {
          skipped.stopTimesUnknownStop++;
          continue;
        }
        const seq = parseInt(vals[stHeaders.seqIdx] || '1', 10);
        const key = `${tripId}_${seq}`;
        batch.push({
          key,
          values: `(${escapeSql(key)}, ${escapeSql(tripId)}, ${escapeSql(stopId)}, ${seq}, ${escapeSql(vals[stHeaders.aIdx] || '')}, ${escapeSql(vals[stHeaders.dIdx] || '')}, 0, 0)`,
        });
        if (batch.length >= 5000) {
          stats.stopTimesCount += await upsertBatch('StopTime', cols, ['id'], batch);
          batch = [];
          if (stats.stopTimesCount % 250000 < 5000) {
            console.log(`[GtfsNetworkImporter]   ... ${stats.stopTimesCount} stop times`);
          }
        }
      }
      stats.stopTimesCount += await upsertBatch('StopTime', cols, ['id'], batch);
      console.log(`[GtfsNetworkImporter] Ingested ${stats.stopTimesCount} stop times.`);
    }

    // ----------------------------------------------------
    // 11. Landmark aliases, DataSource and DataImport
    // ----------------------------------------------------
    console.log('[GtfsNetworkImporter] Step 11/11: Seeding landmark aliases and recording the import...');
    const aliasRows: Array<{ key: string; values: string }> = [];
    let aliasCounter = 1;
    for (const landmark of LANDMARK_ALIASES) {
      const searchNorm = normalizeStopName(landmark.canonicalSearch);
      let canonicalStopId: string | null = null;
      for (const [sId, s] of stopMap.entries()) {
        const norm = normalizeStopName(s.name);
        if (norm === searchNorm || norm.startsWith(searchNorm)) {
          canonicalStopId = sId;
          break;
        }
      }
      if (!canonicalStopId) continue;
      for (const alias of landmark.names) {
        const aliasId = `alias_${aliasCounter++}`;
        const lang = /[^\u0000-\u007F]/.test(alias) ? 'kn' : 'en';
        aliasRows.push({
          key: aliasId,
          values: `(${escapeSql(aliasId)}, ${escapeSql(alias)}, ${escapeSql(normalizeStopName(alias))}, ${escapeSql(canonicalStopId)}, ${escapeSql(lang)}, 'LANDMARK_SEED', 1.0)`,
        });
      }
    }
    stats.aliasesCount = await upsertBatch('StopAlias', ['id', 'alias', 'normalizedAlias', 'canonicalStopId', 'language', 'source', 'confidence'], ['id'], aliasRows);
    console.log(`[GtfsNetworkImporter] Seeded ${stats.aliasesCount} landmark stop aliases.`);

    // Fares (fare_attributes + fare_rules): zone-to-zone prices from the feed, stored in the existing
    // Fare table (originStage/destStage = GTFS zone ids). route_id is kept only when the route exists.
    const fareAttrFile = path.join(targetDir, 'fare_attributes.txt');
    const fareRulesFile = path.join(targetDir, 'fare_rules.txt');
    if (fs.existsSync(fareAttrFile) && fs.existsSync(fareRulesFile)) {
      const prices = new Map<string, { price: number; currency: string }>();
      const attrLines = fs.readFileSync(fareAttrFile, 'utf-8').split(/\r?\n/).filter((l) => l.trim());
      const ah = parseCsvLine(attrLines[0].replace(/^\uFEFF/, ''));
      for (let i = 1; i < attrLines.length; i++) {
        const v = parseCsvLine(attrLines[i]);
        const price = parseFloat(v[ah.indexOf('price')]);
        if (!isNaN(price)) prices.set(v[ah.indexOf('fare_id')], { price, currency: v[ah.indexOf('currency_type')] || 'INR' });
      }
      let isFirst = true;
      let fi = 0, ri = 1, oi = 2, di = 3;
      let batch: Array<{ key: string; values: string }> = [];
      for await (const line of readLines(fareRulesFile)) {
        if (isFirst) {
          const h = parseCsvLine(line.replace(/^\uFEFF/, ''));
          fi = h.indexOf('fare_id'); ri = h.indexOf('route_id'); oi = h.indexOf('origin_id'); di = h.indexOf('destination_id');
          isFirst = false;
          continue;
        }
        const v = parseCsvLine(line);
        const attr = prices.get(v[fi]);
        const origin = v[oi];
        const dest = v[di];
        if (!attr || !origin || !dest) continue;
        const routeId = v[ri] && routeIds.has(v[ri]) ? v[ri] : null;
        const key = `fare_${routeId || 'all'}_${origin}_${dest}`;
        batch.push({ key, values: `(${escapeSql(key)}, ${escapeSql(routeId)}, ${escapeSql(origin)}, ${escapeSql(dest)}, ${attr.price}, ${escapeSql(attr.currency)})` });
        if (batch.length >= 5000) {
          stats.faresCount += await upsertBatch('Fare', ['id', 'routeId', 'originStage', 'destStage', 'fareAmount', 'currency'], ['id'], batch);
          batch = [];
        }
      }
      stats.faresCount += await upsertBatch('Fare', ['id', 'routeId', 'originStage', 'destStage', 'fareAmount', 'currency'], ['id'], batch);
      console.log(`[GtfsNetworkImporter] Ingested ${stats.faresCount} zone fares.`);
    }

    await upsertBatch(
      'DataSource',
      ['id', 'name', 'url', 'version', 'type', 'status', 'createdAt', 'updatedAt'],
      ['name'],
      [{
        key: 'bmtc-gtfs',
        values: `('bmtc_gtfs_static', 'bmtc-gtfs', 'https://github.com/Vonter/bmtc-gtfs', '20260907', 'GTFS_STATIC', 'ACTIVE', ${escapeSql(nowIso)}, ${escapeSql(nowIso)})`,
      }]
    );

    for (const [k, v] of Object.entries(skipped)) {
      if (v > 0) stats.errors.push(`Skipped ${v} rows: ${k}`);
    }
    stats.durationSeconds = (Date.now() - startTime) / 1000;

    const recordCountsJson = JSON.stringify({
      agencies: stats.agenciesCount,
      calendars: stats.calendarsCount,
      stops: stats.stopsCount,
      routes: stats.routesCount,
      variants: stats.variantsCount,
      routeStops: stats.routeStopsCount,
      trips: stats.tripsCount,
      stopTimes: stats.stopTimesCount,
      shapes: stats.shapesCount,
      shapePoints: stats.shapePointsCount,
      aliases: stats.aliasesCount,
      fares: stats.faresCount,
    });
    const importId = `import_${Date.now()}`;
    await prisma.$executeRawUnsafe(
      `INSERT INTO "DataImport" ("id", "sourceName", "version", "downloadedAt", "processedAt", "recordCounts", "checksum", "status", "report") VALUES (${escapeSql(importId)}, 'bmtc-gtfs', '20260907', ${escapeSql(nowIso)}, ${escapeSql(new Date().toISOString())}, ${escapeSql(recordCountsJson)}, NULL, 'COMPLETED', ${escapeSql(JSON.stringify(stats))});`
    );

    console.log(`[GtfsNetworkImporter] Ingestion SUCCESSFUL in ${stats.durationSeconds.toFixed(2)} seconds!`);
    console.log(recordCountsJson);
    if (stats.errors.length) console.log(`[GtfsNetworkImporter] Notes: ${stats.errors.join('; ')}`);
    return stats;
  }
}
