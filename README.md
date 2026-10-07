# GNSS availability dan pemeriksaan observasi

Script Python dengan matplotlib untuk ekspor gambar. Memindai subfolder `rawdata`, membaca isi observasi,
dan membuat timeline HTML mandiri yang dapat dibuka secara offline.

```powershell
python gnss_availability.py
```

Buka `output/availability.html` di browser. Filter stasiun dan tanggal, arahkan pointer
ke kotak hourly, atau klik untuk melihat metrik. Semua label waktu dalam UTC.

## Konfigurasi pengguna dan multi gunung

Edit `config.json`, lalu jalankan `python gnss_availability.py`. Argumen CLI selalu
mengungguli nilai konfigurasi. Lokasi data/output relatif dihitung terhadap folder
config.json; lokasi absolut juga bisa dipakai. Pada JSON Windows, gunakan `/` atau
escape backslash `\\`.

Struktur yang disarankan:

```text
rawdata/
  DEMPO/
    CDEM/2026/10/01/...
    CTAK/Ref.Data.26/Month.Oct/Day.01/...
  KRAKATAU/
    ST01/2026/10/01/...
  RINJANI/
    ST01/2026/10/01/...
```

Gunung dibaca dari folder. Nama stasiun dibaca dari `MARKER NAME` pada header RINEX
asli atau hasil konversi. Jika header kosong/tidak tersedia/`-UNKNOWN-`, nama folder
stasiun dipakai. Identitas laporan menggunakan `GUNUNG/STASIUN`: ST01 di KRAKATAU dan
RINJANI tetap terpisah. Header contoh arsip GTMD menyebut **GRTM**, sehingga kini
ditampilkan sebagai `DEMPO/GRTM`. Perbedaan nama folder/header dicatat pada files.json.
`stations.json` mencantumkan nama stasiun, gunung, dan nama folder asal.

Contoh mengatur pilihan dan periode (gabungkan ke config.json yang ada):

```json
{
  "data_directory": "D:/JupyterCode/GNSS_availability/rawdata",
  "output_directory": "output",
  "data_layout": "auto",
  "volcanoes": ["DEMPO", "KRAKATAU", "RINJANI"],
  "station_filter": "ALL",
  "station_name_source": "header",
  "period": {
    "start": "2026-10-01T00:00:00Z",
    "end": "2026-11-01T00:00:00Z"
  },
  "split_by_volcano": true
}
```

Pilihan **ALL**:

- `volcanoes: "ALL"`: semua gunung, atau daftar nama untuk sebagian gunung.
- `station_filter: "ALL"`: semua stasiun, atau daftar kode header/folder/`GUNUNG/STASIUN`.
- `period.start: "ALL"`: dari awal data yang dipilih.
- `period.end: "ALL"`: sampai akhir data yang dipilih.
- Keduanya ALL: seluruh rentang data. Akhir periode selalu **eksklusif**.

HTML memuat filter Gunung dan Stasiun dengan pilihan ALL. Laporan gabungan ada di
`output`; jika `split_by_volcano: true`, HTML/CSV/JSON dan gambar juga dibuat di
`output/DEMPO`, `output/KRAKATAU`, dan seterusnya. Tidak perlu membuat config per gunung.

| Pengaturan | Kegunaan / nilai |
|---|---|
| `data_directory`, `output_directory` | Lokasi sumber data dan hasil |
| `data_layout` | `auto`, `volcano_station` untuk root/gunung/stasiun, atau `station` untuk root/stasiun |
| `volcanoes`, `station_filter` | ALL atau daftar nama; filter tidak membedakan huruf besar/kecil |
| `station_name_source` | `header` (default) atau `folder` |
| `period.start`, `period.end` | Timestamp/tanggal UTC atau ALL |
| `split_by_volcano` | Simpan hasil per gunung selain gabungan |
| `interval_seconds` | Interval yang diharapkan untuk semua stasiun; null berarti header/inferensi |
| `stations` | Override interval dan tanggal aktif per stasiun; utamakan kunci `DEMPO/CDEM` |
| `time_scale` | `utc` sesuai instruksi, atau `header` untuk konversi skala waktu header |
| `image.mode` | auto, hourly, daily, both, none |
| `image.format`, `image.dpi`, `image.title` | png/jpeg/both, 50–600 dpi, judul gambar |
| `filter_files_by_date` | false membaca semua header; true melewati file di luar periode berdasarkan folder/nama |
| `converter_timeout` | Batas waktu setiap proses konversi dalam detik |
| `tools`, `converters` | Jalur executable dan konverter alternatif |

Default `filter_files_by_date: false` menjaga penemuan semua stasiun, termasuk yang
tidak punya data dalam periode pilihan. Untuk arsip besar, true dapat mempercepat scan,
tetapi stasiun yang seluruh filenya di luar periode tidak akan muncul. Folder tanggal
harus akurat jika opsi ini diaktifkan. Pemilihan stasiun berdasarkan header tetap
memerlukan pembacaan/konversi untuk menemukan nama tersebut.

