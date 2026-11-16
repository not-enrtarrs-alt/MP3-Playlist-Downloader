# YouTube setup

Unauthenticated downloads can be rate-limited. Private or age-restricted playlists may require valid cookies. Cookies are sensitive: keep them on your machine and never paste or send them to anyone.

In **Settings → YouTube**, choose None, a locally exported Netscape-format `cookies.txt`, or a supported browser. Use a trusted browser export tool if needed; never upload the exported file to a website. Browser cookie access may fail because the browser is open, uses a different profile, or protects its cookie store. Select a playlist and use **Test cookies** only when you want to make a network request. Only the cookie file's basename is displayed.

For a file-based setup:

1. Sign in to YouTube in your own browser. Choose a reputable export tool that writes the Netscape `cookies.txt` format locally; review its permissions before installing it.
2. Export only the cookies needed for YouTube authentication, to a private local location. Do not add the file to this repository, attach it to support requests, or paste its contents into a terminal/chat.
3. In Settings, select **cookies.txt**, choose the file, and save. Select a playlist you can access and explicitly click **Test cookies** when you want to make a network request. Remove outdated exports when no longer needed.

For browser mode, select Chrome, Firefox, Edge, Brave, Chromium, Opera or Vivaldi. Browser-profile access and OS-protected cookie stores vary; if extraction fails, close the browser when appropriate or use a locally exported file. The application stores only the selected path/browser, never cookie contents.

If YouTube shows bot checks or rate limits, pause and retry later; cookies may help. yt-dlp must be kept up to date when YouTube changes. When using a packaged application, updating yt-dlp requires rebuilding the app. Explicit file deletes use the Recycle Bin rather than permanent deletion.
