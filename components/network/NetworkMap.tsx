import React, { useEffect, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { NetworkMapProps, freshnessColor } from './networkMapShared';

let Maps: any = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  Maps = require('react-native-maps');
} catch {
  Maps = null;
}

const BENGALURU = { latitude: 12.9716, longitude: 77.5946, latitudeDelta: 0.25, longitudeDelta: 0.25 };

/** Native map (react-native-maps). Markers are keyed by vehicle id so they update in place. */
export default function NetworkMap({ vehicles, selectedVehicleId, onSelectVehicle, routeLines, stops, onSelectStop, focus, stopVariant = 'dot', selectedStopId, userLocation,
  mapType = 'standard', pois, onSelectPoi }: NetworkMapProps) {
  const mapRef = useRef<any>(null);

  useEffect(() => {
    const pts = (routeLines || []).flatMap(l => l.coords).map(([latitude, longitude]) => ({ latitude, longitude }));
    if (pts.length > 1 && mapRef.current) {
      mapRef.current.fitToCoordinates(pts, { edgePadding: { top: 40, bottom: 40, left: 40, right: 40 }, animated: true });
    }
  }, [routeLines]);

  useEffect(() => {
    if (routeLines?.length || stopVariant !== 'stand' || selectedStopId || !mapRef.current) return;
    const pts = (stops || []).map(s => ({ latitude: s.latitude, longitude: s.longitude }));
    if (userLocation) pts.push(userLocation);
    if (pts.length > 1) mapRef.current.fitToCoordinates(pts, { edgePadding: { top: 60, bottom: 60, left: 60, right: 60 }, animated: true });
  }, [stops, stopVariant]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (focus && mapRef.current) mapRef.current.animateToRegion({ ...focus, latitudeDelta: 0.03, longitudeDelta: 0.03 }, 400);
  }, [focus?.latitude, focus?.longitude]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!Maps?.default) {
    return (
      <View style={styles.fallback}>
        <Text style={styles.fallbackText}>Map component is not available in this build.</Text>
      </View>
    );
  }
  const { default: MapView, Marker, Polyline } = Maps;

  return (
    <MapView ref={mapRef} style={StyleSheet.absoluteFill} initialRegion={BENGALURU} showsUserLocation mapType={mapType === 'satellite' ? 'satellite' : 'standard'}>
      {(pois || []).map(p => (
        <Marker key={`poi-${p.id}`} coordinate={{ latitude: p.latitude, longitude: p.longitude }} title={p.label} onPress={() => onSelectPoi?.(p.id)}>
          <View style={[styles.poi, { borderColor: p.color }]}><Text style={{ fontSize: 13 }}>{p.emoji}</Text></View>
        </Marker>
      ))}
      {(routeLines || []).map((l, i) => (
        <Polyline key={`line-${i}`} coordinates={l.coords.map(([latitude, longitude]) => ({ latitude, longitude }))} strokeColor={l.color || '#1976D2'} strokeWidth={5} />
      ))}
      {(stops || []).map(s => (
        <Marker key={`stop-${s.id}`} coordinate={{ latitude: s.latitude, longitude: s.longitude }} title={s.name}
          pinColor={s.id === selectedStopId ? '#F28C28' : '#12355B'} onPress={() => onSelectStop?.(s)} accessibilityLabel={`Bus stop ${s.name}`} />
      ))}
      {vehicles.map(v => (
        <Marker
          key={v.vehicle_id}
          coordinate={{ latitude: v.latitude, longitude: v.longitude }}
          onPress={() => onSelectVehicle?.(v.vehicle_id)}
          accessibilityLabel={`Bus ${v.route_number || v.vehicle_number || v.vehicle_id}, ${v.freshness}`}
          zIndex={v.vehicle_id === selectedVehicleId ? 10 : 1}
        >
          <View style={[styles.bus, { backgroundColor: freshnessColor(v.freshness) }, v.vehicle_id === selectedVehicleId && styles.busSelected]}>
            <Text style={styles.busText}>{v.route_number || v.vehicle_number || 'Bus'}</Text>
          </View>
        </Marker>
      ))}
    </MapView>
  );
}

const styles = StyleSheet.create({
  fallback: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EEF2F5' },
  fallbackText: { color: '#5F6B76' },
  bus: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 8, borderWidth: 2, borderColor: '#fff' },
  busSelected: { borderColor: '#12355B', transform: [{ scale: 1.2 }] },
  busText: { color: '#fff', fontWeight: '800', fontSize: 11 },
  poi: { width: 28, height: 28, borderRadius: 14, backgroundColor: '#fff', borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
});
