/** Expo app config wrapper: EAS builds abort while endpoints are placeholders
 *  (EXPO_PUBLIC_* baked in at build time) — local dev unaffected; see the runbook. */

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
