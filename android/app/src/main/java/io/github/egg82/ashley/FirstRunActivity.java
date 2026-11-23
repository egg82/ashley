package io.github.egg82.ashley;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.TextView;

/** Asks once for the site's address, saves it and opens it. */
public class FirstRunActivity extends Activity {
    private EditText address;
    private TextView error;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.first_run);
        address = findViewById(R.id.address);
        error = findViewById(R.id.error);
        address.setSelection(address.getText().length());
        address.setOnEditorActionListener((v, action, event) -> {
            if (action != EditorInfo.IME_ACTION_GO) return false;
            open();
            return true;
        });
        findViewById(R.id.open).setOnClickListener(v -> open());
    }

    private void open() {
        Uri site = Site.parse(address.getText().toString());
        if (site == null) {
            error.setVisibility(View.VISIBLE);
            return;
        }
        Site.save(this, site);
        startActivity(new Intent(this, SiteLauncherActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        finish();
    }
}
