' hermes-hold.vbs
' Menahan VM WSL2 tetap hidup tanpa menampilkan jendela konsol.
'
' WSL2 mematikan VM sekitar satu menit setelah sesi terakhir ditutup. Proses
' 'sleep infinity' di bawah ini adalah sesi penahannya, supaya systemd dan
' hermes-gateway di dalam Ubuntu tetap berjalan.
'
' Argumen Run: 0 = jendela disembunyikan, False = jangan tunggu proses selesai.
' Karena itu skrip ini berakhir seketika, sementara wsl.exe tetap hidup di latar.

CreateObject("WScript.Shell").Run "wsl.exe -d Ubuntu -- sleep infinity", 0, False
