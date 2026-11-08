import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';

// ── Save a generated PDF into the user's chosen device folder (Android) ──────
// Modern Android can't write into public storage silently: the first save
// opens the SAF directory picker (one time), we remember the granted folder
// URI, and every later save writes there without any dialog — that is the
// "download" step of the PDF export flow.
//
// iOS has no Downloads folder and no way to write user storage silently, so
// canSaveToDevice() is false there and the export sheet only offers Share
// (whose SHEET contains "Save to Files", the Apple-native save path).

const { EncodingType, StorageAccessFramework: SAF } = FileSystem;

// AsyncStorage key for the granted SAF folder. Bumping the key makes every
// device ask for the folder permission again on next save.
const SAF_DIR_KEY = 'pdf_save_dir_v1';

const PDF_MIME = 'application/pdf';

// Thrown when the user closes the folder picker without picking a folder, so
// callers can treat it as a normal "no" instead of a failure.
export class SaveCancelledError extends Error {
  constructor() {
    super('Save to device was cancelled: no folder permission granted.');
    this.name = 'SaveCancelledError';
  }
}

// Save is a real download only on Android; on iOS the share sheet is the
// platform-idiomatic save path ("Save to Files").
export function canSaveToDevice() {
  return Platform.OS === 'android';
}

// Android-safe, locale-independent base file name (NO extension — SAF derives
// ".pdf" from the mimeType passed to createFileAsync). Dots would confuse the
// DocumentsProvider, hence the dashes/underscores only.
// e.g. SleepMonitor-SessionReport-2026-11-08_15-32
export function pdfBaseName(kind, when = new Date()) {
  const pad = n => String(n).padStart(2, '0');
  const stamp = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`
    + `_${pad(when.getHours())}-${pad(when.getMinutes())}`;
  return `SleepMonitor-${kind}-${stamp}`;
}

// Returns the granted SAF directory URI, asking (once per grant) through the
// OS folder picker. The picker opens inside the Downloads folder.
async function requestSaveDirectory(dirHintKey) {
  const initialUri = dirHintKey
    ? SAF.getUriForDirectoryInRoot(dirHintKey)
    : null;
  const { granted, directoryUri } = await SAF.requestDirectoryPermissionsAsync(initialUri);
  if (!granted || !directoryUri) throw new SaveCancelledError();
  await AsyncStorage.setItem(SAF_DIR_KEY, directoryUri);
  return directoryUri;
}

// ── Copy a PDF into the granted folder ───────────────────────────────────────
// `uri` — the file:// URI of the temp PDF expo-print rendered.
// `baseName` — extension-free name from pdfBaseName().
// Resolves to the SAF content:// URI of the saved copy; the temp file is
// deleted afterwards so the report does not linger in the app cache.
export async function savePdfToDevice({ uri, baseName, dirHintKey = 'Download' }) {
  if (!canSaveToDevice()) {
    throw new Error('savePdfToDevice is only available on Android.');
  }

  // First save: open the picker. Refreshes only when the stored grant is gone.
  let dirUri = await AsyncStorage.getItem(SAF_DIR_KEY);
  const isFresh = !dirUri;
  if (!dirUri) {
    dirUri = await requestSaveDirectory(dirHintKey);
  }

  const write = async target => {
    const fileUri = await SAF.createFileAsync(target, baseName, PDF_MIME);
    const base64 = await FileSystem.readAsStringAsync(uri, {
      encoding: EncodingType.Base64,
    });
    await FileSystem.writeAsStringAsync(fileUri, base64, {
      encoding: EncodingType.Base64,
    });
    return fileUri;
  };

  try {
    const savedUri = await write(dirUri);
    // Temp PDF is now duplicated into the SAF folder — drop the cache copy.
    await FileSystem.deleteAsync(uri, { idempotent: true });
    return savedUri;
  } catch (e) {
    // A stored path can go stale between saves (permission revoked, app
    // data cleared). Ask again exactly once; a brand-new picker rejection
    // still propagates the original error.
    if (isFresh) throw e;
    await AsyncStorage.removeItem(SAF_DIR_KEY);
    const retryDir = await requestSaveDirectory(dirHintKey);
    try {
      const savedUri = await write(retryDir);
      // Temp PDF is now duplicated into the SAF folder — drop the cache copy.
      await FileSystem.deleteAsync(uri, { idempotent: true });
      return savedUri;
    } catch (e2) {
      if (e2 instanceof SaveCancelledError) throw e2;
      await AsyncStorage.removeItem(SAF_DIR_KEY);
      throw e2;
    }
  }
}
