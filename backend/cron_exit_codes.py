"""Zamanlanmış iş (cron) çıkış-kodu sözleşmesi — denetim JOBS-002.

SORUN: sedna-sync, sales-sync ve exchange-rates cron'ları adım hataları olsa da
`exit 0` dönüyordu. systemd `oneshot` birimi bunu 'başarılı' sayıyor ve
`OnFailure=sprenses-alert@...` (DR-003 drop-in'leri) hiç tetiklenmiyordu — yani
alarm altyapısı kuruluydu ama iş sessizce çöküp exit 0 döndüğü için boşa çıkıyordu.

SÖZLEŞME (systemd oneshot birimleri bu çıkış kodunu okur):
  EXIT_OK      = 0  → tam başarı VEYA iyi huylu atlama (tünel kapalı, yapılandırılmamış)
  EXIT_FATAL   = 1  → iş HİÇ başlayamadı (ör. admin kullanıcı yok, önkoşul eksik)
  EXIT_PARTIAL = 2  → iş koştu ama ≥1 adım hata verdi → birim 'failed' → alarm tetiklenir

Kısmi başarı ayrı kodla (2) raporlanır ki 'hiç başlayamadı' (1) durumundan ayırt
edilebilsin; ikisi de sıfırdan farklı olduğundan ikisi de `OnFailure` tetikler.
"""

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PARTIAL = 2


def exit_code_for_steps(*, started: bool, failed_steps: int) -> int:
    """Adım sonuçlarını sözleşmedeki çıkış koduna eşle.

    started=False → EXIT_FATAL (iş önkoşulu sağlanamadı, hiç koşamadı).
    failed_steps>0 → EXIT_PARTIAL (koştu ama en az bir adım hata verdi).
    aksi halde → EXIT_OK.
    """
    if not started:
        return EXIT_FATAL
    if failed_steps > 0:
        return EXIT_PARTIAL
    return EXIT_OK
