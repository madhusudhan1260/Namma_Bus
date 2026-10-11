import React, { useMemo } from 'react';
import { View, StyleSheet } from 'react-native';
// @ts-ignore
import { toQR } from 'toqr';

interface QRCodeViewProps {
  value: string;
  size?: number;
  color?: string;
  backgroundColor?: string;
}

interface Run {
  x: number;
  width: number;
}

interface RowRuns {
  y: number;
  runs: Run[];
}

export const QRCodeView: React.FC<QRCodeViewProps> = ({
  value,
  size = 200,
  color = '#000000',
  backgroundColor = '#FFFFFF',
}) => {
  const { rowRuns, dimension } = useMemo(() => {
    try {
      const bytes: Uint8Array = toQR(value);
      const dim = Math.round(Math.sqrt(bytes.length));
      const rows: RowRuns[] = [];

      for (let y = 0; y < dim; y++) {
        const runs: Run[] = [];
        let startX: number | null = null;

        for (let x = 0; x < dim; x++) {
          const isDark = bytes[y * dim + x] === 1;
          if (isDark) {
            if (startX === null) {
              startX = x;
            }
          } else {
            if (startX !== null) {
              runs.push({ x: startX, width: x - startX });
              startX = null;
            }
          }
        }

        if (startX !== null) {
          runs.push({ x: startX, width: dim - startX });
        }

        if (runs.length > 0) {
          rows.push({ y, runs });
        }
      }

      return { rowRuns: rows, dimension: dim };
    } catch {
      return { rowRuns: [], dimension: 21 };
    }
  }, [value]);

  const moduleSize = size / dimension;

  return (
    <View
      style={[
        styles.container,
        {
          width: size,
          height: size,
          backgroundColor,
        },
      ]}
    >
      {rowRuns.map(row =>
        row.runs.map(run => (
          <View
            key={`${row.y}-${run.x}`}
            style={[
              styles.moduleRun,
              {
                top: row.y * moduleSize,
                left: run.x * moduleSize,
                width: run.width * moduleSize,
                height: moduleSize,
                backgroundColor: color,
              },
            ]}
          />
        ))
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'relative',
    overflow: 'hidden',
  },
  moduleRun: {
    position: 'absolute',
  },
});
