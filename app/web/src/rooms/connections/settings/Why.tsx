// The panel that opens the Home Assistant settings: what they are for, in plain words.
export function Why() {
  return (
    <section class="panel set-why">
      <h2>Why these settings exist</h2>
      <p>
        Ashley reads things other people wrote: emails, web pages, calendar invites. Some of that could try to give her
        orders. So once she has read something like that, she takes care. Lights and music still just happen. Locks, the
        garage and scripts happen only if you asked for them yourself; anything else waits for your OK.
      </p>
      <p>These settings say which of your house’s things she can read without taking care, and which others deserve it.</p>
    </section>
  );
}
