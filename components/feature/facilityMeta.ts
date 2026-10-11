import { Ionicons } from '@expo/vector-icons';
import { FacilityCategory } from '../../services/networkApi';

/** Icon, map emoji, colour and label key for each facility category. */
export const FACILITY: Record<FacilityCategory, { icon: keyof typeof Ionicons.glyphMap; emoji: string; color: string; label: string }> = {
  TOILETS: { icon: 'male-female-outline', emoji: '🚻', color: '#1FC79A', label: 'facToilets' },
  MEDICAL: { icon: 'medkit-outline', emoji: '💊', color: '#E5484D', label: 'facMedical' },
  ATM: { icon: 'card-outline', emoji: '🏧', color: '#2E8BF0', label: 'facAtm' },
  WATER: { icon: 'water-outline', emoji: '🚰', color: '#0EA5E9', label: 'facWater' },
  PARKING: { icon: 'car-outline', emoji: '🅿️', color: '#6366F1', label: 'facParking' },
  POLICE: { icon: 'shield-outline', emoji: '🚓', color: '#1E3A8A', label: 'facPolice' },
  HOSPITAL: { icon: 'medical-outline', emoji: '🏥', color: '#DC2626', label: 'facHospital' },
  FOOD: { icon: 'restaurant-outline', emoji: '🍽️', color: '#F59E0B', label: 'facFood' },
};
export const FACILITY_ORDER: FacilityCategory[] = ['TOILETS', 'MEDICAL', 'ATM', 'WATER', 'PARKING', 'POLICE', 'HOSPITAL', 'FOOD'];
