import { Modal, View, Text, TouchableOpacity, ActivityIndicator, StyleSheet } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { EXPORT_SHEET_TEXT } from '../config/displayText';

// Bottom "action sheet" for choosing which PDF to export. Shared by the
// patient's Report tab and the doctor's patient detail screen.
//
// rows: [{ key, icon, title, subtitle, enabled, reason, busy, onPress }]
//   enabled=false greys the row and shows `reason` under the subtitle
//   (e.g. nightly analysis not run yet); busy=true renders a spinner.
export default function ReportExportSheet({ visible, onClose, rows }) {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <TouchableOpacity
        style={styles.overlay}
        activeOpacity={1}
        onPress={onClose}
      >
        {/* Inner touchable claims taps on the title, gaps and disabled rows so
            they don't bubble to the overlay's close handler. No onPress: the
            sheet itself closes only via rows, Cancel, backdrop or back. */}
        <TouchableOpacity style={styles.sheet} activeOpacity={1}>
          <View style={styles.handle} />
          <View style={styles.handle} />
          <Text style={styles.title}>{EXPORT_SHEET_TEXT.title}</Text>

          {rows.map(row => (
            <TouchableOpacity
              key={row.key}
              style={[styles.row, !(row.enabled ?? true) && styles.rowDisabled]}
              activeOpacity={0.75}
              disabled={!(row.enabled ?? true) || row.busy}
              onPress={() => {
                onClose();
                row.onPress?.();
              }}
            >
              <View style={styles.rowIconWrap}>
                {row.busy
                  ? <ActivityIndicator size="small" color="#818cf8" />
                  : <MaterialCommunityIcons
                      name={row.icon || 'file-pdf-box'}
                      size={22}
                      color={(row.enabled ?? true) ? '#818cf8' : '#444'}
                    />
                }
              </View>

              <View style={styles.rowBody}>
                <Text
                  style={[
                    styles.rowTitle,
                    !(row.enabled ?? true) && { color: '#555' },
                  ]}
                >
                  {row.title}
                </Text>
                <Text style={styles.rowSubtitle}>{row.subtitle}</Text>
                {!(row.enabled ?? true) && row.reason
                  ? <Text style={styles.rowReason}>ⓘ {row.reason}</Text>
                  : null}
              </View>
            </TouchableOpacity>
          ))}

          <TouchableOpacity style={styles.cancelBtn} activeOpacity={0.75} onPress={onClose}>
            <Text style={styles.cancelText}>{EXPORT_SHEET_TEXT.cancel}</Text>
          </TouchableOpacity>
        </TouchableOpacity>
      </TouchableOpacity>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.65)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#13131f',
    borderTopWidth: 1,
    borderTopColor: '#2a2a4a',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 24,
    gap: 8,
  },
  handle: {
    alignSelf: 'center',
    width: 42,
    height: 4,
    borderRadius: 2,
    backgroundColor: '#2a2a4a',
    marginBottom: 8,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: '#e2e8f0',
    marginBottom: 6,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    backgroundColor: '#0d0d18',
    borderRadius: 14,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    padding: 14,
  },
  rowDisabled: {
    opacity: 0.6,
  },
  rowIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: '#13132a',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowBody: {
    flex: 1,
    gap: 3,
  },
  rowTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#e2e8f0',
  },
  rowSubtitle: {
    fontSize: 12,
    color: '#666',
    lineHeight: 17,
  },
  rowReason: {
    fontSize: 11,
    color: '#fbbf24',
    marginTop: 2,
  },
  cancelBtn: {
    alignItems: 'center',
    paddingVertical: 10,
    marginTop: 4,
  },
  cancelText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#818cf8',
  },
});
