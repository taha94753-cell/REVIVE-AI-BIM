// Privacy, terms and the 404 page: fill in the operator's contact address when the server has one (app.contact_email).
try {
  const { contact_email: mail } = await (await fetch('/api/public/overview')).json();
  if (mail) document.querySelectorAll('[data-contact]').forEach(el => {
    const a = el.querySelector('[data-contact-link]');
    a.href = `mailto:${mail}`; a.textContent = mail; el.hidden = false;
  });
} catch { /* offline: the pages read fine without it */ }
