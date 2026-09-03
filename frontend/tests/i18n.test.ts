import assert from "node:assert/strict";
import test from "node:test";

import {
  initialLanguage,
  readStoredLanguage,
} from "../src/i18n/language-provider";
import {
  LANGUAGE_STORAGE_KEY,
  decisionStatusLabel,
  exitReasonLabel,
  selectLanguage,
  translations,
} from "../src/i18n/translations";

test("English is the hydration-safe default language", () => {
  assert.equal(initialLanguage(), "en");
  assert.equal(translations.en.hero.decisionValue, "Decision Value");
});

test("language selection switches EN to ID", () => {
  assert.equal(selectLanguage("en", "id"), "id");
  assert.equal(translations.id.hero.decisionValue, "Nilai Keputusan");
});

test("language selection switches ID to EN", () => {
  assert.equal(selectLanguage("id", "en"), "en");
});

test("saved language is restored separately from initial render", () => {
  const storage = {
    getItem(key: string) {
      assert.equal(key, LANGUAGE_STORAGE_KEY);
      return "id";
    },
  };

  assert.equal(initialLanguage(), "en");
  assert.equal(readStoredLanguage(storage), "id");
});

test("a normal reject is localized as no trade", () => {
  assert.equal(decisionStatusLabel("REJECT", "en"), "NO TRADE");
  assert.equal(decisionStatusLabel("REJECT", "id"), "TIDAK MASUK");
});

test("an accepted decision is localized as trade", () => {
  assert.equal(decisionStatusLabel("ACCEPT", "en"), "TRADE");
  assert.equal(decisionStatusLabel("ACCEPT", "id"), "MASUK");
});

test("realized replay and exit reasons have EN and ID coverage", () => {
  assert.equal(translations.en.replay.buy, "BUY");
  assert.equal(translations.en.replay.sell, "SELL");
  assert.equal(translations.en.replay.badExecution, "Bad Execution");
  assert.equal(translations.en.replay.correctExecution, "Correct Execution");
  assert.equal(exitReasonLabel("TIME_EXIT", "en"), "TIME EXIT");
  assert.equal(translations.id.replay.buy, "BELI");
  assert.equal(translations.id.replay.sell, "JUAL");
  assert.equal(translations.id.replay.badExecution, "Eksekusi Merugi");
  assert.equal(translations.id.replay.correctExecution, "Eksekusi Berhasil");
  assert.equal(exitReasonLabel("TIME_EXIT", "id"), "BATAS WAKTU");
});

test("pipeline failure states remain explicit failures", () => {
  for (const status of ["ANALYSIS_FAILED", "CRITIC_FAILED", "RISK_FAILED"]) {
    assert.equal(decisionStatusLabel(status, "en"), status);
    assert.equal(decisionStatusLabel(status, "id"), status);
  }
});