```powershell
python gnss_availability.py --volcano DEMPO RINJANI --station ALL --start 2026-10-01 --end 2026-11-01
python gnss_availability.py --volcano ALL --start ALL --end ALL
```

Override `stations` menerima nama qualified terlebih dahulu, kemudian nama header,
kemudian kode folder. Untuk perbedaan periode aktif atau sampling antar gunung,
gunakan nama qualified. Laporan JSON lama yang belum memiliki identitas gunung perlu
dibuat ulang sebelum filter gunung dipakai lewat `--from-report`.

Rentang tertentu (waktu akhir **eksklusif**):

```powershell
python gnss_availability.py --start 2026-10-01 --end 2026-10-02
python gnss_availability.py --root rawdata/DEMPO --output output_dempo
```

## Format dan konverter

- RINEX observation 2/3/4: parser Python langsung; `.obs`, `.rnx`, `.yyo`.
- Leica `.m00`/`.mdb`: konversi TEQC, kemudian parser observasi yang sama.
- Trimble `.T01`/`.T02`: runpkr00 `-g -d` menghasilkan DAT/TGD, kemudian TEQC.
- ZIP: membaca anggota observasi; file navigasi tidak dihitung sebagai observasi.

Script mencari `teqc.exe` dan `runpkr00.exe` di subfolder `tools` terlebih dahulu,
kemudian folder script, lalu PATH. Pencarian folder `tools` relatif terhadap lokasi script.
Jalur tools relatif pada konfigurasi juga dihitung dari folder script.
Kedua executable sudah tersedia dalam folder `tools` workspace ini. Jika runpkr00 gagal
dengan Windows error 14001 (side-by-side configuration), pasang
[Microsoft Visual C++ 2008 SP1 Redistributable MFC Security Update](https://www.microsoft.com/en-us/download/details.aspx?id=26368),
pilih `vcredist_x86.exe` meskipun Windows 64-bit, lalu jalankan ulang script.
Unduhan runpkr00 Windows tersedia melalui
[dokumentasi UNAVCO](https://kb.unavco.org/article/112/trimble-runpkr00-latest-versions-744.html).
Letakkan executable dan dependency bawaannya dalam `tools` dan jalankan ulang script.
Untuk Trimble, tanggal folder diberikan ke TEQC dengan `-week YYYY:MM:DD`.
Ini mencegah tebakan GPS week berdasarkan jam komputer ketika DAT/TGD tidak menyediakan
informasi week sebelum epoch pertama. Tanggal folder harus sesuai tanggal data.

TEQC dijalankan dengan `-max_rx_SVs 64` agar jumlah satelit pada contoh Leica tidak
ditolak oleh batas receiver bawaan. Peringatan konverter dicatat dalam `files.json`;
TEQC dapat melewati record atau sinyal yang tidak didukung. Metrik sinyal hanya mencakup
observasi yang berhasil diterjemahkan. Rujukan:
[tutorial TEQC](https://www.unavco.org/software/data-processing/teqc/tutorial/tutorial.html),
[spesifikasi RINEX](https://files.igs.org/pub/data/format/rinex305.pdf).

Untuk alat lain, konfigurasi daftar argumen tanpa shell. Gunakan `{input}` dan `{output}`.
Contoh berikut adalah bentuk konfigurasi, bukan nama executable yang disediakan:

```json
{
  "converters": {
    "trimble": {
      "argv": ["C:/GNSS/converter.exe", "{input}", "{output}"],
      "stdout": false
    }
  }
}
```

Jika alat mengeluarkan RINEX ke stdout, set `stdout: true`. File input dikerjakan dalam
folder temporary; data asli tidak diubah. Konverter harus menghasilkan RINEX observasi biasa,
bukan Hatanaka/compact RINEX. Arsip GZIP/Hatanaka belum didukung.

## Waktu dan denominator

Default `--time-scale utc` mengikuti instruksi bahwa seluruh waktu data adalah UTC,
meskipun header contoh menyebut GPS. Perbedaan tersebut dicatat dalam laporan.
Jika timestamp isi data sebenarnya mengikuti header:

```powershell
python gnss_availability.py --time-scale header
```

Mode header mengurangi LEAP SECONDS untuk GPS/GAL/QZS. LEAP SECONDS harus tersedia
pada header; UTC/GLO diperlakukan sebagai UTC sesuai representasi waktu RINEX.
Skala lain ditolak. Waktu folder/nama file hanya menempatkan file yang belum bisa
dibaca; file sukses memakai timestamp observasi aktual. Pola hourly `a`–`x` diasumsikan
00–23 UTC; `0` berarti harian.

`config.json` dapat menetapkan interval sampling dan periode aktif stasiun:

```json
{
  "converter_timeout": 180,
  "tools": {
    "teqc": "C:/GNSS/teqc.exe",
    "runpkr00": "C:/GNSS/runpkr00.exe"
  },
  "stations": {
    "CDEM": {
      "interval_seconds": 15,
      "active_start": "2026-10-01T00:00:00Z",
      "active_end": "2026-10-02T00:00:00Z"
    }
  },
  "converters": {}
}
```

Jangan menyalin jalur tools contoh kecuali sesuai lokasi sebenarnya. Tanpa konfigurasi
periode aktif, semua stasiun diasumsikan diharapkan sepanjang rentang laporan bersama.
Folder contoh memuat September dan Oktober; akibatnya hari di antaranya tampil kosong.
Gunakan filter tanggal/CLI atau periode aktif untuk rentang operasional yang sesuai.
Masa depan dikecualikan berdasarkan jam komputer.

Prioritas interval: konfigurasi stasiun, konfigurasi global `interval_seconds`, header,
lalu selisih epoch yang paling sering muncul. Sumber interval dicatat. Untuk menghindari
salah inferensi pada data bergap, gunakan interval yang diharapkan dari konfigurasi receiver.

## Metrik dan warna

- **Abu-abu:** tidak ada observasi.
- **Hijau muda sampai tua:** kelengkapan sampling parsial sampai lengkap.
- **Garis oranye:** ada file yang belum dapat dinilai, termasuk konverter tidak tersedia.
- **Putih pucat:** di luar periode aktif atau waktu mendatang.

Epoch hanya dihitung bila memiliki observasi numerik satelit, bukan sekadar baris timestamp.
Timestamp identik dari file yang bertumpang tindih digabung. Persentase memakai slot sampling
yang terisi agar epoch berdekatan tidak menggandakan denominator.
Epoch dengan event flag 0/1 dihitung; event dan record cycle slip terpisah tidak dihitung
sebagai epoch observasi. Kehilangan lock dihitung dari bit 0 LLI pada pengukuran fase.

Metrik: epoch aktual/harapan, persentase sampling, gap count, gap terpanjang (termasuk
awal/akhir interval), first/last observation, mean/minimum satelit, mean C/N₀ dari
observable `S`, jumlah flag kehilangan lock, power failure, serta daftar sinyal.
Gap di bawah 5% interval diabaikan sebagai toleransi jitter. C/N₀ merupakan rerata semua
satelit/sinyal yang tersedia, bukan ambang lulus kualitas; blank SNR tidak dianggap nol.
Tidak ada penilaian multipath atau akurasi posisi pada versi ini.

Ringkasan persentase hanya memakai jam yang dapat dinilai; jumlah jam tidak diketahui
ditampilkan terpisah. Kotak hijau lengkap berarti cakupan epoch lengkap, bukan jaminan
seluruh sinyal lengkap atau posisi akurat. Periksa indikator observasi dan peringatan
konverter pada detail. Belum ada ambang kualitas C/N₀ atau LLI yang ditetapkan.

## Output dan verifikasi

### PNG dan JPEG untuk grup / laporan

Secara default script menghasilkan PNG dan JPEG dengan lebar 1.800 piksel (150 dpi).
Mode otomatis menghasilkan hourly dan daily untuk rentang sampai 62 hari; untuk rentang
lebih panjang, hanya daily agar gambar tetap terbaca. Daily lintas tahun menggunakan
satu panel per tahun dengan urutan stasiun yang sama. Gunakan 300 dpi untuk laporan
(lebar 3.600 piksel). Jika diperlukan: `python -m pip install matplotlib`.

```powershell
# Analisis sekaligus ekspor gambar
python gnss_availability.py --start 2026-10-01 --end 2026-10-02 --title "DEMPO - GNSS availability"

# Ekspor ulang hasil tersimpan tanpa konversi raw data
python gnss_availability.py --from-report output/availability.json --start 2026-10-01 --end 2026-10-02

# Gambar harian resolusi laporan
python gnss_availability.py --from-report output/availability.json --images daily --image-format png --dpi 300 --output output_laporan
```

`--images`: `auto` (default), `hourly`, `daily`, `both`, atau `none`.
`--image-format`: `both` (default), `png`, atau `jpeg`.
Gambar hourly/daily bernama `availability_hourly.png/.jpeg` dan
`availability_daily.png/.jpeg`. Ekspor ulang ke folder yang sama mengganti gambar
dengan nama yang sama; gunakan `--output` berbeda untuk menyimpan beberapa periode.
Mode `--from-report` hanya menghasilkan gambar dan tidak mengubah JSON/CSV/HTML sumber.

Persentase harian dan ringkasan dibobot dengan epoch yang diharapkan, bukan rerata
persentase jam. Jam unknown dikecualikan dari persentase dan jumlahnya ditampilkan.
Hari yang seluruhnya belum dinilai berwarna oranye; hari dengan sebagian jam unknown
memakai garis oranye. Putih berarti di luar periode aktif/laporan, abu-abu berarti
observasi kosong. Gambar mengikuti konfigurasi periode aktif pada laporan sumber.

- `availability.html`: timeline dengan filter, tooltip, dan detail.
- `availability.csv` / `availability.json`: metrik per stasiun per jam.
- `files.json`: hasil pemeriksaan file, peringatan, dan error.

```powershell
python -m unittest -v
```

Pengujian mencakup pembacaan observasi, gap, duplikasi, skala waktu, observasi kosong,
dan file tidak terbaca. Data contoh Leica serta RINEX juga diuji dengan pemindaian nyata.
