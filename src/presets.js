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
    id: "x-platform",
    name: "X (formerly Twitter)",
    description: "Based on the X Rules (help.x.com/en/rules-and-policies/x-rules). Allows adult content and political speech if honestly labeled; blocks CSAM, NCII, hate speech, terrorism, and platform manipulation.",
    mode: MODES.BLACKLIST,
    blacklist: [
      "child sexual exploitation", "child grooming",
      "terrorism and violent extremism",
      "violent threats", "violence glorification",
      "adult content", "non-consensual intimate media",
      "hate speech", "harassment",
      "self-harm promotion",
      "spam and fraud", "impersonation", "misinformation",
      "doxxing and privacy violations",
      "illegal drugs", "illegal weapons sales", "intellectual property theft",
      "synthetic and manipulated media",
      "animal cruelty",
    ],
    whitelist: [],
    customInstructions:
      "BLOCK content that attacks, dehumanizes, or threatens people based on protected characteristics " +
      "(race, ethnicity, national origin, caste, sexual orientation, gender, gender identity, religion, age, disability, serious disease). " +
      "ALLOW adult or sexual content when it is honestly labeled as such and implies a consensual adult context — X permits this if age-gated. " +
      "BLOCK any sexual content involving minors, non-consent, or exploitation regardless of framing. " +
      "ALLOW violent or disturbing content when it is clearly framed as news reporting, documentary, or analytical commentary rather than glorified or incited. " +
      "ALLOW controversial or offensive political opinions about public figures, governments, and ideologies — X does not restrict legal political expression and applies a public-interest exception for statements by or about public figures. " +
      "BLOCK coordinated inauthentic behavior, artificial amplification, impersonation, and content designed to manipulate civic processes such as elections.",
  },
  {
    id: "truth-social",
    name: "Truth Social",
    description: "Based on Truth Social Community Guidelines (help.truthsocial.com/community-guidelines-page/) and Terms of Service (help.truthsocial.com/legal/terms-of-service/). NSFW allowed if labeled; no hate speech or misinformation policy; very permissive on political speech.",
    mode: MODES.BLACKLIST,
    blacklist: [
      "child sexual exploitation", "child grooming",
      "terrorism and violent extremism",
      "violent threats",
      "adult content",
      "harassment",
      "spam and fraud", "impersonation",
      "doxxing and privacy violations",
      "illegal drugs", "illegal weapons sales", "intellectual property theft",
    ],
    whitelist: [],
    customInstructions:
      "ALLOW NSFW content — including suggestive, crude, or sexually implicit material — when it is honestly labeled as such. " +
      "Truth Social permits this via their double-filter system. " +
      "BLOCK explicit pornographic content that is unlabeled or presented without any framing or context. " +
      "BLOCK child sexual exploitation regardless of framing. " +
      "ALLOW political speech, partisan opinions, and inflammatory rhetoric including content that would be restricted on other platforms — " +
      "Truth Social has no published hate speech or misinformation policy and explicitly positions itself as a free-speech platform. " +
      "Only block political content if it constitutes a direct, credible violent threat against a named individual or group. " +
      "BLOCK spam, fraud, phishing, impersonation, doxxing, illegal drug sales, and intellectual property theft.",
  },
  {
    id: "bluesky",
    name: "Bluesky",
    description: "Based on Bluesky Community Guidelines (bsky.social/about/support/community-guidelines). Comprehensive policy; adult content allowed if labeled via Ozone; hard block on election misinformation; broad hate speech coverage.",
    mode: MODES.BLACKLIST,
    blacklist: [
      "child sexual exploitation", "child grooming",
      "terrorism and violent extremism",
      "violent threats", "violence glorification",
      "adult content", "non-consensual intimate media",
      "hate speech", "harassment",
      "self-harm promotion",
      "spam and fraud", "impersonation", "misinformation",
      "doxxing and privacy violations",
      "illegal drugs", "illegal weapons sales", "intellectual property theft",
      "animal cruelty", "animal sexual abuse",
    ],
    whitelist: [],
    customInstructions:
      "BLOCK content that attacks or demeans people based on protected characteristics including age, ethnicity, gender identity, religion, sexual orientation, disability, and national origin. " +
      "ALLOW adult or sexual content when it is honestly labeled — Bluesky permits this via their Ozone labeling system. " +
      "BLOCK non-consensual sexual content and any sexual content involving minors regardless of framing. " +
      "ALLOW graphic violent content when clearly contextualized as sports, martial arts, fiction, film, or art. " +
      "BLOCK graphic violence designed to shock, intimidate, or glorify real-world harm. " +
      "BLOCK false information about voting procedures, election dates, polling locations, or voter eligibility — Bluesky treats election misinformation as a hard violation. " +
      "BLOCK harmful misinformation only when it is likely to cause immediate real-world harm; ALLOW contested claims, satire, and opinion even on sensitive topics. " +
      "BLOCK sexual content involving animals (real or realistic depictions) and content depicting animal abuse, torture, or fighting. " +
      "ALLOW content depicting legal hunting, fishing, or wildlife activities.",
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
