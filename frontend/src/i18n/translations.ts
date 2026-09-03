export type Language = "en" | "id";

export const DEFAULT_LANGUAGE: Language = "en";
export const LANGUAGE_STORAGE_KEY = "regret-language";

export type Translation = {
  header: {
    subtitle: string;
    overview: string;
    decisions: string;
    replay: string;
    paperMode: string;
    apiHealthy: string;
    apiDegraded: string;
    refresh: string;
    refreshing: string;
  };
  hero: {
    decisionValue: string;
    positiveDescription: string;
    negativeDescription: string;
    explanation: string;
    avoidedLoss: string;
    missedAlpha: string;
    evaluated: string;
    paperExecutions: string;
    protectedDecision: string;
    protectedDecisions: string;
    rejectedWinner: string;
    rejectedWinners: string;
    trackedShadows: string;
    noExecutions: string;
    paperLedger: string;
  };
  stream: {
    title: string;
    confidence: string;
    risk: string;
    noTrade: string;
    fallbackCritic: string;
    safeFailure: string;
  };
  replay: {
    title: string;
    saidNo: string;
    saidYes: string;
    rejectedQuestion: (symbol: string) => string;
    acceptedQuestion: (symbol: string) => string;
    entryScenario: string;
    evaluatedAt: string;
    hypotheticalPerformance: string;
    avoidedLoss: string;
    missedAlpha: string;
    correctExecution: string;
    badExecution: string;
    avoidedNarrative: (value: string) => string;
    missedNarrative: (value: string) => string;
    correctNarrative: (value: string) => string;
    badNarrative: (value: string) => string;
    decisionValue: string;
    replayDecision: string;
    noOutcome: string;
    outcomePending: string;
    entryPoint: string;
    evaluationPoint: string;
    factualPoints: string;
  };
  audit: {
    title: string;
    marketScout: string;
    candidateDiscovered: string;
    azureAnalyst: string;
    confidence: (value: string) => string;
    adversarialCritic: string;
    challenge: string;
    pass: string;
    consensus: string;
    adjustedConfidence: (value: string) => string;
    riskGate: string;
    noTrade: string;
    belowThreshold: string;
    persistedDetails: string;
    persistedNote: string;
    analystRecord: string;
    confidenceLabel: string;
    entry: string;
    stop: string;
    target: string;
    invalidation: string;
    evidence: string;
    verdict: string;
    adjustment: string;
    consistency: string;
    concerns: string;
    riskSummary: string;
  };
  states: {
    partialData: string;
    backendOffline: string;
    unavailable: string;
    startApi: (url: string) => string;
    retry: string;
    noSyntheticData: string;
    noDecision: string;
    detailsUnavailable: string;
  };
  footer: string;
};

