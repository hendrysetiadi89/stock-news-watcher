#!/bin/bash
# Dipanggil oleh Hermes cron dalam mode --no-agent.
# Letaknya WAJIB di ~/.hermes/scripts/ -- Hermes menolak script di luar folder itu.
#
# stdout sengaja dikosongkan: Hermes memperlakukan stdout kosong sebagai tick senyap,
# sedangkan stdout yang terisi akan dikirim apa adanya ke Telegram. Pengiriman berita
# sudah dilakukan watch.py sendiri lewat Bot API.
# stderr disimpan ke log. Exit code diteruskan: watch.py mengembalikan 1 kalau semua
# sumber gagal, dan Hermes mengubahnya jadi alert error.
#
# Flag:
#   --limit 100          jaring lebar untuk run pertama setelah gateway sempat mati
#   --empty-notice 60    kabari kalau sudah 60 menit hening
#
# Pesan "radar saham aktif" TIDAK dikirim dari sini. Itu ditangani hook systemd
# (hermes-gateway.service.d/announce.conf) supaya terkirim tepat saat gateway
# menyala, bukan menunggu tick cron berikutnya.

LOG="$HOME/.hermes/logs/stock-news-watcher.log"
mkdir -p "$(dirname "$LOG")"

exec python3 "$HOME/.hermes/skills/stock-news-watcher/watch.py" \
  --telegram \
  --limit 100 \
  --empty-notice 60 \
  >/dev/null 2>>"$LOG"
