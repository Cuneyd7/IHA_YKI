@echo off
title GitHub Otomatik Senkronizasyon
echo ===================================================
echo YKI Kodlari Icin Otomatik Senkronizasyon Basladi...
echo ===================================================
echo Bu pencere acik kaldigi surece kodlariniz her 60 saniyede bir
echo kontrol edilip GitHub'a gonderilecektir.
echo.

:dongu
:: Once buluttaki yenilikleri cek (Hata almamak icin)
git pull --no-edit >nul 2>&1

:: Sonra senin degisikliklerini gonder
git add .
git commit -m "Python IDLE uzerinden otomatik guncelleme"
git push
timeout /t 60 >nul
goto dongu