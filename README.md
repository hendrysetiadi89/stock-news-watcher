# Stock News Watcher — Panduan Pengguna

Notifikasi Telegram otomatis untuk berita dan keterbukaan informasi pasar modal Indonesia,
berjalan di komputer sendiri lewat Hermes Agent.

Dokumen ini menggantikan seluruh catatan setup sebelumnya.

---

## Daftar isi

1. [Apa yang dilakukan aplikasi ini](#1-apa-yang-dilakukan-aplikasi-ini)
2. [Prasyarat](#2-prasyarat)
3. [Setup dari nol](#3-setup-dari-nol)
4. [Konfigurasi](#4-konfigurasi)
5. [Menjalankan manual](#5-menjalankan-manual)
6. [Penjadwalan otomatis](#6-penjadwalan-otomatis)
7. [Autostart saat komputer menyala](#7-autostart-saat-komputer-menyala)
8. [Operasi harian](#8-operasi-harian)
9. [Troubleshooting](#9-troubleshooting)
10. [Catatan teknis](#10-catatan-teknis)

---

## 1. Apa yang dilakukan aplikasi ini

Setiap beberapa menit, aplikasi memeriksa lima sumber berita pasar modal, mengambil yang
**belum pernah dilaporkan sebelumnya**, menyaringnya berdasarkan topik yang Anda pilih,
lalu mengirimkannya ke Telegram.

**Sumber yang dipantau:**

| Sumber | Cara ambil | Volume harian |
|---|---|---|
| Pasar Dana | scrape `news-index` per tanggal | ~39 artikel |
| IDN Financials | scrape halaman berita (bahasa Inggris) | ~15 artikel |
| Kontan Insight | RSS | ~10 artikel |
| Kabar Bursa | RSS | ~50 artikel |
| IDX Keterbukaan Informasi | API resmi bursa | puluhan pengumuman |

**Alur kerja:**

```
watch.py  →  ambil 5 sumber  →  buang yang sudah pernah dikirim (seen.db)
          →  saring berdasarkan topik (config.json)
          →  kirim ke Telegram Bot API
```

Penjadwalan ditangani cron milik Hermes Agent. Pengiriman notifikasi **tidak memakai LLM**,
sehingga tidak menghabiskan kuota model dan tetap bekerja meski autentikasi provider bermasalah.

**Letak berkas** (di dalam WSL Ubuntu):

| Berkas | Isi |
|---|---|
| `~/.hermes/skills/stock-news-watcher/watch.py` | program utama |
| `~/.hermes/skills/stock-news-watcher/config.json` | pengaturan sumber & topik |
| `~/.hermes/skills/stock-news-watcher/seen.db` | riwayat berita yang sudah dikirim |
| `~/.hermes/skills/stock-news-watcher/SKILL.md` | instruksi untuk mode agent |
| `~/.hermes/scripts/stock-news.sh` | pembungkus yang dipanggil cron |
| `~/.config/systemd/user/hermes-gateway.service.d/announce.conf` | hook pengumuman "radar aktif" |
| `%USERPROFILE%\.hermes\hermes-hold.vbs` | penahan VM WSL2 (sisi Windows) |
| `~/.hermes/logs/stock-news-watcher.log` | log jalannya program |
| `~/.hermes/.env` | token Telegram |

---

## 2. Prasyarat

- Windows 10/11 dengan WSL2 dan Ubuntu
- Akun Telegram
- Akun Nous Portal (hanya diperlukan untuk fitur obrolan dan mode agent, **bukan** untuk notifikasi berita)

> **Terminal mana?**
> Perintah yang diawali `wsl`, `taskschd.msc`, atau `$env:` dijalankan di **PowerShell**.
> Perintah `hermes`, `python3`, `sudo`, dan yang memakai `~/` dijalankan di **Ubuntu**.
>
> ```
> PS C:\Users\hendr>     ← Windows
> hendr@Hendry:~$        ← Ubuntu
> ```
>
> Membuka Ubuntu: Start menu → ketik `Ubuntu` → Enter. Atau ketik `wsl` di PowerShell.
>
> Agar tidak salah terminal, jadikan Ubuntu profil default di Windows Terminal:
> **Ctrl+,** → Startup → Default profile → Ubuntu → Save.

---

## 3. Setup dari nol

### 3.1 Pasang WSL2 — *PowerShell sebagai Administrator*

```powershell
wsl --install -d Ubuntu
```

Reboot bila diminta. Saat Ubuntu pertama kali dibuka, Anda membuat username dan password
UNIX baru — akun lokal Linux, tidak terkait akun Microsoft.

Kalau `wsl --install` diblokir, aktifkan dulu lewat *Turn Windows features on or off*:
**Virtual Machine Platform** dan **Windows Subsystem for Linux**, lalu reboot.

### 3.2 Pasang Hermes Agent — *Ubuntu*

```bash
sudo apt update && sudo apt install -y curl python3
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
exec $SHELL -l
hermes --version
```

### 3.3 Set zona waktu — *Ubuntu*

```bash
sudo ln -sf /usr/share/zoneinfo/Asia/Jakarta /etc/localtime
date
```

Harus menunjukkan WIB. **Jangan dilewat** — Ubuntu default memakai UTC, dan jadwal
jadwal berjam akan meleset 7 jam dari yang Anda maksud.

### 3.4 Autentikasi Nous Portal — *Ubuntu*

```bash
hermes auth
```

Buka URL yang muncul di browser Windows. Langkah ini **tidak** diperlukan untuk notifikasi
berita, tapi tanpanya bot tidak bisa diajak mengobrol.

### 3.5 Buat bot Telegram

1. Chat **@BotFather** → `/newbot`
2. Isi nama tampilan bebas, mis. `Radar Saham`
3. Isi username — harus unik dan berakhiran `bot`, mis. `radarsaham_hendry_bot`
4. Simpan token yang diberikan. **Token ini setara password bot** — jangan dibagikan.
5. Chat **@userinfobot** → catat user ID numerik Anda

### 3.6 Sambungkan Telegram ke Hermes — *Ubuntu*

```bash
hermes gateway setup
```

Pilih Telegram, masukkan token dan user ID. Wizard menawarkan menjalankan gateway — pilih ya.

Verifikasi:

```bash
hermes gateway status
grep -o '^[A-Z_]*' ~/.hermes/.env
```

Harus terlihat `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_ALLOWED_USERS`. Kalau
`TELEGRAM_HOME_CHANNEL` juga ada, itu tujuan default notifikasi terjadwal.

> Di Ubuntu ber-systemd, gateway dipasang sebagai **systemd user service**.
> **Jangan** menjalankan `hermes gateway run` dari shell — Hermes akan menolaknya, karena
> gateway kedua meninggalkan dispatcher liar yang menulis ke database yang sama.
> Kelola dengan `hermes gateway status` / `restart`.

### 3.7 Pasang berkas aplikasi — *Ubuntu*

Kloning repo ini ke lokasi kerjanya, lalu pasang pembungkus cron dan hook pengumuman:

```bash
git clone <url-repo> ~/.hermes/skills/stock-news-watcher
cd ~/.hermes/skills/stock-news-watcher

# pembungkus yang dipanggil cron
mkdir -p ~/.hermes/scripts
cp stock-news.sh ~/.hermes/scripts/
chmod +x ~/.hermes/scripts/stock-news.sh

# hook: umumkan "radar saham aktif" setiap gateway menyala
mkdir -p ~/.config/systemd/user/hermes-gateway.service.d
cp systemd/announce.conf ~/.config/systemd/user/hermes-gateway.service.d/
systemctl --user daemon-reload
```

### 3.8 Seed — *Ubuntu*, sekali saja

```bash
python3 ~/.hermes/skills/stock-news-watcher/watch.py --seed
```

Ini menandai semua berita yang ada **sekarang** sebagai sudah dibaca, sehingga run pertama
tidak mengirim ratusan berita lama sekaligus.

> Jalankan seed **hanya setelah semua sumber terbukti berhasil diambil**. Sumber yang gagal
> saat seed tidak ikut ditandai, sehingga seluruh backlog-nya akan terkirim pada run pertama.

---

## 4. Konfigurasi

Semua pengaturan ada di `config.json`. Untuk sekadar menyalakan/mematikan, **tidak perlu
mengedit berkas** — gunakan perintah CLI.

```bash
cd ~/.hermes/skills/stock-news-watcher
python3 watch.py --list
```

### 4.1 Menyalakan / mematikan sumber

```bash
python3 watch.py --disable-source kabarbursa
python3 watch.py --enable-source kabarbursa
```

Nama yang valid: `pasardana`, `idnfinancials`, `kontan_insight`, `kabarbursa`, `idx_disclosure`

Sumber yang OFF tidak dikunjungi sama sekali. Menyalakannya kembali aman — berita yang
terbit selama ia mati tidak dikirim susulan.

### 4.2 Menyalakan / mematikan topik

```bash
python3 watch.py --disable-topic makro_dan_moneter
python3 watch.py --enable-topic komoditas
```

| Topik | Default | Contoh kata kunci |
|---|---|---|
| `ihsg_dan_pasar` | ON | ihsg, indeks, bursa, emiten, suspensi |
| `aksi_korporasi` | ON | rups, dividen, ipo, right issue, buyback, merger |
| `kinerja_keuangan` | ON | laba, rugi, pendapatan, laporan keuangan |
| `aliran_dana_asing` | ON | asing, foreign, net buy, inflow |
| `makro_dan_moneter` | ON | rupiah, inflasi, bi rate, the fed, ojk |
| `komoditas` | OFF | emas, batu bara, cpo, nikel, minyak |
| `global` | OFF | wall street, nasdaq, hang seng, nikkei |

**Cara kerja penyaringan:** sebuah berita lolos kalau judulnya mengandung salah satu kata
kunci dari topik yang ON. Pencocokan bersifat **substring dan tidak peduli huruf besar-kecil**
— kata kunci `dividen` otomatis menangkap `Dividen`, `dividend`, dan `Pembagian Dividen Tunai`.

> **Aturan penting:** kalau **semua** topik dimatikan, penyaringan mati total dan
> **semua** berita lolos. Bukan sebaliknya.

### 4.3 Batasan topik per sumber

Sebuah sumber bisa dibatasi hanya pada topik tertentu. Secara default hanya IDX yang dibatasi:

```json
"idx_disclosure": {
  "enabled": true,
  "label": "IDX Keterbukaan Informasi",
  "topics": ["aksi_korporasi", "kinerja_keuangan"]
}
```

Ini disengaja. IDX menerbitkan puluhan pengumuman rutin setiap hari
("Pencatatan Saham", "Laporan Bulanan Registrasi Pemegang Efek"). Tanpa pembatasan ini,
kata "saham" di topik `ihsg_dan_pasar` akan meloloskan hampir semuanya.

Efeknya: `--disable-topic aksi_korporasi` memangkas IDX secara drastis, sedangkan
`--enable-topic komoditas` tidak berpengaruh apa pun pada IDX.

Untuk mengubahnya, edit `config.json`. Menambah nama ke daftar hanya **memperlebar** yang
lolos — aman. Mengosongkannya (`"topics": []`) membuat semua topik aktif berlaku untuk IDX.

### 4.4 Watchlist emiten

Di `config.json`, bagian `options`:

```json
"tickers": ["BBCA", "TLKM", "ANTM"]
```

Berita yang menyebut kode ini **selalu lolos**, menembus seluruh penyaringan topik. Berguna
untuk memantau emiten tertentu secara penuh tanpa melonggarkan filter untuk yang lain.

### 4.5 Opsi lain

| Opsi | Default | Arti |
|---|---|---|
| `max_per_run` | 15 | maksimal item per run (bisa ditimpa `--limit`) |
| `pasardana_days` | 2 | berapa hari ke belakang Pasardana diambil |
| `idx_page_size` | 50 | berapa pengumuman IDX diambil per panggilan |

### 4.6 Mengedit berkas langsung

```bash
nano ~/.hermes/skills/stock-news-watcher/config.json
```

Selalu buat cadangan dulu, dan periksa setelah menyimpan:

```bash
cp config.json config.json.bak
# ...edit...
python3 -c "import json;json.load(open('config.json',encoding='utf-8'));print('JSON valid')"
```

Kalau rusak: `cp config.json.bak config.json`.

Dua kesalahan JSON yang paling sering: menulis `True` alih-alih `true`, dan koma di
belakang entri terakhir.

---

## 5. Menjalankan manual

```bash
cd ~/.hermes/skills/stock-news-watcher
```

| Perintah | Fungsi |
|---|---|
| `python3 watch.py --list` | tampilkan status sumber & topik |
| `python3 watch.py --dry-run` | lihat berita baru **tanpa** menandainya sudah dibaca |
| `python3 watch.py` | cetak berita baru sebagai JSON, tandai sudah dibaca |
| `python3 watch.py --telegram` | kirim berita baru ke Telegram |
| `python3 watch.py --seed` | tandai semua yang ada sekarang sebagai sudah dibaca |
| `python3 watch.py --limit 50` | ubah batas item untuk run ini saja |
| `python3 watch.py --empty-notice 60` | kirim "tidak ada berita baru" bila sudah 60 menit hening |

Agar tidak perlu berpindah folder:

```bash
echo "alias saham='python3 ~/.hermes/skills/stock-news-watcher/watch.py'" >> ~/.bashrc
source ~/.bashrc
saham --list
```

### Membuktikan pengiriman Telegram bekerja

Kalau lama tidak ada notifikasi dan Anda ingin memastikan sistemnya hidup:

```bash
cd ~/.hermes/skills/stock-news-watcher
mv seen.db seen.db.hold
python3 watch.py --telegram --limit 3
mv -f seen.db.hold seen.db
```

Database dedup disingkirkan sementara sehingga semua berita dianggap baru, tiga di antaranya
dikirim, lalu database asli dikembalikan agar tidak ada berita terkirim dua kali.

### Notifikasi "radar saham aktif"

Dikirim **setiap kali gateway menyala** — saat WSL boot, saat `hermes gateway restart`,
atau saat systemd menghidupkannya kembali setelah crash. Pemicunya bukan cron, melainkan
`ExecStartPost` pada `hermes-gateway.service` (lihat `systemd/announce.conf`), sehingga
pesannya datang seketika dan tidak perlu menunggu tick berikutnya.

```
✅ Radar saham aktif
16:14 WIB · gateway menyala

Sumber (2): IDN Financials, IDX Keterbukaan Informasi
Topik (5): ihsg_dan_pasar, aksi_korporasi, kinerja_keuangan, aliran_dana_asing, makro_dan_moneter
```

Hook itu memanggil `watch.py --telegram --announce`, yang hanya mengirim pesan lalu keluar
tanpa mengambil data dari kelima situs — supaya start-up gateway tidak tertunda.

Dua pengaman pada hook: awalan `-` pada `ExecStartPost` membuat kegagalan diabaikan
(gateway tetap dianggap berhasil start walau Telegram tak terjangkau), dan `timeout 60`
mencegah hook menggantung proses start-up.

Menguji tanpa reboot:

```bash
hermes gateway restart
```

`watch.py` juga punya `--startup-notice` dengan mode `always`, `once`, `daily`, atau angka
menit jeda. Itu jalur alternatif lewat cron dan **tidak dipakai** pada setup ini —
pengumuman ditangani hook systemd supaya tidak ada dua sumber yang saling menimpa.

### Notifikasi saat tidak ada berita

`--empty-notice` punya dua mode:

| Nilai | Perilaku | Volume |
|---|---|---|
| `always` | kirim di setiap tick tanpa berita | ~90 pesan/hari |
| `60` (angka menit) | kirim hanya bila sudah sekian menit **hening** | ~8 pesan/hari |
| tidak dipakai | tidak pernah kirim | 0 |

Hitungannya adalah hening sejak **pesan terakhir apa pun**, bukan sejak notice terakhir.
Jadi kalau berita masuk pukul 10.00, notice paling cepat muncul pukul 11.00.

Bentuk pesannya:

```
🔕 Tidak ada berita baru
13:26 WIB · 65 item dipantau
```

Angka "item dipantau" adalah jumlah berita yang berhasil diambil dari semua sumber pada tick
tersebut — tanda hidup. Kalau angkanya anjlok drastis, ada sumber yang bermasalah.

---

## 6. Penjadwalan otomatis

### 6.1 Membuat jadwal — *Ubuntu*

```bash
hermes cron create "*/2 * * * *" \
  --no-agent \
  --script stock-news.sh \
  --deliver telegram \
  --name "Berita saham (jam bursa)"
```

Format jadwal adalah cron 5 kolom: `menit jam tanggal bulan hari`.
`*/2 * * * *` berarti tiap 2 menit, sepanjang hari, setiap hari — tanpa filter jam
maupun hari.

Kalau ingin membatasi, kolomnya adalah `menit jam tanggal bulan hari`:

| Ekspresi | Arti |
|---|---|
| `*/2 * * * *` | tiap 2 menit, tanpa batas (dipakai sekarang) |
| `*/2 * * * 1-5` | tiap 2 menit, hanya Senin–Jumat |
| `*/5 8-18 * * 1-5` | tiap 5 menit, 08.00–18.59, hari kerja |
| `0 9 * * 1-5` | sekali sehari pukul 9 pagi, hari kerja |

> **Batas jam bersifat inklusif.** Kalau nanti Anda memakai filter jam, `8-18` mencakup
> seluruh jam 18 — tick terakhir pukul 18.59, bukan 18.00.

> **Beban pada sumber.** Interval 2 menit berarti ~720 run per hari, masing-masing memanggil
> IDX dan IDN Financials. IDX diketahui membatasi laju dan sesekali membalas 403. Mekanisme
> coba-ulang menanganinya dan dedup mencegah berita hilang, tetapi pantau log beberapa hari:
>
> ```bash
> grep -c "GAGAL fetch" ~/.hermes/logs/stock-news-watcher.log
> grep "tertinggal" ~/.hermes/logs/stock-news-watcher.log | tail -20
> ```
>
> Kalau kegagalan menjadi terus-menerus dan bukan sesekali, longgarkan ke `*/5`.

Contoh jadwal lain:

| Ekspresi | Arti |
|---|---|
| `*/15 * * * *` | tiap 15 menit, sepanjang hari |
| `0 9 * * 1-5` | sekali sehari pukul 9 pagi, hari kerja |
| `*/10 8-17 * * *` | tiap 10 menit, 8 pagi–17.59, setiap hari |

### 6.2 Mengelola jadwal

```bash
hermes cron list
hermes cron run <job_id>       # jalankan sekarang, tanpa menunggu jadwal
hermes cron pause <job_id>
hermes cron resume <job_id>
hermes cron edit <job_id> --schedule "*/5 * * * *"
hermes cron remove <job_id>
```

`hermes cron run` adalah cara tercepat menguji seluruh rantai tanpa menunggu.

### 6.3 Aturan mode `--no-agent`

Mode ini menjalankan script tanpa LLM sama sekali. Tiga hal yang menentukan bentuk
`stock-news.sh`:

- Script **wajib** berada di dalam `~/.hermes/scripts/`. Path di luar itu ditolak.
- **stdout kosong = tick senyap.** stdout yang tidak kosong dikirim apa adanya ke Telegram —
  itu sebabnya output `watch.py` dibuang ke `/dev/null`, kalau tidak potongan JSON hasilnya
  ikut terkirim tiap 5 menit.
- **Exit code bukan nol memicu alert error.** `watch.py` mengembalikan 1 hanya kalau
  **semua** sumber gagal, jadi Anda tetap diberi tahu bila ada yang benar-benar rusak.

Environment subprocess dibersihkan dari kredensial Hermes. Ini tidak jadi masalah karena
`watch.py` membaca token Telegram langsung dari berkas `~/.hermes/.env`.

### 6.4 Mode agent (opsional)

Kalau ingin berita dirangkum dan diterjemahkan alih-alih dikirim mentah:

```bash
hermes cron create "every 2h" \
  "Jalankan skill stock-news-watcher untuk mengambil berita saham baru, lalu kirim ringkasannya. Kalau tidak ada berita baru, jawab persis [SILENT]." \
  --skill stock-news-watcher --name "Ringkasan saham" --deliver telegram
```

Mode ini memakai kuota LLM, jadi jangan dijadwalkan tiap 5 menit. Kata `[SILENT]` membuat
Hermes tidak mengirim apa pun saat tidak ada berita.

Kedua job bisa hidup berdampingan — keduanya berbagi `seen.db` yang sama, jadi tidak akan
ada duplikat: siapa pun yang jalan lebih dulu menandai item sebagai terbaca.

---

## 7. Autostart saat komputer menyala

Gateway dijalankan systemd, dan systemd hanya berjalan ketika distro WSL hidup. Windows
mematikan WSL begitu tidak ada proses di dalamnya, jadi diperlukan dua hal.

### 7.1 Aktifkan linger — *Ubuntu*

```bash
loginctl enable-linger $USER
loginctl show-user $USER | grep Linger
```

Harus `Linger=yes`. Tanpa ini, service baru menyala saat Anda membuka terminal Ubuntu.

### 7.2 Bangunkan WSL saat login Windows

Buka **Task Scheduler** (`taskschd.msc`) → **Create Task**:

| Tab | Isian |
|---|---|
| General | Nama `Hermes Gateway (WSL)`; pilih **Run only when user is logged on**; **jangan** centang *Run with highest privileges* |
| Triggers | **At log on** → akun Anda → *Delay task for* **30 seconds** |
| Actions | Program: `wscript.exe`  ·  Arguments: `"C:\Users\<nama>\.hermes\hermes-hold.vbs"` |
| Conditions | hilangkan centang *Start only if on AC power* |
| Settings | centang *restart every 1 minute, up to 3 times* |

`hermes-hold.vbs` berisi satu baris:

```vbs
CreateObject("WScript.Shell").Run "wsl.exe -d Ubuntu -- sleep infinity", 0, False
```

Argumen `0` menyembunyikan jendela konsol, `False` berarti tidak menunggu selesai. Jadi
VBS-nya berakhir seketika sementara `wsl.exe` tetap hidup di latar sebagai **penahan VM**.

Karena itu **`State` task akan kembali `Ready` dalam sedetik, dan itu benar** — penahannya
ada di dalam WSL, bukan pada proses Windows yang harus terus hidup.

Menjalankan `wsl.exe -- sleep infinity` langsung dari Actions juga bekerja, tetapi
meninggalkan jendela konsol terbuka sepanjang sesi. Pembungkus VBS ini menghilangkannya.

Karena task selesai seketika, opsi *restart on failure* jadi tidak berguna. Sebagai
pengaman, tambahkan trigger kedua: *Daily*, ulangi setiap 1 jam. Menjalankan VBS saat
penahan sudah hidup tidak berbahaya — hanya satu proses menganggur beberapa KB.

> **Jangan pakai `-- /bin/true` atau perintah sekali jalan lain.** Perintah itu langsung
> selesai, VM kembali menganggur, dan beberapa menit kemudian Windows mematikannya —
> gateway ikut mati, cron berhenti, dan bot mengirim
> "Gateway shutting down - Your current task will be interrupted".
> Linger menjaga service hidup *di dalam* distro; ia tidak mencegah distronya dimatikan.

Cara memastikan ini benar-benar bekerja: biarkan satu jam, lalu jalankan `uptime -p` di
Ubuntu. Kalau angkanya bertambah terus, VM bertahan. Kalau selalu kembali ke menit-menit
pertama, berarti ada yang masih mematikannya.

Sebagai pengaman tambahan, bisa juga dibuat `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
vmIdleTimeout=-1
```

lalu `wsl --shutdown` sekali agar terbaca.

> Perlakukan ini **hanya sebagai pelengkap**. Kunci `vmIdleTimeout` dilaporkan tidak
> konsisten antar versi Windows dan pada banyak sistem tidak berpengaruh sama sekali.
> Yang benar-benar menentukan adalah proses penahan (`sleep infinity`).

Penyebab dasarnya: WSL2 mematikan VM sekitar **satu menit setelah sesi terakhir ditutup**.
Itu perilaku bawaan. Setiap perintah sekali jalan seperti
`wsl -d Ubuntu -- <perintah>` membuka sesi lalu menutupnya, sehingga tanpa proses penahan
VM akan mati semenit kemudian dan gateway ikut berhenti — memunculkan pesan
"Gateway shutting down" di Telegram.

### 7.3 Verifikasi — *PowerShell*

```powershell
wsl --shutdown
```

Tunggu 10 detik, klik kanan task → **Run**, tunggu ±20 detik:

```powershell
wsl -d Ubuntu -- bash -lc "hermes gateway status"
```

Bukti sesungguhnya baru didapat setelah restart Windows: login, tunggu semenit, jalankan
perintah yang sama, dan periksa apakah `Active: since` cocok dengan waktu login Anda.

---

## 8. Operasi harian

```bash
# apakah semuanya hidup?
hermes gateway status
hermes cron list

# apa yang terjadi belakangan ini?
tail -30 ~/.hermes/logs/stock-news-watcher.log
journalctl --user -u hermes-gateway -f

# setelah mengubah konfigurasi Hermes
hermes gateway restart
```

Bentuk log yang sehat:

```
[13:15:11] Kontan Insight: 10 item
[13:15:11] Kabar Bursa: 50 item
[13:15:11] IDN Financials: 15 item
[13:15:11] Pasar Dana: 78 item
[13:15:11] IDX Keterbukaan Informasi: 50 item
[13:15:11] 3 item terkirim dalam 1 pesan
```

Tanda `<-- PERIKSA: 0 item` menandakan sebuah sumber berhenti menghasilkan apa pun.

---

## 9. Troubleshooting

| Gejala | Penyebab & tindakan |
|---|---|
| Tidak ada notifikasi sama sekali | Cek `hermes cron list` (job ada & aktif) dan `hermes gateway status`. Buktikan jalur Telegram dengan trik `seen.db` di bagian 5. |
| Sepi tapi sistem sehat | Wajar. Cek `--list` — sumber mungkin ada yang OFF, atau topik terlalu sempit. |
| Bot balas "Provider Authentication failed" | Jalankan `hermes auth`. **Tidak memengaruhi notifikasi berita** — cron `--no-agent` tidak memakai LLM. |
| Bot diam total | Gateway mati. `hermes gateway status`, lalu `hermes gateway restart`. |
| Bot balas "not authorized" | User ID Anda belum ada di `TELEGRAM_ALLOWED_USERS` di `~/.hermes/.env`. |
| `IDX: GAGAL fetch (403)` sesekali | Normal. IDX membatasi laju; program mencoba ulang 3× dengan jeda 3 dan 8 detik. Tick berikutnya tetap menangkap beritanya. |
| Sebuah sumber `0 item` terus-menerus | Struktur situs berubah. Parser terkait di `watch.py` perlu disesuaikan. |
| Notifikasi membanjir | Perbesar interval cron, matikan topik, atau persempit sumber. |
| Berita terkirim dua kali | `seen.db` terhapus atau tergantikan. Jalankan `--seed` untuk menyetel ulang. |
| `command not found: wsl` | Anda sudah berada di dalam Ubuntu. `wsl` adalah perintah Windows. |
| `python3: can't open file '/mnt/c/...'` | Anda tidak berada di folder yang benar. `cd ~/.hermes/skills/stock-news-watcher`. |
| `hermes cron list` bilang kosong padahal ada | Anda menjalankannya di PowerShell. Instalasi Hermes di Windows terpisah dan punya profilnya sendiri. |
| `hermes gateway run` ditolak | Benar — gateway sudah dikelola systemd. Gunakan `hermes gateway restart`. |

**Menyetel ulang riwayat dari nol:**

```bash
cd ~/.hermes/skills/stock-news-watcher
rm seen.db
python3 watch.py --seed
```

---

## 10. Catatan teknis

### Cara dedup bekerja

Kunci dedup adalah **URL**, bukan waktu terbit. Konsekuensinya: artikel yang judulnya
diperbarui tidak dikirim ulang, tick yang terlewat tidak menyebabkan berita hilang, dan
duplikasi tautan di halaman sumber otomatis tergabung.

Semua item yang terlihat ditandai sudah dibaca **walaupun tersaring topik**. Ini disengaja:
kalau tidak, menyalakan sebuah topik akan langsung memicu banjir berita lama.

### Keanehan tiap sumber

**Pasardana** — halaman `news-index?date=YYYY-MM-DD` memuat seluruh berita satu hari tanpa
pagination. Judul diambil dari tag `<h2>` di dalam anchor; memakai seluruh teks anchor akan
ikut menyerap nomor urut, kategori, jam, dan nama penulis. Diambil untuk hari ini dan
kemarin agar tidak ada yang terlewat saat pergantian hari.

**IDN Financials** — setiap artikel muncul dua kali: anchor gambar (judul ada di atribut
`title=`) dan anchor teks (berformat `"04 Sep 2026 06:00\n\nJudul"`). Judul diambil dari
atribut `title` lebih dulu. Isinya berbahasa Inggris.

**IDX** — memakai endpoint `/primary/NewsAnnouncement/GetAllAnnouncement`, yaitu endpoint
yang dipakai halaman keterbukaan informasi itu sendiri. Terurut menurun, 100 item mencakup
sekitar 19 jam, dan ketertinggalannya terhadap waktu nyata hanya belasan menit.

> **Jangan kembali ke `/primary/ListedCompany/GetAnnouncement`.** Endpoint itu tampak mirip
> dan mengembalikan data yang ter-parse rapi, tetapi **tertinggal berjam-jam** — pernah
> terukur 5,5 jam, dan pencarian per kode emiten bahkan hanya mengembalikan data berbulan
> lalu. Kesegarannya tidak terlihat dari bentuk responsnya; hanya terlihat kalau
> dibandingkan dengan apa yang tampil di halaman web.
>
> Jangan pula menambahkan parameter `dateFrom` / `dateTo` / `keyword` / `emitenType` pada
> endpoint yang baru — server membalas **503**.
>
> Halaman HTML-nya sendiri tidak bisa dipakai: dilindungi Cloudflare, klien non-browser
> mendapat halaman captcha.

Tidak ada permalink HTML per pengumuman, sehingga tautan menunjuk langsung ke **berkas PDF**
— yang dipilih adalah lampiran dengan `IsAttachment = 0`. Judul berformat
`[KODE] Judul Pengumuman`; `Code` dipad spasi sehingga perlu di-strip. Item ber-`IsHidden`
dibuang. Setiap run mencatat ketertinggalan endpoint ke log, dengan penanda
`<-- PERIKSA: endpoint tertinggal jauh` bila melewati 90 menit.

**Kontan Insight & Kabar Bursa** — RSS biasa. Perlu dicatat bahwa `pasardana.id/feed`,
`pasardana.id/rss`, dan `kabarbursa.com/feed` semuanya tidak ada; hanya
`kabarbursa.com/feed.xml` yang valid.

### Menambah sumber baru

Di `watch.py`:

1. Tambahkan entri di fungsi `source_urls()`
2. Tulis fungsi parser yang mengembalikan daftar dict berisi
   `title`, `url`, `published`, `category`, `source`, `tickers`
3. Daftarkan parser itu di dict `PARSERS`
4. Tambahkan entri sumbernya di `DEFAULT_CONFIG["sources"]`

Program hanya memakai pustaka bawaan Python — tidak perlu `pip install` apa pun.

### Batas Telegram

Telegram membatasi sekitar 20 pesan per menit per chat dan 4096 karakter per pesan. Karena
itu banyak berita digabung ke dalam sedikit pesan: 100 berita menjadi sekitar 9 pesan yang
terkirim dalam ~12 detik. Preview tautan dimatikan karena satu pesan memuat banyak tautan.
