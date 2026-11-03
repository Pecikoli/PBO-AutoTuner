# PBO AutoTuner (Ryzen 5000 / 7000 / 9000 masaüstü)

**Dil / Language:** Türkçe (bu dosya) · [English](README.md)

> **English summary:** Fully automatic per-core Curve Optimizer (PBO) tuner for AMD Ryzen 5000/7000/9000 desktop CPUs
> on Windows. It finds the most negative stable CO value for every physical core, survives crashes and reboots by
> resuming where it left off, and prints a table you can enter in the BIOS. It reuses `ryzen-smu-cli` (PawnIO driver) and
> y-cruncher from [CoreCycler](https://github.com/sp00n/CoreCycler), which is **not** included in the repository; setup
> downloads it from its official release with your consent. The interface comes in Turkish and English (`--lang tr|en`), and the full documentation is in
> [README.md](README.md). **Validated on a Ryzen 9 9950X3D only; the Zen 3 / Zen 4 presets are untested.
> Use at your own risk** (see the disclaimer below).

Her fiziksel çekirdek için **en negatif stabil Curve Optimizer (CO)** değerini kendi kendine bulan,
çökmelerden sonra kaldığı yerden devam eden bir ayarlayıcı. Sonunda BIOS'a girebileceğin bir tablo verir.

> **Durum:** Gerçek donanımda yalnızca **Ryzen 9 9950X3D** üzerinde (yazarın makinesinde) uçtan uca denendi: `doctor`,
> hızlı ve tam çalışma, çökmeden sonra devam. Arama/durum/çökme-devam mantığı ayrıca sahte işlemciyle ve rastgele çökme
> enjekte eden 300'den fazla otomatik testle doğrulandı. Zen 3 / Zen 4 ön ayarları ve 12 çekirdekli işlemciler **henüz gerçek makinede
> denenmedi.** `kur.bat` ile kurulum temiz bir Windows'ta denendi ve çalışıyor. `doctor` komutu her adımı senin makinende tek tek
> sınar; ilk gerçek çalıştırmayı başında dur.

## Sorumluluk reddi

- Curve Optimizer'ı zorlamak sistem donmasına, beklenmedik yeniden başlamalara ve nadiren dosya/veri bozulmasına yol
  açabilir. Çalıştırmadan önce önemli verilerini yedekle.
- Araç, donanıma erişmek için bir çekirdek sürücüsü (PawnIO) kullanır ve istersen oturum açılışında çalışan bir
  zamanlanmış görev kurar (`install-autostart`).
- PBO/undervolt garantiyi etkileyebilir. Yazılım olduğu gibi, hiçbir garanti vermeden sunulur (bkz. [LICENSE](LICENSE));
  sonuçlardan sen sorumlusun.
- Bu proje CoreCycler'ın yazarıyla veya AMD ile ilişkili değildir.

## Desteklenen işlemciler

İşlemci Windows kayıt defterinden (aile/model) otomatik algılanır; y-cruncher ikilisi, CO tabanı ve başlangıç değeri ona
göre seçilir. `config.toml`'da elle yazdığın değerler korunur; yalnızca nesil için imkânsız olanlar düzeltilir veya hata verir.

| Nesil | y-cruncher | `floor` (en derin CO) | `start_co` | Durum |
|---|---|---|---|---|
| Zen 5, Ryzen 9000 | `24-ZN5 ~ Komari` | 50 | 20 | **9950X3D'de gerçek donanımda denendi** |
| Zen 4, Ryzen 7000 | `22-ZN4 ~ Kizuna` | 50 | 15 | ön ayar var, **denenmedi** |
| Zen 3, Ryzen 5000 | `19-ZN2 ~ Kagari` | 30 | 10 | ön ayar var, **denenmedi** |

- Zen 3 AVX-512 desteklemez (Kizuna/Komari çalışmaz) ve CO aralığı -30'a kadardır. **5800X3D'de CO kilitlidir**, araç çalışmaz.
- Algılanamayan işlemcide `config.toml`'a `generation = "zen3"` / `"zen4"` / `"zen5"` yaz.
- 6 ve 8 çekirdekli (tek CCD) ile 12 çekirdekli (6+6) işlemciler simülasyonda sınandı. 12 çekirdekte WHEA olaylarını çekirdeğe
  eşleyen APIC ID boşluk kuralı (CoreCycler notlarına göre ikinci CCD'nin ID'leri 16'dan başlar) **doğrulanmadı**; yanlışsa
  yalnızca WHEA eşleşmesi kaçabilir, y-cruncher'ın kendi hata tespiti etkilenmez.
- Intel ve Zen 2 desteklenmez.

## Nasıl çalışır

Frekansı doğrudan sabitleyemezsin; Ryzen'da CO voltaj eğrisini kaydırır, işlemci de güç/ısı payı elverdiği
ölçüde daha yükseğe boost eder. Araç şunu yapar:

1. **Tur tur arama:** Her turda her çekirdek bir seviye test edilir (tek çekirdeğe y-cruncher yükü). Test edilen
   çekirdek dışındakiler **kendi bilinen değerlerinde** kalır (CO 0'da değil). Böylece koşul gerçek kullanıma yakındır.
   * **İniş:** ilk test -20'de (`start_co`), sonra 5'er adım negatife iner, en fazla -50'ye kadar (`floor`; ryzen-smu-cli
     daha derinini uygulamaz: gerçek makinede -55 yazılınca -50 geri okundu). İlk hatada o çekirdek ayrılır.
   * **İkili arama:** son geçen ve ilk kalan değer arasını 1'e kadar daraltır (orta uzunlukta test).
   * **Onay:** `bulunan sınır - 2` değerini uzun testle doğrular; kalırsa 2 geri çekip tekrar dener.
2. **Doğrulama:** bulunan TÜM değerler birlikte uygulanmışken her çekirdeği tekrar test eder; kalanı geri çeker.
3. **Tüm çekirdek yük testi:** kalırsa hepsini 2 geri çeker (hangi çekirdeğin kaldığını y-cruncher söylemez).
4. Raporda her çekirdek için CO, çökme sayısı ve CO 0'a göre etkin MHz farkı (yaklaşık) yer alır.

**Neden "birlikte"?** İlk gerçek çalıştırmada (9950X3D) eski izole mod (diğerleri CO 0) 16 çekirdeğin hepsini -40'ta
hatasız gösterdi; oysa diğer çekirdekler de derin CO'dayken aynı çekirdeklerden çoğu -40'ta ilk saniyede hata verdi
(çekirdek 13 ancak -24'te geçti). Yani bir çekirdeğin limiti diğerlerinin CO'suna bağlı. İzole mod hâlâ
`isolate_cores = true` ile seçilebilir ama önerilmez.

**Çökme akışı:** Her testten önce "şu seviyeyi deniyorum" diske yazılır. Sistem çökerse sonraki açılışta o seviye
"kaldı" sayılır ve arama bir sonraki adımdan devam eder. Çökme sonrası değerler BIOS'a döner; araç ilk iş
hepsini 0'a çeker. Yarım kalan test seviyeleri asla "geçti" sayılmaz.

**Koruma:** Arada hiç test tamamlanmadan 8 çökme olursa veya test dışında 3 beklenmedik yeniden başlatma
olursa durur ve senden onay ister (`run --force`).

## Kurulum (Windows 10/11)

**Kolay yol:** proje klasöründeki **`kur.bat`** dosyasına çift tıkla (yönetici gerekmez). Şunları yapar:
1. Python 3.11+ varsa kullanır; yoksa önce **winget** ile, o da yoksa python.org'dan Python 3.12'yi kullanıcı için sessizce kurar.
2. `psutil`'i kurar (`pip`; gerekirse `ensurepip` ve `--user` ile).
3. `config.toml` yoksa `config.example.toml`'dan üretir; proje klasörünün içinde veya yanında bir `CoreCycler*` klasörü
   bulursa yolu otomatik yazar. Var olan `config.toml`'a dokunmaz; yalnızca içindeki `corecycler_dir` geçersizse (ör. örnek
   yol `C:\Tools\CoreCycler` ya da silinmiş bir klasör) ve geçerli bir CoreCycler bulunduysa yalnızca o satırı düzeltir.
4. Hangi Python'a psutil kurulduğunu `python_path.txt`'ye yazar; `run_as_admin.bat` o Python'u kullanır.
5. **PawnIO** sürücüsü kurulu değilse, onayını alıp kurar (ryzen-smu-cli'nin işlemciye erişmek için kullandığı imzalı
   çekirdek sürücüsü; namazso, GPL lisanslı). Önce `winget install namazso.PawnIO` denenir; olmazsa GitHub'dan
   sabit sürüm (2.2.0) indirilip **SHA-256 doğrulandıktan sonra** `-install -silent` ile kurulur. UAC (yönetici) onayı penceresi
   çıkar. Sorulmasını istemezsen `python -m pbo_tuner.setup_env --yes`, hiç kurulmasın istersen `--no-pawnio`.
   Windows yeniden başlatma isterse kurulum sonunda söyler.
6. **CoreCycler** yoksa onayını alıp resmi GitHub sürümünden (v0.11.0.3, ~45 MB; açılınca ~370 MB) indirir, **SHA-256'sını
   doğrular** ve proje klasörüne açar. `.7z` arşivini Windows'un kendi `tar.exe`'siyle (yoksa kuruluysa 7-Zip ile) açar.
   Sorulmasını istemezsen `--yes`, hiç indirilmesin istersen `--no-corecycler`. CoreCycler'ın lisansı CC BY-NC-SA 4.0'dır
   (ticari olmayan kullanım); repoya konmaz, doğrudan resmi sayfadan inen kopya kullanılır.
   CoreCycler klasörü var ama eksikse (ör. antivirüs bir dosyayı silmişse) onayınla klasörü **silmeden**
   `CoreCycler-v0.11.0.3.eksik-<tarih>` adıyla kenara alır ve yeniden indirir.

Elle yapılması gerekenler:
- **CoreCycler 0.11.x:** `kur.bat` indiremezse (internet yok, reddettin vb.) https://github.com/sp00n/CoreCycler/releases
  adresinden indirip proje klasörünün içine aç.
- **BIOS:** Curve Optimizer'ı **Auto/0** bırak (tuner kendi değerlerini yazar). PBO'yu istediğin gibi ayarlayabilirsin, ama
  tuning boyunca sabit tut. RAM/EXPO kararsızsa sonuçlar yanıltıcı olur.

`kur.bat` bittikten sonra `run_as_admin.bat` dosyasına **sağ tık > Yönetici olarak çalıştır**: komut vermeden açılırsa bir menü
gösterir (1 = doctor, 2 = hızlı deneme, 3 = asıl çalışma...).

`kur.bat` kendi mesajlarını Windows diline göre Türkçe veya İngilizce gösterir (aşağıdaki "Arayüz dili" bölümüne bak).

*Elle kurulum:* Python 3.11+, `pip install psutil`, PawnIO (https://pawnio.eu), `config.example.toml`'u `config.toml` yapıp `corecycler_dir` yolunu yaz.
Komutları yönetici komut isteminde `python -m pbo_tuner ...` ile de çalıştırabilirsin.

## Kullanım

```
python -m pbo_tuner doctor            # ortamı sınar (CO okur, aynen geri yazar, y-cruncher'ı 15 sn koşar)
python -m pbo_tuner run --quick       # kısa testler (~2 saat), kaba sonuç; sonucu BIOS'a girme
python -m pbo_tuner run               # asıl çalışma (çökme yoksa ~5-6 saat; her çökme +~5 dk)
python -m pbo_tuner status            # çekirdek çekirdek ilerleme
python -m pbo_tuner report            # raporu yeniden üret (data\report.txt, results.json, bios_values.csv)
python -m pbo_tuner apply             # nihai değerleri geçici uygula (yeniden başlatınca silinir)
python -m pbo_tuner reset             # tüm CO'ları 0'a çek (geçici)
python -m pbo_tuner run --simulate    # donanıma dokunmadan algoritmayı sahte işlemcide izle
python -m pbo_tuner share             # sonucunu anonim olarak paylaşmak için rapor hazırla (menü 12)
```

Önce `doctor`, sonra `run --quick`, sonra asıl `run` önerilir. `--quick` sonucunu BIOS'a girme; yalnızca
sistemin akışı doğru yürüttüğünü görmek içindir. Bitince `--fresh` ile sıfırdan uzun çalışma başlat.

### Arayüz dili (Türkçe / English)

Menü, `doctor`, günlük, rapor ve kurulum mesajları Türkçe veya İngilizce gösterilebilir. Dil şu sırayla seçilir:

1. Komut satırı: `python -m pbo_tuner --lang en run` (`--lang` alt komuttan önce yazılır; menü için `run_as_admin.bat --lang en`)
2. Ortam değişkeni: `PBO_LANG=en`
3. `config.toml` içinde: `[ui]` bölümünde `language = "en"` (`"tr"`, `"en"` veya `"auto"`)
4. Hiçbiri yoksa sistem dili (`auto`): Windows ekran dili veya bölgesel ayarı Türkçeyse Türkçe, değilse İngilizce.

`kur.bat` kendi mesajlarını Windows bölgesel/kurulum diline (veya `PBO_LANG`'e) göre seçer; `config.toml`'daki ayar yalnızca Python
mesajlarını etkiler. Kayıtlı durum dosyasındaki notlar, yazıldıkları dilde kalır.

### Düşük yük / boşta testi (`lowload`, menü 11)

CO kararsızlığı çoğu zaman ağır yükte değil, **boşta veya hafif yükte** ortaya çıkar (çekirdek düşük voltajla yüksek
frekansa sıçrar). y-cruncher'ın ağır testleri bunu yakalamaz. Normal çalışma bittikten sonra:

```
python -m pbo_tuner lowload                       # çekirdek başına 180 sn + 30 dk boşta (~1,5 saat)
python -m pbo_tuner lowload --idle-minutes 240    # gece bırakmak için daha uzun boşta testi
```

Komutu **yönetici** komut isteminde çalıştır. Yarıda kalırsa (pencereyi kapattın, çökme oldu vb.) aynı komutu tekrar yazman
ya da menüden `3` (run) seçmen yeterli: kaldığı yerden devam eder; yeni süre değerleri o çalışmada kullanılmaz.

1. **Çekirdek başına hafif + aralıklı yük:** tüm CO değerleri uygulanmışken, her çekirdeğe AVX2 tabanlı hafif y-cruncher
   testleri (BKT, BBP, SNT) bindirilir ve süreç ~300 ms çalışıp ~700 ms durdurulur (sık boşta↔yük geçişi, ortalama yük
   ~%30). Hata verirse o çekirdek 2 geri çekilir ve yeniden denenir.
2. **Boşta bekleme:** hiç yük yok, yalnızca WHEA izlenir. Sistem çökerse araç bunu kaydeder ve raporda uyarır;
   hangi çekirdeğin sorumlu olduğu bilinemez. Boşta hata nadir ve rastgele olduğu için kısa bir bekleme onu kesin olarak
   elemez.

Boşta çökme olursa çözüm yolları: (a) en derin CO'ları (-45/-50) geri çekmek, (b) Curve Shaper ile düşük frekans
bantlarına voltaj eklemek (bu araç henüz yapmıyor).

### Çökmeden sonra kendiliğinden devam

```
python -m pbo_tuner install-autostart
```
Oturum açılışında devam eden bir görev kurar. Bunun çalışması için Windows'un **otomatik oturum açması**
gerekir, yoksa çökmeden sonra giriş ekranında bekler (Sysinternals Autologon önerilir). Sistem donarsa
(yeniden başlamazsa) reset tuşuna bas; araç kaldığı yerden devam eder. Kurulumu `remove-autostart` kaldırır;
çalışma bitince de otomatik kalkar. Otomatik devam penceresi hata olmadan biterse kapanır; sonuç her zaman
`data\report.txt` içindedir.

### Sonuçları paylaşma (`share`, menü 12)

Aracı farklı işlemcilerde (özellikle Zen 3 / Zen 4 ve 12 çekirdekli modeller) denediysen sonucunu paylaşmak aracı
geliştirmeye yardım eder:

```
python -m pbo_tuner share              # anonim rapor hazırla, ekranda göster; onaylarsan GitHub sayfasını aç
python -m pbo_tuner share --no-values  # çekirdek başına CO değerlerini rapora koyma
python -m pbo_tuner share --no-open    # yalnızca hazırla ve kaydet (data\share_report.txt)
```

- **Hiçbir şey kendiliğinden gönderilmez.** Rapor ekranda tam olarak gösterilir. Soruya açıkça `e` dersen tarayıcıda
  önceden doldurulmuş bir GitHub "issue" sayfası açılır ve **"Submit new issue"ya sen basarsın**. Sunucu yoktur.
- Gönderdiğin rapor GitHub'da **herkese açıktır** ve GitHub hesap adınla birlikte görünür.
- Raporda şunlar olur: araç sürümü, Windows ve Python sürümü, işlemci modeli ve nesli, çekirdek sayısı, PawnIO sürümü,
  çalışmanın aşaması, çökme sayısı, uyarılar, çekirdek başına nihai CO / çökme / boost farkı ve son `doctor` çıktısı.
  Kullanıcı adı, bilgisayar adı ve klasör yolları rapordan çıkarılır; yine de göndermeden önce oku.
- CO değerleri **o tek işlemciye özeldir**; başkasının değerlerini kendi işlemcine uygulama. Raporlar değer dağıtmak için
  değil, aracın hangi işlemcilerde çalıştığını ve nerede takıldığını görmek içindir.

### Sonucu kalıcı yapma

`data\report.txt` içindeki tabloyu BIOS'ta
`Advanced > AMD Overclocking > Precision Boost Overdrive > Curve Optimizer > Per Core`
altına gir (Sign = Negative, Magnitude = değer). BIOS çekirdek numarası 0'dan başlar; Ryzen Master 1'den.

## Sınırlar ve dürüst notlar

- **Aracı Görev Yöneticisi'nden öldürürsen** (Ctrl+C değil) son uygulanan CO sistemde kalabilir; hemen
  `python -m pbo_tuner reset` çalıştır (Ctrl+C ile durdurursan araç kendisi sıfırlar).
- **Sıcaklık izleme yok.** Tek çekirdek y-cruncher yükü termal olarak hafiftir ama soğutmayı yine de izle.
- **Test geçmesi kalıcı kararlılık demek değildir.** CO kararsızlığı çoğu zaman *boşta/düşük yükte* ortaya çıkar.
  BIOS'a girdikten sonra birkaç gün normal kullanımda (oyun, boşta, uyku/uyanma) dene; sporadik çökme olursa
  ilgili çekirdeği 2-3 geri çek. Uzun süreli kesin onay için `confirm_cycles` / `validate_cycles` değerlerini artır.
- **Etkin MHz yaklaşıktır** (Windows performans sayaçları). Kesin değer için HWiNFO kullan.
- **WHEA:** Yalnızca işlemci olayları (ID 18/19) ve test edilen çekirdeğe ait olanlar hata sayılır; PCIe vb. sayılmaz.
- **Çekirdekler birbirine bağlıdır:** Bir çekirdeğin sınırı, diğerlerinin CO değerine göre değişir. Bu yüzden arama,
  diğer çekirdekler kendi bilinen değerlerindeyken yapılır ve nihai tablo ayrıca birlikte doğrulanır. Yine de
  bütün-çekirdek yükte ve gerçek kullanımda kontrol et.
- **Alternatif:** CoreCycler 0.11'in kendi "Automatic Test Mode"u da Ryzen 9000'de benzer işi yapar
  (-50'den başlayıp geri çeker). Bu araç 0'dan inip ikili arama yaptığı için mantıken daha az çökme üretmesi beklenir (iki aracı karşılaştırarak ölçmedim).
- Garanti/hasar sorumluluğu sana aittir; PBO/undervolt garantiyi etkileyebilir.

## Sorun giderme

| Belirti | Bak |
|---|---|
| `doctor`: CO okuma hatası | PawnIO kurulu mu? CoreCycler 0.11+ mı? Yönetici misin? Defender sürücüyü engelliyor mu? |
| `doctor`: y-cruncher log dosyası yok | Antivirüs sarmalayıcıyı (`helpers\WriteConsoleToWriteFileWrapper.exe`) engelliyor olabilir |
| Çok sık "stres süreci CPU kullanmıyor" | `config.toml` > `[safety] cpu_load_check = false` deneyin |
| `ARAÇ HATASI: Gerekli dosyalar bulunamadı` (veya `FileNotFoundError: [WinError 2]`) | CoreCycler eksik ya da `config.toml`'daki `corecycler_dir` yanlış. Önce `kur.bat`'ı yeniden çalıştır: CoreCycler yoksa/eksikse onayınla indirir ve geçersiz `corecycler_dir` satırını düzeltir. Olmazsa `doctor` hangi dosyanın eksik olduğunu söyler; antivirüs `ryzen-smu-cli.exe` dosyasını silmiş olabilir (istisna ekle) |
| `kur.bat`: "CoreCycler açılamadı" | Antivirüs `y-cruncher` / `ryzen-smu-cli` dosyalarını silmiş olabilir (istisna ekle); Windows'ta `tar.exe` yoksa 7-Zip kur; ya da CoreCycler'ı elle indir |
| `ARAÇ HATASI: y-cruncher başlamadı` (İngilizce: `TOOL ERROR: y-cruncher did not start`) | `mode` adı `test_programs\y-cruncher\Binaries` içindeki dosyayla aynı mı? |
| Çok düşük CO değerleri | RAM/EXPO/PSU kaynaklı kararsızlık olabilir; önce onları stok yapıp dene |

## Dosyalar

`pbo_tuner/search.py` arama algoritması (saf mantık) · `state.py` kalıcı durum · `tuner.py` orkestratör ·
`hw.py` Windows adaptörleri · `sim.py` sahte işlemci · `report.py` rapor · `__main__.py` komut satırı ·
`i18n.py` dil seçimi · `lang_en.py` İngilizce metinler (yeni bir ekran metni `tr("...")` ile yazılır ve buraya karşılığı
eklenir; test eksik çeviriyi yakalar) · `tests/` otomatik testler (`python -m pytest tests`).

## Hata bildirme

Sorun açarken şunları ekle: işlemci modeli, Windows sürümü, `python -m pbo_tuner doctor` çıktısı ve `data\tuner.log`
içindeki ilgili kısım (`python -m pbo_tuner share` ortam bilgisini ve son `doctor` çıktısını senin için hazırlar). Zen 3 / Zen 4 ve 12 çekirdekli işlemcilerdeki sonuçlar özellikle değerlidir.

## Üçüncü taraf yazılımlar ve lisanslar

Bu repo aşağıdakilerin hiçbirini **içermez**. Kullanıcı kendisi indirir ya da kurulum sırasında resmi kaynağından indirilir.
Her biri kendi lisansına tabidir:

| Proje | Rolü | Lisans |
|---|---|---|
| [CoreCycler](https://github.com/sp00n/CoreCycler) (sp00n) | ryzen-smu-cli, y-cruncher ve log sarmalayıcıyı sağlar; kurulumda onayınla resmi sürümden indirilir | CC BY-NC-SA 4.0 (ticari kullanıma kapalı) |
| [ryzen-smu-cli](https://github.com/rawhide-kobayashi/ryzen-smu-cli) / ZenStates-Core | CO okuma ve yazma | kendi depolarındaki lisans |
| [y-cruncher](https://www.numberworld.org/y-cruncher/) (Alexander Yee) | stres testi | [kendi lisansı](https://www.numberworld.org/y-cruncher/license.html) |
| [PawnIO](https://pawnio.eu) (namazso) | çekirdek sürücüsü | GPL-2.0-or-later |

Bu araç, birlikte çalışabilmek için CoreCycler'ın komut satırı ve y-cruncher yapılandırma biçimini izler. CoreCycler'dan
(PowerShell) kod kopyalanmadı; bu araç Python ile baştan yazıldı.

## Lisans

[MIT](LICENSE). Yukarıdaki üçüncü taraf yazılımlar bunun dışındadır.
