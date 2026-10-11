import React, { useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useAccessT } from '../../constants/accessI18n';
import { useTransit } from '../../context/TransitContext';
import { NetworkVehicle } from '../../types/network';
import NetworkMap from '../network/NetworkMap';
import { MapPoi } from '../network/networkMapShared';
import { NetworkBusSheet } from '../network/NetworkBusSheet';
import { Pulse } from '../ui/motion';

/**
 * Map showing live BMTC buses (all of them, or a filtered set), with optional route lines / pins, tap-a-bus
 * details and a pulsing "N live buses" badge. Positions come only from the BMTC feed.
 */
export function LiveBusesMap({ vehicles, live, mapType, routeLines, pois, focus, selectedId, onSelect, stops, onSelectPoi }: {
  vehicles: NetworkVehicle[];
  live: boolean;
  mapType: 'standard' | 'satellite';
  routeLines?: { coords: [number, number][]; color?: string }[];
  pois?: MapPoi[];
  focus?: { latitude: number; longitude: number } | null;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  stops?: any[];
  onSelectPoi?: (id: string) => void;
}) {
  const { a } = useAccessT();
  const { preferredLanguage: lang } = useTransit();
  const [ownSel, setOwnSel] = useState<string | null>(null);
  const sel = selectedId !== undefined ? selectedId : ownSel;
  const setSel = onSelect || setOwnSel;
  const selected = useMemo(() => vehicles.find(v => v.vehicle_id === sel) || null, [vehicles, sel]);
  return (
    <View style={{ flex: 1 }}>
      <NetworkMap vehicles={vehicles} selectedVehicleId={sel} onSelectVehicle={id => setSel(id)} routeLines={routeLines} pois={pois} mapType={mapType}
        stops={stops} stopVariant="stand" onSelectPoi={onSelectPoi}
        focus={focus || (selected ? { latitude: selected.latitude, longitude: selected.longitude } : null)} />
      <View style={styles.badge} pointerEvents="none">
        <Pulse style={{ width: 10, height: 10, marginRight: 8 }}>
          <View style={[styles.dot, { backgroundColor: live && vehicles.length ? '#168A45' : '#8A959F' }]} />
        </Pulse>
        <Text style={styles.badgeText}>{live ? a('fsLiveCount', { n: vehicles.length }) : a('mapFeedUnavailable')}</Text>
      </View>
      <NetworkBusSheet vehicle={selected} missing={false} lang={lang} onClose={() => setSel(null)} />
    </View>
  );
}

const styles = StyleSheet.create({
  badge: { position: 'absolute', bottom: 16, left: 12, flexDirection: 'row', alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.95)', borderRadius: 20,
    paddingHorizontal: 12, paddingVertical: 7, zIndex: 500, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 4 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  badgeText: { fontSize: 12, fontWeight: '800', color: '#1E1E24' },
});
