# Dumps to fetch manually

The shell could not download these (login or Cloudflare). If you get them, put them in a
new folder here with a sidecar `.md` like the others.

| What | Where | Why it matters |
|---|---|---|
| DX7 template by "major7th" for the Remote SL | Gearspace thread "DX7 template for Novation Remote SL controller": https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/840889-dx7-template-novation-remote-sl-controller.html (attachments need a login; the fetch got a Cloudflare page) | Another hand-made SysEx-heavy template (Yamaha DX7 parameter changes) |
| Novation Remote SL Template Editor (Mac/Win) | https://downloads.novationmusic.com/novation/remote/remote-37-sl (`remoteslzeroeditor1.1.8535.dmg.zip`, `remotezerosleditorsetup1.1.8517.exe2_.zip`) | Not a dump, but its binary probably contains the field tables and default template. Not downloaded: it is a large proprietary app and we do not need to run it |
| Blofeld template thread | https://gearspace.com/threads/waldorf-blofeld-novation-remote-sl-templates.800252/ | Possible SysEx-heavy community templates |
| Matrix 1000 template thread | https://gearspace.com/threads/controlling-oberheim-matrix-1000-using-novation-remote-sl.810930/ | Same |
| KVR "Novation Remote Automap Library" thread | https://www.kvraudio.com/forum/viewtopic.php?t=428933 | Links to more user templates |
| Archive.org copies of the old Novation template library | https://web.archive.org/web/2009*/novationmusic.com/support/* | Older template packs (pre-OS 4.1) would show whether the header bytes 9–10 encode a version |

No MkII or Compact templates were collected. If any turn up, put them in `dumps/other-models/`,
not here: they are different devices and their format is not known to match.
