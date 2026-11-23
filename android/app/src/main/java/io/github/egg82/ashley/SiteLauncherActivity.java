package io.github.egg82.ashley;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

import androidx.annotation.Nullable;

import com.google.androidbrowserhelper.trusted.LauncherActivity;

/**
 * Opens the saved site in a Trusted Web Activity (a Custom Tab where no browser supports one). With no site saved yet
 * it hands over to {@link FirstRunActivity}. A URL handed in with the intent is opened only when it is on the saved
 * site; anything else opens the site's front page.
 */
public class SiteLauncherActivity extends LauncherActivity {
    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (!isFinishing() && Site.saved(this) == null) {
            startActivity(new Intent(this, FirstRunActivity.class));
            finish();
        }
    }

    @Override
    protected boolean shouldLaunchImmediately() {
        return Site.saved(this) != null;
    }

    @Override
    protected Uri getLaunchingUrl() {
        Uri site = Site.saved(this);
        Uri asked = getIntent().getData();
        return Site.onSite(asked, site) ? asked : site;
    }

    @Override
    protected boolean isTrustedIntentUrl(@Nullable Uri uri) {
        return Site.onSite(uri, Site.saved(this));
    }
}
