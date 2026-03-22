// ─── Prompt Presets ───────────────────────────────────────────────────────────
// A bank of reusable moderation configurations for different use-cases.
// Each preset corresponds to a specific platform context or benchmark dataset.

import { MODES } from "./moderator.js";

export const PRESETS = [
  {
    id: "school-whitelist",
    name: "School assistant (whitelist)",
    description: "Restricts a student assistant to academic topics only.",
    mode: MODES.WHITELIST,
    blacklist: [],
    whitelist: [
      "math", "science", "history", "literature", "geography", "grammar",
      "biology", "chemistry", "physics", "algebra", "geometry",
      "programming basics", "reading", "writing", "essays",
    ],
    customInstructions:
      "Do not allow requests for complete homework answers or full essay drafts — only hints, explanations, and worked examples are appropriate. " +
      "Block requests that ask the assistant to 'do' the assignment rather than help the student understand.",
  },
  {
    id: "general-blacklist",
    name: "General platform (blacklist)",
    description: "Blocks common harmful content categories for a general-purpose platform.",
    mode: MODES.BLACKLIST,
    blacklist: ["violence", "adult content", "drugs", "weapons", "hacking"],
    whitelist: [],
    customInstructions: "",
  },
  {
    id: "ethos-hate-speech",
    name: "ETHOS — Hate speech detection",
    description: "Matches the ETHOS binary dataset: hate speech across race, gender, religion, sexual orientation, national origin, and disability.",
    mode: MODES.BLACKLIST,
    blacklist: [
      "racism", "sexism", "homophobia", "antisemitism",
      "xenophobia", "islamophobia", "ableism", "religious hatred",
    ],
    whitelist: [],
    customInstructions:
      "BLOCK if the text attacks, demeans, or threatens a person or group based on a protected characteristic " +
      "(race, ethnicity, national origin, religion, gender, sexual orientation, disability). " +
      "ALLOW if the text merely discusses, quotes, or reports on these topics without itself being hateful. " +
      "Focus on the intent and framing of the text, not just the presence of sensitive words.",
  },
];
