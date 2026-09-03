import { Dashboard } from "@/components/dashboard";
import { LanguageProvider } from "@/i18n/language-provider";

export default function Home() {
  return (
    <LanguageProvider>
      <Dashboard />
    </LanguageProvider>
  );
}
