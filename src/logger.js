const DEBUG = import.meta.env.VITE_DEBUG === "true";

const logger = {
  proxy: (...args) => DEBUG && console.log("[proxy]", ...args),
  api:   (...args) => DEBUG && console.log("[api]",   ...args),
  mod:   (...args) => DEBUG && console.log("[mod]",   ...args),
  ui:    (...args) => DEBUG && console.log("[ui]",    ...args),
};

export default logger;
