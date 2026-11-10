// The service worker, served at /sw.js with scope /. Push only: no fetch handler and no caching, so the page is always
// the one the server has. A push's payload is `{title, body, url, agree}`, encrypted to this browser by Web Push; `agree`
// is the id of the held proposal the body shows, or null, and gives the notification an Agree action that POSTs it.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let shown = {};
  try {
    shown = event.data ? event.data.json() : {};
  } catch {
    // A payload that does not parse still gets a notification, with nothing in it but her name.
  }
  event.waitUntil(self.registration.showNotification(shown.title || 'Ashley', {
    body: shown.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { url: shown.url || '/', agree: Number.isInteger(shown.agree) ? shown.agree : null },
    actions: Number.isInteger(shown.agree) ? [{ action: 'agree', title: 'Agree' }] : [],
  }));
});

const unagreed = () => self.registration.showNotification('Ashley', {
  body: 'That could not be agreed to from here. Open the app to see it.',
  icon: '/icon-192.png',
  data: { url: '/', agree: null },
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const agree = event.notification.data?.agree;
  if (event.action === 'agree' && Number.isInteger(agree)) {
    event.waitUntil(fetch('/api/chat/agree', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ proposal_id: agree }),
    }).then((response) => response.ok || unagreed()).catch(unagreed));
    return;
  }
  const url = new URL(event.notification.data?.url || '/', self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((tabs) => {
    const open = tabs.find((tab) => new URL(tab.url).origin === self.location.origin);
    return open ? open.navigate(url.href).then((tab) => (tab ?? open).focus()) : self.clients.openWindow(url.href);
  }));
});
