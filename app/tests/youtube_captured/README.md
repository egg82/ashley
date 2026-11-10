`watch_page.html` is an invented watch page in the shape YouTube serves: a title and the `ytInitialPlayerResponse` it assigns, which keeps
only `playabilityStatus.status`, the caption track list, `videoDetails` (id, title, length, channel, author, description) and the
microformat's publish date, channel name and length. Every name, id and sentence in it is made up.

`captions.en.json3` is an invented English automatic track in the shape `yt-dlp --skip-download --write-auto-subs --sub-langs en
--sub-format json3` writes: 40 events, timed as a real track's are, with the words made up.
