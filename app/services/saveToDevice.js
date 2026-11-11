import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';

// First save opens the SAF directory picker (once); the granted folder URI is
// remembered for silent later saves. iOS can't write user storage → Share only.

const { EncodingType, StorageAccessFramework: SAF } = FileSystem;

// AsyncStorage key for the granted SAF folder — bumping it makes every device re-ask for the folder permission.
const SAF_DIR_KEY = 'pdf_save_dir_v1';

const PDF_MIME = 'application/pdf';

// Thrown when the picker closes without a grant, so callers treat it as a normal "no".
export class SaveCancelledError extends Error {
  constructor() {
    super('Save to device was cancelled: no folder permission granted.');
    this.name = 'SaveCancelledError';
  }
}

// Real download only on Android; iOS saves via the share sheet's native "Save to Files".
export function canSaveToDevice() {
  return Platform.OS === 'android';
}

// Extension-free base name — SAF derives ".pdf" from the mimeType, and dots
// confuse the DocumentsProvider. e.g. SleepMonitor-SessionReport-2026-11-08_15-32
export function pdfBaseName(kind, when = new Date()) {
  const pad = n => String(n).padStart(2, '0');
  const stamp = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`
    + `_${pad(when.getHours())}-${pad(when.getMinutes())}`;
  return `SleepMonitor-${kind}-${stamp}`;
}

// Asks (once per grant) through the OS folder picker and stores the granted URI.
async function requestSaveDirectory(dirHintKey) {
  const initialUri = dirHintKey
    ? SAF.getUriForDirectoryInRoot(dirHintKey)
    : null;
  const { granted, directoryUri } = await SAF.requestDirectoryPermissionsAsync(initialUri);
  if (!granted || !directoryUri) throw new SaveCancelledError();
  await AsyncStorage.setItem(SAF_DIR_KEY, directoryUri);
  return directoryUri;
}

// Resolves to the SAF content:// URI; the temp file is dropped in EVERY
// terminal state (see the finally below).
export async function savePdfToDevice({ uri, baseName, dirHintKey = 'Download' }) {
  if (!canSaveToDevice()) {
    throw new Error('savePdfToDevice is only available on Android.');
  }

  // The read stays FIRST: a missing source or full disk fails before any SAF
  // write or grant touch, so the catch below can blame GRANT, never source.
  let base64;
  try {
    base64 = await FileSystem.readAsStringAsync(uri, {
      encoding: EncodingType.Base64,
    });

    // First save: open the picker. Refreshes only when the stored grant is gone.
    let dirUri = await AsyncStorage.getItem(SAF_DIR_KEY);
    const isFresh = !dirUri;
    if (!dirUri) {
      dirUri = await requestSaveDirectory(dirHintKey);
    }

    const write = async target => {
      const fileUri = await SAF.createFileAsync(target, baseName, PDF_MIME);
      await FileSystem.writeAsStringAsync(fileUri, base64, {
        encoding: EncodingType.Base64,
      });
      return fileUri;
    };

    try {
      const savedUri = await write(dirUri);
      return savedUri;
    } catch (e) {
      // A stored grant can go stale (permission revoked, app data cleared) —
      // ask again exactly once; a fresh rejection still propagates the error.
      if (isFresh) throw e;
      await AsyncStorage.removeItem(SAF_DIR_KEY);
      const retryDir = await requestSaveDirectory(dirHintKey);
      try {
        return await write(retryDir);
      } catch (e2) {
        if (e2 instanceof SaveCancelledError) throw e2;
        await AsyncStorage.removeItem(SAF_DIR_KEY);
        throw e2;
      }
    }
  } finally {
    // EVERY exit path lands here: the temp copy has no future, delete it. A
    // cleanup failure is swallowed — it must never change the call's outcome.
    await FileSystem.deleteAsync(uri, { idempotent: true }).catch(e => {
      console.warn('temp report cleanup failed (ignored):', e);
    });
  }
}
