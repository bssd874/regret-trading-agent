"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  resolveLanguage,
  selectLanguage,
  translations,
  type Language,
  type Translation,
} from "./translations";

type LanguageContextValue = {
  language: Language;
  copy: Translation;
  setLanguage: (language: Language) => void;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function initialLanguage(): Language {
  return DEFAULT_LANGUAGE;
}

export function readStoredLanguage(
  storage: Pick<Storage, "getItem">,
): Language {
  return resolveLanguage(storage.getItem(LANGUAGE_STORAGE_KEY));
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, updateLanguage] = useState<Language>(initialLanguage);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      updateLanguage(readStoredLanguage(window.localStorage));
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const setLanguage = useCallback((selected: Language) => {
    updateLanguage((current) => selectLanguage(current, selected));
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, selected);
  }, []);

  const value = useMemo(
    () => ({ language, copy: translations[language], setLanguage }),
    [language, setLanguage],
  );

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage(): LanguageContextValue {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within LanguageProvider");
  }
  return context;
}
