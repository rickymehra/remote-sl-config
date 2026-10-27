# C0_all.syx: C0 Full backup (do this first)

Settings changed on the SL:

    Nothing to change. This saves all 40 templates before anything else.

Dumped with: GLOBAL → page 4 → press button 2 (All)

Notes: OS 4.2.02. Byte-identical to backup_all.syx (dumps are deterministic). All 40 arrived within ~3 s of pressing retry: the port buffered the Dump All sent while the wizard sat at the retry prompt.

Findings:

- · received 40 message(s)
- ✔ bulk flag (byte 7) values: [1]
- ★ header bytes 9-10 on a live 'All' dump: 22 02
- · 14 slot(s) differ from factory: ['Digitakt', 'Digitakt', 'CH-3', 'CH-4', 'CH-5', 'CH-6', 'CH-7', 'CH-8']
