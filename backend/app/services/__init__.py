"""Domain servis katmanı (HTTP'siz saf iş mantığı; router'lar buradan import eder).

utils/ = teknik yardımcılar (font, dosya doğrulama, audit). services/ = domain iş mantığı
(import orchestration, KPI/maliyet hesabı). Router'lar services'ten import eder; tersi olmaz.
"""
