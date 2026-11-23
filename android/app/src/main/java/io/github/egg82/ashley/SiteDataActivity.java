package io.github.egg82.ashley;

import android.net.Uri;

import androidx.annotation.Nullable;

import com.google.androidbrowserhelper.trusted.ManageDataLauncherActivity;

/** The system's "Manage space" screen for the app: the browser's data for the saved site. */
public class SiteDataActivity extends ManageDataLauncherActivity {
    @Nullable
    @Override
    protected Uri getDefaultUrlForManagingSpace() {
        return Site.saved(this);
    }
}
