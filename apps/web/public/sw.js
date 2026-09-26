// No household content or authenticated responses are cached.
self.addEventListener("push", event => {
  const candidate = event.data?.json()?.url;
  const url = ["/approvals", "/constitution", "/tonight"].includes(candidate) ? candidate : "/approvals";
  event.waitUntil(self.registration.showNotification("Hirz needs your attention", {
    body: "Open Hirz to review your household request.", icon: "/icon.svg", tag: "hirz-attention",
    data: { url },
  }));
});
self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow(["/approvals", "/constitution", "/tonight"].includes(event.notification.data?.url) ? event.notification.data.url : "/approvals"));
});