export const translations: Record<Language, Translation> = {
  en: {
    header: {
      subtitle: "Counterfactual Intelligence",
      overview: "Overview",
      decisions: "Decisions",
      replay: "Replay",
      paperMode: "Paper Mode",
      apiHealthy: "API Healthy",
      apiDegraded: "API Degraded",
      refresh: "Refresh",
      refreshing: "Refreshing",
    },
    hero: {
      decisionValue: "Decision Value",
      positiveDescription: "Net value created or protected by REGRET's decisions.",
      negativeDescription: "Net value destroyed or missed by REGRET's decisions.",
      explanation: "REGRET measures not only the trades it takes, but also the opportunities it deliberately rejects.",
      avoidedLoss: "Avoided Loss",
      missedAlpha: "Missed Alpha",
      evaluated: "Evaluated",
      paperExecutions: "Paper Exec",
      protectedDecision: "protected decision",
      protectedDecisions: "protected decisions",
      rejectedWinner: "rejected winner",
      rejectedWinners: "rejected winners",
      trackedShadows: "shadow trades tracked",
      noExecutions: "No naturally accepted executions",
      paperLedger: "Paper ledger only",
    },
    stream: {
      title: "Decision Stream",
      confidence: "Conf",
      risk: "Risk",
      noTrade: "NO TRADE",
      fallbackCritic: "Fallback critic",
      safeFailure: "Stopped safely before risk or execution.",
    },
    replay: {
      title: "Counterfactual Replay",
      saidNo: "REGRET SAID NO.",
      saidYes: "REGRET SAID YES.",
      rejectedQuestion: (symbol) => `What if REGRET had taken this trade on ${symbol}?`,
      acceptedQuestion: (symbol) => `What happened after REGRET traded ${symbol}?`,
      entryScenario: "Entry Scenario",
      evaluatedAt: "Evaluated At",
      hypotheticalPerformance: "Hypothetical Performance",
      avoidedLoss: "Avoided Loss",
      missedAlpha: "Missed Alpha",
      correctExecution: "Correct Execution",
      badExecution: "Bad Execution",
      avoidedNarrative: (value) => `The decision protected ${value} of decision value against adverse price action.`,
      missedNarrative: (value) => `The decision missed ${value} of potential upside.`,
      correctNarrative: (value) => `The decision created ${value} of decision value.`,
      badNarrative: (value) => `The decision lost ${value} of decision value.`,
      decisionValue: "Decision Value",
      replayDecision: "Replay Decision",
      noOutcome: "No evaluated outcome for this decision yet.",
      outcomePending: "Replay appears after the configured evaluation horizon.",
      entryPoint: "Entry",
      evaluationPoint: "Exit",
      factualPoints: "Two recorded price points only",
    },
    audit: {
      title: "Why did REGRET choose not to trade?",
      marketScout: "Market Scout",
      candidateDiscovered: "Candidate discovered",
      azureAnalyst: "Azure Analyst",
      confidence: (value) => `${value} confidence`,
      adversarialCritic: "Adversarial Critic",
      challenge: "CHALLENGE",
      pass: "PASS",
      consensus: "Consensus",
      adjustedConfidence: (value) => `${value} adjusted confidence`,
      riskGate: "Risk Gate",
      noTrade: "NO TRADE",
      belowThreshold: "Below 70% confidence threshold",
      persistedDetails: "Persisted decision evidence",
      persistedNote: "Structured records only — never hidden chain-of-thought.",
      analystRecord: "Analyst record",
      confidenceLabel: "Confidence",
      entry: "Entry",
      stop: "Stop",
      target: "Target",
      invalidation: "Invalidation",
      evidence: "Evidence",
      verdict: "Verdict",
      adjustment: "Adjustment",
      consistency: "Consistency",
      concerns: "Concerns",
      riskSummary: "Risk Gate",
    },
    states: {
      partialData: "Partial data could not be loaded. Available sections remain live.",
      backendOffline: "Backend offline",
      unavailable: "Decision data is unavailable",
      startApi: (url) => `Start the REGRET API at ${url}, then retry.`,
      retry: "Retry connection",
      noSyntheticData: "No cached or synthetic trading data is being shown.",
      noDecision: "No decision is available for replay.",
      detailsUnavailable: "Detailed agent reasoning is unavailable.",
    },
    footer: "Read-only decision review · no execution actions",
  },
  id: {
    header: {
      subtitle: "Counterfactual Intelligence",
      overview: "Overview",
      decisions: "Keputusan",
      replay: "Replay",
      paperMode: "Paper Mode",
      apiHealthy: "API Healthy",
      apiDegraded: "API Degraded",
      refresh: "Perbarui",
      refreshing: "Memperbarui",
    },
    hero: {
      decisionValue: "Nilai Keputusan",
      positiveDescription: "Nilai bersih yang dihasilkan atau dilindungi oleh keputusan REGRET.",
      negativeDescription: "Nilai bersih yang hilang atau terlewat akibat keputusan REGRET.",
      explanation: "REGRET tidak hanya mengukur trade yang diambil, tetapi juga peluang yang sengaja dipilih untuk tidak diambil.",
      avoidedLoss: "Kerugian Dihindari",
      missedAlpha: "Peluang Profit Terlewat",
      evaluated: "Keputusan Dievaluasi",
      paperExecutions: "Eksekusi Paper",
      protectedDecision: "keputusan dilindungi",
      protectedDecisions: "keputusan dilindungi",
      rejectedWinner: "pemenang ditolak",
      rejectedWinners: "pemenang ditolak",
      trackedShadows: "shadow trade dipantau",
      noExecutions: "Belum ada eksekusi yang diterima alami",
      paperLedger: "Khusus ledger paper",
    },
    stream: {
      title: "Alur Keputusan",
      confidence: "Kep",
      risk: "Risiko",
      noTrade: "TIDAK MASUK",
      fallbackCritic: "Fallback Critic",
      safeFailure: "Dihentikan dengan aman sebelum risiko atau eksekusi.",
    },
    replay: {
      title: "Simulasi Kontrafaktual",
      saidNo: "REGRET MEMILIH TIDAK MASUK.",
      saidYes: "REGRET MEMILIH MASUK.",
      rejectedQuestion: () => "Bagaimana jika REGRET mengambil trade ini?",
      acceptedQuestion: (symbol) => `Apa yang terjadi setelah REGRET mengambil trade ${symbol}?`,
      entryScenario: "Harga Masuk",
      evaluatedAt: "Harga Evaluasi",
      hypotheticalPerformance: "Performa Hipotetis",
      avoidedLoss: "Kerugian Dihindari",
      missedAlpha: "Peluang Profit Terlewat",
      correctExecution: "Eksekusi Tepat",
      badExecution: "Eksekusi Buruk",
      avoidedNarrative: (value) => `Keputusan ini melindungi nilai sebesar ${value}.`,
      missedNarrative: (value) => `Keputusan ini melewatkan potensi keuntungan sebesar ${value}.`,
      correctNarrative: (value) => `Keputusan ini menghasilkan nilai sebesar ${value}.`,
      badNarrative: (value) => `Keputusan ini mengurangi nilai sebesar ${value}.`,
      decisionValue: "Nilai Keputusan",
      replayDecision: "Putar Ulang Keputusan",
      noOutcome: "Belum ada hasil evaluasi untuk keputusan ini.",
      outcomePending: "Replay tersedia setelah horizon evaluasi tercapai.",
      entryPoint: "Masuk",
      evaluationPoint: "Evaluasi",
      factualPoints: "Hanya dua titik harga tercatat",
    },
    audit: {
      title: "Mengapa REGRET memilih tidak masuk?",
      marketScout: "Market Scout",
      candidateDiscovered: "Kandidat ditemukan",
      azureAnalyst: "Azure Analyst",
      confidence: (value) => `Kepercayaan ${value}`,
      adversarialCritic: "Adversarial Critic",
      challenge: "TANTANGAN",
      pass: "LOLOS",
      consensus: "Consensus",
      adjustedConfidence: (value) => `Kepercayaan disesuaikan ${value}`,
      riskGate: "Risk Gate",
      noTrade: "TIDAK MASUK",
      belowThreshold: "Di bawah ambang kepercayaan 70%",
      persistedDetails: "Bukti keputusan tersimpan",
      persistedNote: "Hanya catatan terstruktur — bukan proses berpikir tersembunyi.",
      analystRecord: "Catatan Analyst",
      confidenceLabel: "Kepercayaan",
      entry: "Masuk",
      stop: "Stop",
      target: "Target",
      invalidation: "Invalidasi",
      evidence: "Bukti",
      verdict: "Putusan",
      adjustment: "Penyesuaian",
      consistency: "Konsistensi",
      concerns: "Kekhawatiran",
      riskSummary: "Risk Gate",
    },
    states: {
      partialData: "Sebagian data tidak dapat dimuat. Bagian yang tersedia tetap aktif.",
      backendOffline: "Backend offline",
      unavailable: "Data keputusan tidak tersedia",
      startApi: (url) => `Jalankan API REGRET di ${url}, lalu coba lagi.`,
      retry: "Coba hubungkan lagi",
      noSyntheticData: "Tidak ada data cache atau data trading sintetis yang ditampilkan.",
      noDecision: "Belum ada keputusan untuk diputar ulang.",
      detailsUnavailable: "Detail penalaran agen tidak tersedia.",
    },
    footer: "Tinjauan keputusan read-only · tanpa aksi eksekusi",
  },
};

export function resolveLanguage(value: string | null | undefined): Language {
  return value === "id" ? "id" : "en";
}

export function selectLanguage(_current: Language, selected: Language): Language {
  return selected;
}

export function decisionStatusLabel(
  status: string,
  language: Language,
): string {
  if (["ANALYSIS_FAILED", "CRITIC_FAILED", "RISK_FAILED"].includes(status)) {
    return status;
  }
  if (status === "REJECT" || status === "REJECTED") {
    return translations[language].stream.noTrade;
  }
  return status;
}
