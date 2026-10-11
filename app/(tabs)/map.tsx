import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { COLORS, SPACING } from '../../constants/theme';
import { useTransit } from '../../context/TransitContext';
import { t } from '../../constants/i18n';
import { NetworkLiveView } from '../../components/network/NetworkLiveView';

/** Live map of the real BMTC network (routes, stops and buses from the BMTC feed via NammaRoute). */
export default function MapScreen() {
  const mapParams = useLocalSearchParams<{ vehicle?: string; route?: string; search?: string }>();
  const { preferredLanguage } = useTransit();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Ionicons name="map" size={22} color={COLORS.primary} />
        <Text style={styles.title} accessibilityRole="header">{t('netTitle', preferredLanguage)}</Text>
      </View>
      <NetworkLiveView
        initialVehicleId={typeof mapParams.vehicle === 'string' ? mapParams.vehicle : null}
        initialRoute={typeof mapParams.route === 'string' && mapParams.route ? mapParams.route : null}
        searchFocus={mapParams.search === 'bus' || mapParams.search === 'route' ? mapParams.search : null}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  header: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm },
  title: { fontSize: 20, fontWeight: '900', color: COLORS.deepNavy },
});
