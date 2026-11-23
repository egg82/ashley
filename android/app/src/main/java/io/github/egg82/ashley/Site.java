package io.github.egg82.ashley;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The deployment this copy of the app opens: its origin, {@code https://<host>/}, asked for once on first run and kept
 * in the app's own storage. The APK names no site, so one build serves every deployment; changing the site means
 * clearing the saved one, which reinstalling the app does.
 */
final class Site {
    private static final String PREFS = "site";
    private static final String KEY = "url";
    private static final Pattern HTTPS_HOST =
            Pattern.compile("https://([a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?)/?", Pattern.CASE_INSENSITIVE);

    private Site() {}

    /** {@code https://<host>/} for {@code typed} that is {@code https://<host>} with an optional slash; else null. */
    static Uri parse(String typed) {
        Matcher m = HTTPS_HOST.matcher(typed.trim());
        if (!m.matches()) return null;
        return Uri.parse("https://" + m.group(1).toLowerCase(Locale.ROOT) + "/");
    }

    /** The saved site, or null before the first run has saved one. */
    static Uri saved(Context context) {
        String url = prefs(context).getString(KEY, null);
        return url == null ? null : parse(url);
    }

    static void save(Context context, Uri site) {
        prefs(context).edit().putString(KEY, site.toString()).apply();
    }

    /** Whether {@code uri} is an https URL on {@code site}'s host; false when either is null. */
    static boolean onSite(Uri uri, Uri site) {
        return uri != null && site != null && "https".equalsIgnoreCase(uri.getScheme()) && uri.getPort() == -1
                && site.getHost().equalsIgnoreCase(uri.getHost());
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
