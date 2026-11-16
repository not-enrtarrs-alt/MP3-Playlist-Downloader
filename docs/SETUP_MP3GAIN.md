# mp3gain setup

mp3gain changes MP3 gain **permanently** without re-encoding. Test on a copy first. A failed run may already have changed a file; the app marks a track equalized only on success.

1. Obtain a trusted Windows mp3gain command-line distribution from the [mp3gain project](https://mp3gain.sourceforge.net/). It is old software; some builds are 32-bit and may not work on every system.
2. Place `mp3gain.exe` in `tools\mp3gain\` next to the app/repository, put it on PATH, or select it under **Settings → Tools**. No binary is shipped with this repository.
3. Use **Settings → Tools → Test mp3gain /?** and verify that your build accepts the app's command: `mp3gain /r /k /s s "file.mp3"`. The options apply track gain, prevent clipping, and avoid writing a gain tag. These flags were verified against the user's configured mp3gain 1.5.2, including a disposable synthetic MP3; other builds may differ.
4. Select downloaded tracks and choose **Equalize selected**. Optional automatic equalization after download is off by default.

If mp3gain is missing or fails, files remain available and are not marked equalized. No files are permanently deleted by default; explicit deletes go to the Recycle Bin.
