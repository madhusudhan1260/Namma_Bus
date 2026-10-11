import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { NetworkMapProps, freshnessColor } from './networkMapShared';

const BENGALURU: L.LatLngExpression = [12.9716, 77.5946];

function busIcon(label: string, color: string, selected: boolean): L.DivIcon {
  const size = selected ? 34 : 26;
  const safe = label.replace(/[<>&"]/g, '');
  return L.divIcon({
    className: '',
    iconSize: [size + 40, size],
    iconAnchor: [size / 2, size / 2],
    html:
      `<div style="display:flex;align-items:center;gap:4px;transform:translate(0,0)">` +
      `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:${selected ? 3 : 2}px solid #fff;` +
      `box-shadow:0 1px 4px rgba(15,23,42,.45);display:flex;align-items:center;justify-content:center;color:#fff;font:700 11px sans-serif">🚌</div>` +
      `<span style="background:#12355B;color:#fff;font:700 11px sans-serif;padding:1px 5px;border-radius:6px;white-space:nowrap">${safe}</span></div>`,
  });
}

function standIcon(name: string, selected: boolean): L.DivIcon {
  const size = selected ? 34 : 26;
  const safe = name.replace(/[<>&"]/g, '');
  return L.divIcon({
    className: '',
    iconSize: [size, size + 8],
    iconAnchor: [size / 2, size + 6],
    html:
      `<div title="${safe}" style="display:flex;flex-direction:column;align-items:center;${selected ? 'animation:nbBounce .5s ease-out' : ''}">` +
      `<div style="width:${size}px;height:${size}px;border-radius:9px;background:${selected ? '#F28C28' : '#12355B'};border:2px solid #fff;` +
      `box-shadow:0 2px 6px rgba(15,23,42,.4);display:flex;align-items:center;justify-content:center;color:#fff;font:800 ${selected ? 15 : 12}px sans-serif">🚏</div>` +
      `<div style="width:2px;height:7px;background:${selected ? '#F28C28' : '#12355B'}"></div></div>`,
  });
}

const youIcon = L.divIcon({
  className: '',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
  html:
    '<div style="position:relative;width:22px;height:22px">' +
    '<div style="position:absolute;inset:0;border-radius:50%;background:rgba(25,118,210,.25);animation:nbPing 1.6s ease-out infinite"></div>' +
    '<div style="position:absolute;left:5px;top:5px;width:12px;height:12px;border-radius:50%;background:#1976D2;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div></div>',
});

// Keyframes for the stand bounce and the "you are here" ping (injected once)
if (typeof document !== 'undefined' && !document.getElementById('nb-map-keyframes')) {
  const style = document.createElement('style');
  style.id = 'nb-map-keyframes';
  style.textContent =
    '@keyframes nbPing{0%{transform:scale(.6);opacity:.9}100%{transform:scale(2.2);opacity:0}}' +
    '@keyframes nbBounce{0%{transform:translateY(-12px)}60%{transform:translateY(2px)}100%{transform:translateY(0)}}' +
    '@media (prefers-reduced-motion: reduce){[style*="nbPing"],[style*="nbBounce"]{animation:none!important}}' +
    '@media (max-width: 899px){.leaflet-bottom.leaflet-right{margin-bottom:28px}}';
  document.head.appendChild(style);
}

/**
 * Web map (Leaflet + OpenStreetMap tiles). The map is created once; markers are updated in place on
 * every poll (no re-creation), and every valid bus is drawn — there is no count limit.
 */
const TILES = {
  standard: { url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', attribution: '&copy; OpenStreetMap contributors', maxZoom: 19 },
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics', maxZoom: 19,
  },
};

function poiIcon(emoji: string, color: string): L.DivIcon {
  return L.divIcon({
    className: '',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    // Filled with the category colour so the pin stays visible even where emoji fonts are missing
    html: `<div style="width:28px;height:28px;border-radius:50%;background:${color};border:2.5px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);` +
      `display:flex;align-items:center;justify-content:center;font-size:13px;line-height:1">${emoji}</div>`,
  });
}

export default function NetworkMap({ vehicles, selectedVehicleId, onSelectVehicle, routeLines, stops, onSelectStop, focus, stopVariant = 'dot', selectedStopId, userLocation,
  mapType = 'standard', pois, onSelectPoi }: NetworkMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersRef = useRef<Map<string, { marker: L.Marker; key: string }>>(new Map());
  const linesRef = useRef<L.LayerGroup | null>(null);
  const stopsRef = useRef<L.LayerGroup | null>(null);
  const onSelectRef = useRef(onSelectVehicle);
  onSelectRef.current = onSelectVehicle;
  const onStopRef = useRef(onSelectStop);
  onStopRef.current = onSelectStop;
  const youRef = useRef<L.Marker | null>(null);
  const tileRef = useRef<L.TileLayer | null>(null);
  const poiRef = useRef<L.LayerGroup | null>(null);
  const onPoiRef = useRef(onSelectPoi);
  onPoiRef.current = onSelectPoi;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: false }).setView(BENGALURU, 12);
    L.control.zoom({ position: 'bottomright' }).addTo(map); // keeps the top-left free for the Map / Satellite switch
    tileRef.current = L.tileLayer(TILES[mapType].url, { maxZoom: TILES[mapType].maxZoom, attribution: TILES[mapType].attribution }).addTo(map);
    linesRef.current = L.layerGroup().addTo(map);
    poiRef.current = L.layerGroup().addTo(map);
    stopsRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    // Container may size after first paint, and panels / sheets can resize it later: always re-measure
    setTimeout(() => map.invalidateSize(), 50);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => map.invalidateSize()) : null;
    if (ro && containerRef.current) ro.observe(containerRef.current);
    return () => {
      ro?.disconnect();
      map.remove();
      mapRef.current = null;
      markersRef.current.clear();
    };
  }, []);

  // Buses: add / update / remove in place
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const seen = new Set<string>();
    for (const v of vehicles) {
      seen.add(v.vehicle_id);
      const selected = v.vehicle_id === selectedVehicleId;
      const label = v.route_number || v.vehicle_number || v.vehicle_id;
      const key = `${label}|${v.freshness}|${selected}`;
      const existing = markersRef.current.get(v.vehicle_id);
      if (existing) {
        existing.marker.setLatLng([v.latitude, v.longitude]);
        if (existing.key !== key) {
          existing.marker.setIcon(busIcon(label, freshnessColor(v.freshness), selected));
          existing.marker.setZIndexOffset(selected ? 1000 : 0);
          existing.key = key;
        }
      } else {
        const marker = L.marker([v.latitude, v.longitude], {
          icon: busIcon(label, freshnessColor(v.freshness), selected),
          keyboard: true,
          title: `Bus ${label}`,
          zIndexOffset: selected ? 1000 : 0,
        })
          .on('click', () => onSelectRef.current?.(v.vehicle_id))
          .addTo(map);
        markersRef.current.set(v.vehicle_id, { marker, key });
      }
    }
    for (const [id, m] of markersRef.current.entries()) {
      if (!seen.has(id)) {
        m.marker.remove();
        markersRef.current.delete(id);
      }
    }
  }, [vehicles, selectedVehicleId]);

  // Route geometry + stops
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !linesRef.current || !stopsRef.current) return;
    linesRef.current.clearLayers();
    stopsRef.current.clearLayers();
    const bounds: L.LatLngExpression[] = [];
    for (const line of routeLines || []) {
      if (line.coords.length < 2) continue;
      L.polyline(line.coords, { color: line.color || '#1976D2', weight: 5, opacity: 0.85 }).addTo(linesRef.current);
      bounds.push(...line.coords);
    }
    for (const s of stops || []) {
      if (stopVariant === 'stand') {
        L.marker([s.latitude, s.longitude], { icon: standIcon(s.name, s.id === selectedStopId), keyboard: true, title: s.name,
          zIndexOffset: s.id === selectedStopId ? 900 : 0 })
          .on('click', () => onStopRef.current?.(s))
          .addTo(stopsRef.current);
      } else {
        L.circleMarker([s.latitude, s.longitude], { radius: 5, color: '#12355B', weight: 2, fillColor: '#fff', fillOpacity: 1 })
          .bindTooltip(s.name)
          .on('click', () => onStopRef.current?.(s))
          .addTo(stopsRef.current);
      }
      if (!routeLines?.length) bounds.push([s.latitude, s.longitude]);
    }
    if (userLocation && stopVariant === 'stand') bounds.push([userLocation.latitude, userLocation.longitude]);
    if (bounds.length > 1 && !selectedStopId) map.fitBounds(L.latLngBounds(bounds), { padding: [40, 40], maxZoom: 17 });
  }, [routeLines, stops, stopVariant, selectedStopId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Map / Satellite
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    tileRef.current?.remove();
    tileRef.current = L.tileLayer(TILES[mapType].url, { maxZoom: TILES[mapType].maxZoom, attribution: TILES[mapType].attribution }).addTo(map);
    tileRef.current.bringToBack();
  }, [mapType]);

  // Points of interest (facilities, journey start / end)
  useEffect(() => {
    const layer = poiRef.current;
    const map = mapRef.current;
    if (!layer || !map) return;
    layer.clearLayers();
    for (const p of pois || []) {
      L.marker([p.latitude, p.longitude], { icon: poiIcon(p.emoji, p.color), title: p.label, keyboard: true, zIndexOffset: 800 })
        .bindTooltip(p.label)
        .on('click', () => onPoiRef.current?.(p.id))
        .addTo(layer);
    }
    if ((pois || []).length > 1 && !(routeLines || []).length) {
      map.fitBounds(L.latLngBounds((pois || []).map(p => [p.latitude, p.longitude] as L.LatLngExpression)), { padding: [50, 50], maxZoom: 17 });
    }
  }, [pois]); // eslint-disable-line react-hooks/exhaustive-deps

  // "You are here"
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    youRef.current?.remove();
    youRef.current = userLocation
      ? L.marker([userLocation.latitude, userLocation.longitude], { icon: youIcon, interactive: false, zIndexOffset: 1200 }).addTo(map)
      : null;
  }, [userLocation?.latitude, userLocation?.longitude]); // eslint-disable-line react-hooks/exhaustive-deps

  // Focus on a point (selected bus or stop)
  useEffect(() => {
    if (focus && mapRef.current) mapRef.current.flyTo([focus.latitude, focus.longitude], Math.max(mapRef.current.getZoom(), 16), { duration: 0.6 });
  }, [focus?.latitude, focus?.longitude]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: 280 }} aria-label={stopVariant === 'stand' ? 'Map of nearby BMTC bus stops' : 'Map of Bengaluru with BMTC buses'} />;
}
