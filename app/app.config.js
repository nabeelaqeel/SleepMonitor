/**
 * Expo app config wrapper.
 *
 * `config` is the merged app.json — returned unchanged, except that this
 * wrapper makes EAS cloud builds fail while placeholder endpoints remain:
 * EXPO_PUBLIC_* values are baked into the bundle at build time, so a
 * still-unfilled `app/eas.json` ("SET_ME_EC2_PUBLIC_IP") must abort the
 * build instead of silently producing an APK with useless endpoints.
 *
 * Local dev is unaffected: `npx expo start` does not set EAS_BUILD, and its
 * values (from app/.env.development) are real. See the author-side deployment runbook for §-references.
 */

module.exports = ({ config }) => {
  if (process.env.EAS_BUILD) {
    const required = ["EXPO_PUBLIC_BROKER_IP", "EXPO_PUBLIC_API_URL"];
    for (const name of required) {
      const value = process.env[name];
      if (!value || value.includes("SET_ME")) {
        throw new Error(
          `${name} is missing or still a placeholder (value: ${value || "unset"}) — ` +
            "fill it in app/eas.json before building (see the author-side deployment runbook)."
        );
      }
    }
  }
  return config;
};
