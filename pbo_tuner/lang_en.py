"""İngilizce çeviri sözlüğü: anahtar = Türkçe kaynak metin (`i18n.tr` çağrılarındaki metnin aynısı).
Her anahtarın değeri aynı {yer tutucuları} içermelidir (tests/test_i18n.py denetler)."""

EN = {
    "\n================================================================================\n PBO AutoTuner - UYARI\n * Bu araç işlemcinin voltaj/frekans eğrisini (Curve Optimizer) CANLI değiştirir ve\n   bilerek kararsız ayarlara iner. Çökme, mavi ekran, kendiliğinden yeniden başlatma\n   BEKLENEN davranıştır. Çalışma durumu diske kaydedilir ve devam eder.\n * Çalışırken önemli dosyalarını kaydet/kapat. Windows kurulumunun bozulma riskine karşı\n   bir sistem geri yükleme noktası oluşturman önerilir.\n * Anakartta BIOS'ta Curve Optimizer = Auto/0 olmalı (araç test sırasında kendi değerlerini yazar).\n * Sistem DONARSA (yeniden başlamaz) reset tuşuna bas; araç kaldığı yerden devam eder.\n * Garanti/hasar sorumluluğu sana aittir. PBO/undervolt garantiyi etkileyebilir.\n================================================================================\n":
        "\n================================================================================\n PBO AutoTuner - WARNING\n * This tool changes the processor's voltage/frequency curve (Curve Optimizer) LIVE and\n   deliberately steps down to unstable settings. Crashes, blue screens and spontaneous\n   reboots are EXPECTED behaviour. Progress is saved to disk and resumes automatically.\n * Save and close important files while it runs. Creating a system restore point is\n   recommended in case your Windows installation gets damaged.\n * In the motherboard BIOS, Curve Optimizer must be Auto/0 (the tool writes its own values during tests).\n * If the system FREEZES (does not reboot), press the reset button; the tool resumes where it left off.\n * You are responsible for any warranty issues or damage. PBO/undervolting may affect your warranty.\n================================================================================\n",
    'Rapor yazıldı: {path}':
        'Report written: {path}',
    "Plan: her çekirdekte ~{sec} sn hafif + aralıklı yük (tüm CO'lar uygulanmış), sonra {idle} dk boşta bekleme. Yaklaşık {est} dk.":
        'Plan: ~{sec} s of light + intermittent load per core (all CO values applied), then {idle} min idle wait. About {est} min.',
    'Kalan çekirdek 2 geri çekilip yeniden denenir. Boşta beklerken bilgisayara dokunma; uyku modunu kapat.':
        'A core that fails is backed off by 2 and retried. Do not touch the computer during the idle wait; disable sleep mode.',
    'Aşama: {stage}   çökme: {crashes}   durduruldu: {halted}   bekleyen test: {pending}':
        'Stage: {stage}   crashes: {crashes}   halted: {halted}   pending test: {pending}',
    'Çekirdek  faz       kararlı  kararsız  aday  nihai  çökme':
        'Core      phase      stable  unstable  cand  final  crash',
    'Uygulandı (geçici, yeniden başlatınca silinir): {values}':
        'Applied (temporary, cleared on reboot): {values}',
    "Tüm çekirdeklerin CO değeri 0'a çekildi (geçici).":
        'CO of all cores set to 0 (temporary).',
    "Aşağıdaki rapor GitHub'da paylaşılacak içeriğin TAMAMIDIR. Hiçbir şey kendiliğinden gönderilmez: GitHub sayfasında 'Submit new issue'ya sen basarsın. Gönderirsen rapor, GitHub hesap adınla birlikte HERKESE AÇIK görünür. Kullanıcı adı, bilgisayar adı ve klasör yolları çıkarılmıştır; yine de göndermeden önce oku.":
        "The report below is the COMPLETE content that would be shared on GitHub. Nothing is sent automatically: you press 'Submit new issue' on the GitHub page yourself. If you submit it, the report is PUBLIC together with your GitHub account name. User name, computer name and folder paths have been removed; still, read it before submitting.",
    'Raporu şuraya da kaydettim: {path}':
        'I also saved the report here: {path}',
    "Oturum açılışında otomatik devam görevi kuruldu: '{name}'.":
        "Auto-resume task installed to run at logon: '{name}'.",
    "ÖNEMLİ: çökmeden sonra kendiliğinden devam için Windows'un otomatik oturum açması gerekir":
        'IMPORTANT: to resume by itself after a crash, Windows must log in automatically',
    '(Sysinternals Autologon: https://learn.microsoft.com/sysinternals/downloads/autologon).':
        '(Sysinternals Autologon: https://learn.microsoft.com/sysinternals/downloads/autologon).',
    'Windows':
        'Windows',
    'Yönetici hakları':
        'Administrator rights',
    'psutil kurulu':
        'psutil installed',
    'config: corecycler_dir':
        'config: corecycler_dir',
    'Çekirdek topolojisi':
        'Core topology',
    '{n} çekirdek, SMT {state}':
        '{n} cores, SMT {state}',
    'y-cruncher + log sarmalayıcı dosyaları':
        'y-cruncher + log wrapper files',
    'Etkin frekans ölçümü (isteğe bağlı)':
        'Effective frequency measurement (optional)',
    'Ortam kontrolü (doctor)  <- ÖNCE BUNU ÇALIŞTIR':
        'Environment check (doctor)  <- RUN THIS FIRST',
    'Hızlı deneme (run --quick, ~2 saat, kaba sonuç)':
        'Quick trial (run --quick, ~2 h, rough result)',
    'Asıl çalışma / kaldığı yerden devam (run)':
        'Main run / resume where it left off (run)',
    'Sıfırdan başla (run --fresh)':
        'Start from scratch (run --fresh)',
    'Durumu göster (status)':
        'Show status (status)',
    'Raporu göster (report)':
        'Show report (report)',
    'Nihai değerleri geçici uygula (apply)':
        'Apply final values temporarily (apply)',
    "Tüm CO değerlerini 0'a çek (reset)":
        'Reset all CO values to 0 (reset)',
    'Çökme sonrası otomatik devam kur':
        'Install auto-resume after a crash',
    'Otomatik devamı kaldır':
        'Remove auto-resume',
    'Düşük yük / boşta kararlılık testi (lowload)':
        'Low-load / idle stability test (lowload)',
    'Sonuçları paylaş: anonim rapor hazırla (share)':
        'Share results: prepare an anonymous report (share)',
    '[SİMÜLASYON] gizli çekirdek limitleri: {limits}':
        '[SIMULATION] hidden core limits: {limits}',
    "Gerekli dosyalar bulunamadı: {files}. CoreCycler klasörü eksik ya da bozuk olabilir, config.toml'daki corecycler_dir yanlış olabilir veya antivirüs dosyaları silmiş olabilir. `python -m pbo_tuner doctor` ile kontrol edin; CoreCycler'ı yeniden kurmak için kur.bat'ı çalıştırın.":
        'Required files were not found: {files}. The CoreCycler folder may be missing or damaged, corecycler_dir in config.toml may be wrong, or an antivirus may have deleted the files. Check with `python -m pbo_tuner doctor`; to reinstall CoreCycler, run kur.bat.',
    'Önceki durum yedeklendi: {name}':
        'Previous state backed up: {name}',
    'Otomatik devam: {sec} sn sonra başlıyor (Ctrl+C ile iptal)...':
        'Auto-resume: starting in {sec} s (Ctrl+C to cancel)...',
    'HATA: Yönetici olarak çalıştırın (SMU erişimi için gerekli).':
        'ERROR: run as administrator (required for SMU access).',
    'Yarım kalmış bir düşük yük testi var (aşama: {stage}, tamamlanan çekirdek: {done}). Kaldığı yerden devam ediliyor; yeni --seconds/--idle-minutes değerleri bu çalışmada kullanılmaz.':
        'An unfinished low-load test exists (stage: {stage}, cores completed: {done}). Resuming where it left off; new --seconds/--idle-minutes values are not used for this run.',
    'Düşük yük testi için önce normal çalışmanın bitmiş olması gerekir.':
        'The normal run must be finished before the low-load test.',
    'Test edilecek CO değerleri: ':
        'CO values to be tested: ',
    'İptal edildi.':
        'Cancelled.',
    'Kayıtlı çalışma yok.':
        'No saved run.',
    'Uygulanacak nihai değer yok (arama + doğrulama bitmeli).':
        'No final values to apply (search + validation must be finished).',
    'Uyarı: çalışma bitmedi (aşama: {stage}). Yine de uygulamak için --yes ekleyin.':
        'Warning: the run is not finished (stage: {stage}). Add --yes to apply anyway.',
    'Kayıtlı çalışma yok: rapor yalnızca ortam bilgisini içeriyor (`doctor` çıktısı varsa o da eklenir).':
        'No saved run: the report only contains environment information (plus the `doctor` output, if there is one).',
    'Paylaşmak istersen şu adreste yeni bir issue aç ve raporu yapıştır: {url}':
        'If you want to share it, open a new issue at this address and paste the report: {url}',
    'Tarayıcıda GitHub sayfasını açayım mı?':
        'Open the GitHub page in the browser?',
    'Hiçbir şey gönderilmedi. Rapor yalnızca bilgisayarında duruyor: {path}':
        'Nothing was sent. The report only stays on your computer: {path}',
    'Rapor adrese sığmadığı için bazı bölümler çıkarıldı; sayfa açılınca {path} dosyasını yorum kutusuna sürükleyin.':
        'The report did not fit in the link, so some sections were left out; once the page opens, drag the file {path} into the comment box.',
    "GitHub sayfası açıldı. Göndermek için 'Submit new issue'ya bas; vazgeçersen sayfayı kapatman yeterli.":
        "The GitHub page was opened. Press 'Submit new issue' to send it; to back out, just close the page.",
    'Tarayıcı açılamadı. Şu adresi elle aç: {url}':
        'The browser could not be opened. Open this address by hand: {url}',
    'Yalnızca Windows.':
        'Windows only.',
    'Görev oluşturulamadı (yönetici olarak çalıştırın):':
        'Could not create the task (run as administrator):',
    'PBO AutoTuner {version} ortam kontrolü':
        'PBO AutoTuner {version} environment check',
    'config.toml [paths] içine yazın':
        'set it in config.toml [paths]',
    'CO okuma (PawnIO + ryzen-smu-cli)':
        'CO read (PawnIO + ryzen-smu-cli)',
    'mevcut değerler: {cur}':
        'current values: {cur}',
    'CO yazma + geri okuma doğrulaması':
        'CO write + read-back verification',
    '(mevcut değerler aynen yazıldı)':
        '(current values written back unchanged)',
    'WHEA olay günlüğü okuma':
        'WHEA event log read',
    'son 30 günde {n} WHEA olayı':
        '{n} WHEA events in the last 30 days',
    'y-cruncher ön testi (çekirdek 0, ~15 sn, mevcut CO ile)...':
        'y-cruncher pre-test (core 0, ~15 s, with current CO)...',
    'y-cruncher çalıştı ve hata bildirmedi':
        'y-cruncher ran and reported no errors',
    'Boost ölçümü deneniyor (çekirdek 0)...':
        'Trying boost measurement (core 0)...',
    "ölçülemedi; rapor MHz'siz olur":
        'could not be measured; the report will have no MHz values',
    'AMD Ryzen çekirdek başı Curve Optimizer otomatik ayarlayıcı':
        'Automatic per-core Curve Optimizer tuner for AMD Ryzen',
    'config.toml yolu (varsayılan: ./config.toml)':
        'path to config.toml (default: ./config.toml)',
    'arayüz dili: auto (sistem dili), tr veya en (config.toml [ui] language ile de seçilir)':
        'interface language: auto (system language), tr or en (can also be set with config.toml [ui] language)',
    'aramayı başlat / kaldığı yerden devam et':
        'start the search / resume where it left off',
    'kısa testler (kaba sonuç)':
        'short tests (rough result)',
    'eski durumu yedekleyip sıfırdan başla':
        'back up the old state and start from scratch',
    'çökme döngüsü korumasını sıfırlayıp devam et':
        'reset the crash-loop protection and continue',
    'uyarı onayını atla':
        'skip the warning confirmation',
    '(görev zamanlayıcı için) iş yoksa sessizce çık':
        '(for the task scheduler) exit silently if there is nothing to do',
    'sahte işlemciyle dene (donanıma dokunmaz)':
        'try with a fake CPU (does not touch the hardware)',
    'simülasyon tohumu':
        'simulation seed',
    'ortam/araç kontrolü':
        'environment/tool check',
    'durumu göster':
        'show status',
    'raporu yeniden üret':
        'regenerate the report',
    "tüm CO'ları 0'a çek (geçici)":
        'set all CO values to 0 (temporary)',
    'nihai CO değerleriyle düşük yük + boşta bekleme testi':
        'low-load + idle wait test with the final CO values',
    'çekirdek başına süre (varsayılan config: 180)':
        'seconds per core (config default: 180)',
    'boşta bekleme süresi, dk (varsayılan config: 30, 0 = atla)':
        'idle wait duration in minutes (config default: 30, 0 = skip)',
    "anonim sonuç raporu hazırla; onaylarsan GitHub'da paylaşmak için sayfayı aç":
        'prepare an anonymous results report; if you agree, open the GitHub page to share it',
    'çekirdek başına CO değerlerini rapora koyma':
        'leave the per-core CO values out of the report',
    'tarayıcıyı açma; yalnızca raporu hazırla ve kaydet':
        'do not open the browser; only prepare and save the report',
    "nihai değerleri geçici uygula (BIOS'a girmeden)":
        'apply the final values temporarily (without entering the BIOS)',
    'Otomatik devam atlandı: araç güvenlik için durdurulmuştu. `run --force` ile elle başlatın.':
        'Auto-resume skipped: the tool was halted for safety. Start it manually with `run --force`.',
    'DURDURULDU: {e}':
        'HALTED: {e}',
    'ARAÇ HATASI: {e}':
        'TOOL ERROR: {e}',
    '`python -m pbo_tuner doctor` ile ortamı kontrol edin.':
        'Check the environment with `python -m pbo_tuner doctor`.',
    'Kullanıcı tarafından durduruldu. İlerleme kaydedildi; `run` ile devam edebilirsiniz.':
        'Stopped by the user. Progress is saved; you can continue with `run`.',
    'Devam etmek için EVET yaz: ':
        'Type YES to continue: ',
    'Hata: {e}':
        'Error: {e}',
    'Görev silindi.':
        'Task deleted.',
    'Görev bulunamadı/silinemedi.':
        'Task not found / could not be deleted.',
    "       Not: BIOS'ta CO ayarlı. Araç test sırasında kendi değerlerini yazar; BIOS'ta 0/Auto önerilir.":
        '       Note: CO is set in the BIOS. The tool writes its own values during tests; 0/Auto in the BIOS is recommended.',
    'CO okuma/yazma':
        'CO read/write',
    '       PawnIO yüklü mü? https://pawnio.eu  | CoreCycler 0.11+ sürümünü kullandığınızdan emin olun.':
        '       Is PawnIO installed? https://pawnio.eu  | make sure you are using CoreCycler 0.11+.',
    '       Uyarı: geçmişte WHEA olayları var; bu normal olabilir ama araç yalnızca test sırasındakileri sayar.':
        '       Warning: there are past WHEA events; this can be normal, but the tool only counts those that occur during tests.',
    '       log sonu:':
        '       end of log:',
    'y-cruncher log dosyası oluştu':
        'y-cruncher log file was created',
    'log yok: sarmalayıcı çalışmıyor olabilir (Defender/AV?)':
        'no log: the wrapper may not be running (Defender/antivirus?)',
    'Her şey hazır. `python -m pbo_tuner run` ile başlayabilirsin.':
        'Everything is ready. You can start with `python -m pbo_tuner run`.',
    'Yukarıdaki HATA satırlarını düzeltip tekrar çalıştırın.':
        'Fix the FAIL lines above and run it again.',
    "!! Yönetici değilsin. doctor/run için pencereyi 'Yönetici olarak çalıştır' ile aç.":
        "!! You are not an administrator. Open the window with 'Run as administrator' for doctor/run.",
    'Çıkış':
        'Exit',
    'Geçersiz seçim.':
        'Invalid choice.',
    '(komut bitti, çıkış kodu {code})':
        '(command finished, exit code {code})',
    'Ayar hatası: {e}':
        'Configuration error: {e}',
    'Araç hatası: {e}':
        'Tool error: {e}',
    'TAMAM':
        'OK',
    'HATA':
        'FAIL',
    'açık':
        'on',
    'kapalı':
        'off',
    'çökme sonrası otomatik devam görevi kur':
        'install the auto-resume-after-crash task',
    'otomatik devam görevini sil':
        'delete the auto-resume task',
    'Seçim: ':
        'Choice: ',
    '[e/H]':
        '[y/N]',
    "language 'auto', 'tr' veya 'en' olmalı, '{value}' verildi":
        "language must be 'auto', 'tr' or 'en', got '{value}'",
    "floor 1..50 arasında olmalı (ryzen-smu-cli -50'den derinini uygulamaz)":
        'floor must be between 1 and 50 (ryzen-smu-cli does not apply anything deeper than -50)',
    'start_co 0..floor arasında olmalı':
        'start_co must be between 0 and floor',
    'coarse_step>=1, margin>=0, confirm_backoff>=1 olmalı':
        'coarse_step>=1, margin>=0, confirm_backoff>=1 required',
    'threads_per_core 1 veya 2 olmalı':
        'threads_per_core must be 1 or 2',
    'tests boş olamaz':
        'tests must not be empty',
    'seconds_per_test >= 5 olmalı':
        'seconds_per_test must be >= 5',
    'lowload_seconds >= 30 ve idle_minutes >= 0 olmalı':
        'lowload_seconds must be >= 30 and idle_minutes >= 0',
    'lowload_pulse_*_ms >= 50 ve lowload_tests dolu olmalı':
        'lowload_pulse_*_ms must be >= 50 and lowload_tests must not be empty',
    '{name} >= 1 olmalı':
        '{name} must be >= 1',
    "config.toml: bilinmeyen anahtar '{key}'":
        "config.toml: unknown key '{key}'",
    'İşlemci: {name} -> {label}; mode={mode}, floor={floor}, start_co={start}':
        'CPU: {name} -> {label}; mode={mode}, floor={floor}, start_co={start}',
    'UYARI: floor={floor} bu nesil için fazla; {label} en fazla -{max} destekler. floor {max} yapıldı.':
        'WARNING: floor={floor} is too deep for this generation; {label} supports at most -{max}. floor set to {max}.',
    'UYARI: mode = {mode!r} bu nesil için önerilen ikili değil ({rec!r}).':
        'WARNING: mode = {mode!r} is not the recommended binary for this generation ({rec!r}).',
    "Ryzen 7 5800X3D'de Curve Optimizer kilitlidir; bu araç bu işlemcide çalışmaz.":
        'Curve Optimizer is locked on the Ryzen 7 5800X3D; this tool does not work on this processor.',
    'İşlemci tanınmadı ({name!r}; {ident!r}). Desteklenenler: Ryzen 5000/7000/9000 masaüstü. Biliyorsanız config.toml dosyasına şunlardan birini yazın: generation = "zen3" / "zen4" / "zen5".':
        'Processor not recognised ({name!r}; {ident!r}). Supported: Ryzen 5000/7000/9000 desktop. If you know it, put one of these in config.toml: generation = "zen3" / "zen4" / "zen5".',
    "generation 'auto', 'zen3', 'zen4' veya 'zen5' olmalı, '{value}' verildi":
        "generation must be 'auto', 'zen3', 'zen4' or 'zen5', got '{value}'",
    "{key} = {value!r} AVX-512 kullanır; Zen 3 desteklemez. config.toml'daki bu satırı silin (nesle göre otomatik seçilir).":
        '{key} = {value!r} uses AVX-512; Zen 3 does not support it. Delete this line from config.toml (it is chosen automatically per generation).',
    '(config ile seçildi)':
        '(selected via config)',
    'ryzen-smu-cli boş çıktı verdi':
        'ryzen-smu-cli returned empty output',
    '{n} CO değeri bekleniyordu, {got} geldi: {line!r}':
        'expected {n} CO values, got {got}: {line!r}',
    'mantıksız CO değeri okundu (|değer| > {max}): {values}':
        'implausible CO value read (|value| > {max}): {values}',
    'ryzen-smu-cli {args} başarısız ({tries} deneme): {last}':
        'ryzen-smu-cli {args} failed ({tries} attempts): {last}',
    'yazılan {written} ile geri okunan {read} farklı':
        'written {written} differs from read-back {read}',
    'psutil kurulu değil: pip install psutil':
        'psutil is not installed: pip install psutil',
    "Gerçek donanım modu yalnızca Windows'ta çalışır (deneme için --simulate kullanın).":
        'Real hardware mode only works on Windows (use --simulate to try it).',
    'config.toml içinde [paths] corecycler_dir ayarlanmamış.':
        'corecycler_dir is not set under [paths] in config.toml.',
    'çıkış kodu {code}; stderr={err!r}; stdout={out!r}':
        'exit code {code}; stderr={err!r}; stdout={out!r}',
    '{n} değer gerekli, {got} verildi':
        '{n} values required, {got} given',
    'geçersiz CO değerleri: {values}':
        'invalid CO values: {values}',
    'wevtutil başarısız: {err}':
        'wevtutil failed: {err}',
    '{sec:.0f} sn içinde bitmedi':
        'did not finish within {sec:.0f} s',
    'WHEA hatası (boşta, {n} olay)':
        'WHEA error (idle, {n} events)',
    'WHEA hatası ({n} olay, APIC {apic})':
        'WHEA error ({n} events, APIC {apic})',
    "ryzen-smu-cli başlatılamadı: {path} ({err}). CoreCycler klasörü eksik ya da bozuk olabilir, config.toml'daki corecycler_dir yanlış olabilir veya antivirüs dosyayı silmiş olabilir. `python -m pbo_tuner doctor` ile kontrol edin; CoreCycler'ı yeniden kurmak için kur.bat'ı çalıştırın.":
        'ryzen-smu-cli could not be started: {path} ({err}). The CoreCycler folder may be missing or damaged, corecycler_dir in config.toml may be wrong, or an antivirus may have deleted the file. Check with `python -m pbo_tuner doctor`; to reinstall CoreCycler, run kur.bat.',
    'y-cruncher başlamadı (çıkış kodu {code}). `doctor` komutunu çalıştırın. Log: {log}':
        'y-cruncher did not start (exit code {code}). Run the `doctor` command. Log: {log}',
    'y-cruncher beklenmedik şekilde kapandı (çıkış kodu {code})':
        'y-cruncher exited unexpectedly (exit code {code})',
    'stres süreci CPU kullanmıyor (yük {load:.2f}, beklenen >= {expected:.2f})':
        'stress process is not using the CPU (load {load:.2f}, expected >= {expected:.2f})',
    'PBO AutoTuner sonuç raporu':
        'PBO AutoTuner result report',
    'Tarih: {date}   Aşama: {stage}   Toplam çökme: {crashes}':
        'Date: {date}   Stage: {stage}   Total crashes: {crashes}',
    'Çekirdek  CCD   Nihai CO   Arama sonucu   Çökme   MHz önce   MHz sonra   Fark':
        'Core     CCD   Final CO   Search found   Crash    MHz pre    MHz post   Diff',
    "BIOS'a girmek için:":
        'To enter in the BIOS:',
    "  Her çekirdek için Sign = Negative, Magnitude = aşağıdaki değer (BIOS çekirdek numarası 0'dan başlar,":
        '  For each core set Sign = Negative, Magnitude = the value below (BIOS core numbering starts at 0,',
    "  Ryzen Master 1'den başlar).":
        '  Ryzen Master starts at 1).',
    "BIOS'a girmeden geçici uygulamak için (yeniden başlatınca silinir):":
        'To apply temporarily without entering the BIOS (cleared on reboot):',
    '  python -m pbo_tuner apply          # veya: ryzen-smu-cli.exe --offset {vals}':
        '  python -m pbo_tuner apply          # or: ryzen-smu-cli.exe --offset {vals}',
    "Not: Bu değerler kısa/orta süreli testlerle bulundu. BIOS'a girdikten sonra gerçek kullanımda":
        'Note: These values were found with short/medium tests. After entering them in the BIOS, try them in real use',
    '(oyun, boşta, uyku/uyanma) birkaç gün dene; sporadik çökme olursa ilgili çekirdeği 2-3 geri çek.':
        '(games, idle, sleep/wake) for a few days; if you get sporadic crashes, back the affected core off by 2-3.',
    'Etkin MHz değerleri Windows sayaçlarından yaklaşık ölçümdür.':
        'Effective MHz values are approximate measurements from Windows counters.',
    "Uzatma yapıldı: çekirdekler {cores} tabandan (-{base} civarı) -{floor}'a kadar yeniden arandı. Uzatmadan önceki değerler: {before}":
        'Extension done: cores {cores} were searched again from the floor (around -{base}) down to -{floor}. Values before the extension: {before}',
    'Boşta bekleme testi: {result}':
        'Idle wait test: {result}',
    '(Boşta kararsızlık nadir ve rastgeledir; kısa bir bekleme onu kesin olarak elemez.)':
        '(Idle instability is rare and random; a short wait cannot rule it out.)',
    'UYARILAR:':
        'WARNINGS:',
    'Düşük yük testi (çekirdek başına ~{sec} sn, aralıklı hafif yük): ':
        'Low-load test (~{sec} s per core, intermittent light load): ',
    'geçti ({min} dk, yük yok)':
        'passed ({min} min, no load)',
    'KALDI (WHEA)':
        'FAILED (WHEA)',
    "SİSTEM ÇÖKTÜ (boşta kararsızlık; CO'lar derin olabilir)":
        'SYSTEM CRASHED (idle instability; CO values may be too deep)',
    'atlandı':
        'skipped',
    'yapılmadı':
        'not done',
    'tüm çekirdekler geçti.':
        'all cores passed.',
    '0 (stok)':
        '0 (stock)',
    'geri çekilenler: ':
        'backed off: ',
    'çekirdek {c}: -{a0} -> -{a1}':
        'core {c}: -{a0} -> -{a1}',
    'psutil kuruluyor (pip)...':
        'Installing psutil (pip)...',
    '  SHA-256 doğrulandı.':
        '  SHA-256 verified.',
    'PawnIO {version} indiriliyor: {url}':
        'Downloading PawnIO {version}: {url}',
    "PawnIO kurulu görünmüyor. Bu, ryzen-smu-cli'nin işlemciye erişmek için kullandığı imzalı bir çekirdek sürücüsüdür":
        'PawnIO does not appear to be installed. It is the signed kernel driver that ryzen-smu-cli uses to access the processor',
    '(namazso, GPL lisanslı, imzalı sürücü: https://pawnio.eu). Kurulum için UAC (yönetici) onayı istenecek.':
        '(namazso, GPL-licensed, signed driver: https://pawnio.eu). A UAC (administrator) prompt will appear for the installation.',
    'PawnIO kurulumu doğrulanamadı (çıkış kodu {code}). UAC penceresini reddetmiş olabilirsiniz; elle kurun: https://pawnio.eu':
        'Could not verify the PawnIO installation (exit code {code}). You may have declined the UAC prompt; install it manually: https://pawnio.eu',
    'CoreCycler bulunamadı. Resmi GitHub sürümünden indirilebilir ({url}; ~{dl} MB, açılınca ~{ex} MB).':
        'CoreCycler was not found. It can be downloaded from the official GitHub release ({url}; ~{dl} MB, ~{ex} MB once extracted).',
    '(sp00n; CC BY-NC-SA 4.0 lisanslı: yalnızca ticari olmayan kullanım. Bu araç onu repoya koymaz, doğrudan buradan indirir.)':
        '(sp00n; licensed CC BY-NC-SA 4.0: non-commercial use only. This project does not include it in its repository; setup downloads it straight from the official page.)',
    'Kontroller:':
        'Checks:',
    'Sonraki adım: run_as_admin.bat dosyasına sağ tık > Yönetici olarak çalıştır > menüden 1 (doctor).':
        'Next step: right-click run_as_admin.bat > Run as administrator > choose 1 (doctor) from the menu.',
    'psutil zaten kurulu.':
        'psutil is already installed.',
    "  '{name}' başarısız, sıradaki yöntem deneniyor...":
        "  '{name}' failed, trying the next method...",
    'config.toml zaten var, dokunulmadı.':
        'config.toml already exists, left untouched.',
    'UYARI: config.toml içindeki corecycler_dir geçerli bir CoreCycler klasörünü göstermiyor: {path}':
        'WARNING: corecycler_dir in config.toml does not point to a valid CoreCycler folder: {path}',
    'UYARI: config.example.toml bulunamadı; config.toml oluşturulamadı.':
        'WARNING: config.example.toml not found; could not create config.toml.',
    'config.toml oluşturuldu, CoreCycler yolu: {path}':
        'config.toml created, CoreCycler path: {path}',
    'config.toml oluşturuldu ama CoreCycler klasörü bulunamadı: dosyadaki corecycler_dir satırını elle düzenleyin.':
        'config.toml created but the CoreCycler folder was not found: edit the corecycler_dir line in the file by hand.',
    '  UYARI: SHA-256 uyuşmuyor (beklenen {expected}, gelen {got}). Dosya silindi, kurulmayacak.':
        '  WARNING: SHA-256 mismatch (expected {expected}, got {got}). File deleted, it will not be installed.',
    "PawnIO yalnızca Windows'ta gerekir; atlandı.":
        'PawnIO is only needed on Windows; skipped.',
    'PawnIO zaten kurulu{ver}.':
        'PawnIO is already installed{ver}.',
    'PawnIO kurulumu atlandı. Sonra elle kurabilirsiniz: https://pawnio.eu':
        'PawnIO installation skipped. You can install it by hand later: https://pawnio.eu',
    'winget ile kuruluyor...':
        'Installing with winget...',
    '  winget ile kurulum doğrulanamadı (çıkış kodu {code}); doğrudan indirme denenecek.':
        '  Could not verify the winget installation (exit code {code}); trying a direct download.',
    'PawnIO kuruldu; Windows yeniden başlatma isteyebilir. Sorun görürseniz bilgisayarı yeniden başlatın.':
        'PawnIO installed; Windows may ask for a restart. If you see problems, restart the computer.',
    'PawnIO kuruldu.':
        'PawnIO installed.',
    '  Arşivi açacak program bulunamadı (Windows tar.exe veya 7-Zip). 7-Zip kurup tekrar deneyin: https://www.7-zip.org':
        '  No program found to extract the archive (Windows tar.exe or 7-Zip). Install 7-Zip and try again: https://www.7-zip.org',
    '  {name} ile açılıyor...':
        '  Extracting with {name}...',
    '  {name} ile açma başarısız (çıkış kodu {code}){detail}':
        '  Extraction with {name} failed (exit code {code}){detail}',
    '{path} klasörü var ama eksik görünüyor (ör. antivirüs bir dosyayı silmiş olabilir). Onay verirsen silinmeden kenara alınır ve yeniden indirilir.':
        '{path} exists but looks incomplete (an antivirus may have deleted a file, for example). If you agree, it is moved aside without being deleted and downloaded again.',
    'CoreCycler indirmesi atlandı. Elle indirin: https://github.com/sp00n/CoreCycler/releases':
        'CoreCycler download skipped. Download it by hand: https://github.com/sp00n/CoreCycler/releases',
    'Diskte yeterli boş yer yok (en az ~{mb} MB gerekir); CoreCycler indirilmedi.':
        'Not enough free disk space (at least ~{mb} MB needed); CoreCycler was not downloaded.',
    'CoreCycler {version} indiriliyor (~{dl} MB)...':
        'Downloading CoreCycler {version} (~{dl} MB)...',
    'Açılıyor (~{mb} MB, bir iki dakika sürebilir)...':
        'Extracting (~{mb} MB, may take a minute or two)...',
    'CoreCycler kuruldu: {path}':
        'CoreCycler installed: {path}',
    'HATA: Python {major}.{minor} veya üzeri gerekli.':
        'ERROR: Python {major}.{minor} or newer is required.',
    'HATA: psutil kurulamadı. Elle deneyin:  python -m pip install psutil   (internet bağlantısını kontrol edin)':
        'ERROR: could not install psutil. Try by hand:  python -m pip install psutil   (check your internet connection)',
    'PawnIO adımı atlandı (--no-pawnio).':
        'PawnIO step skipped (--no-pawnio).',
    '  [?]     PawnIO: Windows dışında denetlenemez':
        '  [?]     PawnIO: cannot be checked outside Windows',
    '  NOT: PawnIO kurulumundan sonra yeniden başlatma gerekebilir; doctor hata verirse bilgisayarı yeniden başlatın.':
        '  NOTE: a restart may be needed after installing PawnIO; if doctor reports an error, restart the computer.',
    'PBO AutoTuner kurulum yardımcısı':
        'PBO AutoTuner setup helper',
    "sormadan PawnIO'yu da kur ve CoreCycler'ı da indir":
        'also install PawnIO and download CoreCycler without asking',
    'PawnIO adımını atla':
        'skip the PawnIO step',
    "CoreCycler'ı indirme adımını atla":
        'skip the CoreCycler download step',
    'arayüz dili: auto (sistem dili), tr veya en':
        'interface language: auto (system language), tr or en',
    'psutil kuruldu ({name}).':
        'psutil installed ({name}).',
    'config.toml içindeki corecycler_dir geçersizdi ({old}); {new} olarak güncellendi.':
        'corecycler_dir in config.toml was invalid ({old}); updated to {new}.',
    '  indirme başarısız: {e}':
        '  download failed: {e}',
    'PawnIO sürücüsü kurulsun mu?':
        'Install the PawnIO driver?',
    'PawnIO kuruldu (winget).':
        'PawnIO installed (winget).',
    'CoreCycler indirilip kurulsun mu?':
        'Download and install CoreCycler?',
    "Eksik klasör silinmedi, '{aside}' adıyla kenara alındı.":
        "The incomplete folder was not deleted; it was moved aside as '{aside}'.",
    "CoreCycler açılamadı. Antivirüs dosyaları silmiş olabilir (y-cruncher / ryzen-smu-cli); istisna ekleyip tekrar deneyin ya da CoreCycler'ı elle kurun: https://github.com/sp00n/CoreCycler/releases":
        'Could not extract CoreCycler. Antivirus may have deleted files (y-cruncher / ryzen-smu-cli); add an exclusion and try again, or install CoreCycler by hand: https://github.com/sp00n/CoreCycler/releases',
    ': indirip proje klasörüne açın (CoreCycler 0.11.x): https://github.com/sp00n/CoreCycler/releases':
        ': download it and extract it into the project folder (CoreCycler 0.11.x): https://github.com/sp00n/CoreCycler/releases',
    'PawnIO sürücüsü':
        'PawnIO driver',
    ': algılanamadı (bu kontrol kesin değil). https://pawnio.eu adresinden kurun.':
        ': not detected (this check is not definitive). Install it from https://pawnio.eu.',
    '(yok)':
        '(none)',
    ' (sürüm {v})':
        ' (version {v})',
    "'{path}' kenara alınamadı ({err}); CoreCycler kurulmadı.":
        "Could not move '{path}' aside ({err}); CoreCycler was not installed.",
    'EKSİK':
        'MISSING',
    'EKSİK?':
        'MISSING?',
    '[E/h]':
        '[Y/n]',
    'max_boots aşıldı':
        'max_boots exceeded',
    '*** SİSTEM ÇÖKTÜ (simülasyon) -> yeniden başlatılıyor ***':
        '*** SYSTEM CRASHED (simulation) -> rebooting ***',
    'sim: CLI {max} üstünü kabul etmiyor: {values}':
        'sim: CLI does not accept anything above {max}: {values}',
    'sim: boşta WHEA':
        'sim: idle WHEA',
    'sim: hata (çekirdek {c}, a={a}, limit={lim})':
        'sim: error (core {c}, a={a}, limit={lim})',
    'sim: aralıklı hata (çekirdek {c}, a={a})':
        'sim: intermittent error (core {c}, a={a})',
    'durum dosyası sürümü uyumsuz: {version}':
        'state file version mismatch: {version}',
    'tüm değerler geri çekildi':
        'all values backed off',
    'uzatma: çekirdekler {cores} CO -{old} -> -{new}':
        'extension: cores {cores} CO -{old} -> -{new}',
    'düşük yük testi başlatıldı: {sec} sn/çekirdek, boşta {idle} dk':
        'low-load test started: {sec} s/core, idle {idle} min',
    'Arada hiç test tamamlanmadan üst üste {n} çökme oldu.':
        '{n} crashes in a row without any test completing in between.',
    "!! ÇÖKME tespit edildi: {kind} testi, çekirdek {core}, CO -{a}. Bu seviye 'kaldı' sayılıyor.":
        '!! CRASH detected: {kind} test, core {core}, CO -{a}. This level is counted as failed.',
    'çökme: {kind} çekirdek={core} CO=-{a}':
        'crash: {kind} core={core} CO=-{a}',
    '  çekirdek {core:2d} [{phase}] CO {co:+d}  ({level}, ~{secs} sn){tag}':
        '  core {core:2d} [{phase}] CO {co:+d}  ({level}, ~{secs} s){tag}',
    'izole (diğer çekirdekler CO 0)':
        'isolated (other cores at CO 0)',
    'birlikte (tur tur)':
        'combined (round by round)',
    'Aşama 2/5: çekirdek başına CO araması, mod: {mode}.':
        'Stage 2/5: per-core CO search, mode: {mode}.',
    'Aşama 3/5: tüm değerler uygulanmışken çekirdek çekirdek doğrulama.':
        'Stage 3/5: core-by-core validation with all values applied.',
    'Aşama 4/5: tüm çekirdek birlikte yük testi.':
        'Stage 4/5: all-core load test.',
    'Düşük yük testi: çekirdek başına ~{sec} sn hafif yük, {on}/{off} ms aralıklı. Tüm CO değerleri uygulanmış durumda.':
        'Low-load test: ~{sec} s of light load per core, {on}/{off} ms on/off. All CO values are applied.',
    'Uzatma için önce normal çalışmanın bitmiş olması gerekir (`status` ile bakın).':
        'The normal run must be finished before an extension (check with `status`).',
    'Yeni taban ({new}) eskisinden ({old}) büyük olmalı (en fazla 50).':
        'The new floor ({new}) must be greater than the old one ({old}) (at most 50).',
    'Çekirdek(ler) {bad} tabana dayanmıyor; uzatılabilir olanlar: {candidates}':
        'Core(s) {bad} are not at the floor; extendable ones: {candidates}',
    'Tabana dayanan çekirdek yok; uzatılacak bir şey yok.':
        'No core is at the floor; nothing to extend.',
    'Düşük yük testi için önce normal çalışmanın bitmiş olması gerekir (`status` ile bakın).':
        'The normal run must be finished before the low-load test (check with `status`).',
    'Yeni çalışma başlatıldı ({n} çekirdek, SMT={smt}).':
        'New run started ({n} cores, SMT={smt}).',
    'Test dışında üst üste {n} beklenmedik yeniden başlatma oldu.':
        '{n} unexpected reboots in a row outside of tests.',
    '{why} Güvenlik için durduruldu. Sistemin kararsızlığı bu araçtan bağımsız bir sorundan (RAM/PSU/ısı/BIOS) olabilir. Kontrol edip `run --force` ile devam edin.':
        '{why} Halted for safety. The instability may come from a problem unrelated to this tool (RAM/PSU/heat/BIOS). Check it and continue with `run --force`.',
    "Aşama 1/5: CO 0'da etkin boost frekansları ölçülüyor (yaklaşık değer).":
        'Stage 1/5: measuring effective boost frequencies at CO 0 (approximate).',
    'uzatılan çekirdekler geri çekildi':
        'extended cores backed off',
    '  tüm çekirdekler, {minutes} dk':
        '  all cores, {minutes} min',
    '      -> KALDI ({reason}); {what} ({step})':
        '      -> FAILED ({reason}); {what} ({step})',
    'Boşta bekleme testi: {minutes} dk, hiç yük yok, tüm CO değerleri uygulanmış.':
        'Idle wait test: {minutes} min, no load at all, all CO values applied.',
    'Aşama 5/5: nihai değerlerle boost ölçümü.':
        'Stage 5/5: boost measurement with the final values.',
    '!! CO sıfırlanamadı: {e}':
        '!! Could not reset CO: {e}',
    'Durum dosyası {saved} çekirdek için, sistem {now}. `run --fresh` ile yeniden başlayın.':
        'The state file is for {saved} cores, the system has {now}. Start over with `run --fresh`.',
    'Önceki çalışma bulundu: aşama={stage}, toplam çökme={crashes}.':
        'Previous run found: stage={stage}, total crashes={crashes}.',
    'Önceki çalışma yarıda kesilmiş (yeniden başlatma yok). Aynı seviye tekrar denenecek.':
        'The previous run was interrupted (no reboot). The same level will be retried.',
    '!! Test dışında beklenmedik yeniden başlatma ({n}). Araç temiz kapanmamış.':
        '!! Unexpected reboot outside a test ({n}). The tool did not shut down cleanly.',
    'test dışı beklenmedik yeniden başlatma':
        'unexpected reboot outside a test',
    'çökme/yeniden başlatma':
        'crash/reboot',
    '   (arama durumu bu testle uyuşmuyor; yoksayıldı)':
        '   (search state does not match this test; ignored)',
    '  çekirdek {c:2d}: {mhz} MHz':
        '  core {c:2d}: {mhz} MHz',
    'GEÇTİ':
        'PASSED',
    'KALDI: {reason}':
        'FAILED: {reason}',
    '  => Çekirdek {core}: nihai aday CO -{final}':
        '  => Core {core}: final candidate CO -{final}',
    '--- Tur {rnd}: {n} çekirdek ---':
        '--- Round {rnd}: {n} cores ---',
    '  çekirdek {core}: CO -{a} doğrulanıyor (~{secs} sn)':
        '  core {core}: validating CO -{a} (~{secs} s)',
    "      -> KALDI ({reason}); CO -{a}'a geri çekildi":
        '      -> FAILED ({reason}); backed off to CO -{a}',
    '      -> GEÇTİ':
        '      -> PASSED',
    'UYARI: tüm çekirdek testi geri çekilmelere rağmen geçmedi':
        'WARNING: the all-core test still failed despite backing off',
    '  !! Tüm çekirdek testi geçmedi. RAM/ısı/PSU gibi başka bir kararsızlık kaynağı olabilir.':
        '  !! The all-core test failed. Another source of instability such as RAM/heat/PSU may be responsible.',
    '  çekirdek {core:2d}: CO -{a} (~{sec} sn)':
        '  core {core:2d}: CO -{a} (~{sec} s)',
    'UYARI: boşta bekleme testi kaldı: {reason}':
        'WARNING: idle wait test failed: {reason}',
    '      -> KALDI ({reason})':
        '      -> FAILED ({reason})',
    'UYARI: boşta beklerken sistem çöktü; CO değerleri boşta kararsız olabilir':
        'WARNING: the system crashed while idle; CO values may be unstable at idle',
    'ölçülemedi':
        'n/a',
}
