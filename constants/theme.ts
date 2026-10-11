// Professional Public Transit Design System (Light-First)
export const COLORS = {
  // Primary Transit Blues & Navies
  deepNavy: '#12355B',          // Main brand navy for key headers and brand accents
  primary: '#1976D2',           // Professional Transit Blue (primary actions, active states)
  primaryDark: '#0F5AA6',       // Deeper blue for pressed states
  primaryMedium: '#2F80C9',     // Medium blue for secondary highlights
  lightBlue: '#EAF4FB',         // Soft blue tint for pill backgrounds, info boxes
  secondary: '#1976D2',         // Transit blue
  accent: '#12355B',            // Deep navy accent

  // Backgrounds & Surfaces (Light-First)
  background: '#F5F7FA',        // Clean light neutral background
  surface: '#FFFFFF',           // Clean crisp white card background
  surfaceElevated: '#FFFFFF',   // Elevated card background with crisp border
  surfaceSubtle: '#EEF2F5',     // Secondary surface / input backgrounds
  card: '#FFFFFF',              // Card background
  cardBorder: '#E1E7ED',        // Semantic alias for card borders
  border: '#E1E7ED',            // Subtle crisp border
  borderSubtle: '#EDF2F7',      // Very subtle divider lines
  divider: '#E5E9F0',           // Table / list dividers

  // Text Colors
  textPrimary: '#17212B',       // High-contrast deep slate navy for headings and primary text
  textSecondary: '#5F6B76',     // Readable neutral gray for metadata and body copy
  textMuted: '#8A959F',         // Subtle gray for hints, timestamps, and captions
  textInverse: '#FFFFFF',       // Crisp white text on blue/dark buttons
  textWhite: '#FFFFFF',

  // Semantic Status Colors (Only used to communicate status)
  success: '#168A45',           // Success green
  successBg: '#E8F5EE',         // Light green background
  warning: '#C47A00',           // Amber warning
  warningBg: '#FFF4DB',         // Light amber background
  error: '#C62828',             // Error / packed red
  errorBg: '#FDECEC',           // Light red background
  info: '#1976D2',              // Information blue
  infoBg: '#EAF4FB',            // Light blue info background

  // Transit Specific Status
  crowdLow: '#168A45',          // Green for comfortable seating
  crowdLowBg: '#E8F5EE',
  crowdMedium: '#C47A00',       // Amber for moderate / few seats
  crowdMediumBg: '#FFF4DB',
  crowdHigh: '#C62828',         // Red for crowded / standing room
  crowdHighBg: '#FDECEC',

  // Bus Service Badges
  vajraBadge: '#12355B',        // Deep navy badge for Vajra AC
  vajraBg: '#EAF4FB',
  ordinaryBadge: '#5F6B76',     // Slate gray badge for BMTC Ordinary
  ordinaryBg: '#EEF2F5',

  // Interactive Touch
  touchHighlight: 'rgba(25, 118, 210, 0.08)',
};

export const SPACING = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
};

export const RADIUS = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 14,
  xl: 16,
  full: 9999,
};

export const SHADOWS = {
  xs: {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.04,
    shadowRadius: 2,
    elevation: 1,
  },
  sm: {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 2,
  },
  md: {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07,
    shadowRadius: 6,
    elevation: 3,
  },
  lg: {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 10,
    elevation: 5,
  },
  subtle: {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 2,
  },
  card: {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07,
    shadowRadius: 6,
    elevation: 3,
  },
  elevated: {
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 10,
    elevation: 5,
  },
};

export const FONT = {
  regular: 'System',
  medium: 'System',
  bold: 'System',
};

// Reusable Typography System for Professional Metropolitan Transit UX
export const TYPOGRAPHY = {
  appBrand: {
    fontSize: 22,
    fontWeight: '800' as const,
    color: COLORS.deepNavy,
    letterSpacing: -0.4,
  },
  screenTitle: {
    fontSize: 20,
    fontWeight: '700' as const,
    color: COLORS.textPrimary,
    letterSpacing: -0.2,
  },
  sectionTitle: {
    fontSize: 15,
    fontWeight: '700' as const,
    color: COLORS.textPrimary,
    letterSpacing: -0.1,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: '700' as const,
    color: COLORS.textPrimary,
  },
  body: {
    fontSize: 14,
    color: COLORS.textPrimary,
    lineHeight: 20,
  },
  secondary: {
    fontSize: 12,
    color: COLORS.textSecondary,
    lineHeight: 17,
  },
  caption: {
    fontSize: 11,
    color: COLORS.textMuted,
    lineHeight: 15,
  },
  button: {
    fontSize: 14,
    fontWeight: '700' as const,
    color: COLORS.textInverse,
    letterSpacing: 0.1,
  },
  numericData: {
    fontSize: 18,
    fontWeight: '800' as const,
    color: COLORS.primary,
    letterSpacing: 0.5,
  },
  statusLabel: {
    fontSize: 10,
    fontWeight: '700' as const,
    letterSpacing: 0.6,
    textTransform: 'uppercase' as const,
  },
};


