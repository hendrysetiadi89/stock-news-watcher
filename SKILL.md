---
name: stock-news-watcher
description: Pantau berita saham/pasar modal Indonesia terbaru dari Pasardana, IDN Financials, Kontan Insight, Kabar Bursa, dan keterbukaan informasi IDX, deteksi item baru, lalu rangkum dan kirim notifikasi. Gunakan saat diminta mengecek berita saham baru atau saat menjalankan cron job notifikasi berita saham.
---

# Stock News Watcher

Skill ini memantau 5 sumber pasar modal Indonesia dan hanya melaporkan item yang **belum pernah dilaporkan sebelumnya** (dedup disimpan di `seen.db`).

Sumber mana yang aktif dan topik mana yang dipantau diatur di `config.json` — jangan
mengubahnya sendiri kecuali user memang meminta.

## Cara pakai

Jalankan script berikut (Windows):

```
python "%USERPROFILE%\.hermes\skills\stock-news-watcher\watch.py"
```

Script mencetak JSON ke stdout:

```json
{ "new_count": 3, "items": [ { "title": "...", "url": "...", "published": "...", "source": "..." } ] }
```

Setiap item punya field `topics` berisi topik yang cocok (mis. `aksi_korporasi`),
dan `src_key` sumbernya.

Flag yang tersedia:
- `--seed` — tandai semua item saat ini sebagai sudah dibaca (jalankan SEKALI saat setup).
- `--telegram` — kirim langsung ke Telegram tanpa perlu LLM.
- `--dry-run` — lihat hasil tanpa menandai sudah dibaca.
- `--limit N` — maksimal item per run (default dari `config.json`).
- `--list` — tampilkan status sumber & topik.
- `--enable-source K` / `--disable-source K` / `--enable-topic K` / `--disable-topic K`
  — pakai ini kalau user minta menyalakan/mematikan sumber atau topik.

## Yang harus kamu lakukan saat dipanggil dari cron

1. Jalankan script di atas (tanpa `--telegram`) dan baca JSON-nya.
2. Kalau `new_count` bernilai 0, jawab **persis** `[SILENT]` dan berhenti — jangan kirim apa pun.
3. Kalau ada berita baru, susun pesan ringkas dalam Bahasa Indonesia:
   - Maksimal 8 berita paling relevan dengan saham/pasar modal.
   - Format tiap item: judul tebal, satu kalimat inti (kalau perlu buka artikel untuk konteks), nama sumber, lalu URL.
   - Sebutkan kode emiten (4 huruf kapital) kalau ada di judul.
   - Jangan mengarang angka atau isi berita yang tidak ada di sumber.
4. Total pesan di bawah 500 kata.

## Catatan

- Kontan Insight & Kabar Bursa memakai RSS. Pasardana di-scrape dari `news-index` per tanggal
  (judul dari tag `<h2>`, plus jam dan kategori seperti "News - Stocks"). IDN Financials
  di-scrape dari halaman daftar berita dan isinya berbahasa Inggris — terjemahkan judulnya
  ke Bahasa Indonesia saat merangkum.
- IDX Keterbukaan Informasi memakai API resmi bursa. Judulnya berformat
  `[KODE] Judul Pengumuman` dan URL-nya menunjuk langsung ke **file PDF**, bukan halaman web —
  sebutkan itu sebagai "dokumen PDF" saat merangkum, dan jangan mengaku sudah membaca isi PDF
  kalau kamu belum membukanya.
- Kalau satu sumber gagal diambil, script tetap lanjut dengan sumber lain (error dicatat ke stderr).
