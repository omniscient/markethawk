/*
 * MarketHawk Service Worker
 * Handes Web Push notifications even when the tab is closed.
 */

self.addEventListener('push', (event) => {
  if (!(self.Notification && self.Notification.permission === 'granted')) {
    return;
  }

  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      console.error('Error parsing push data:', e);
      data = { title: 'MarketHawk Alert', body: event.data.text() };
    }
  }

  const title = data.title || 'MarketHawk Alert';
  const options = {
    body: data.body || 'New scanner event detected.',
    icon: '/logo192.png', // Update if you have a specific icon
    badge: '/logo192.png',
    data: data, // Store the full data object for click handler
    vibrate: [100, 50, 100],
    tag: data.ticker || 'markethawk-alert', // Collapse multiple alerts for same ticker
    renotify: true,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const urlToOpen = event.notification.data?.url || '/alerts';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // If a tab is already open at the URL, focus it
      for (let i = 0; i < windowClients.length; i++) {
        const client = windowClients[i];
        if (client.url.includes(urlToOpen) && 'focus' in client) {
          return client.focus();
        }
      }
      // If no tab is open, open a new one
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
