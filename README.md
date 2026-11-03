# PBO AutoTuner (Ryzen 5000 / 7000 / 9000 desktop)

**Language / Dil:** [Türkçe](README.tr.md) · English (this file)

An automatic tuner that finds the **most negative stable Curve Optimizer (CO) value** for every physical core by
itself and resumes where it left off after crashes. At the end it gives you a table you can enter in the BIOS.

> **Status:** Tested end to end on real hardware only on a **Ryzen 9 9950X3D** (the author's machine): `doctor`, quick
> and full runs, and resuming after crashes. The search / state / crash-resume logic was also verified with a fake
> processor and more than 300 automated tests that inject random crashes. The Zen 3 / Zen 4 presets and 12-core
> processors **have not been tried on a real machine yet.** Installation through `kur.bat` was tried on a clean
> Windows and works. The
> `doctor` command checks every step on your machine one by one; stay at the computer for the first real run.

The interface (menu, `doctor`, log, report, setup messages) is available in **English and Turkish**; see
[Interface language](#interface-language).

## Disclaimer

- Pushing Curve Optimizer can cause system freezes, unexpected reboots and, rarely, file/data corruption. Back up
  important data before running it.
- The tool uses a kernel driver (PawnIO) to reach the hardware and, if you want, installs a scheduled task that runs
  at logon (`install-autostart`).
- PBO/undervolting may affect your warranty. The software is provided as is, without any warranty (see
  [LICENSE](LICENSE)); you are responsible for the results.
- This project is not affiliated with the author of CoreCycler or with AMD.

## Supported processors

The processor is detected automatically from the Windows registry (family/model); the y-cruncher binary, the CO floor
and the starting value are chosen accordingly. Values you write by hand in `config.toml` are kept; only values that are
impossible for the generation are corrected or rejected with an error.

| Generation | y-cruncher | `floor` (deepest CO) | `start_co` | Status |
|---|---|---|---|---|
| Zen 5, Ryzen 9000 | `24-ZN5 ~ Komari` | 50 | 20 | **tested on real hardware (9950X3D)** |
| Zen 4, Ryzen 7000 | `22-ZN4 ~ Kizuna` | 50 | 15 | preset exists, **untested** |
| Zen 3, Ryzen 5000 | `19-ZN2 ~ Kagari` | 30 | 10 | preset exists, **untested** |

- Zen 3 does not support AVX-512 (Kizuna/Komari do not work) and its CO range only goes to -30. **CO is locked on the
  5800X3D**, so the tool does not work there.
- If your processor is not detected, put `generation = "zen3"` / `"zen4"` / `"zen5"` in `config.toml`.
- 6- and 8-core (single CCD) and 12-core (6+6) processors were tested in simulation. On 12 cores, the APIC ID gap rule
  that maps WHEA events to cores (according to CoreCycler's notes the second CCD's IDs start at 16) is **not
  verified**; if it is wrong, only the WHEA matching can miss something, y-cruncher's own error detection is not
  affected.
- Intel and Zen 2 are not supported.

## How it works

You cannot pin the frequency directly; on Ryzen, CO shifts the voltage curve and the processor boosts higher as far
as its power/thermal headroom allows. The tool does the following:

1. **Round-by-round search:** In every round each core is tested at one level (a y-cruncher load on a single core).
   The cores that are not being tested stay **at their own known values** (not at CO 0), so the conditions are close
   to real use.
   * **Descent:** the first test is at -20 (`start_co`), then it steps down in increments of 5, to at most -50
     (`floor`; ryzen-smu-cli does not apply anything deeper: on the real machine, writing -55 read back -50). A core
     is set aside at its first failure.
   * **Bisection:** narrows the gap between the last passing and the first failing value down to 1 (medium-length
     tests).
   * **Confirmation:** verifies `found limit - 2` with a long test; if it fails, it backs off by 2 and tries again.
2. **Validation:** with ALL found values applied together, it tests every core again and backs off the ones that fail.
3. **All-core load test:** if it fails, it backs everything off by 2 (y-cruncher does not tell which core failed).
4. The report lists CO, crash count and the effective MHz difference against CO 0 (approximate) for every core.

**Why "combined"?** In the first real run (9950X3D) the old isolated mode (the other cores at CO 0) showed all 16
cores as error-free at -40; yet when the other cores were also at deep CO, most of the same cores failed at -40 within
the first second (core 13 only passed at -24). So one core's limit depends on the others' CO. Isolated mode can still
be selected with `isolate_cores = true` but is not recommended.

**Crash flow:** Before every test, "I am trying this level" is written to disk. If the system crashes, that level is
counted as failed at the next boot and the search continues from the next step. After a crash the values return to
the BIOS values; the first thing the tool does is set them all to 0. Test levels that were cut short are never
counted as passed.

**Protection:** If 8 crashes happen without any test completing in between, or 3 unexpected reboots happen outside
tests, it stops and asks for your confirmation (`run --force`).

## Installation (Windows 10/11)

**Easy way:** double-click **`kur.bat`** in the project folder (no administrator rights needed). It does the following:
1. Uses Python 3.11+ if present; otherwise installs Python 3.12 for the current user silently, first with **winget**
   and, failing that, from python.org.
2. Installs `psutil` (`pip`; with `ensurepip` and `--user` if needed).
3. If `config.toml` does not exist, creates it from `config.example.toml`; if it finds a `CoreCycler*` folder inside or
   next to the project folder, it writes the path automatically. An existing `config.toml` is never touched.
4. Writes the Python that psutil was installed into to `python_path.txt`; `run_as_admin.bat` uses that Python.
5. If the **PawnIO** driver is not installed, asks for your consent and installs it (the signed kernel driver that
   ryzen-smu-cli uses to reach the processor; namazso, GPL-licensed). It first tries `winget install namazso.PawnIO`;
   if that fails, it downloads the pinned version (2.2.0) from GitHub and installs it with `-install -silent` **after
   verifying the SHA-256**. A UAC (administrator) prompt appears. If you do not want to be asked, use
   `python -m pbo_tuner.setup_env --yes`; to skip installing it altogether, use `--no-pawnio`. If Windows asks for a
   restart, the setup tells you at the end.
6. If **CoreCycler** is missing, asks for your consent and downloads it from the official GitHub release (v0.11.0.3,
   ~45 MB; ~370 MB once extracted), **verifies its SHA-256** and extracts it into the project folder. It extracts the
   `.7z` archive with Windows' own `tar.exe` (or with 7-Zip if that is installed). If you do not want to be asked, use
   `--yes`; to skip the download altogether, use `--no-corecycler`. CoreCycler is licensed CC BY-NC-SA 4.0
   (non-commercial use); it is not put in the repository, the copy downloaded from the official page is used.

What you need to do by hand:
- **CoreCycler 0.11.x:** if `kur.bat` cannot download it (no internet, you declined, etc.), download it from
  https://github.com/sp00n/CoreCycler/releases and extract it into the project folder.
- **BIOS:** leave Curve Optimizer at **Auto/0** (the tuner writes its own values). You can set PBO as you like, but
  keep it constant during tuning. If RAM/EXPO is unstable, the results will be misleading.

After `kur.bat` finishes, **right-click `run_as_admin.bat` > Run as administrator**: when opened without a command it
shows a menu (1 = doctor, 2 = quick trial, 3 = main run...).

`kur.bat` shows its own messages in Turkish or English depending on the Windows language (see "Interface language"
below).

*Manual installation:* Python 3.11+, `pip install psutil`, PawnIO (https://pawnio.eu), turn `config.example.toml` into
`config.toml` and write the `corecycler_dir` path. You can also run the commands with `python -m pbo_tuner ...` in an
administrator command prompt.

## Usage

```
python -m pbo_tuner doctor            # checks the environment (reads CO, writes it back unchanged, runs y-cruncher for 15 s)
python -m pbo_tuner run --quick       # short tests (~2 hours), rough result; do not enter the result in the BIOS
python -m pbo_tuner run               # the main run (~5-6 hours without crashes; each crash adds ~5 min)
python -m pbo_tuner status            # progress core by core
python -m pbo_tuner report            # regenerate the report (data\report.txt, results.json, bios_values.csv)
python -m pbo_tuner apply             # apply the final values temporarily (cleared on reboot)
python -m pbo_tuner reset             # set all CO values to 0 (temporary)
python -m pbo_tuner run --simulate    # watch the algorithm on a fake processor without touching the hardware
python -m pbo_tuner share             # prepare an anonymous report to share your results (menu 12)
```

The recommended order is `doctor`, then `run --quick`, then the real `run`. Do not enter the `--quick` result in the
BIOS; it is only there to see that the system carries out the flow correctly. When it finishes, start the long run
from scratch with `--fresh`.

### Interface language

The menu, `doctor`, log, report and setup messages can be shown in English or Turkish. The language is chosen in this
order:

1. Command line: `python -m pbo_tuner --lang en run` (`--lang` goes before the subcommand; for the menu use
   `run_as_admin.bat --lang en`)
2. Environment variable: `PBO_LANG=en`
3. In `config.toml`: `language = "en"` in the `[ui]` section (`"tr"`, `"en"` or `"auto"`)
4. If none is given, the system language (`auto`): Turkish if the Windows display language or regional setting is
   Turkish, otherwise English.

`kur.bat` chooses its own messages from the Windows regional/install language (or `PBO_LANG`); the `config.toml` setting only
affects the Python messages. Notes inside an existing state file stay in the language they were written in.

### Low-load / idle test (`lowload`, menu 11)

CO instability often shows up not under heavy load but **at idle or under light load** (the core jumps to a high
frequency at low voltage). y-cruncher's heavy tests do not catch this. After the normal run has finished:

```
python -m pbo_tuner lowload                       # 180 s per core + 30 min idle (~1.5 hours)
python -m pbo_tuner lowload --idle-minutes 240    # a longer idle test to leave running overnight
```

Run the command in an **administrator** command prompt. If it is interrupted (you closed the window, a crash, etc.),
typing the same command again or choosing `3` (run) in the menu is enough: it resumes where it left off, and new
duration values are not used for that run.

1. **Light + intermittent load per core:** with all CO values applied, light AVX2-based y-cruncher tests (BKT, BBP,
   SNT) are run on every core and the process is run for ~300 ms and paused for ~700 ms (frequent idle<->load
   transitions, average load ~30%). If it fails, that core is backed off by 2 and retried.
2. **Idle wait:** no load at all, only WHEA is watched. If the system crashes, the tool records it and warns in the
   report; which core is responsible cannot be known. Idle failures are rare and random, so a short wait cannot rule
   them out.

If you get an idle crash, the ways out are: (a) back off the deepest CO values (-45/-50), (b) add voltage to the low
frequency bands with Curve Shaper (this tool does not do that yet).

### Resuming by itself after a crash

```
python -m pbo_tuner install-autostart
```
It installs a task that resumes the run at logon. For this to work, Windows needs **automatic sign-in**, otherwise it
waits at the sign-in screen after a crash (Sysinternals Autologon is recommended). If the system freezes (does not
reboot), press the reset button; the tool resumes where it left off. `remove-autostart` removes the task; it is also
removed automatically when the run finishes. The auto-resume window closes if it finishes without an error; the result
is always in `data\report.txt`.

### Sharing your results (`share`, menu 12)

If you tried the tool on another processor (especially Zen 3 / Zen 4 and 12-core models), sharing the result helps
improve it:

```
python -m pbo_tuner share              # prepare an anonymous report and show it; if you agree, open the GitHub page
python -m pbo_tuner share --no-values  # leave the per-core CO values out of the report
python -m pbo_tuner share --no-open    # only prepare and save it (data\share_report.txt)
```

- **Nothing is sent automatically.** The complete report is shown on screen. Only if you explicitly answer `y` does the
  browser open a pre-filled GitHub "issue" page, and **you press "Submit new issue" yourself**. There is no server.
- A report you submit is **public** on GitHub, shown together with your GitHub account name.
- The report contains: tool version, Windows and Python version, processor model and generation, core count, PawnIO
  version, the stage of the run, crash count, warnings, per-core final CO / crashes / boost difference, and the last
  `doctor` output. User name, computer name and folder paths are removed from it; still, read it before submitting.
- CO values belong to **that one chip**; do not apply someone else's values to your own processor. The reports are not
  meant to distribute values, but to see which processors the tool works on and where it gets stuck.

### Making the result permanent

Enter the table in `data\report.txt` in the BIOS under
`Advanced > AMD Overclocking > Precision Boost Overdrive > Curve Optimizer > Per Core`
(Sign = Negative, Magnitude = value). BIOS core numbering starts at 0; Ryzen Master starts at 1.

## Limits and honest notes

- **If you kill the tool from Task Manager** (rather than Ctrl+C), the last applied CO can remain in the system;
  run `python -m pbo_tuner reset` immediately (if you stop it with Ctrl+C, the tool resets it itself).
- **There is no temperature monitoring.** A single-core y-cruncher load is thermally light, but keep an eye on your
  cooling anyway.
- **Passing a test does not mean permanent stability.** CO instability often shows up *at idle / under low load*. After
  entering the values in the BIOS, try them for a few days of normal use (games, idle, sleep/wake); if you get
  sporadic crashes, back the affected core off by 2-3. For a long-term definitive confirmation, increase
  `confirm_cycles` / `validate_cycles`.
- **Effective MHz is approximate** (Windows performance counters). Use HWiNFO for exact values.
- **WHEA:** only processor events (ID 18/19) that belong to the core under test count as errors; PCIe etc. do not.
- **Cores depend on each other:** one core's limit changes with the others' CO values. That is why the search is done
  while the other cores are at their own known values, and the final table is validated together separately. Still,
  check under all-core load and in real use.
- **Alternative:** CoreCycler 0.11's own "Automatic Test Mode" does a similar job on Ryzen 9000 (it starts at -50 and
  backs off). Because this tool descends from 0 and uses bisection, it should logically produce fewer crashes (I have
  not measured this by comparing the two tools).
- You are responsible for warranty issues and damage; PBO/undervolting may affect your warranty.

## Troubleshooting

| Symptom | Look at |
|---|---|
| `doctor`: CO read error | Is PawnIO installed? Is it CoreCycler 0.11+? Are you an administrator? Is Defender blocking the driver? |
| `doctor`: no y-cruncher log file | An antivirus may be blocking the wrapper (`helpers\WriteConsoleToWriteFileWrapper.exe`) |
| Very frequent "stress process is not using the CPU" | try `config.toml` > `[safety] cpu_load_check = false` |
| `TOOL ERROR: Required files were not found` (or `FileNotFoundError: [WinError 2]`) | Does `corecycler_dir` in `config.toml` point to the right folder? (it must contain `tools\ryzen-smu-cli\ryzen-smu-cli.exe`; `C:\Tools\CoreCycler` is only an example path). An antivirus may have deleted the file. `doctor` tells you which file is missing; `kur.bat` downloads CoreCycler again |
| `kur.bat`: "Could not extract CoreCycler" | An antivirus may have deleted `y-cruncher` / `ryzen-smu-cli` files (add an exclusion); install 7-Zip if Windows has no `tar.exe`; or download CoreCycler by hand |
| `TOOL ERROR: y-cruncher did not start` | Is the `mode` name the same as a file in `test_programs\y-cruncher\Binaries`? |
| Very low CO values | The instability may come from RAM/EXPO/PSU; set those to stock first and try again |

## Files

`pbo_tuner/search.py` search algorithm (pure logic) · `state.py` persistent state · `tuner.py` orchestrator ·
`hw.py` Windows adapters · `sim.py` fake processor · `report.py` report · `__main__.py` command line ·
`i18n.py` language selection · `lang_en.py` English texts (a new on-screen text is written with `tr("...")` and its
translation is added there; a test catches a missing translation) · `tests/` automated tests
(`python -m pytest tests`).

## Reporting problems

When opening an issue, include: the processor model, the Windows version, the output of
`python -m pbo_tuner doctor` and the relevant part of `data\tuner.log` (`python -m pbo_tuner share` prepares the environment information and the last `doctor` output for you). Results on Zen 3 / Zen 4 and on 12-core
processors are especially valuable.

## Third-party software and licenses

This repository does **not** contain any of the following. The user downloads them, or they are downloaded from their
official source during setup. Each is subject to its own license:

| Project | Role | License |
|---|---|---|
| [CoreCycler](https://github.com/sp00n/CoreCycler) (sp00n) | provides ryzen-smu-cli, y-cruncher and the log wrapper; downloaded from the official release during setup, with your consent | CC BY-NC-SA 4.0 (non-commercial) |
| [ryzen-smu-cli](https://github.com/rawhide-kobayashi/ryzen-smu-cli) / ZenStates-Core | reading and writing CO | the license in their own repositories |
| [y-cruncher](https://www.numberworld.org/y-cruncher/) (Alexander Yee) | stress test | [its own license](https://www.numberworld.org/y-cruncher/license.html) |
| [PawnIO](https://pawnio.eu) (namazso) | kernel driver | GPL-2.0-or-later |

To work together with it, this tool follows CoreCycler's command line and y-cruncher configuration format. No code
was copied from CoreCycler (PowerShell); this tool was written from scratch in Python.

## License

[MIT](LICENSE). The third-party software above is excluded from it.
