#!/bin/bash
# Claude Code PreToolUse(Bash) guard'ı — gizli dosyaların `git add -f/--force` ile
# .gitignore'u atlayıp GitHub yedeğine (Stop-hook her tur push ediyor) sızmasını engeller.
#
# stdin: {"tool_name":"Bash","tool_input":{"command":"..."}}
# exit 2 = aracı engelle (stderr mesajı Claude'a iletilir) · exit 0 = izin ver
# Hata/parse edilemezse exit 0 (güvenli varsayılan — normal komutları bloklamaz).

cmd=$(python3 -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

if printf '%s' "$cmd" | grep -qE 'git[[:space:]]+add[[:space:]].*(-f|--force)' \
   && printf '%s' "$cmd" | grep -qiE '\.env([^.]|$)|\.pem|\.key|secret'; then
  echo "ENGELLENDİ: gizli dosya (.env/.pem/.key/secret) 'git add -f' ile zorla eklenemez — .gitignore'u atlamak Stop-hook'un GitHub push'unda sır sızdırır." >&2
  exit 2
fi

exit 0
