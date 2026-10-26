(function () {
  const links = Array.from(document.querySelectorAll('.nav a[href^="#"]'));
  if (!links.length) return;
  const sections = links
    .map((link) => document.querySelector(link.getAttribute('href')))
    .filter(Boolean);
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        links.forEach((link) => {
          const active = link.getAttribute('href') === '#' + entry.target.id;
          link.style.background = active ? 'rgba(79,70,229,.12)' : '';
          link.style.borderColor = active ? 'rgba(79,70,229,.35)' : '';
        });
      });
    },
    { rootMargin: '-20% 0px -70% 0px' }
  );
  sections.forEach((section) => observer.observe(section));
})();
