#!/usr/bin/env bash
# preflight.sh — G-DIVE Supabase key rol on-kontrolu
# RLS / guvenlik / Supabase degisikliginden ONCE calistir.
# Her cron wrapper'inin SUPABASE_KEY'inin service_role oldugunu DOGRULAR.
# eyJ prefix'i YETMEZ: eski-stil anon key de eyJ ile baslar. Bu yuzden
# JWT payload decode edilip role claim'i okunur.
# RED (exit 1) = anon/publishable/bilinmeyen bulundu -> degisiklik YAPMA.
# (25 Haz: anon key + RLS hardening = cron 401, 10 saat kayip. Bir daha olmasin.)

set -u

WRAPPERS=(
  /root/g-dive-gex/run_c4_cron.sh
  /root/g-dive-gex/run_edge_shadow_cron.sh
  /root/g-dive-gex/spx_env.sh
)

fail=0

b64url_decode() {
  local s="${1//-/+}"; s="${s//_//}"
  local pad=$(( (4 - ${#s} % 4) % 4 )) i
  for ((i=0; i<pad; i++)); do s+="="; done
  printf '%s' "$s" | base64 -d 2>/dev/null
}

check_key() {
  local key="$1" role
  case "$key" in
    sb_publishable_*) echo "ANON (sb_publishable) — YASAK"; return 1 ;;
    sb_secret_*)      echo "secret (sb_secret) — OK";        return 0 ;;
    eyJ*)
      role="$(b64url_decode "$(printf '%s' "$key" | cut -d. -f2)" \
              | sed -n 's/.*"role"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
      if [ "$role" = "service_role" ]; then
        echo "service_role JWT — OK"; return 0
      else
        echo "JWT role='${role:-?}' — service_role DEGIL, YASAK"; return 1
      fi ;;
    "")  echo "SUPABASE_KEY satiri bulunamadi"; return 1 ;;
    *)   echo "bilinmeyen key formati — YASAK";  return 1 ;;
  esac
}

extract_key() {
  local raw k
  raw="$(grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_]*SUPABASE_KEY=' "$1" | head -1)"
  [ -z "$raw" ] && { printf ''; return; }
  k="${raw#*SUPABASE_KEY=}"
  k="${k%%[[:space:]]*}"
  k="${k#[\"\']}"; k="${k%[\"\']}"
  printf '%s' "$k"
}

echo "=== G-DIVE preflight: Supabase key rol kontrolu ==="
for f in "${WRAPPERS[@]}"; do
  if [ ! -f "$f" ]; then
    echo "  x $(basename "$f") — dosya yok"; fail=1; continue
  fi
  msg="$(check_key "$(extract_key "$f")")"
  if [ $? -eq 0 ]; then
    echo "  ok $(basename "$f"): $msg"
  else
    echo "  x  $(basename "$f"): $msg"; fail=1
  fi
done
echo "==============================================="
if [ "$fail" -ne 0 ]; then
  echo "RED — RLS/guvenlik degisikligi YAPMA. x satirlarini duzelt."
  echo "(Anon key ile RLS hardening = cron 401 olur, 25 Haz 10-saat kaybi.)"
  exit 1
fi
echo "GECTI — 3 wrapper da service_role. RLS degisikligi guvenli."
exit 0
